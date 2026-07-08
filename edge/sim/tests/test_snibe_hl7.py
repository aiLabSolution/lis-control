"""SNIBE MAGLUMI X3 HL7 v2.5 OUL^R22 fixture anchors -- LIS-176."""

import hashlib
from pathlib import Path

import pytest

from edge_sim.fixtures import load_fixture
from edge_sim.replay import replay
from edge_sim.transport import MllpTransport

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RESULT = FIXTURES_ROOT / "snibelis-maglumi-x3-oul-r22-result"
QC = FIXTURES_ROOT / "snibelis-maglumi-x3-oul-r22-qc"

_WIRE_PAYLOAD_SHA256 = {
    "snibelis-maglumi-x3-oul-r22-result": (
        "490696e73a2ae896290b35cda842465b7670c34048e05983742d9b3e2e9658bf",
        303,
    ),
    "snibelis-maglumi-x3-oul-r22-qc": (
        "313d825b261a016d2a1bcc7929ad56bee29ea4af373f85d139ec04e8107b82cb",
        203,
    ),
}


def _normalized_wire_payload(message: bytes) -> bytes:
    normalized = message.replace(b"\r\n", b"\r").replace(b"\n", b"\r").rstrip(b"\r")
    return normalized + b"\r"


@pytest.mark.parametrize("fixture_dir", [RESULT, QC], ids=lambda p: p.name)
def test_fixture_normalized_wire_payload_matches_pinned_cross_language_anchor(fixture_dir):
    fx = load_fixture(fixture_dir)
    expected_digest, expected_len = _WIRE_PAYLOAD_SHA256[fx.id]

    wire_payload = _normalized_wire_payload(fx.message_bytes)

    assert len(wire_payload) == expected_len
    assert hashlib.sha256(wire_payload).hexdigest() == expected_digest


@pytest.mark.parametrize("fixture_dir", [RESULT, QC], ids=lambda p: p.name)
def test_snibe_hl7_fixture_replays_over_mllp_byte_faithfully(fixture_dir):
    fx = load_fixture(fixture_dir)

    res = replay(fx, MllpTransport())

    assert res.transport == "mllp"
    assert res.round_trip_ok is True
    assert res.received == fx.message_bytes
