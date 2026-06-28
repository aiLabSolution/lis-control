"""Stage-1 milestone E2E — *first result through the pipe* (LIS-17 / S1.5).

Ties the Stage-1 edge pipeline together on one captured analyzer message: a
(simulated) EDAN H60S sends an ``ORU^R01`` over MLLP; the edge listener de-frames
it, **acknowledges** it (``ACK^R01``, MSA-1 = ``AA``), and **parses + normalizes**
it to a Result — analyzer-native code/unit preserved beside the resolved LOINC/UCUM,
finality carried from OBX-11 — and emits the core ingest contract DTO (the seam the
core ``ResultIngestService.ingest`` persists, core ADR-0003).

This is the milestone exit gate of Stage 1 (``LIS_IMPLEMENTATION_PLAN.md`` §1): the
single automated assertion that the parts proven in isolation by earlier slices —
MLLP frame/ACK (S1.1 / LIS-13), tolerant ``ORU^R01`` parse + LOINC/UCUM normalization
(S1.2 / LIS-14), and the raw-archive round-trip (S1.4 / LIS-16) — compose end-to-end
into a normalized, acknowledged Result. The cross-process leg (handing the DTO to a
live/Testcontainers core over the wire) waits on the S1.0 substrate decision
(ADR-0003); core-side persistence of the DTO is already proven by LIS-15.

The edge here behaves as the **host/listener**: the analyzer is the TCP client (EDAN
H60S dials our port 7999), so the message arrives framed on the wire and the ACK is
framed back. :class:`MllpTransport` stands in for the socket; the codec is identical.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ack import AckCode, build_ack, parse_msh
from .ingest import to_ingest_payload
from .mllp import frame
from .normalize import NormalizedObservation, Normalizer
from .oru import OruReport, parse_oru_r01
from .transport import MllpTransport

__all__ = [
    "MilestoneOutcome",
    "run_milestone",
    "result_status",
    "RESULT_STATUS_FINAL",
]

RESULT_STATUS_FINAL = "final"

# HL7 Table 0085 (OBX-11 observation result status) → a stable lowercase lifecycle
# label. The milestone asserts the captured result is *final* (``F``); the other
# states are mapped so a non-final observation is reported, not silently dropped.
_OBX11_STATUS = {
    "F": RESULT_STATUS_FINAL,  # final results
    "U": RESULT_STATUS_FINAL,  # status change to final w/o retransmit (0085) — final
    "C": "corrected",  # correction that replaces a final result
    "P": "preliminary",  # preliminary results
    "R": "preliminary",  # results entered, not verified
    "S": "preliminary",  # partial results
    "I": "pending",  # specimen in lab, results pending
    "X": "cancelled",  # results cannot be obtained for this observation
    "W": "cancelled",  # posted as wrong (e.g. wrong patient) — retraction
    "D": "deleted",  # delete the observation
}


def result_status(obx11: str) -> str:
    """Map an OBX-11 observation result status code to a lifecycle label.

    Unknown/empty codes map to ``"unknown"`` (tolerant — the milestone asserts
    ``final`` explicitly rather than assuming it)."""
    return _OBX11_STATUS.get((obx11 or "").strip().upper(), "unknown")


@dataclass(frozen=True)
class MilestoneOutcome:
    """The end-to-end outcome of one ``ORU^R01`` through the edge milestone path."""

    received: bytes  # the de-framed inbound application payload (post-MLLP)
    round_trip_ok: bool  # the payload survived MLLP frame/de-frame byte-for-byte
    ack: bytes  # the ACK application payload the listener built
    ack_wire: bytes  # the ACK as framed back on the MLLP wire (SB … EB CR)
    ack_code: str  # MSA-1 (AA on accept)
    ack_message_code: str  # ACK MSH-9.1 (e.g. "ACK")
    ack_trigger_event: str  # ACK MSH-9.2 (e.g. "R01")
    report: OruReport
    observations: tuple[NormalizedObservation, ...]
    result_statuses: tuple[str, ...]  # per-observation finality (OBX-11 mapped)

    @property
    def all_final(self) -> bool:
        """True when every observation is a final result (OBX-11 = F)."""
        return bool(self.result_statuses) and all(
            s == RESULT_STATUS_FINAL for s in self.result_statuses
        )

    @property
    def accepted(self) -> bool:
        """True when the listener accepted the message (ACK MSA-1 = AA)."""
        return self.ack_code == AckCode.AA.value

    def ingest_payload(self) -> list[dict]:
        """The core ingest contract DTOs (core ADR-0003) for the **final**
        observations only — what the edge hands the core persistence seam.

        Non-final observations (preliminary / corrected / cancelled / …, OBX-11 ≠
        F/U) are **held back**: the edge does not land a non-final result in the
        append-only Result store as if authoritative — persisting a preliminary
        result indistinguishably from a final one is a clinical hazard. Carrying
        finality onto the row (so a later preliminary→final reconciliation can
        supersede it) is deferred (ADR-0013); until then, only final results flow."""
        return to_ingest_payload(
            obs
            for obs, finality in zip(self.observations, self.result_statuses)
            if finality == RESULT_STATUS_FINAL
        )


def run_milestone(
    message: bytes,
    *,
    normalizer: Normalizer | None = None,
    ack_timestamp: str | None = None,
) -> MilestoneOutcome:
    """Drive ``message`` (an ``ORU^R01`` application payload) through the full edge
    milestone path and return the :class:`MilestoneOutcome`.

    The message is framed onto an MLLP wire and de-framed back (the listener
    receiving it), acknowledged, and parsed + normalized. ``ack_timestamp`` pins
    MSH-7 for a deterministic ACK (the wire/ACK are otherwise time-stamped now).
    """
    sent = bytes(message)

    # Listener leg: the analyzer's framed message arrives; de-frame it.
    transport = MllpTransport()
    transport.send(sent)
    received = transport.receive()

    # Acknowledge (original-mode AA) and frame the ACK back onto the wire.
    ack = build_ack(received, code=AckCode.AA, timestamp=ack_timestamp)
    ack_wire = frame(ack)
    ack_msh = parse_msh(ack)

    # Parse + normalize the received result.
    report = parse_oru_r01(received)
    rows = tuple((normalizer or Normalizer()).normalize_report(report))
    statuses = tuple(result_status(o.status) for o in report.observations)

    return MilestoneOutcome(
        received=received,
        round_trip_ok=(received == sent),
        ack=ack,
        ack_wire=ack_wire,
        ack_code=AckCode.AA.value,
        ack_message_code=ack_msh.message_code,
        ack_trigger_event=ack_msh.trigger_event,
        report=report,
        observations=rows,
        result_statuses=statuses,
    )
