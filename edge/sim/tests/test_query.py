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
from edge_sim.oru import parse_oru_r01
from edge_sim.query import (
    QueryError,
    build_query,
    build_query_response,
    correlates,
    parse_query,
    parse_query_response,
)

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
QRY = FIXTURES_ROOT / "edan-h60s-host-query-qry-r02"
EDAN_RESULT = FIXTURES_ROOT / "edan-h60s-oru-r01"
WHEN_Q = "20260628093500"
WHEN_R = "20260628093501"


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
