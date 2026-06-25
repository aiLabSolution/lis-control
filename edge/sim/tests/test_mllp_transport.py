"""``MllpTransport`` — the MLLP framing transport plugged into the harness
``Transport`` interface (LIS-13 / S1.1), plus a fixture replay through it.

The replay engine only knows the ``Transport`` contract, so a fixture's captured
payload must survive an MLLP frame/de-frame round-trip byte-for-byte exactly as
it does over loopback (verification pyramid level 2, plan §1).
"""

from pathlib import Path

import pytest

from edge_sim.mllp import CR, EB, SB
from edge_sim.replay import replay
from edge_sim.transport import MllpTransport, TransportError

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MLLP_FIXTURE = FIXTURES_ROOT / "example-mllp-oru-r01"


def test_name():
    assert MllpTransport().name == "mllp"


def test_roundtrip_is_byte_faithful():
    t = MllpTransport()
    msg = b"MSH|^~\\&|SIM-1\rOBX|1|NM|718-7^Hemoglobin^LN\r"
    assert t.roundtrip(msg) == msg


def test_send_applies_mllp_framing_on_the_wire():
    t = MllpTransport()
    t.send(b"HI")
    assert t.wire_bytes() == bytes([SB]) + b"HI" + bytes([EB, CR])


def test_send_receive_fifo():
    t = MllpTransport()
    t.send(b"a")
    t.send(b"b")
    assert t.receive() == b"a"
    assert t.receive() == b"b"


def test_receive_empty_raises():
    with pytest.raises(TransportError, match="no complete"):
        MllpTransport().receive()


def test_send_non_bytes_raises():
    with pytest.raises(TransportError):
        MllpTransport().send("not-bytes")  # type: ignore[arg-type]


def test_receive_recovers_from_corrupt_wire_bytes():
    # Corrupt bytes on the wire surface as TransportError (never a raw MllpError),
    # and the transport recovers: a subsequently sent message still arrives.
    from edge_sim.mllp import CR as _CR
    from edge_sim.mllp import EB as _EB
    from edge_sim.mllp import SB as _SB

    t = MllpTransport()
    t._wire.extend(bytes([_SB]) + b"X" + bytes([_EB]) + b"Z")  # EB not followed by CR
    with pytest.raises(TransportError):
        t.receive()
    t.send(b"GOOD")
    assert t.receive() == b"GOOD"


def test_replay_mllp_fixture_byte_faithful():
    from edge_sim.fixtures import load_fixture

    fx = load_fixture(MLLP_FIXTURE)
    res = replay(fx, MllpTransport())
    assert res.transport == "mllp"
    assert res.round_trip_ok is True
    assert res.received == fx.message_bytes
