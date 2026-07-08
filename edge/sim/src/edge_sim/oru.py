"""``ORU^R01`` result extraction — LIS-14 / S1.2.

Walks a parsed HL7 v2 message (:mod:`edge_sim.hl7`) and lifts the result content
into a typed, transport-neutral :class:`OruReport`: the sending analyzer, the
patient/specimen identifiers, and one :class:`RawObservation` per ``OBX`` segment
carrying the analyzer-native code/unit *as reported*. Normalization to LOINC/UCUM
is a separate concern (:mod:`edge_sim.normalize`).

Tolerant (plan §1): a missing/empty ``PID``/``OBR`` field yields ``""``; a
truncated ``OBX`` yields empty trailing attributes; a non-``ORU`` message still
parses (with whatever ``OBX`` segments it has). Only a message with no ``MSH`` is
rejected — without it the message cannot be identified.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from .hl7 import Message, parse_message, unescape

__all__ = [
    "RawObservation",
    "OruReport",
    "OruParseError",
    "RESULT_TYPE_PATIENT",
    "RESULT_TYPE_CALIBRATION",
    "RESULT_TYPE_QC",
    "RESULT_TYPE_BLANK",
    "parse_oru_r01",
]

RESULT_TYPE_PATIENT = "PATIENT"
RESULT_TYPE_CALIBRATION = "CALIBRATION"
RESULT_TYPE_QC = "QC"
RESULT_TYPE_BLANK = "BLANK"

_EDAN_HISTOGRAM_CODE = re.compile(r"^(.+)_PNG_BASE64(?:_(\d+))?$", re.IGNORECASE)
_NUMERIC_RANGE = re.compile(
    r"\s*(-?\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(-?\d+(?:\.\d+)?)\s*",
    re.IGNORECASE,
)


class OruParseError(Exception):
    """Raised when a message cannot be read as an ORU at all (no ``MSH``)."""


@dataclass(frozen=True)
class RawObservation:
    """One ``OBX`` observation, exactly as the analyzer reported it."""

    set_id: str  # OBX-1
    value_type: str  # OBX-2 (NM, ST, ...)
    raw_code: str  # OBX-3.1 observation identifier
    raw_text: str  # OBX-3.2 observation text
    raw_system: str  # OBX-3.3 coding system (e.g. 99RAC local, LN LOINC)
    sub_id: str  # OBX-4 observation sub-id (carries the warning code for an in-band 'Alarm' OBX, e.g. W3001)
    value: str  # OBX-5
    raw_unit: str  # OBX-6.1 units, as reported
    reference_range: str  # OBX-7
    abnormal_flags: str  # OBX-8
    status: str  # OBX-11 observation result status (F, P, ...)
    completion_time: str = ""  # analyzer completion timestamp (ASTM R-13); "" for HL7 ORU


@dataclass(frozen=True)
class OruReport:
    """The transport-neutral content of an ``ORU^R01`` (or any OBX-bearing message)."""

    message_type: str  # MSH-9 e.g. "ORU^R01"
    sending_app: str  # MSH-3 (analyzer)
    sending_facility: str  # MSH-4
    message_control_id: str  # MSH-10
    patient_id: str  # PID-3.1 -> PID-2.1 (SD1 MRN); EDAN H90-series uses PID-2 (see _patient_id)
    patient_name: str  # PID-5 (raw)
    specimen_id: str  # OBR-3 filler order; EDAN H90-series prefers OBR-20 (barcode), else OBR-2 (see _specimen_id)
    order_code: str  # OBR-4.1
    observations: tuple[RawObservation, ...]
    result_type: str = RESULT_TYPE_PATIENT  # MSH-16: PATIENT / CALIBRATION / QC
    qc_lot_number: str = ""  # OBR-14 for SD1 QC/calibration uploads; always "" for EDAN (a timestamp, see gate)
    qc_type: str = ""  # OBR-20 for SD1 QC type / level; always "" for EDAN (see barcode)
    barcode: str = ""  # EDAN OBR-20 scanned barcode (LIS-149 AC3, see _edan_obr20); "" for non-EDAN or a blank OBR-20


def parse_oru_r01(message: Message | bytes | str) -> OruReport:
    """Extract an :class:`OruReport` from ``message`` (raw bytes/str or a
    pre-parsed :class:`Message`)."""
    msg = message if isinstance(message, Message) else parse_message(message)

    msh = msg.first("MSH")
    if msh is None:
        raise OruParseError("message has no MSH segment; cannot identify as ORU")

    enc = msg.encoding

    def u(value: str) -> str:
        return unescape(value, enc)

    pid = msg.first("PID")
    obr = msg.first("OBR")

    edan = _is_edan_h90(msh)

    observations = tuple(
        obs for seg in msg.all("OBX") if (obs := _observation(seg, u, edan)) is not None
    )
    result_type = _result_type(msh.field(16))
    if obr and _is_blank_sample_obr(obr, u):
        result_type = RESULT_TYPE_BLANK

    return OruReport(
        message_type=u(msh.field(9)),
        sending_app=u(msh.field(3)),
        sending_facility=u(msh.field(4)),
        message_control_id=u(msh.field(10)),
        patient_id=u(_patient_id(pid, edan)) if pid else "",
        patient_name=u(pid.field(5)) if pid else "",
        specimen_id=u(_specimen_id(obr, edan)) if obr else "",
        order_code=u(obr.component(4, 1)) if obr else "",
        result_type=result_type,
        # EDAN repurposes OBR-14 as a timestamp (H90 §3.2.3 "Specimen Received
        # Date/Time"), not the SD1 QC lot number — force it blank there so a timestamp
        # can never be misread as a QC lot. Non-EDAN analyzers are unaffected.
        qc_lot_number="" if edan else (u(obr.field(14)) if obr else ""),
        # EDAN repurposes OBR-20 as the scanned barcode (see barcode below), not the
        # SD1 QC type/level — force it blank there so a barcode can never be misread
        # as a QC type. Non-EDAN analyzers are unaffected.
        qc_type="" if edan else (u(obr.field(20)) if obr else ""),
        barcode=u(_edan_obr20(obr)) if obr and edan else "",
        observations=observations,
    )


def _is_edan_h90(msh) -> bool:
    """True when the message is an EDAN **H90-series** upload (H90/H90S/H95/H95S/
    H96/H96S/H98S/**H99S**).

    The H90-series repurposes standard HL7 field positions (KB
    ``EDAN\\WI\\82-01.54.460907`` §5): the analyte code rides in **OBX-4** (OBX-3 is
    a suspect flag), the sample id in **OBR-2** (OBR-3 is the reviewing doctor), and
    the patient number in **PID-2** (PID-3 is ``Age^unit``). Every H90-series device
    announces type ``H90`` in ``MSH-3.1`` (model code in ``MSH-3.3`` — e.g.
    ``H90^^507`` = H99S, §7) and ``EDANLAB`` in ``MSH-4`` (§5.1). Detecting on either
    lets us apply the EDAN field profile without disturbing standard-HL7 analyzers.

    The EDAN **H60S** also belongs here: the 2026-07-06 physical bench (LIS-20) proved
    the real H60S emits ``MSH-3 'H60^7907'`` / ``MSH-4 'EDANLAB'`` with the code in
    OBX-4 — the H90-family layout, not the clean-HL7 ``H60S``/``EDAN``/OBX-3 the seed
    originally assumed. The ``MSH-4 == 'EDANLAB'`` arm routes it correctly."""
    return (
        msh.component(3, 1).strip().upper() == "H90"
        or msh.field(4).strip().upper() == "EDANLAB"
    )


def _patient_id(pid, edan: bool = False) -> str:
    """The patient/medical-record identifier from a ``PID`` segment.

    PID-3.1 (the CX patient identifier list) is the canonical id for most
    analyzers. The Seamaty SD1 instead carries the MRN in PID-2 (manual §3.3), so
    we fall back to PID-2.1 only when PID-3 is absent/blank — a present PID-3 always
    wins, leaving PID-3 analyzers (e.g. the RAYTO RAC-050) unaffected (LIS-86 / S2.10).
    Emptiness is tested on the stripped value so a whitespace-only PID-3 does not
    shadow a real PID-2 MRN (the very identifier this fallback exists to preserve).

    The EDAN H90-series (``edan=True``) is the inverse: the patient number is in
    PID-2 and PID-3 is ``Age^unit`` (KB §5.2), so PID-2 is preferred and the PID-3
    age is never used as an identifier.
    """
    if edan:
        pid2 = pid.component(2, 1)
        return pid2 if pid2.strip() else ""
    pid3 = pid.component(3, 1)
    return pid3 if pid3.strip() else pid.component(2, 1)


def _edan_obr20(obr) -> str:
    """The raw OBR-20 value, or ``""`` when absent/whitespace-only (LIS-149 AC3).

    OBR-20 is the H90-series "Patient ID or Barcode" field (KB §3.2.3; worked
    example §6.1): a **worklist-driven** result echoes the barcode the host scanned
    and handed back on the order-download ORF — the only reliable join key back to
    the OpenELIS order, since OBR-2 there is the analyzer's own sample counter, not
    an accession. A **direct-attach** result (no worklist) leaves OBR-20 blank.
    Corroborated by the real H60S bench pcap (OBR-20 == OBR-2, i.e. the scanned
    identifier, not the SD1 QC type/level convention this field carries for
    non-EDAN analyzers). NOT yet captured on real H99S wire — the H99S ORUs
    captured so far are MSH-only connection-test pings. Whitespace-only is treated
    as absent so it falls back like a blank field would, rather than becoming a
    present-but-empty barcode.
    """
    value = obr.field(20)
    return value if value.strip() else ""


def _specimen_id(obr, edan: bool = False) -> str:
    """The specimen/sample identifier from an ``OBR`` segment.

    Standard analyzers carry it in OBR-3 (filler order number). The EDAN H90-series
    (``edan=True``) prefers a stripped-non-blank **OBR-20** (the scanned barcode,
    LIS-149 AC3 — see :func:`_edan_obr20`), falling back to **OBR-2** (OBR-3 is the
    reviewing doctor, KB §5.3a) only when OBR-20 is absent — the direct-attach shape,
    where OBR-2 IS the accession. Matches the OBR-20-then-OBR-2 preference the
    edge/drivers bridge parser applies; the sim has no OE order-menu lookup, so
    (unlike the bridge) the barcode itself becomes the join key here.
    """
    if edan:
        obr20 = _edan_obr20(obr)
        if obr20:
            return obr20
        obr2 = obr.field(2)
        return obr2 if obr2.strip() else ""
    return obr.field(3)


def _result_type(msh16: str) -> str:
    """Seamaty SD1 result-type dispatcher from ``MSH-16``.

    The vendor protocol uses 0=patient, 1=calibration, 2=QC. Unknown or blank
    values stay patient for backward compatibility with analyzers that do not
    populate this field.
    """
    value = (msh16 or "").strip()
    if value == "1":
        return RESULT_TYPE_CALIBRATION
    if value == "2":
        return RESULT_TYPE_QC
    return RESULT_TYPE_PATIENT


def _is_blank_sample_obr(obr, u) -> bool:
    """True when an OBR explicitly labels the material as a blank sample."""
    return any("blank sample" in u(field).lower() for field in obr.fields)


def _observation(seg, u, edan: bool = False) -> RawObservation | None:
    # EDAN family (H90-series and, per the 2026-07-06 bench, the H60S): the analyte
    # code/name rides in OBX-4 (OBX-3 is a suspect flag, KB §5.4). Read the code from
    # OBX-4 there; standard analyzers keep the OBX-3.1 observation identifier.
    raw_code = u(seg.field(4)) if edan else u(seg.component(3, 1))
    if edan and seg.field(2).strip().upper() == "ST":
        match = _EDAN_HISTOGRAM_CODE.match(raw_code)
        if match and match.group(2):
            # EDAN emits scaled duplicate histograms as *_PNG_BASE64_2/_3. The
            # canonical base image is persisted; scaled variants are dropped so
            # they never normalize or enter the result stream.
            return None
    reference_range = u(seg.field(7))
    abnormal_flags = (
        _computed_edan_abnormal_flag(u(seg.field(5)), reference_range)
        if edan and seg.field(2).strip().upper() in {"NM", "SN"}
        else u(seg.field(8))
    )
    return RawObservation(
        set_id=u(seg.field(1)),
        value_type=u(seg.field(2)),
        raw_code=raw_code,
        raw_text=u(seg.component(3, 2)),
        raw_system=u(seg.component(3, 3)),
        sub_id=u(seg.field(4)),
        value=u(seg.field(5)),
        raw_unit=u(seg.component(6, 1)),
        reference_range=reference_range,
        abnormal_flags=abnormal_flags,
        status=u(seg.field(11)),
    )


def _computed_edan_abnormal_flag(value: str, reference_range: str) -> str:
    """Compute EDAN H/L/N from OBX-5 vs OBX-7; ignore EDAN's numeric OBX-8 codes."""
    if not value.strip() or not reference_range.strip():
        return ""
    match = _NUMERIC_RANGE.match(reference_range)
    if not match:
        return ""
    try:
        numeric_value = Decimal(value.strip())
        low = Decimal(match.group(1))
        high = Decimal(match.group(2))
    except InvalidOperation:
        return ""
    if low > high:
        return ""
    if numeric_value < low:
        return "L"
    if numeric_value > high:
        return "H"
    return "N"
