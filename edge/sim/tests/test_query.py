"""Bidirectional host-query (QRD/QRF) — LIS-18 / S1.6.

Stage 1's bidirectional exit-gate bullet: an EDAN H60S host-query (QRY^R02 with
QRD/QRF) is **answered** (ORF^R04, MSA-1 = AA, echoing the query id) and **a result
returns** — which normalizes through the S1.2 pipeline to a Result. Proven on the
captured query fixture answered from the EDAN H60S result fixture, over MLLP framing.
"""

from pathlib import Path

import pytest

from edge_sim.fixtures import load_fixture
from edge_sim.mllp import MllpDecoder, frame
from edge_sim.normalize import STATUS_NORMALIZED, Normalizer
from edge_sim.oru import OruReport, parse_oru_r01
from edge_sim.query import (
    QueryError,
    QueryRecord,
    QueryResponse,
    WorklistOrder,
    build_worklist_query_response,
    build_query,
    build_query_response,
    correlates,
    parse_query,
    parse_query_response,
    parse_worklist_query_response,
    worklist_correlates,
)


def _query_record(query_id="Q0231-01", subject_id="SPEC-0231"):
    return QueryRecord(
        query_datetime="", format_code="R", priority="I", query_id=query_id,
        subject_id=subject_id, what_subject="RES", control_id="C1",
        sending_app="H60S", sending_facility="EDAN",
    )


def _response(ack_code="AA", query_id="Q0231-01", specimen="SPEC-0231"):
    report = OruReport(
        message_type="ORF^R04", sending_app="", sending_facility="",
        message_control_id="", patient_id="", patient_name="",
        specimen_id=specimen, order_code="", observations=(),
    )
    return QueryResponse(ack_code=ack_code, query_id=query_id, report=report)

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
QRY = FIXTURES_ROOT / "edan-h60s-host-query-qry-r02"
H99S_WORKLIST_QRY = FIXTURES_ROOT / "edan-h99s-worklist-query-qry-r02"
EDAN_RESULT = FIXTURES_ROOT / "edan-h60s-oru-r01"
WHEN_Q = "20260628093500"
WHEN_R = "20260628093501"
WHEN_H99S = "20260703112800"


def _edan_result():
    return parse_oru_r01(load_fixture(EDAN_RESULT).message_bytes)


def test_parse_query_reads_qrd_qrf():
    q = parse_query(load_fixture(QRY).message_bytes)
    assert q.query_id == "Q0231-01"
    assert q.subject_id == "SPEC-0231"
    assert q.what_subject == "RES"
    assert q.priority == "I"
    assert q.format_code == "R"
    assert q.sending_app == "H60S"
    assert q.control_id == "H60SQ0231"


def test_query_fixture_matches_expected_block():
    fx = load_fixture(QRY)
    q = parse_query(fx.message_bytes)
    exp = fx.expected
    assert q.query_id == exp["query_id"]
    assert q.subject_id == exp["subject_id"]
    assert q.what_subject == exp["what_subject"]


def test_build_query_round_trips():
    built = build_query(
        query_id="Q0231-01", subject_id="SPEC-0231",
        control_id="H60SQ0231", query_datetime=WHEN_Q,
    )
    q = parse_query(built)
    assert q.query_id == "Q0231-01"
    assert q.subject_id == "SPEC-0231"
    assert q.what_subject == "RES"
    # the built query carries the QRY^R02 message type
    assert b"QRY^R02" in built


def test_parse_query_requires_qrd():
    with pytest.raises(QueryError):
        parse_query(b"MSH|^~\\&|H60S|EDAN|LIS|LAB|20260628093500||QRY^R02|X|P|2.4")


def test_host_answers_query_and_result_returns():
    """The exit gate: a host-query is answered (MSA-1=AA, query id echoed) and the
    returned result normalizes to the EDAN H60S Result rows."""
    q = parse_query(load_fixture(QRY).message_bytes)
    orf = build_query_response(q, _edan_result(), response_datetime=WHEN_R, control_id="LISR0231")
    resp = parse_query_response(orf)

    assert resp.ack_code == "AA"
    assert resp.query_id == "Q0231-01"  # echoes the request's QRD-4
    assert resp.report.specimen_id == "SPEC-0231"
    assert correlates(q, resp) is True

    rows = Normalizer().normalize_report(resp.report)
    assert [r.raw_code for r in rows] == ["WBC", "RBC", "HGB", "HCT", "MCV", "PLT"]
    assert [r.loinc for r in rows] == ["6690-2", "789-8", "718-7", "4544-3", "787-2", "777-3"]
    assert [r.raw_unit for r in rows] == ["10^9/L", "10^12/L", "g/L", "%", "fL", "10^9/L"]
    assert all(r.status == STATUS_NORMALIZED for r in rows)


def test_bidirectional_exchange_over_mllp_framing():
    """Query and answer survive MLLP frame/de-frame byte-for-byte and still correlate."""
    q_bytes = load_fixture(QRY).message_bytes
    q = parse_query(q_bytes)
    orf = build_query_response(q, _edan_result(), response_datetime=WHEN_R, control_id="LISR0231")

    # both messages go over the wire framed; the listener de-frames each in turn.
    decoder = MllpDecoder()
    received = decoder.feed(frame(q_bytes) + frame(orf))
    assert len(received) == 2
    assert received[0] == q_bytes  # query survived framing
    assert received[1] == orf  # answer survived framing

    q_rx = parse_query(received[0])
    resp_rx = parse_query_response(received[1])
    assert correlates(q_rx, resp_rx) is True


def test_correlation_rejects_mismatched_query_id():
    q = parse_query(load_fixture(QRY).message_bytes)
    # answer a *different* query id — must not correlate to our request.
    other = q.__class__(**{**q.__dict__, "query_id": "Q9999-99"})
    orf = build_query_response(other, _edan_result(), response_datetime=WHEN_R, control_id="LISR0231")
    resp = parse_query_response(orf)
    assert resp.query_id == "Q9999-99"
    assert correlates(q, resp) is False


def test_correlation_rejects_non_accept_ack():
    q = parse_query(load_fixture(QRY).message_bytes)
    orf = build_query_response(
        q, _edan_result(), response_datetime=WHEN_R, control_id="LISR0231", ack_code="AE"
    )
    resp = parse_query_response(orf)
    assert resp.ack_code == "AE"
    assert correlates(q, resp) is False


def test_response_re_escapes_reserved_chars_in_units():
    """A unit carrying the component separator (10^9/L) is re-escaped on the wire
    (10\\S\\9/L) so the answer is conformant HL7 and unescapes back."""
    q = parse_query(load_fixture(QRY).message_bytes)
    orf = build_query_response(q, _edan_result(), response_datetime=WHEN_R, control_id="LISR0231")
    assert b"10\\S\\9/L" in orf  # escaped on the wire
    resp = parse_query_response(orf)
    assert resp.report.observations[0].raw_unit == "10^9/L"  # unescaped on parse


def test_response_msa2_echoes_query_control_id():
    """MSA-2 of the answer echoes the query's MSH-10 (the message it acknowledges)."""
    q = parse_query(load_fixture(QRY).message_bytes)
    orf = build_query_response(q, _edan_result(), response_datetime=WHEN_R, control_id="LISR0231")
    msa = next(s for s in orf.split(b"\r") if s.startswith(b"MSA"))
    assert msa.decode("ascii").split("|")[2] == q.control_id  # "H60SQ0231"


# --- EDAN H99S worklist/order-download query (LIS-149 / DEC-06) -------------


def test_h99s_worklist_query_fixture_reads_barcode_subject():
    fx = load_fixture(H99S_WORKLIST_QRY)
    q = parse_query(fx.message_bytes)
    exp = fx.expected
    assert q.query_id == exp["query_id"]  # QRD-4 = "1" on the real wire
    assert q.subject_id == "DEV01260000000000002"
    assert q.subject_id == exp["barcode"]
    assert q.what_subject == exp["sample_number"]  # QRD-9 = analyzer sample number "1"
    assert q.control_id == exp["control_id"]  # MSH-10 = "3"
    assert q.sending_app.split("^", 1)[0] == exp["sending_app_msh3_1"]  # MSH-3.1 = "H90"
    assert q.sending_facility == exp["sending_facility"]  # MSH-4 = "EDANLAB"


def test_h99s_worklist_answer_echoes_barcode_and_panel():
    q = parse_query(load_fixture(H99S_WORKLIST_QRY).message_bytes)
    # accession_number is unused for an EDAN build (the barcode comes from the query, and
    # the accession never rides the download wire); the codes derive the CBC panel.
    order = WorklistOrder(
        accession_number="2",
        patient_id="17",
        analyzer_codes=("WBC", "HGB"),
    )

    orf = build_worklist_query_response(
        q, (order,), response_datetime=WHEN_H99S, control_id="ORFQ-1"
    )
    resp = parse_worklist_query_response(orf)

    assert b"ORF^R04" in orf
    assert b"|P|2.4||||3\r" in orf  # EDAN H90-series MSH-16 query-response type
    assert b"MSA|AA|3\r" in orf  # MSA-2 echoes the query control id (MSH-10 = 3)
    assert b"QRD|20260706|R|1|1||||DEV01260000000000002|1\r" in orf  # echoed QRD
    assert b"PID|1||17\r" in orf
    # ONE EDAN panel OBR replicating the accepted §6.2 download field-for-field: OBR-2 =
    # sample no (1), OBR-5 = 0, OBR-11 = CBC int (1), OBR-18 = Administrator, OBR-19 = 0,
    # OBR-20 = barcode (QRD-8), OBR-30 = 1, OBR-31 = CBC name (the accept key).
    assert b"OBR||1|||0||||||1|||||||Administrator|0|DEV01260000000000002||||||||||1|CBC" in orf
    assert orf.count(b"OBR|") == 1  # WBC+HGB collapse to one panel, not per-analyte
    assert b"^^^WBC^WBC" not in orf  # no generic per-analyte encoding
    assert b"EDANLAB^H90" not in orf  # OBR-4 empty in the download direction

    assert resp.ack_code == "AA"
    assert resp.query_id == "1"
    assert resp.subject_id == "DEV01260000000000002"
    assert worklist_correlates(q, resp) is True
    assert len(resp.orders) == 1
    assert resp.orders[0].barcode == "DEV01260000000000002"  # OBR-20 (the join key)
    assert resp.orders[0].panel_code == "1"  # CBC int, from OBR-11
    assert resp.orders[0].panel_name == "CBC"  # measurement-item name, from OBR-31
    assert resp.orders[0].accession_number == ""  # accession not on the download wire
    assert resp.orders[0].analyzer_codes == ()  # panel-level, not per-analyte


def test_h99s_worklist_exchange_over_mllp_framing():
    q_bytes = load_fixture(H99S_WORKLIST_QRY).message_bytes
    q = parse_query(q_bytes)
    orf = build_worklist_query_response(
        q,
        (WorklistOrder(accession_number="2", patient_id="17", analyzer_codes=("WBC",)),),
        response_datetime=WHEN_H99S,
        control_id="ORFQ-1",
    )

    decoder = MllpDecoder()
    received = decoder.feed(frame(q_bytes) + frame(orf))

    assert received[0] == q_bytes
    assert received[1] == orf
    assert worklist_correlates(parse_query(received[0]), parse_worklist_query_response(received[1]))


def test_worklist_answer_non_edan_uses_generic_per_analyte_obr():
    """A non-EDAN-H90 querier (not H90 in MSH-3.1, not EDANLAB in MSH-4) keeps the generic
    per-analyte ORF: accession in OBR-2/3, code in OBR-4, one OBR per code — no EDAN panel
    repurposing. Guards the non-EDAN host-query users against regression (mirror of the
    bridge's nonEdanKeepsGenericPerTestOrf)."""
    q = QueryRecord(
        query_datetime="20260706", format_code="R", priority="I", query_id="Q9",
        subject_id="SPEC-9", what_subject="RES", control_id="C9",
        sending_app="ACME", sending_facility="ACMEDX",
    )
    order = WorklistOrder(accession_number="2", patient_id="17", analyzer_codes=("WBC", "HGB"))
    orf = build_worklist_query_response(q, (order,), response_datetime=WHEN_H99S, control_id="ORF9")
    resp = parse_worklist_query_response(orf)

    assert b"OBR|1|2|2|^^^WBC^WBC|||||||A" in orf
    assert b"OBR|2|2|2|^^^HGB^HGB|||||||A" in orf
    assert b"EDANLAB^H90" not in orf
    # generic parse recovers the per-analyte codes and the accession from OBR-2/3
    assert [(o.accession_number, o.analyzer_codes) for o in resp.orders] == [
        ("2", ("WBC",)),
        ("2", ("HGB",)),
    ]
    assert all(o.panel_code == "" and o.panel_name == "" and o.barcode == "" for o in resp.orders)


def test_h99s_worklist_answer_echoes_barcode_join_key_in_obr20():
    """LIS-149 AC1 (forward half): the EDAN worklist ORF echoes the scanned barcode in
    OBR-20 (the "Patient ID or Barcode" field, spec §6.2) so the analyzer's follow-up ORU
    can be reconciled back to the same OpenELIS order — no orphan sample. The barcode is
    read back out of the parsed response (not a literal) and anchored against the query
    subject, so a dropped barcode (emitted "") cannot pass vacuously. The internal accession
    never rides the wire; the host reconciles the barcode to it on each leg.

    The return half (a real result-bearing ORU^R01 reconciled back via its OBR-20 barcode)
    is now closed by its sibling below,
    ``test_h99s_worklist_result_closes_loop_no_orphan`` — the ORU parser learned the OBR-20
    barcode preference (LIS-149 AC3). Still not validated on real H99S result wire (the
    H99S ORUs captured so far are MSH-only connection-test pings; the sibling H60S and spec
    §6.1 show the layout) — spec-backed + H60S-corroborated only, per that test's docstring."""
    q = parse_query(load_fixture(H99S_WORKLIST_QRY).message_bytes)
    order = WorklistOrder(accession_number="2", patient_id="17", analyzer_codes=("WBC", "HGB"))
    orf = build_worklist_query_response(q, (order,), response_datetime=WHEN_H99S, control_id="ORFQ-1")
    resp = parse_worklist_query_response(orf)

    assert worklist_correlates(q, resp) is True
    assert len(resp.orders) == 1
    assert resp.orders[0].barcode == q.subject_id  # OBR-20 echoes the queried barcode
    assert resp.orders[0].accession_number == ""  # accession stays host-side, off the wire
    assert resp.orders[0].panel_code == "1"  # CBC panel int (OBR-11)
    assert resp.orders[0].panel_name == "CBC"  # measurement-item name (OBR-31, the accept key)


def test_h99s_worklist_result_closes_loop_no_orphan():
    """LIS-149 AC3 return leg: the analyzer's follow-up result ORU^R01 reports against
    its OWN sample counter in OBR-2 (meaningless off-instrument) but echoes the SAME
    barcode the worklist ORF gave it (above) in OBR-20 — the only reliable join key back
    to the originally-submitted order (spec §3.2.3 / §6.1; H60S-corroborated; NOT yet
    captured on real H99S wire — the H99S ORUs captured so far are MSH-only
    connection-test pings). The sim has no OE order-menu lookup (unlike the production
    bridge's ``BarcodeAccessionResolver``) — the barcode IS the join key here, so the
    originally-submitted order's ``accession_number`` is modelled as the barcode itself.

    Ports the bridge ``HostQueryResultRoundTripTest`` return-half assertion (see the
    design spec's bridge test list). A self-consistency check alone — comparing two
    values both DERIVED by the code under test (the ORF-parsed barcode vs. the
    ORU-parsed specimen_id) — would be vacuous if a bug affected both derivations the
    same way, so this also anchors to ``order.accession_number``: a ground-truth value
    fixed BEFORE any parsing happens and never even serialized onto the EDAN worklist
    wire (``build_worklist_query_response`` ignores it for EDAN), so it cannot leak in
    from the code under test."""
    barcode = load_fixture(H99S_WORKLIST_QRY).expected["barcode"]  # real bench-captured ground truth
    q = parse_query(load_fixture(H99S_WORKLIST_QRY).message_bytes)
    # The originally-submitted order: on this deployment the barcode IS the join key
    # (no separate OE-side numeric accession in the sim world), so its accession is
    # anchored to that same ground-truth barcode.
    order = WorklistOrder(accession_number=barcode, patient_id="17", analyzer_codes=("WBC", "HGB"))
    orf = build_worklist_query_response(q, (order,), response_datetime=WHEN_H99S, control_id="ORFQ-1")
    resp = parse_worklist_query_response(orf)
    assert resp.orders[0].barcode == q.subject_id  # forward leg (AC1) still holds

    # The analyzer's own result ORU: OBR-2 is its private sample counter (13, unrelated
    # to anything host-side); OBR-20 echoes the same barcode the worklist gave it.
    counter = "13"
    result_msg = (
        "MSH|^~\\&|H90^^507|EDANLAB|||20260706213000||ORU^R01|10|P|2.4||||0||UTF8\r"
        f"PID|1|{order.patient_id}\r"
        f"OBR|1|{counter}||EDANLAB^H90|||20260706213000|||||||||||||{resp.orders[0].barcode}\r"
        "OBX||NM|0|WBC|7.1|10\\S\\9/L|4.0-10.0|0|0|0||7.1^10\\S\\9/L"
    ).encode("utf-8")
    report = parse_oru_r01(result_msg)

    assert report.specimen_id != counter  # must NOT orphan on the analyzer's own OBR-2 counter
    assert report.specimen_id == resp.orders[0].barcode  # self-consistency: OBR-20 read back matches the ORF echo
    assert report.specimen_id == order.accession_number  # anchor-to-source: the non-vacuous half
    assert report.barcode == resp.orders[0].barcode


# --- correlation logic (unit-level, incl. the empty-id/subject guards) -------


def test_correlates_accepts_matching_answer():
    assert correlates(_query_record(), _response()) is True


def test_correlates_rejects_empty_subject():
    """An empty subject must not vacuously match an empty specimen echo."""
    assert correlates(_query_record(subject_id=""), _response(specimen="")) is False


def test_correlates_rejects_empty_query_id():
    assert correlates(_query_record(query_id=""), _response(query_id="")) is False


def test_correlates_rejects_specimen_mismatch():
    assert correlates(_query_record(subject_id="SPEC-0231"), _response(specimen="SPEC-9999")) is False


def test_correlates_rejects_non_accept_ack():
    assert correlates(_query_record(), _response(ack_code="AE")) is False


# --- tolerant parsing of a malformed/partial query response ------------------


def test_parse_query_response_tolerates_missing_msa_and_qrd():
    """A response without MSA/QRD parses (tolerant) with empty ack/query id — which
    then correctly fails correlation rather than crashing."""
    msg = (
        "MSH|^~\\&|LIS|LAB|H60S|EDAN|20260628093501||ORF^R04|R1|P|2.4\r"
        "OBR|1||SPEC-0231|CBC\r"
        "OBX|1|NM|WBC^Leukocytes^99EDAN||6.8|10\\S\\9/L|||||F"
    ).encode("ascii")
    resp = parse_query_response(msg)
    assert resp.ack_code == ""
    assert resp.query_id == ""
    assert resp.report.specimen_id == "SPEC-0231"
    assert correlates(_query_record(), resp) is False  # no echoed id -> no correlation


def test_parse_query_response_requires_msh():
    with pytest.raises(QueryError):
        parse_query_response(b"OBR|1||SPEC-0231|CBC")
