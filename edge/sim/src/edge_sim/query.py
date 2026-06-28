"""HL7 v2 bidirectional **host-query** (QRD/QRF) — LIS-18 / S1.6.

Stage 1's bidirectional path: a (simulated) EDAN H60S host-queries the LIS for a
sample — an HL7 v2 query message (`QRY^R02`) carrying a **QRD** (query definition)
and **QRF** (query filter) — and the host **answers** with an `ORF^R04` (response to
results query) that acknowledges the query (`MSA-1 = AA`), **echoes the QRD query id**
(so the requester correlates the answer to its request), and carries the result
(`OBR`/`OBX`) — which normalizes through the existing S1.2 pipeline to a Result. This
is the milestone exit-gate bullet "an EDAN H60S host-query (QRD/QRF) is answered and a
result returns" (`LIS_IMPLEMENTATION_PLAN.md` §1).

Scope is the **simulator/protocol** substrate (edge/sim, no hardware). The *live*
bidirectional host-query deployment to pilot sites is deferred post-pilot under change
control (ADR-0008); building the QRD/QRF correlation here de-risks that rollout and
gives a conformance fixture pair, exactly as Stage 2's bidirectional ASTM path stays
simulator-driven until a bidirectional unit is on hand.

Tolerant, like the rest of the harness: a missing QRD/QRF/MSA field yields `""`; only
a message with no `MSH` is rejected (it cannot be identified). Builders emit canonical
`\\r`-separated segments and apply no wire framing — the MLLP transport does that, so a
query/response survives the `0x0B … 0x1C 0x0D` envelope byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hl7 import Message, parse_message, unescape
from .oru import OruParseError, OruReport, parse_oru_r01

__all__ = [
    "QueryRecord",
    "QueryResponse",
    "QueryError",
    "WHAT_RESULTS",
    "parse_query",
    "build_query",
    "parse_query_response",
    "build_query_response",
    "correlates",
]

_SEG = "\r"
_DEFAULT_ENCODING_CHARS = "^~\\&"
WHAT_RESULTS = "RES"  # QRD-9 "What Subject Filter" code for a results query


class QueryError(Exception):
    """Raised when a message cannot be read as a query / query response at all."""


@dataclass(frozen=True)
class QueryRecord:
    """The QRD/QRF content of a host-query (`QRY^R02`)."""

    query_datetime: str  # QRD-1
    format_code: str  # QRD-2 (R = record-oriented)
    priority: str  # QRD-3 (I = immediate, D = deferred)
    query_id: str  # QRD-4 — the correlation id the response echoes
    subject_id: str  # QRD-8 who/what subject filter (the sample/specimen queried)
    what_subject: str  # QRD-9 what subject filter (e.g. RES = results)
    control_id: str  # MSH-10 of the carrying query message
    sending_app: str  # MSH-3 (the querier, e.g. the analyzer)
    sending_facility: str  # MSH-4


@dataclass(frozen=True)
class QueryResponse:
    """The content of an `ORF^R04` answering a host-query: the acknowledgment, the
    echoed query id, and the returned result (parsed for normalization)."""

    ack_code: str  # MSA-1 (AA on accept)
    query_id: str  # QRD-4 echoed from the request
    report: OruReport  # the OBR/OBX result the response returned


def _u(msg: Message, value: str) -> str:
    return unescape(value, msg.encoding)


def parse_query(message: Message | bytes | str) -> QueryRecord:
    """Extract a :class:`QueryRecord` from a `QRY^R02` (or any QRD-bearing message)."""
    msg = message if isinstance(message, Message) else parse_message(message)
    msh = msg.first("MSH")
    if msh is None:
        raise QueryError("message has no MSH segment; cannot identify as a query")
    qrd = msg.first("QRD")
    if qrd is None:
        raise QueryError("message has no QRD segment; not a host-query")
    return QueryRecord(
        query_datetime=_u(msg, qrd.field(1)),
        format_code=_u(msg, qrd.field(2)),
        priority=_u(msg, qrd.field(3)),
        query_id=_u(msg, qrd.field(4)),
        subject_id=_u(msg, qrd.component(8, 1)),
        what_subject=_u(msg, qrd.component(9, 1)),
        control_id=_u(msg, msh.field(10)),
        sending_app=_u(msg, msh.field(3)),
        sending_facility=_u(msg, msh.field(4)),
    )


def build_query(
    *,
    query_id: str,
    subject_id: str,
    sending_app: str = "H60S",
    sending_facility: str = "EDAN",
    receiving_app: str = "LIS",
    receiving_facility: str = "LAB",
    control_id: str,
    query_datetime: str,
    what_subject: str = WHAT_RESULTS,
    version: str = "2.4",
    processing_id: str = "P",
) -> bytes:
    """Build a `QRY^R02` host-query for ``subject_id`` (a sample/specimen).

    QRD-4 carries ``query_id`` — the correlation id the response must echo. The QRF
    repeats the subject as its where-filter. Returns the application payload; the
    caller applies MLLP framing."""
    msh = "|".join(
        ["MSH", _DEFAULT_ENCODING_CHARS, sending_app, sending_facility,
         receiving_app, receiving_facility, query_datetime, "", "QRY^R02",
         control_id, processing_id, version]
    )
    # QRD: 1=dt 2=R(record) 3=I(immediate) 4=query_id 5,6,7 empty 8=subject 9=what
    qrd = "|".join(
        ["QRD", query_datetime, "R", "I", query_id, "", "", "", subject_id, what_subject]
    )
    # QRF: 1=where-subject-filter (the same subject); other filters left empty.
    qrf = "|".join(["QRF", subject_id])
    return _SEG.join([msh, qrd, qrf]).encode("latin-1")


def parse_query_response(message: Message | bytes | str) -> QueryResponse:
    """Parse an `ORF^R04` answering a host-query into a :class:`QueryResponse`.

    Reads the acknowledgment (`MSA-1`), the echoed query id (`QRD-4`), and the
    returned result (`OBR`/`OBX`, via the tolerant ORU parser)."""
    msg = message if isinstance(message, Message) else parse_message(message)
    msh = msg.first("MSH")
    if msh is None:
        raise QueryError("message has no MSH segment; cannot identify as a query response")
    msa = msg.first("MSA")
    qrd = msg.first("QRD")
    try:
        report = parse_oru_r01(msg)
    except OruParseError as exc:  # pragma: no cover - MSH presence already checked
        raise QueryError(f"query response carries no readable result: {exc}") from exc
    return QueryResponse(
        ack_code=_u(msg, msa.field(1)) if msa else "",
        query_id=_u(msg, qrd.field(4)) if qrd else "",
        report=report,
    )


def build_query_response(
    query: QueryRecord,
    result: OruReport,
    *,
    sending_app: str = "LIS",
    sending_facility: str = "LAB",
    response_datetime: str,
    control_id: str,
    ack_code: str = "AA",
    version: str = "2.4",
    processing_id: str = "P",
) -> bytes:
    """Build the host's `ORF^R04` answer to ``query``, returning ``result``.

    Acknowledges the query (`MSA-1`, default `AA`, MSA-2 echoes the query's MSH-10),
    echoes the QRD query id so the requester correlates the answer, and serializes the
    result's `OBR`/`OBX` (re-escaping any reserved characters in unit/code). Routing is
    swapped relative to the inbound query. Returns the application payload (no framing)."""
    msh = "|".join(
        ["MSH", _DEFAULT_ENCODING_CHARS, sending_app, sending_facility,
         query.sending_app, query.sending_facility, response_datetime, "",
         "ORF^R04", control_id, processing_id, version]
    )
    msa = "|".join(["MSA", ack_code, query.control_id])
    # Echo the QRD (correlation id + subject) so the requester matches the answer.
    qrd = "|".join(
        ["QRD", query.query_datetime, query.format_code or "R", query.priority or "I",
         query.query_id, "", "", "", query.subject_id, query.what_subject or WHAT_RESULTS]
    )
    obr = "|".join(["OBR", "1", "", result.specimen_id, result.order_code])
    segs = [msh, msa, qrd, obr]
    for obs in result.observations:
        segs.append(
            "|".join(
                ["OBX", obs.set_id, obs.value_type or "NM",
                 _esc_component(obs.raw_code, obs.raw_text, obs.raw_system),
                 "", obs.value, _esc(obs.raw_unit), obs.reference_range,
                 obs.abnormal_flags, "", "", obs.status or "F"]
            )
        )
    return _SEG.join(segs).encode("latin-1")


def correlates(query: QueryRecord, response: QueryResponse) -> bool:
    """True when ``response`` is an accepted answer to ``query``: the response echoes
    the request's query id, was accepted (`MSA-1 = AA`), and returned the queried
    subject (the specimen ids match)."""
    return (
        bool(query.query_id)
        and query.query_id == response.query_id
        and response.ack_code == "AA"
        and query.subject_id == response.report.specimen_id
    )


def _esc(value: str) -> str:
    """Re-escape HL7 reserved characters in a field value so a round-tripped unit/code
    (e.g. ``10^9/L``) is emitted as conformant ``10\\S\\9/L`` rather than splitting the
    component. Mirrors :func:`edge_sim.hl7.unescape` in reverse for the reserved set."""
    return (
        value.replace("\\", "\\E\\")
        .replace("^", "\\S\\")
        .replace("~", "\\R\\")
        .replace("&", "\\T\\")
        .replace("|", "\\F\\")
    )


def _esc_component(*parts: str) -> str:
    """Join CE components with ``^`` after escaping each (the component separators
    between them are real, the ones *inside* a part are escaped)."""
    return "^".join(_esc(p) for p in parts)
