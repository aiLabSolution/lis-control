"""HL7 v2 ``ACK^R01`` construction for the MLLP listener — LIS-13 / S1.1.

When a (simulated) analyzer sends an ``ORU^R01`` over MLLP, the host must
acknowledge it. HL7 v2 defines two acknowledgment modes:

* **Original** — the receiver returns an ``ACK`` whose ``MSA-1`` is
  ``AA`` (accept), ``AE`` (error) or ``AR`` (reject).
* **Enhanced** — acknowledgment is split into a transport-level *commit* ACK
  (``MSA-1`` = ``CA``/``CE``/``CR``) and a later application ACK. Whether a
  commit ACK is sent at all is governed by the inbound ``MSH-15`` (accept
  acknowledgment type): ``AL`` always, ``NE`` never, ``SU`` on success, ``ER``
  on error.

A positive ACK is ``MSA-1`` = ``AA`` (or commit ``CA``). A **negative** ACK —
``AE`` (application error) or ``AR`` (application reject) — additionally carries a
populated HL7 ``ERR`` segment naming the error condition (HL7 Table 0357);
:func:`build_nak` builds it.

This module knows only as much of the inbound message as acknowledgment
requires — the ``MSH`` segment. The full, tolerant ``ORU^R01`` parser and
LOINC/UCUM normalization are a separate slice (S1.2 / LIS-14); nothing here
inspects ``PID``/``OBR``/``OBX``. *Deciding* whether a message is rejected (and
with which condition) is the listener's job (:func:`edge_sim.milestone.acknowledge`);
this module only builds the ACK/NAK once that verdict is reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

__all__ = [
    "AckCode",
    "AckMode",
    "Hl7AckError",
    "Hl7ErrorCondition",
    "Msh",
    "parse_msh",
    "build_ack",
    "build_nak",
    "wants_accept_ack",
]

_SEGMENT_SEP = "\r"


class Hl7AckError(Exception):
    """Raised when the inbound message cannot be acknowledged (no/invalid MSH,
    or an acknowledgment code that does not match the requested mode)."""


class AckMode(Enum):
    """The HL7 v2 acknowledgment mode being produced."""

    ORIGINAL = "original"
    ENHANCED = "enhanced"


class AckCode(Enum):
    """``MSA-1`` acknowledgment codes. AA/AE/AR are original-mode; CA/CE/CR are
    the enhanced-mode commit codes."""

    AA = "AA"  # application accept
    AE = "AE"  # application error
    AR = "AR"  # application reject
    CA = "CA"  # commit accept
    CE = "CE"  # commit error
    CR = "CR"  # commit reject


_ORIGINAL_CODES = {AckCode.AA, AckCode.AE, AckCode.AR}
_ENHANCED_CODES = {AckCode.CA, AckCode.CE, AckCode.CR}


class Hl7ErrorCondition(Enum):
    """HL7 Table 0357 (message error condition) codes carried in the ``ERR`` segment
    of a negative acknowledgment. ``.code`` is the table value, ``.text`` its
    human-readable meaning."""

    SEGMENT_SEQUENCE_ERROR = ("100", "Segment sequence error")
    REQUIRED_FIELD_MISSING = ("101", "Required field missing")
    DATA_TYPE_ERROR = ("102", "Data type error")
    UNSUPPORTED_MESSAGE_TYPE = ("200", "Unsupported message type")
    UNSUPPORTED_EVENT_CODE = ("201", "Unsupported event code")
    APPLICATION_ERROR = ("207", "Application internal error")

    @property
    def code(self) -> str:
        return self.value[0]

    @property
    def text(self) -> str:
        return self.value[1]


@dataclass(frozen=True)
class Msh:
    """The fields of an inbound ``MSH`` that acknowledgment needs."""

    field_sep: str
    encoding_chars: str
    sending_app: str
    sending_facility: str
    receiving_app: str
    receiving_facility: str
    message_code: str
    trigger_event: str
    control_id: str
    processing_id: str
    version: str
    accept_ack_type: str
    application_ack_type: str

    @property
    def component_sep(self) -> str:
        return self.encoding_chars[0] if self.encoding_chars else "^"


def _first_segment(message: bytes) -> str:
    text = message.decode("latin-1")
    # tolerate \r, \n, or \r\n line endings on the first segment
    return text.replace("\r\n", "\r").replace("\n", "\r").split(_SEGMENT_SEP, 1)[0]


def parse_msh(message: bytes) -> Msh:
    """Read the inbound ``MSH`` segment. Tolerant of missing trailing fields;
    raises :class:`Hl7AckError` if the message does not start with ``MSH``."""
    seg = _first_segment(message)
    if not seg.startswith("MSH") or len(seg) < 4:
        raise Hl7AckError("message does not start with an MSH segment")
    field_sep = seg[3]
    fields = seg.split(field_sep)

    def f(i: int) -> str:
        return fields[i] if i < len(fields) else ""

    encoding_chars = f(1)
    comp_sep = encoding_chars[0] if encoding_chars else "^"
    msg_type = f(8).split(comp_sep)
    return Msh(
        field_sep=field_sep,
        encoding_chars=encoding_chars,
        sending_app=f(2),
        sending_facility=f(3),
        receiving_app=f(4),
        receiving_facility=f(5),
        message_code=msg_type[0] if msg_type else "",
        trigger_event=msg_type[1] if len(msg_type) > 1 else "",
        control_id=f(9),
        processing_id=f(10),
        version=f(11),
        accept_ack_type=f(14),
        application_ack_type=f(15),
    )


def wants_accept_ack(accept_ack_type: str | None, success: bool) -> bool:
    """Should a (commit) acknowledgment be sent, per the inbound ``MSH-15``?

    ``AL`` always, ``NE`` never, ``SU`` only on success, ``ER`` only on error.
    An empty/absent value means original mode — always acknowledge.
    """
    code = (accept_ack_type or "").strip().upper()
    if code in ("", "AL"):
        return True
    if code == "NE":
        return False
    if code == "SU":
        return success
    if code == "ER":
        return not success
    # Unknown code: be conservative and acknowledge.
    return True


_DEFAULT_ENCODING_CHARS = "^~\\&"

# HL7 v2.3.1 added the message-structure ID as MSH-9's 3rd component; from then on
# an acknowledgment of ORU^R01 is ACK^R01^ACK rather than ACK^R01.
_MSG_STRUCTURE_FROM = (2, 3, 1)


def _now_hl7() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _ack_message_type(msh: Msh, comp: str) -> str:
    """MSH-9 for the acknowledgment: ``ACK^<trigger>`` (v2.1–2.3) or
    ``ACK^<trigger>^ACK`` (v2.3.1+, which carries the message-structure ID)."""
    if not msh.trigger_event:
        return "ACK"
    msg_type = f"ACK{comp}{msh.trigger_event}"
    if _version_tuple(msh.version) >= _MSG_STRUCTURE_FROM:
        msg_type += f"{comp}ACK"
    return msg_type


def _ack_segments(
    message: bytes,
    *,
    code: AckCode | None,
    mode: AckMode,
    control_id: str | None,
    timestamp: str | None,
    text: str,
) -> tuple[list[str], Msh]:
    """Build the shared ``MSH`` + ``MSA`` segments of an acknowledgment and return
    them alongside the parsed inbound :class:`Msh`, so :func:`build_ack` and
    :func:`build_nak` produce an identical header/MSA and differ only in whether an
    ``ERR`` segment is appended."""
    msh = parse_msh(message)

    if code is None:
        code = AckCode.CA if mode is AckMode.ENHANCED else AckCode.AA
    valid = _ENHANCED_CODES if mode is AckMode.ENHANCED else _ORIGINAL_CODES
    if code not in valid:
        raise Hl7AckError(f"{code.value} is not a valid MSA-1 code for {mode.value} mode")

    sep = msh.field_sep
    comp = msh.component_sep
    ts = timestamp if timestamp is not None else _now_hl7()
    ack_control_id = control_id if control_id is not None else msh.control_id
    ack_type = _ack_message_type(msh, comp)

    msh_seg = sep.join(
        [
            "MSH",
            msh.encoding_chars or _DEFAULT_ENCODING_CHARS,  # MSH-2 is required
            msh.receiving_app,  # sender <- inbound receiver
            msh.receiving_facility,
            msh.sending_app,  # receiver <- inbound sender
            msh.sending_facility,
            ts,
            "",  # MSH-8 security
            ack_type,  # MSH-9
            ack_control_id,  # MSH-10
            msh.processing_id,  # MSH-11
            msh.version,  # MSH-12
        ]
    )
    msa_seg = sep.join(["MSA", code.value, msh.control_id, text])
    return [msh_seg, msa_seg], msh


def build_ack(
    message: bytes,
    *,
    code: AckCode | None = None,
    mode: AckMode = AckMode.ORIGINAL,
    control_id: str | None = None,
    timestamp: str | None = None,
    text: str = "",
) -> bytes:
    """Build an ``ACK`` for the inbound ``message``.

    The response echoes the inbound trigger event (``ACK^R01`` for an
    ``ORU^R01``), swaps the sending/receiving routing, and sets ``MSA-2`` to the
    inbound message control id. ``code`` defaults to ``AA`` (original) or ``CA``
    (enhanced); ``control_id`` defaults to the inbound control id; ``timestamp``
    defaults to the current UTC time (pass an explicit value for deterministic
    output). Returns the ACK application payload — caller applies MLLP framing.

    For a *negative* acknowledgment that carries a populated ``ERR`` segment, use
    :func:`build_nak`.
    """
    segments, _msh = _ack_segments(
        message, code=code, mode=mode, control_id=control_id, timestamp=timestamp, text=text
    )
    return _SEGMENT_SEP.join(segments).encode("latin-1")


def _err_segment(msh: Msh, condition: Hl7ErrorCondition, text: str) -> str:
    """Build a populated HL7 ``ERR`` segment for a negative acknowledgment.

    Targets the pre-v2.5 ``ERR-1`` form — the whole v1 fleet is HL7 v2.3.1–v2.4
    (EDAN H60S = v2.4, Seamaty SD1 = v2.3.1). ``ERR-1`` is the *Error Code and
    Location* (CM): its 4th component is the error code as a ``CE``
    ``<code>&<text>&HL70357`` keyed to HL7 Table 0357. The location components
    (1–3) are left empty because the reject is message-level, not field-level."""
    sep = msh.field_sep
    comp = msh.component_sep
    sub = msh.encoding_chars[3] if len(msh.encoding_chars) > 3 else "&"
    code_ce = sub.join([condition.code, text or condition.text, "HL70357"])
    err1 = comp.join(["", "", "", code_ce])  # ^^^<code&text&HL70357>
    return sep.join(["ERR", err1])


def build_nak(
    message: bytes,
    *,
    reject: bool = False,
    condition: Hl7ErrorCondition = Hl7ErrorCondition.APPLICATION_ERROR,
    text: str = "",
    control_id: str | None = None,
    timestamp: str | None = None,
) -> bytes:
    """Build a **negative** acknowledgment carrying a populated HL7 ``ERR`` segment.

    ``MSA-1`` is ``AE`` (application error) by default, or ``AR`` (application
    reject) when ``reject=True``. By convention here ``AE`` means *the message was
    received but could not be processed* (e.g. an ``ORU^R01`` with no result
    observations) and ``AR`` means *the message is refused* (e.g. an unsupported
    message type). The ``ERR`` segment names the HL7 Table 0357 ``condition``;
    ``text`` overrides the human-readable reason in both ``MSA-3`` and the ``ERR``
    code (defaulting to the condition's standard text).

    Like :func:`build_ack`, this reads only the inbound ``MSH`` (the reject
    *reason* is the listener's decision, not this builder's). Returns the NAK
    application payload — the caller applies MLLP framing.
    """
    code = AckCode.AR if reject else AckCode.AE
    segments, msh = _ack_segments(
        message,
        code=code,
        mode=AckMode.ORIGINAL,
        control_id=control_id,
        timestamp=timestamp,
        text=text or condition.text,
    )
    segments.append(_err_segment(msh, condition, text))
    return _SEGMENT_SEP.join(segments).encode("latin-1")
