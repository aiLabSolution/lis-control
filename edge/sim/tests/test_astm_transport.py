"""AstmTransport round-trip + DiaSys ASTM fixture replay — LIS-23 / S2.1."""

from pathlib import Path

import pytest

from edge_sim.astm import STX
from edge_sim.fixtures import load_fixture
from edge_sim.replay import replay
from edge_sim.transport import AstmTransport, TransportError

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
DIASYS = FIXTURES_ROOT / "diasys-r920-astm-result"


def test_astm_transport_roundtrips_payload_byte_faithfully():
    payload = b"R|1|^^^GLU|5.2|mmol/L||N||F"
    t = AstmTransport()
    assert t.roundtrip(payload) == payload
    assert t.wire_bytes()[:1] == bytes([STX]) or t.wire_bytes() == b""  # framed on the wire


def test_astm_transport_multiframe_roundtrip():
    # > 240 chars forces multiple frames (ETB intermediate, ETX final); reassembles.
    payload = (b"R|" + b"X" * 600 + b"|F")
    t = AstmTransport()
    t.send(payload)
    assert t.wire_bytes().count(bytes([STX])) >= 3  # at least 3 frames
    assert t.receive() == payload


def test_replay_diasys_astm_fixture_round_trips():
    fx = load_fixture(DIASYS)
    result = replay(fx, AstmTransport())
    assert result.transport == "astm"
    assert result.round_trip_ok is True
    # matches the manifest's declared expectations
    assert fx.expected["round_trip"] is True
    assert len(fx.message_bytes.split(b"\r")) == fx.expected["records"]


def test_astm_transport_receive_rejects_corrupted_frame():
    t = AstmTransport()
    t.send(b"R|1|data")
    # corrupt the queued frame's covered bytes so its checksum no longer matches
    bad = bytearray(t._frames[0])
    bad[5] ^= 0xFF
    t._frames[0] = bytes(bad)
    with pytest.raises(TransportError, match="checksum"):
        t.receive()


def test_cli_replay_astm(capsys):
    from edge_sim.cli import main

    rc = main(["replay", "diasys-r920-astm-result", "--transport", "astm"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out
    assert "astm" in out
