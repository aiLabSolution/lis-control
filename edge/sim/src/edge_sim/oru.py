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
import hashlib
import re

from .hl7 import Message, Segment, parse_message, unescape

__all__ = [
    "RawObservation",
    "SpecimenGroup",
    "OruReport",
    "OruParseError",
    "RESULT_TYPE_PATIENT",
    "RESULT_TYPE_CALIBRATION",
    "RESULT_TYPE_QC",
    "RESULT_TYPE_BLANK",
    "mint_accession",
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
class SpecimenGroup:
    """One wire specimen/order and only the observations attributed to it.

    Patient identity is carried beside the specimen accession, never used as a
    substitute for it. A transmission with multiple OBR/O records exposes one
    group per result-bearing order in wire order (ADR-0018).
    """

    patient_id: str
    patient_name: str
    specimen_id: str
    order_code: str
    observations: tuple[RawObservation, ...]
    result_type: str = RESULT_TYPE_PATIENT
    qc_lot_number: str = ""
    qc_type: str = ""
    barcode: str = ""
    edan: bool = False


@dataclass(frozen=True)
class OruReport:
    """The transport-neutral content of an ``ORU^R01`` (or any OBX-bearing message).

    ``groups`` is the lossless per-specimen representation. The original scalar
    fields remain first-group compatibility accessors and ``observations`` remains
    the wire-order flattening across groups, matching the bridge's ParsedResults
    compatibility contract.
    """

    message_type: str  # MSH-9 e.g. "ORU^R01"
    sending_app: str  # MSH-3 (analyzer)
    sending_facility: str  # MSH-4
    message_control_id: str  # MSH-10
    patient_id: str  # PID-3.1 -> PID-2.1 (SD1 MRN); EDAN H90-series uses PID-2 (see _patient_id)
    patient_name: str  # PID-5 (raw)
    specimen_id: str  # OBR-3 filler order; EDAN H90-series prefers OBR-20 (barcode), else OBR-2 (see _specimen_id)
    order_code: str  # OBR-4.1
    observations: tuple[RawObservation, ...]
    result_type: str = RESULT_TYPE_PATIENT  # MSH-16: PATIENT / CALIBRATION / QC (vendor-aware, see _result_type)
    qc_lot_number: str = ""  # OBR-14 for SD1 QC/calibration uploads; OBR-13 for EDAN QC-layout uploads (LIS-110); else ""
    qc_type: str = ""  # OBR-20 for SD1 QC type/level; OBR-3 (raw level digit) for EDAN QC-layout uploads (LIS-110); else ""
    barcode: str = ""  # EDAN OBR-20 scanned barcode (LIS-149 AC3, see _edan_obr20); "" for non-EDAN, a blank OBR-20, or the EDAN QC layout (LIS-110 — OBR-20 is patient-layout only)
    edan: bool = False  # EDAN H90-family announce-gate verdict (_is_edan_h90); drives the normalize.py QC re-kind gate (LIS-110)
    groups: tuple[SpecimenGroup, ...] = ()


@dataclass
class _Hl7GroupBuilder:
    obr: Segment | None
    patient: Segment | None
    observations: list[RawObservation]
    raw_records: list[str]


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

    edan = _is_edan_h90(msh)
    # The message-level type decides the EDAN OBR layout/joins below; the BLANK
    # override is a per-OBR material property layered on top of it (a blank-sample
    # frame is still a patient-layout message — mirrors the bridge, where blank is
    # a group flag and messageResultType stays PATIENT).
    message_result_type = _result_type(msh.field(16), edan)
    edan_qc_layout = edan and (msh.field(16) or "").strip() == "1"

    builders: list[_Hl7GroupBuilder] = []
    current_patient: Segment | None = None
    current: _Hl7GroupBuilder | None = None
    for segment in msg.segments:
        if segment.name == "PID":
            current_patient = segment
        elif segment.name == "OBR":
            current = _Hl7GroupBuilder(
                segment,
                current_patient,
                [],
                [_raw_segment(segment)],
            )
            builders.append(current)
        elif segment.name == "OBX":
            if current is None:
                current = _Hl7GroupBuilder(None, current_patient, [], [])
                builders.append(current)
            current.raw_records.append(_raw_segment(segment))
            observation = _observation(segment, u, edan)
            if observation is not None:
                current.observations.append(observation)

    groups_list: list[SpecimenGroup] = []
    for group_index, builder in enumerate(builders):
        if builder.observations:
            patient_id_for_mint = (
                _patient_id(builder.patient, edan).strip() if builder.patient else ""
            )
            patient_name_for_mint = normalized_patient_name(
                builder.patient.field(5) if builder.patient else ""
            )
            groups_list.append(
                _specimen_group(
                    builder,
                    u=u,
                    edan=edan,
                    edan_qc_layout=edan_qc_layout,
                    message_result_type=message_result_type,
                    mint_parts=(
                        f"{msh.field(3).strip()}|{msh.field(4).strip()}",
                        msh.field(7).strip(),
                        msh.field(10).strip(),
                        patient_id_for_mint,
                        patient_name_for_mint,
                        "\r".join(builder.raw_records),
                        str(group_index),
                    ),
                )
            )
    groups = tuple(groups_list)
    observations = tuple(obs for group in groups for obs in group.observations)

    # Compatibility: the scalar view is the first result-bearing group. A
    # message without results keeps the old tolerant first-PID/first-OBR view.
    first = groups[0] if groups else _specimen_group(
        _Hl7GroupBuilder(msg.first("OBR"), msg.first("PID"), [], []),
        u=u,
        edan=edan,
        edan_qc_layout=edan_qc_layout,
        message_result_type=message_result_type,
    )

    return OruReport(
        message_type=u(msh.field(9)),
        sending_app=u(msh.field(3)),
        sending_facility=u(msh.field(4)),
        message_control_id=u(msh.field(10)),
        patient_id=first.patient_id,
        patient_name=first.patient_name,
        specimen_id=first.specimen_id,
        order_code=first.order_code,
        result_type=first.result_type,
        qc_lot_number=first.qc_lot_number,
        qc_type=first.qc_type,
        barcode=first.barcode,
        observations=observations,
        edan=edan,
        groups=groups,
    )


def _specimen_group(
    builder: _Hl7GroupBuilder,
    *,
    u,
    edan: bool,
    edan_qc_layout: bool,
    message_result_type: str,
    mint_parts: tuple[str, ...] | None = None,
) -> SpecimenGroup:
    """Finalize one OBR (or implicit OBR-less) result group."""
    obr = builder.obr
    patient = builder.patient
    result_type = (
        RESULT_TYPE_BLANK
        if obr and _is_blank_sample_obr(obr, u)
        else message_result_type
    )

    if obr and edan_qc_layout:
        # EDAN QC layout: OBR-2 QC file number, OBR-3 level, OBR-13 lot.
        specimen_id = obr.field(2)
        barcode = ""
        qc_lot_number = obr.field(13)
        qc_type = obr.field(3)
    elif obr and edan and message_result_type == RESULT_TYPE_PATIENT:
        specimen_id = _specimen_id(obr, edan)
        barcode = _edan_obr20(obr)
        qc_lot_number = ""
        qc_type = ""
    elif obr and edan:
        obr2 = obr.field(2)
        specimen_id = obr2 if obr2.strip() else ""
        barcode = qc_lot_number = qc_type = ""
    elif obr:
        specimen_id = _specimen_id(obr)
        barcode = ""
        qc_lot_number = obr.field(14)
        qc_type = obr.field(20)
    else:
        specimen_id = barcode = qc_lot_number = qc_type = ""

    raw_patient_id = _patient_id(patient, edan) if patient else ""
    patient_id = u(raw_patient_id)
    specimen_id = u(specimen_id)
    if not specimen_id.strip() and mint_parts is not None:
        specimen_id = mint_accession("HL7", raw_patient_id, *mint_parts)

    return SpecimenGroup(
        patient_id=patient_id,
        patient_name=u(patient.field(5)) if patient else "",
        specimen_id=specimen_id,
        order_code=u(obr.component(4, 1)) if obr else "",
        observations=tuple(builder.observations),
        result_type=result_type,
        qc_lot_number=u(qc_lot_number),
        qc_type=u(qc_type),
        barcode=u(barcode),
        edan=edan,
    )


def mint_accession(protocol_tag: str, patient_id: str, *content_parts: str) -> str:
    """Mirror the bridge's deterministic ``AccessionMinter`` byte-for-byte.

    The prefix is a sanitized patient id when present, otherwise the protocol
    tag. Each order-significant digest part is UTF-8 encoded and followed by an
    ASCII record-separator byte (0x1e), preventing ambiguous concatenations.
    """
    prefix = re.sub(r"[^A-Za-z0-9_.-]", "", (patient_id or "").strip())
    if not prefix:
        prefix = protocol_tag
    prefix = prefix[:14]  # 25 total - hyphen - 10 lowercase digest characters

    digest = hashlib.sha256()
    for part in content_parts:
        digest.update((part or "").encode("utf-8"))
        digest.update(b"\x1e")
    return f"{prefix}-{digest.hexdigest()[:10]}"


def normalized_patient_name(raw_name: str) -> str:
    """Match the bridge PatientIdentity name used in accession digest inputs."""
    return " ".join(part.strip() for part in (raw_name or "").split("^") if part.strip())


def _raw_segment(segment: Segment) -> str:
    """Reconstruct a non-MSH segment exactly as parsed, without unescaping it."""
    return segment.encoding.field.join(segment.fields)


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

    Standard analyzers prefer OBR-3 (filler order number), then OBR-2 (placer
    order number), matching the bridge's ``parseAccessionFromOBR``. The EDAN H90-series
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
    obr3 = obr.field(3)
    return obr3 if obr3.strip() else obr.field(2)


def _result_type(msh16: str, edan: bool = False) -> str:
    """Vendor-aware result-type dispatcher from ``MSH-16`` (LIS-110).

    Non-EDAN (``edan=False``, e.g. the Seamaty SD1 and every other generic-HL7
    analyzer): the vendor protocol uses 0=patient, 1=calibration, 2=QC. Unknown or
    blank values stay patient for backward compatibility with analyzers that do
    not populate this field. This branch is byte-for-byte unchanged by LIS-110.

    EDAN H60/H90-series (``edan=True``) uses a different encoding entirely. The
    H90-series protocol (``EDAN\\WI\\82-01.54.460907`` §3.2.1) documents:
    0=sample results, 1=blood-cell QC results, 2=test connection, 3=obtain
    patient info / sample measurement items (host-query), 4=protein control
    results, 1000=production tooling data — there is **no calibration value**.
    The H60-specific doc lists only 0/1, but the 2026-07-06/07 physical H60S
    bench (docs/runbooks/edan-h60s-bench-conformance.md) proved the real H60S
    follows the H90 map — it emitted 2 on the MSH-only connection-test ping and
    3 on a host-query QRY^R02, both payload-less frames (no OBX observations, so
    holding them has no patient-result consequence). Only 0/empty (patient) and
    1 (blood-cell QC) map first-class; everything else — the documented
    non-result 2/3, the undispositioned 4 (LIS-224) / 1000, and genuinely
    unknown values — fails closed to QC: an EDAN result-type flag this parser
    doesn't map is NEVER routed to the patient stream. Mirrors the bridge
    ``HL7ResultParser.fromEdanMsh16``.
    """
    value = (msh16 or "").strip()
    if edan:
        if value in ("", "0"):
            return RESULT_TYPE_PATIENT
        return RESULT_TYPE_QC
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
    if edan:
        # OBX-9 (result/research flag) and OBX-7 (reference range) gate the CD-mode
        # -D reticulocyte normalization; a decorated second-channel twin returns None.
        raw_code = _edan_result_code(u(seg.field(4)), u(seg.field(9)), u(seg.field(7)))
        if raw_code is None:
            return None
    else:
        raw_code = u(seg.component(3, 1))
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


def _edan_result_code(
    raw_code: str, obx9_flag: str = "", reference_range: str = ""
) -> str | None:
    """Normalize an EDAN H90-series (CD-mode) OBX-4 code, or return ``None`` to drop
    the row (left unmapped, which OE discards).

    CD mode emits the differential analytes twice: the clean seeded code (e.g.
    ``NEU%``) that maps and persists, and a sub-component-decorated second-channel
    twin (``NEU%\\T\\`` -> ``NEU%&``). Collapsing the twin onto the base code would
    stage a duplicate result row per analyte (no dedup), so the decorated twin is
    dropped; the clean code already carries the value (LIS-190 double-map finding).

    Reticulocytes arrive in CD mode only as ``RET#-D``/``RET%-D`` (no clean ``RET#``).
    The ``-D`` suffix is stripped to the reportable code only when the vendor's own
    signal marks the row reportable: OBX-9 == ``0`` (result, not research) and a
    non-blank OBX-7 range. A research ``-D`` channel (OBX-9 == ``1`` / no range; e.g.
    ``WBC-D``, ``TNC-D``, or a research ``RET#-D``) stays decorated -> unmapped ->
    dropped, never aliased onto reportable LOINC 60474-4 (EDAN H90 LIS protocol §2.2).
    """
    code = (raw_code or "").strip()

    # sub-component-decorated second-channel twin (e.g. NEU%& from NEU%\T\): redundant
    # with the clean seeded code in the same run -> drop it.
    if "&" in code:
        return None

    if code.upper() in {"RET#-D", "RET%-D"}:
        reportable = obx9_flag.strip() == "0" and bool(reference_range.strip())
        if reportable:
            return code[:-2]
    return code


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
