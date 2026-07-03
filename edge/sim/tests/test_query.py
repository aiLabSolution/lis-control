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
    q = parse_query(load_fixture(H99S_WORKLIST_QRY).message_bytes)
    exp = load_fixture(H99S_WORKLIST_QRY).expected
    assert q.query_id == exp["query_id"]
    assert q.subject_id == "DEV01260000000000002"
    assert q.subject_id == exp["barcode"]
    assert q.what_subject == "OTH"
    assert q.control_id == "H99SQ1"
    assert q.sending_app == "H90"
    assert q.sending_facility == "EDANLAB"


def test_h99s_worklist_answer_reconciles_barcode_to_accession_orders():
    q = parse_query(load_fixture(H99S_WORKLIST_QRY).message_bytes)
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
    assert b"|P|2.4||||3\r" in orf  # EDAN H90-series MSH-16 query response type
    assert b"MSA|AA|H99SQ1\r" in orf
    assert b"QRD|20260703112800|R|I|Q-1||||DEV01260000000000002|OTH\r" in orf
    assert b"PID|1||17\r" in orf
    assert b"OBR|1|2|2|^^^WBC^WBC|||||||A" in orf
    assert b"OBR|2|2|2|^^^HGB^HGB|||||||A" in orf

    assert resp.ack_code == "AA"
    assert resp.query_id == "Q-1"
    assert resp.subject_id == "DEV01260000000000002"
    assert worklist_correlates(q, resp) is True
    assert [(o.accession_number, o.patient_id, o.analyzer_codes) for o in resp.orders] == [
        ("2", "17", ("WBC",)),
        ("2", "17", ("HGB",)),
    ]


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
