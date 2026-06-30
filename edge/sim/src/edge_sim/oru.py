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

from .hl7 import Message, parse_message, unescape

__all__ = [
    "RawObservation",
    "OruReport",
    "OruParseError",
    "parse_oru_r01",
]


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


@dataclass(frozen=True)
class OruReport:
    """The transport-neutral content of an ``ORU^R01`` (or any OBX-bearing message)."""

    message_type: str  # MSH-9 e.g. "ORU^R01"
    sending_app: str  # MSH-3 (analyzer)
    sending_facility: str  # MSH-4
    message_control_id: str  # MSH-10
    patient_id: str  # PID-3.1, falling back to PID-2.1 (the SD1's MRN field; see _patient_id)
    patient_name: str  # PID-5 (raw)
    specimen_id: str  # OBR-3 filler order / specimen id
    order_code: str  # OBR-4.1
    observations: tuple[RawObservation, ...]


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

    observations = tuple(_observation(seg, u) for seg in msg.all("OBX"))

    return OruReport(
        message_type=u(msh.field(9)),
        sending_app=u(msh.field(3)),
        sending_facility=u(msh.field(4)),
        message_control_id=u(msh.field(10)),
        patient_id=u(_patient_id(pid)) if pid else "",
        patient_name=u(pid.field(5)) if pid else "",
        specimen_id=u(obr.field(3)) if obr else "",
        order_code=u(obr.component(4, 1)) if obr else "",
        observations=observations,
    )


def _patient_id(pid) -> str:
    """The patient/medical-record identifier from a ``PID`` segment.

    PID-3.1 (the CX patient identifier list) is the canonical id for most
    analyzers. The Seamaty SD1 instead carries the MRN in PID-2 (manual §3.3), so
    we fall back to PID-2.1 only when PID-3 is absent/blank — a present PID-3 always
    wins, leaving PID-3 analyzers (e.g. the EDAN H60S) unaffected (LIS-86 / S2.10).
    Emptiness is tested on the stripped value so a whitespace-only PID-3 does not
    shadow a real PID-2 MRN (the very identifier this fallback exists to preserve).
    """
    pid3 = pid.component(3, 1)
    return pid3 if pid3.strip() else pid.component(2, 1)


def _observation(seg, u) -> RawObservation:
    return RawObservation(
        set_id=u(seg.field(1)),
        value_type=u(seg.field(2)),
        raw_code=u(seg.component(3, 1)),
        raw_text=u(seg.component(3, 2)),
        raw_system=u(seg.component(3, 3)),
        sub_id=u(seg.field(4)),
        value=u(seg.field(5)),
        raw_unit=u(seg.component(6, 1)),
        reference_range=u(seg.field(7)),
        abnormal_flags=u(seg.field(8)),
        status=u(seg.field(11)),
    )
