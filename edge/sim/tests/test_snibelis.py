"""SnibeLis ASTM E1394 session/query conformance -- LIS-108 / S3.0a."""

import hashlib
from pathlib import Path

import pytest

from edge_sim.archive import RawMessageArchive
from edge_sim.astm import ACK, ENQ, EOT, ETX, STX
from edge_sim.fixtures import load_fixture
from edge_sim.replay import check_against_expected, deterministic_round_trip
from edge_sim.snibelis import (
    _wire_payload_bytes,
    build_order_download_response,
    parse_queries,
    run_fixture_session,
    run_query_exchange,
    snibelis_deframe,
    snibelis_frame,
    split_assays,
)
from edge_sim.transport import LoopbackTransport

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RESULT_UPLOAD = FIXTURES_ROOT / "snibelis-maglumi-x3-result-upload"
RESULT_UNMAPPED = FIXTURES_ROOT / "snibelis-maglumi-x3-result-unmapped"
QUERY_REQUEST = FIXTURES_ROOT / "snibelis-maglumi-x3-query-request"

# Cross-language fixture anchors (LIS-174 / D7, memory
# "port-every-assertion-not-just-self-consistency"): SHA-256 of the NORMALIZED
# WIRE PAYLOAD -- non-empty records of message.astm CR-joined + one trailing
# CR, encoded latin-1, i.e. exactly ``_wire_payload_bytes(fixture.message_bytes)``
# -- pinned per fixture below. The result-upload and result-unmapped constants
# are mirrored by inline-payload assertions in the bridge repo
# (openelis-analyzer-bridge, SnibeSimplifiedEnvelopeSessionTest): drift on
# either side (a fixture edit here, or a stale inline payload there) must break
# a test, not just self-consistently agree with itself. The query-request
# anchor is sim-side only for now -- its bridge-side mirror lands with the
# simplified-envelope send half (LIS-177), which is what will consume that
# fixture on the bridge.
_WIRE_PAYLOAD_SHA256 = {
    "snibelis-maglumi-x3-result-upload": (
        "403a123081c02d26a8270785c0a05270b6cf1abbd36c916bfc636f0a09e572db",
        241,
    ),
    "snibelis-maglumi-x3-result-unmapped": (
        "006c5b2c55112a8405dcd956b9c2283c84f3a0d732320ac1fde190e30bbe7ad5",
        291,
    ),
    "snibelis-maglumi-x3-query-request": (
        "8f2955010df2e9f719afeda54ac1e777748a9e56e7597dd003fe30f0aa53fcc8",
        90,
    ),
}


@pytest.mark.parametrize(
    "fixture_dir",
    [RESULT_UPLOAD, RESULT_UNMAPPED, QUERY_REQUEST],
    ids=lambda p: p.name,
)
def test_fixture_normalized_wire_payload_matches_pinned_cross_language_anchor(fixture_dir):
    fx = load_fixture(fixture_dir)
    expected_digest, expected_len = _WIRE_PAYLOAD_SHA256[fx.id]

    wire_payload = _wire_payload_bytes(fx.message_bytes)

    assert len(wire_payload) == expected_len
    assert hashlib.sha256(wire_payload).hexdigest() == expected_digest


def test_snibelis_result_upload_acks_each_control_step_and_parses_results():
    fx = load_fixture(RESULT_UPLOAD)

    result = run_fixture_session(fx)

    assert result.complete is True
    assert result.aborted is False
    assert result.acked_controls == ("ENQ", "STX", "ETX", "EOT")
    assert [event.response for event in result.events] == [bytes([ACK])] * 4
    assert result.wire[:2] == bytes([ENQ, STX])
    assert result.wire[-2:] == bytes([ETX, EOT])
    assert result.wire[-3:] == bytes([0x0D, ETX, EOT])
    assert bytes([STX, ord("1")]) not in result.wire
    assert result.message is not None
    assert result.message.header is not None
    assert result.message.header.sender_name == "Maglumi User"
    assert result.message.patients[0].patient_id == "PID-SNB-108-001"
    order = result.message.patients[0].orders[0]
    assert order.specimen_id == "SNB-108-001"
    assert [r.test_code for r in order.results] == ["TSH", "FT4"]
    assert [r.units for r in order.results] == ["uIU/mL", "pmol/L"]
    assert [r.abnormal_flags for r in order.results] == ["N", "N"]


def test_snibelis_result_upload_archives_and_replays_to_astm_result_rows(tmp_path):
    fx = load_fixture(RESULT_UPLOAD)

    result = deterministic_round_trip(
        fx,
        LoopbackTransport(),
        archive=RawMessageArchive(tmp_path),
        received_at="2026-07-03T00:00:00+00:00",
    )

    assert result.round_trip_ok is True
    assert result.message_type == "ASTM^E1394"
    assert result.patient_id == fx.expected["patient_id"]
    assert result.specimen_id == fx.expected["specimen_id"]
    assert [(row.set_id, row.raw_code, row.value, row.raw_unit) for row in result.observations] == [
        ("1", "TSH", "2.31", "uIU/mL"),
        ("2", "FT4", "14.8", "pmol/L"),
    ]
    assert check_against_expected(result, fx.expected) == []


def test_snibelis_frame_round_trips_documented_simplified_envelope():
    payload = "H|\\^&\rP|1\rL|1|N"

    wire = snibelis_frame(payload)

    assert wire == bytes([ENQ, STX]) + b"H|\\^&\rP|1\rL|1|N\r" + bytes([ETX, EOT])
    assert snibelis_deframe(wire) == b"H|\\^&\rP|1\rL|1|N\r"
    with pytest.raises(ValueError, match="SnibeLis"):
        snibelis_deframe(bytes([STX]) + b"H|\\^&" + bytes([ETX]))


def test_snibelis_query_strips_q3_sample_id_and_builds_order_response():
    qfx = load_fixture(QUERY_REQUEST)

    exchange = run_query_exchange(qfx.message_bytes, ["TSH", "FT4"])

    assert exchange.query_session.acked_controls == ("ENQ", "STX", "ETX", "EOT")
    assert exchange.response_session.acked_controls == ("ENQ", "STX", "ETX", "EOT")
    assert exchange.query.sample_id == "SNB-108-001"
    assert exchange.query.assays_requested == ("ALL",)
    assert exchange.query.status == "O"
    response_order = exchange.response_message.patients[0].orders[0]
    assert response_order.specimen_id == "SNB-108-001"
    assert split_assays(response_order.raw.split("|")[4], exchange.response_message.records[2]) == (
        "TSH",
        "FT4",
    )
    assert b"Q|" not in exchange.response_payload
    assert b"R|" not in exchange.response_payload
    assert b"^^^TSH\\^^^FT4" in exchange.response_payload


def test_snibelis_build_order_response_requires_assays():
    qfx = load_fixture(QUERY_REQUEST)
    query = parse_queries(qfx.message_bytes)[0]

    with pytest.raises(ValueError, match="assay"):
        build_order_download_response(query, [])


def test_snibelis_fixtures_declare_astm_tcp_and_snibelis_framing():
    result = load_fixture(RESULT_UPLOAD)
    query = load_fixture(QUERY_REQUEST)

    assert result.transport == "astm-tcp"
    assert result.framing == "snibelis-astm"
    assert result.expected["session"]["acked_controls"] == ["ENQ", "STX", "ETX", "EOT"]
    assert query.direction == "bidirectional"
    assert query.expected["query"]["sample_id"] == "SNB-108-001"
