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

from .ack import (
    AckCode,
    Hl7ErrorCondition,
    build_ack,
    build_nak,
    parse_msh,
)
from .ingest import to_ingest_payload
from .mllp import frame
from .normalize import KIND_CALIBRATION, KIND_RESULT, KIND_WARNING, NormalizedObservation, Normalizer
from .oru import OruParseError, OruReport, parse_oru_r01
from .transport import MllpTransport

__all__ = [
    "MilestoneOutcome",
    "run_milestone",
    "acknowledge",
    "ListenerDecision",
    "SUPPORTED_RESULT_TYPES",
    "result_status",
    "RESULT_STATUS_FINAL",
]

RESULT_STATUS_FINAL = "final"

# The Stage-1 MLLP listener ingests HL7 v2 result messages (``ORU^R01``). Anything
# else arriving on the result port is an unsupported message type and is rejected
# (``AR``) — e.g. a query (``QRY^R02``) or admit (``ADT``) message mis-routed here.
SUPPORTED_RESULT_TYPES = frozenset({("ORU", "R01")})

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
        """True when every analyte **result** is final (OBX-11 = F).

        Kind-aware, mirroring :meth:`ingest_payload`: in-band warnings
        (``KIND_WARNING``, e.g. the SD1 'Alarm' OBX) are not results, so they do not
        gate result finality — an alarm carries no OBX-11 finality of its own and must
        not drag an otherwise-final result set to non-final (LIS-86 / S2.10)."""
        finals = [
            finality
            for obs, finality in zip(self.observations, self.result_statuses)
            if obs.kind == KIND_RESULT
        ]
        return bool(finals) and all(s == RESULT_STATUS_FINAL for s in finals)

    @property
    def accepted(self) -> bool:
        """True when the listener accepted the message (ACK MSA-1 = AA)."""
        return self.ack_code == AckCode.AA.value

    @property
    def warnings(self) -> tuple[NormalizedObservation, ...]:
        """The in-band instrument warnings (e.g. the SD1 'Alarm' OBX) routed out of
        the result stream — surfaced here as notes so a flag is visible without ever
        masquerading as a patient analyte result (LIS-86 / S2.10)."""
        return tuple(o for o in self.observations if o.kind == KIND_WARNING)

    @property
    def calibrations(self) -> tuple[NormalizedObservation, ...]:
        """Calibration rows routed out of the patient result stream."""
        return tuple(o for o in self.observations if o.kind == KIND_CALIBRATION)

    def ingest_payload(self) -> list[dict]:
        """The core ingest contract DTOs (core ADR-0003) for the **final analyte
        results** only — what the edge hands the core persistence seam.

        Two classes are held back. Non-final observations (preliminary / corrected /
        cancelled / …, OBX-11 ≠ F/U) are not landed in the append-only Result store
        as if authoritative — persisting a preliminary result indistinguishably from
        a final one is a clinical hazard (carrying finality onto the row for a later
        preliminary→final reconciliation is deferred, ADR-0013). In-band instrument
        warnings (``KIND_WARNING``, e.g. the SD1 'Alarm' OBX) and calibration
        rows (``KIND_CALIBRATION``) are routed out entirely — neither is a patient
        result. Until then, only final analyte results flow."""
        return to_ingest_payload(
            obs
            for obs, finality in zip(self.observations, self.result_statuses)
            if finality == RESULT_STATUS_FINAL and obs.kind == KIND_RESULT
        )


@dataclass(frozen=True)
class ListenerDecision:
    """The Stage-1 result-ingestion listener's accept/reject verdict for one inbound
    application message (post-MLLP-de-frame): the ACK/NAK it returns and why."""

    ack: bytes  # the ACK/NAK application payload (MSH + MSA [+ ERR on a NAK])
    ack_wire: bytes  # the same, MLLP-framed (SB … EB CR)
    code: str  # MSA-1: AA (accept) / AE (error) / AR (reject)
    accepted: bool  # True only for MSA-1 = AA
    error_condition: str  # HL7 Table 0357 code on a NAK; "" when accepted


def acknowledge(message: bytes, *, ack_timestamp: str | None = None) -> ListenerDecision:
    """Decide and build the listener's acknowledgment for an inbound ``message``.

    The Stage-1 MLLP listener ingests ``ORU^R01`` results (LIS-13 / S1.1). It returns:

    * **AA** — a supported ``ORU^R01`` carrying ≥1 ``OBX`` result observation;
    * **AR** + a populated ``ERR`` — an *unsupported message type* (anything but
      ``ORU^R01``), e.g. a ``QRY^R02`` query or an ``ADT`` mis-routed to the result
      port (HL7 0357 = 200);
    * **AE** + a populated ``ERR`` — a supported type that **cannot be processed**:
      the body fails to parse (0357 = 102), or an ``ORU^R01`` carries no ``OBX``
      result rows (0357 = 101).

    Raises :class:`~edge_sim.ack.Hl7AckError` when the message has no ``MSH`` — there
    is nothing to acknowledge (no control id to echo, no routing to swap). A real
    listener lets such a frame time out; the MLLP de-framer resynchronises rather
    than surfacing un-de-frameable bytes here (see ADR-0005)."""
    msh = parse_msh(message)  # Hl7AckError if no MSH (nothing to acknowledge)

    if (msh.message_code, msh.trigger_event) not in SUPPORTED_RESULT_TYPES:
        nak = build_nak(
            message,
            reject=True,
            condition=Hl7ErrorCondition.UNSUPPORTED_MESSAGE_TYPE,
            text=(
                f"unsupported message type {msh.message_code}^{msh.trigger_event}; "
                "this listener ingests ORU^R01 results"
            ),
            timestamp=ack_timestamp,
        )
        return ListenerDecision(
            nak, frame(nak), AckCode.AR.value, False,
            Hl7ErrorCondition.UNSUPPORTED_MESSAGE_TYPE.code,
        )

    try:
        report = parse_oru_r01(message)
    except OruParseError as exc:
        nak = build_nak(
            message, reject=False, condition=Hl7ErrorCondition.DATA_TYPE_ERROR,
            text=str(exc), timestamp=ack_timestamp,
        )
        return ListenerDecision(
            nak, frame(nak), AckCode.AE.value, False, Hl7ErrorCondition.DATA_TYPE_ERROR.code
        )

    if not report.observations:
        nak = build_nak(
            message, reject=False, condition=Hl7ErrorCondition.REQUIRED_FIELD_MISSING,
            text="ORU^R01 carries no OBX result observations", timestamp=ack_timestamp,
        )
        return ListenerDecision(
            nak, frame(nak), AckCode.AE.value, False,
            Hl7ErrorCondition.REQUIRED_FIELD_MISSING.code,
        )

    ack = build_ack(message, code=AckCode.AA, timestamp=ack_timestamp)
    return ListenerDecision(ack, frame(ack), AckCode.AA.value, True, "")


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

    # Listener accept/reject decision (AA, or AE/AR + ERR), framed back on the wire.
    decision = acknowledge(received, ack_timestamp=ack_timestamp)
    ack_msh = parse_msh(decision.ack)

    # Parse + normalize the received result.
    report = parse_oru_r01(received)
    rows = tuple((normalizer or Normalizer()).normalize_report(report))
    statuses = tuple(result_status(o.status) for o in report.observations)

    return MilestoneOutcome(
        received=received,
        round_trip_ok=(received == sent),
        ack=decision.ack,
        ack_wire=decision.ack_wire,
        ack_code=decision.code,
        ack_message_code=ack_msh.message_code,
        ack_trigger_event=ack_msh.trigger_event,
        report=report,
        observations=rows,
        result_statuses=statuses,
    )
