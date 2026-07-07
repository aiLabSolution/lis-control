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

LIS-149 / DEC-06 adds the EDAN H99S **order-download / worklist** direction on the
same QRD substrate: the analyzer asks for the order selection for a barcode and the
host answers with `ORF^R04` carrying `PID` + `OBR` order rows. The query subject stays
the barcode in QRD-8; QRD-9 carries the analyzer's own sample number. EDAN H90-series
repurposes the OBR (spec §3.2.3, §6.2 accepted download) — one panel-level OBR whose
OBR-11 is a measurement integer (CBC = 1), OBR-4 is empty, OBR-2 echoes the sample
number, and OBR-20 echoes the scanned barcode (the join key; the accession stays
host-side) — so the generic per-analyte encoding is used only for non-EDAN queriers.

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
    "WHAT_WORKLIST",
    "WorklistOrder",
    "WorklistQueryResponse",
    "parse_query",
    "build_query",
    "parse_query_response",
    "build_query_response",
    "parse_worklist_query_response",
    "build_worklist_query_response",
    "correlates",
    "worklist_correlates",
]

_SEG = "\r"
_DEFAULT_ENCODING_CHARS = "^~\\&"
WHAT_RESULTS = "RES"  # QRD-9 "What Subject Filter" code for a results query
WHAT_WORKLIST = "OTH"  # QRD-9 default for a generic host-order/worklist query

# EDAN H90-series worklist ORF field values, replicating the vendor's accepted §6.2 download
# example field-for-field (semantics §3.2.3). The analyzer downloads a measurement PANEL, not
# per-analyte tests. OBR-4 is EMPTY in the download (EDANLAB^equipment is the device-REPORTING
# convention). The DECISIVE field is OBR-31, the measurement-item NAME the LIS transmits on a
# download (§3.2.3 "Reason for Study") — the panel int in OBR-11 alone is rejected as "not
# matched" (confirmed on the H99S bench).
_EDAN_REFERENCE_GROUP = "0"  # OBR-5
_EDAN_ANALYSIS_DOCTOR = "Administrator"  # OBR-18 (per §6.2 example)
_EDAN_SAMPLE_TYPE_WHOLE_BLOOD = "0"  # OBR-19
_EDAN_LOADING_METHOD = "1"  # OBR-30 (per §6.2 example)
_EDAN_PANEL_CBC = "1"  # OBR-11: CBC=1, CD=0, RET=2, ESR=23, … (only CBC implemented)
_EDAN_PANEL_CBC_NAME = "CBC"  # OBR-31 measurement-item name


def _is_edan_h90(query: QueryRecord) -> bool:
    """EDAN H90-series querier — ``H90`` in MSH-3.1 or ``EDANLAB`` in MSH-4 (spec §5.1).
    Mirrors the bridge ``Hl7HostQueryResponder.isEdanH90Series`` and ``oru._is_edan_h90``
    gates so the sim and the production bridge encode the worklist the same way."""
    msh3_c1 = query.sending_app.split("^", 1)[0].strip()
    return msh3_c1.upper() == "H90" or query.sending_facility.strip().upper() == "EDANLAB"


def _edan_panel_code(analyzer_codes: tuple[str, ...]) -> str:
    """EDAN OBR-11 measurement-panel code (spec §3.2.3). Only CBC (1) is implemented — the
    H99S bench runs CBC; the full panel table (RET/CD/ESR/…) is deferred, so any order
    maps to CBC rather than emitting no panel (which the analyzer rejects)."""
    return _EDAN_PANEL_CBC


def _edan_panel_name(analyzer_codes: tuple[str, ...]) -> str:
    """EDAN OBR-31 measurement-item name (spec §3.2.3 "Reason for Study"): the field the LIS
    transmits the measurement item through on a worklist download. Only CBC is implemented;
    multiple items would be ``+``-separated."""
    return _EDAN_PANEL_CBC_NAME


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


@dataclass(frozen=True)
class WorklistOrder:
    """One host order returned to an analyzer worklist query.

    ``analyzer_codes`` are the per-analyte codes the generic ORF carries (accession in
    OBR-2/3). The EDAN H90-series worklist is panel-level instead (spec §3.2.3 / §6.2): one OBR
    whose OBR-11 is a measurement-panel integer (``panel_code``), OBR-31 the measurement-item
    name (``panel_name``), and OBR-20 the scanned ``barcode`` — the accession is not on the
    download wire. So an EDAN order parses back with empty ``analyzer_codes``/``accession_number``
    and a populated ``panel_code`` (CBC = ``"1"``), ``panel_name`` (``"CBC"``) and ``barcode``."""

    accession_number: str
    patient_id: str
    analyzer_codes: tuple[str, ...]
    panel_code: str = ""
    panel_name: str = ""
    barcode: str = ""


@dataclass(frozen=True)
class WorklistQueryResponse:
    """The `ORF^R04` answer to an analyzer order-download query."""

    ack_code: str  # MSA-1
    query_id: str  # QRD-4 echoed from the request
    subject_id: str  # QRD-8 echoed from the request, usually the barcode
    orders: tuple[WorklistOrder, ...]


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
    obr = "|".join(["OBR", "1", "", _esc(result.specimen_id), _esc(result.order_code)])
    segs = [msh, msa, qrd, obr]
    for obs in result.observations:
        # Every value-bearing field is escaped, not just the unit/code — a reserved
        # character anywhere (value, range, flags) must not break the framing.
        segs.append(
            "|".join(
                ["OBX", obs.set_id, obs.value_type or "NM",
                 _esc_component(obs.raw_code, obs.raw_text, obs.raw_system),
                 "", _esc(obs.value), _esc(obs.raw_unit), _esc(obs.reference_range),
                 _esc(obs.abnormal_flags), "", "", _esc(obs.status or "F")]
            )
        )
    return _SEG.join(segs).encode("latin-1")


def parse_worklist_query_response(message: Message | bytes | str) -> WorklistQueryResponse:
    """Parse an `ORF^R04` worklist/order-download answer.

    The response echoes QRD-4/QRD-8 for correlation. A generic OBR carries one analyzer
    test code in OBR-4 (`^^^WBC^WBC`) and the accession in OBR-2/3; an EDAN H90-series OBR
    leaves OBR-4 empty and is panel-level, with the scanned barcode in OBR-20, the panel
    integer in OBR-11, the measurement-item name in OBR-31, and no accession on the download
    wire (spec §3.2.3 / §6.2). This is not a result parser: there are no OBX rows in the
    order-download payload.
    """
    msg = message if isinstance(message, Message) else parse_message(message)
    msh = msg.first("MSH")
    if msh is None:
        raise QueryError("message has no MSH segment; cannot identify as a worklist response")
    msa = msg.first("MSA")
    qrd = msg.first("QRD")
    pid = msg.first("PID")
    patient_id = ""
    if pid:
        patient_id = _u(msg, pid.component(3, 1) or pid.component(2, 1))

    orders: list[WorklistOrder] = []
    for obr in msg.all("OBR"):
        # Distinguish by OBR-4: the generic ORF carries the analyzer code there
        # (`^^^WBC^WBC`), while the EDAN H90-series worklist OBR leaves OBR-4 empty and is
        # panel-level (spec §6.2) — accession-free, with the panel int in OBR-11, the
        # analyzer sample number in OBR-2, and the scanned barcode in OBR-20 ("Patient ID
        # or Barcode", §3.2.3). The accession never rides the download wire.
        code = _u(msg, obr.component(4, 4) or obr.component(4, 1))
        if code:
            accession = _u(msg, obr.field(2) or obr.field(3))
            if accession or code:
                orders.append(
                    WorklistOrder(
                        accession_number=accession,
                        patient_id=patient_id,
                        analyzer_codes=(code,),
                    )
                )
        else:
            barcode = _u(msg, obr.field(20))
            panel = _u(msg, obr.field(11))
            panel_name = _u(msg, obr.field(31))
            if barcode or panel:
                orders.append(
                    WorklistOrder(
                        accession_number="",
                        patient_id=patient_id,
                        analyzer_codes=(),
                        panel_code=panel,
                        panel_name=panel_name,
                        barcode=barcode,
                    )
                )

    return WorklistQueryResponse(
        ack_code=_u(msg, msa.field(1)) if msa else "",
        query_id=_u(msg, qrd.field(4)) if qrd else "",
        subject_id=_u(msg, qrd.component(8, 1)) if qrd else "",
        orders=tuple(orders),
    )


def build_worklist_query_response(
    query: QueryRecord,
    orders: tuple[WorklistOrder, ...] | list[WorklistOrder],
    *,
    sending_app: str = "LIS",
    sending_facility: str = "LAB",
    response_datetime: str,
    control_id: str,
    ack_code: str = "AA",
    version: str = "2.4",
    processing_id: str = "P",
    application_ack_type: str = "3",
) -> bytes:
    """Build the host's H99S `ORF^R04` order-download answer.

    `QRD-8` echoes the analyzer's barcode subject for correlation. For an EDAN H90-series
    querier the reply replicates the vendor's accepted §6.2 download OBR field-for-field: the
    analyzer's sample number (echoed QRD-9) in OBR-2, an empty OBR-4, the panel integer in
    OBR-11, the scanned barcode (echoed QRD-8) in OBR-20 — the join key the follow-up ORU
    echoes; the accession never rides the wire — and the measurement-item NAME in OBR-31, the
    field §3.2.3 says the LIS transmits the item through on a download (the field the H99S
    reads to accept; OBR-11's int alone is rejected as "not matched"). A non-EDAN querier
    keeps the generic per-analyte OBR (accession in OBR-2/3, code in OBR-4).
    """
    order_rows = tuple(orders)
    patient_id = next((order.patient_id for order in order_rows if order.patient_id), "")
    msh = "|".join(
        ["MSH", _DEFAULT_ENCODING_CHARS, sending_app, sending_facility,
         query.sending_app, query.sending_facility, response_datetime, "",
         "ORF^R04", control_id, processing_id, version, "", "", "", application_ack_type]
    )
    msa = "|".join(["MSA", ack_code, query.control_id])
    qrd = "|".join(
        ["QRD", query.query_datetime, query.format_code or "R", query.priority or "I",
         query.query_id, "", "", "", query.subject_id, query.what_subject or WHAT_WORKLIST]
    )
    segs = [msh, msa, qrd, "|".join(["PID", "1", "", _esc(patient_id)])]

    edan = _is_edan_h90(query)
    set_id = 1
    for order in order_rows:
        codes = tuple(c for c in order.analyzer_codes if c)
        if edan:
            if not codes:
                continue
            # One EDAN panel OBR replicating the vendor's accepted §6.2 download field-for-field
            # (OBR-1 empty): OBR-2 = the analyzer's own sample number (echoed QRD-9), OBR-4 empty
            # (EDANLAB^equipment is the ORU-reporting convention), OBR-5 = reference group,
            # OBR-11 = panel int, OBR-18 = analysis doctor, OBR-19 = sample type, OBR-20 = the
            # scanned barcode (echoed QRD-8; the join key, accession stays host-side), OBR-30 =
            # loading method, OBR-31 = the measurement-item NAME the LIS transmits on a download.
            obr = [""] * 32
            obr[0] = "OBR"
            obr[2] = _esc(query.what_subject)
            obr[5] = _EDAN_REFERENCE_GROUP
            obr[11] = _edan_panel_code(codes)
            obr[18] = _EDAN_ANALYSIS_DOCTOR
            obr[19] = _EDAN_SAMPLE_TYPE_WHOLE_BLOOD
            obr[20] = _esc(query.subject_id)
            obr[30] = _EDAN_LOADING_METHOD
            obr[31] = _edan_panel_name(codes)
            segs.append("|".join(obr))
        else:
            for code in codes:
                segs.append(
                    "|".join(
                        ["OBR", str(set_id), _esc(order.accession_number),
                         _esc(order.accession_number), _esc_component("", "", "", code, code),
                         "", "", "", "", "", "", "A"]
                    )
                )
                set_id += 1
    return _SEG.join(segs).encode("latin-1")


def correlates(query: QueryRecord, response: QueryResponse) -> bool:
    """True when ``response`` is an accepted answer to ``query``: the response echoes
    the request's query id, was accepted (`MSA-1 = AA`), and returned the queried
    subject (the specimen ids match).

    Both the query id **and** the subject must be non-empty — an empty id or specimen
    would otherwise *vacuously* match an empty echo/specimen and bind an answer to the
    wrong request. (This is identity correlation, not authentication: any party that
    saw the query can reproduce its ids — fine for the simulator substrate.)"""
    return (
        bool(query.query_id)
        and bool(query.subject_id)
        and query.query_id == response.query_id
        and response.ack_code == "AA"
        and query.subject_id == response.report.specimen_id
    )


def worklist_correlates(query: QueryRecord, response: WorklistQueryResponse) -> bool:
    """True when an order-download answer is accepted and echoes the query identity.

    Unlike a results-query, the returned accession may differ from the barcode in
    QRD-8 after host reconciliation, so correlation uses the echoed QRD subject, not
    OBR-2/3.
    """
    return (
        bool(query.query_id)
        and bool(query.subject_id)
        and query.query_id == response.query_id
        and query.subject_id == response.subject_id
        and response.ack_code == "AA"
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
