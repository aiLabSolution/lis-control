"""Analyzer-side ASTM E1381/E1394 session harness — LIS-25 / S2.3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .astm import ACK, ENQ, EOT, NAK, AstmReceiver, build_frame
from .e1394 import AstmMessage, parse_e1394
from .fixtures import Fixture

__all__ = [
    "AstmCorruption",
    "AstmSessionEvent",
    "AstmAnalyzerSessionResult",
    "run_analyzer_session",
    "run_fixture_session",
]

AstmCorruptor = Callable[[int, int, bytes], bytes | None]


@dataclass(frozen=True)
class AstmCorruption:
    """Built-in one-shot line-fault injectors for the analyzer session harness.

    ``frame_index`` is zero-based in the transmitted E1394 record sequence.
    """

    kind: str
    frame_index: int = 0
    attempt: int = 0

    @classmethod
    def bad_checksum_once(cls, frame_index: int = 0) -> "AstmCorruption":
        return cls("bad-checksum", frame_index=frame_index)

    @classmethod
    def drop_frame_once(cls, frame_index: int = 0) -> "AstmCorruption":
        return cls("drop-frame", frame_index=frame_index)

    @classmethod
    def stray_control_once(cls, frame_index: int = 0) -> "AstmCorruption":
        return cls("stray-control", frame_index=frame_index)

    def __call__(self, frame_index: int, attempt: int, frame: bytes) -> bytes | None:
        if frame_index != self.frame_index or attempt != self.attempt:
            return frame
        if self.kind == "bad-checksum":
            bad = bytearray(frame)
            # Flip one checksum hex byte (the two checksum bytes precede CR LF).
            bad[-4] = ord("0") if bad[-4] != ord("0") else ord("1")
            return bytes(bad)
        if self.kind == "drop-frame":
            return None
        if self.kind == "stray-control":
            return bytes([0x11])  # XON is not legal as a sender PDU here; host NAKs.
        raise ValueError(f"unknown ASTM corruption kind: {self.kind}")


@dataclass(frozen=True)
class AstmSessionEvent:
    """One sender-to-receiver exchange in the simulated serial session."""

    phase: str
    sent: bytes
    response: bytes
    frame_index: int | None = None
    attempt: int = 0
    record: str = ""


@dataclass
class AstmAnalyzerSessionResult:
    """Outcome of a full analyzer-side ASTM session."""

    payload: bytes = b""
    records: list[str] = field(default_factory=list)
    message: AstmMessage | None = None
    complete: bool = False
    naks: int = 0
    retransmits: int = 0
    timeouts: int = 0
    aborted: bool = False
    events: list[AstmSessionEvent] = field(default_factory=list)

    @property
    def frame_events(self) -> list[AstmSessionEvent]:
        return [event for event in self.events if event.phase == "frame"]

    @property
    def acked_frames(self) -> int:
        return sum(1 for event in self.frame_events if event.response == bytes([ACK]))


def run_fixture_session(
    fixture: Fixture,
    *,
    corrupt: AstmCorruptor | None = None,
    max_retries: int = 6,
) -> AstmAnalyzerSessionResult:
    """Run a fixture's ASTM payload through a full analyzer-side session."""

    return run_analyzer_session(fixture.message_bytes, corrupt=corrupt, max_retries=max_retries)


def run_analyzer_session(
    payload: bytes | str,
    *,
    corrupt: AstmCorruptor | None = None,
    max_retries: int = 6,
) -> AstmAnalyzerSessionResult:
    """Drive ``payload`` as E1394 records over an E1381 ENQ/ACK/NAK/EOT session.

    The analyzer sends one E1381 frame per E1394 record. The host validates each
    frame via :class:`edge_sim.astm.AstmReceiver`; NAKs and simulated timeouts
    cause retransmission of the same frame up to ``max_retries``.
    """

    records = _split_records(payload)
    receiver = AstmReceiver()
    result = AstmAnalyzerSessionResult(records=records)

    response = receiver.feed(bytes([ENQ]))
    result.events.append(AstmSessionEvent("enq", bytes([ENQ]), response))
    if response != bytes([ACK]):
        result.aborted = True
        return result

    for frame_index, record in enumerate(records):
        frame = build_frame((frame_index + 1) % 8, record, final=True)
        attempt = 0
        while True:
            wire = corrupt(frame_index, attempt, frame) if corrupt is not None else frame
            response = b"" if wire is None else receiver.feed(wire)
            sent = b"" if wire is None else wire
            result.events.append(
                AstmSessionEvent(
                    "frame",
                    sent,
                    response,
                    frame_index=frame_index,
                    attempt=attempt,
                    record=record,
                )
            )
            if response == bytes([ACK]):
                break

            if response == bytes([NAK]):
                result.naks += 1
            else:
                result.timeouts += 1

            if attempt >= max_retries:
                result.aborted = True
                break
            attempt += 1
            result.retransmits += 1

        if result.aborted:
            break

    if not result.aborted:
        response = receiver.feed(bytes([EOT]))
        result.events.append(AstmSessionEvent("eot", bytes([EOT]), response))

    result.complete = receiver.complete
    result.records = receiver.records
    result.payload = "\r".join(receiver.records).encode("latin-1")
    if result.payload:
        result.message = parse_e1394(result.payload)
    return result


def _split_records(payload: bytes | str) -> list[str]:
    text = payload.decode("latin-1") if isinstance(payload, (bytes, bytearray)) else payload
    normalized = text.replace("\r\n", "\r").replace("\n", "\r")
    return [record for record in normalized.split("\r") if record.strip()]
