"""SnibeLis ASTM E1394 session/query simulator -- LIS-108 / S3.0a.

The SnibeLis manual examples show a simplified ASTM envelope:

    ENQ, STX, CR-separated E1394 records, ETX, EOT

with an ACK required after each control code. That is not the same as the
checksummed E1381 frames in ``edge_sim.astm``. This module models the documented
SnibeLis variant so the MAGLUMI X3 path has a fixture-level proof before a live
SnibeLis capture decides whether production should use full E1381 or a
SnibeLis-specific receiver mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .astm import ACK, ENQ, EOT, ETX, STX
from .e1394 import AstmMessage, Record, parse_e1394
from .fixtures import Fixture

__all__ = [
    "SnibeLisSessionEvent",
    "SnibeLisSessionResult",
    "SnibeLisQuery",
    "SnibeLisQueryExchange",
    "snibelis_frame",
    "snibelis_deframe",
    "run_snibelis_session",
    "run_fixture_session",
    "parse_queries",
    "split_assays",
    "build_order_download_response",
    "run_query_exchange",
]

_CONTROL_SEQUENCE = (
    ("ENQ", ENQ),
    ("STX", STX),
    ("ETX", ETX),
    ("EOT", EOT),
)


@dataclass(frozen=True)
class SnibeLisSessionEvent:
    """One control-code exchange in the simplified SnibeLis session."""

    control: str
    sent: bytes
    response: bytes
    actor: str


@dataclass
class SnibeLisSessionResult:
    """Outcome of a simplified SnibeLis ASTM E1394 session."""

    payload: bytes = b""
    wire: bytes = b""
    message: AstmMessage | None = None
    complete: bool = False
    aborted: bool = False
    events: list[SnibeLisSessionEvent] = field(default_factory=list)

    @property
    def acked_controls(self) -> tuple[str, ...]:
        return tuple(event.control for event in self.events if event.response == bytes([ACK]))


@dataclass(frozen=True)
class SnibeLisQuery:
    """The Q-record fields SnibeLis uses for host order download."""

    seq: str
    sample_id: str
    assays_requested: tuple[str, ...]
    status: str
    raw: str


@dataclass(frozen=True)
class SnibeLisQueryExchange:
    """A Q-record upload followed by the host's H/P/O/L order response."""

    query_session: SnibeLisSessionResult
    query: SnibeLisQuery
    response_payload: bytes
    response_session: SnibeLisSessionResult
    response_message: AstmMessage


def snibelis_frame(payload: bytes | str) -> bytes:
    """Wrap an E1394 payload in the documented SnibeLis control envelope."""

    body = _wire_payload_bytes(payload)
    return bytes([ENQ, STX]) + body + bytes([ETX, EOT])


def snibelis_deframe(wire: bytes | bytearray) -> bytes:
    """Extract the E1394 payload from a documented SnibeLis envelope."""

    data = bytes(wire)
    if len(data) < 4 or data[0] != ENQ or data[1] != STX or data[-2] != ETX or data[-1] != EOT:
        raise ValueError("not a SnibeLis ENQ/STX/payload/ETX/EOT envelope")
    return data[2:-2]


def run_fixture_session(fixture: Fixture, *, actor: str = "snibelis") -> SnibeLisSessionResult:
    """Run a fixture's payload through the simplified SnibeLis session."""

    return run_snibelis_session(fixture.message_bytes, actor=actor)


def run_snibelis_session(payload: bytes | str, *, actor: str = "snibelis") -> SnibeLisSessionResult:
    """Drive one documented SnibeLis session and ACK each control code.

    The payload bytes are normalized to CR-separated E1394 records because the
    ASTM record terminator is CR even when a checked-in synthetic fixture uses
    platform newlines.
    """

    body = _payload_bytes(payload)
    events = [
        SnibeLisSessionEvent(control, bytes([byte]), bytes([ACK]), actor)
        for control, byte in _CONTROL_SEQUENCE
    ]
    return SnibeLisSessionResult(
        payload=body,
        wire=snibelis_frame(body),
        message=parse_e1394(body),
        complete=True,
        events=events,
    )


def parse_queries(payload: bytes | str) -> tuple[SnibeLisQuery, ...]:
    """Parse Q records from a SnibeLis ASTM E1394 payload."""

    msg = parse_e1394(_payload_bytes(payload))
    queries: list[SnibeLisQuery] = []
    for rec in msg.records:
        if rec.type != "Q":
            continue
        queries.append(
            SnibeLisQuery(
                seq=rec.field(2),
                sample_id=_last_component(rec.field(3), rec),
                assays_requested=split_assays(rec.field(5), rec),
                status=_last_non_empty_field(rec),
                raw=rec.delimiters.field.join(rec.fields),
            )
        )
    return tuple(queries)


def split_assays(value: str, rec: Record) -> tuple[str, ...]:
    """Split a SnibeLis assay field into analyzer-native assay codes."""

    assays = []
    for item in (value or "").split(rec.delimiters.repeat):
        code = _last_component(item, rec).strip()
        if code:
            assays.append(code)
    return tuple(assays)


def build_order_download_response(
    query: SnibeLisQuery,
    assays: tuple[str, ...] | list[str],
    *,
    transmitter: str = "Maglumi User",
    receiver: str = "Lis",
    password: str = "PSWD",
    date: str = "20260703",
) -> bytes:
    """Build the host's H/P/O/L response to a SnibeLis Q-record."""

    normalized = tuple(a.strip() for a in assays if a and a.strip())
    if not normalized:
        raise ValueError("at least one assay is required for a SnibeLis order response")

    assay_field = "\\".join(f"^^^{assay}" for assay in normalized)
    records = [
        f"H|\\^&||{password}|{transmitter}|||||{receiver}||P|E1394-97|{date}",
        "P|1",
        f"O|1|{query.sample_id}||{assay_field}|R",
        "L|1|N",
    ]
    return "\r".join(records).encode("latin-1")


def run_query_exchange(
    query_payload: bytes | str,
    assays: tuple[str, ...] | list[str],
    *,
    transmitter: str = "Maglumi User",
    receiver: str = "Lis",
    date: str = "20260703",
) -> SnibeLisQueryExchange:
    """Run SnibeLis query upload, then host order-download response."""

    query_session = run_snibelis_session(query_payload, actor="snibelis")
    queries = parse_queries(query_session.payload)
    if not queries:
        raise ValueError("SnibeLis query exchange requires at least one Q record")
    query = queries[0]
    response_payload = build_order_download_response(
        query,
        assays,
        transmitter=transmitter,
        receiver=receiver,
        date=date,
    )
    response_session = run_snibelis_session(response_payload, actor="host")
    if response_session.message is None:  # pragma: no cover - run_snibelis_session always parses
        raise ValueError("SnibeLis order response did not parse")
    return SnibeLisQueryExchange(
        query_session=query_session,
        query=query,
        response_payload=response_payload,
        response_session=response_session,
        response_message=response_session.message,
    )


def _payload_bytes(payload: bytes | str) -> bytes:
    text = payload.decode("latin-1") if isinstance(payload, (bytes, bytearray)) else str(payload)
    records = [record for record in text.replace("\r\n", "\r").replace("\n", "\r").split("\r") if record]
    return "\r".join(records).encode("latin-1")


def _wire_payload_bytes(payload: bytes | str) -> bytes:
    body = _payload_bytes(payload)
    if body and not body.endswith(b"\r"):
        return body + b"\r"
    return body


def _last_component(value: str, rec: Record) -> str:
    comps = [c for c in (value or "").split(rec.delimiters.component) if c]
    return comps[-1] if comps else (value or "")


def _last_non_empty_field(rec: Record) -> str:
    for field_value in reversed(rec.fields):
        if field_value:
            return field_value
    return ""
