"""ASTM E1381 low-level codec + session — LIS-23 / S2.1.

ASTM E1381 is the link layer beneath ASTM E1394 (the record content, S2.2 / LIS-24):
a stop-and-wait protocol over RS-232 that frames a record, protects it with a
**modulo-256 checksum**, and recovers from line errors by NAK + retransmit. A
session has three phases (plan §2):

* **Establishment** — the sender raises ``ENQ``; the receiver answers ``ACK``
  (ready) or ``NAK`` (busy).
* **Transfer** — each frame is ``<STX> FN text <ETX|ETB> C1 C2 <CR> <LF>`` where
  ``FN`` is the single-digit frame number (1-7 then 0, cycling), ``ETX`` ends the
  last frame of a record and ``ETB`` an intermediate one, and ``C1 C2`` is the
  checksum of ``FN … ETX|ETB`` as two uppercase hex digits. The receiver validates
  the checksum (and frame number) and answers ``ACK`` or ``NAK``; on ``NAK`` the
  sender **retransmits** the same frame, up to a retry limit.
* **Termination** — the sender sends ``EOT``.

This module is dependency-free and models the session over a deterministic
in-memory link so the ACK/NAK/retransmit behaviour is unit-testable without a real
serial port (``run_session``). The byte-faithful frame round-trip a replay needs is
:class:`~edge_sim.transport.AstmTransport`. E1394 record parsing is S2.2 / LIS-24.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

__all__ = [
    "ENQ",
    "ACK",
    "NAK",
    "EOT",
    "STX",
    "ETX",
    "ETB",
    "CR",
    "LF",
    "MAX_FRAME_TEXT",
    "AstmError",
    "AstmFrame",
    "checksum",
    "build_frame",
    "parse_frame",
    "AstmReceiver",
    "SessionResult",
    "run_session",
]

# ASTM E1381 / ASCII control characters.
ENQ = 0x05  # enquiry — establish the link
ACK = 0x06  # acknowledge — frame accepted / ready
NAK = 0x15  # negative acknowledge — frame rejected, retransmit
EOT = 0x04  # end of transmission — terminate the session
STX = 0x02  # start of text — begin a frame
ETX = 0x03  # end of text — final frame of a record
ETB = 0x17  # end of transmission block — intermediate frame
CR = 0x0D
LF = 0x0A

# E1381 caps a frame's text at 240 characters; longer records split across frames.
MAX_FRAME_TEXT = 240


class AstmError(Exception):
    """Raised when bytes cannot be read as an E1381 frame at all (no ``STX`` /
    too short / no terminator). A checksum or frame-number error is *not* an
    exception — :func:`parse_frame` returns ``valid=False`` so the receiver NAKs."""


@dataclass(frozen=True)
class AstmFrame:
    """A parsed E1381 frame."""

    frame_number: int  # 0-7, or -1 if unreadable
    text: str
    final: bool  # True = ETX (last frame of a record), False = ETB (intermediate)
    valid: bool  # checksum (and frame-number readability) OK
    error: str = ""


def checksum(covered: bytes) -> bytes:
    """The E1381 checksum of ``covered`` (the ``FN … ETX|ETB`` bytes): their sum
    modulo 256 as two uppercase hex digits."""
    return b"%02X" % (sum(covered) & 0xFF)


def build_frame(frame_number: int, text: str | bytes, final: bool = True) -> bytes:
    """Build one E1381 frame: ``STX FN text (ETX|ETB) C1 C2 CR LF``.

    ``frame_number`` is taken modulo 8 (E1381 cycles 1-7 then 0). ``final`` picks
    ``ETX`` (last frame of a record) or ``ETB`` (intermediate).
    """
    body = text.encode("latin-1") if isinstance(text, str) else bytes(text)
    fn = str(frame_number % 8).encode("ascii")
    terminator = bytes([ETX if final else ETB])
    covered = fn + body + terminator
    return bytes([STX]) + covered + checksum(covered) + bytes([CR, LF])


def parse_frame(frame: bytes) -> AstmFrame:
    """Parse one complete E1381 frame. Raises :class:`AstmError` if ``frame`` is not
    a structurally complete ``STX … (ETX|ETB) C1 C2`` frame; returns ``valid=False``
    on a checksum or frame-number error so the caller can NAK."""
    if len(frame) < 6 or frame[0] != STX:
        raise AstmError("not an E1381 frame (missing STX or too short)")
    body = frame[1:]
    if body[-2:] == bytes([CR, LF]):
        body = body[:-2]
    elif body[-1:] == bytes([CR]):
        body = body[:-1]
    if len(body) < 4:
        raise AstmError("E1381 frame too short to hold FN + terminator + checksum")
    terminator = body[-3]
    if terminator not in (ETX, ETB):
        raise AstmError("E1381 frame missing ETX/ETB terminator")

    fn_byte = body[0:1]
    text_bytes = body[1:-3]
    cs_field = body[-2:]
    covered = body[:-2]  # FN … terminator

    valid = True
    error = ""
    if not fn_byte.isdigit():
        valid, error = False, "non-numeric frame number"
        fn = -1
    else:
        fn = int(fn_byte)
    if cs_field.upper() != checksum(covered):
        valid, error = False, "checksum mismatch"
    return AstmFrame(
        frame_number=fn,
        text=text_bytes.decode("latin-1"),
        final=(terminator == ETX),
        valid=valid,
        error=error,
    )


class AstmReceiver:
    """The E1381 receiver half: answers ``ENQ`` with ``ACK``, validates each frame
    (checksum + expected frame number) answering ``ACK``/``NAK``, accepts the record
    text of every ACKed frame, and ends on ``EOT``.

    Frame numbers are expected in sequence (1, 2, … 7, 0, …). A frame whose checksum
    fails, or that is out of sequence, is NAKed; a verbatim retransmit of the
    last-accepted frame is ACKed idempotently (its record is not re-collected)."""

    def __init__(self) -> None:
        self.records: list[str] = []
        self.complete = False
        self.nak_count = 0
        self.state = "neutral"
        self._expected_fn = 1

    def feed(self, pdu: bytes) -> bytes:
        """Process one inbound PDU (``ENQ`` / a frame / ``EOT``) and return the
        control bytes to send back (``ACK``/``NAK``, or empty for ``EOT``)."""
        if not pdu:
            return b""
        head = pdu[0]
        if head == ENQ:
            self.state = "established"
            return bytes([ACK])
        if head == EOT:
            self.complete = True
            self.state = "neutral"
            return b""
        if head == STX:
            return self._on_frame(pdu)
        return self._nak()  # unknown control byte

    def _on_frame(self, pdu: bytes) -> bytes:
        try:
            frame = parse_frame(pdu)
        except AstmError:
            return self._nak()
        if not frame.valid:
            return self._nak()
        if frame.frame_number == self._expected_fn:
            self.records.append(frame.text)
            self._expected_fn = (self._expected_fn + 1) % 8
            return bytes([ACK])
        if frame.frame_number == (self._expected_fn - 1) % 8:
            return bytes([ACK])  # idempotent re-ACK of the last accepted frame
        return self._nak()  # out of sequence

    def _nak(self) -> bytes:
        self.nak_count += 1
        return bytes([NAK])


@dataclass
class SessionResult:
    """Outcome of a full E1381 session driven by :func:`run_session`."""

    records: list[str] = field(default_factory=list)
    complete: bool = False
    naks: int = 0
    retransmits: int = 0
    aborted: bool = False


def run_session(
    records: list[str | bytes],
    *,
    corrupt: Callable[[int, bytes], bytes] | None = None,
    max_retries: int = 6,
) -> SessionResult:
    """Drive a complete E1381 session — one frame per record — sender → receiver
    over a deterministic in-memory link, and report what happened.

    ``corrupt(index, frame)`` (optional) may mutate the on-the-wire bytes of the
    frame for record ``index`` on each transmission, modelling line noise; return
    it unchanged to leave the frame intact. The sender retransmits a NAKed frame up
    to ``max_retries`` times before aborting the session.
    """
    receiver = AstmReceiver()
    result = SessionResult()

    # Establishment.
    if receiver.feed(bytes([ENQ])) != bytes([ACK]):  # pragma: no cover - receiver always ACKs ENQ
        result.aborted = True
        return result

    # Transfer.
    for index, record in enumerate(records):
        frame = build_frame((index + 1) % 8, record, final=True)
        attempts = 0
        while True:
            wire = corrupt(index, frame) if corrupt is not None else frame
            if receiver.feed(wire) == bytes([ACK]):
                break
            result.naks += 1
            if attempts >= max_retries:
                result.aborted = True
                break
            attempts += 1
            result.retransmits += 1
        if result.aborted:
            break

    # Termination.
    if not result.aborted:
        receiver.feed(bytes([EOT]))

    result.records = receiver.records
    result.complete = receiver.complete
    return result
