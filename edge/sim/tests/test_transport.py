"""Transport abstraction + the loopback (identity) transport.

Framed transports — MLLP (LIS-13 / S1.1) and ASTM E1381 (LIS-23 / S2.1) — are
deliberately out of scope here; they plug into the same ``Transport`` interface.
"""

import pytest

from edge_sim.transport import LoopbackTransport, TransportError


def test_name():
    assert LoopbackTransport().name == "loopback"


def test_roundtrip_identity():
    t = LoopbackTransport()
    msg = b"MSH|^~\\&|SIM-1\rOBX|1|NM|718-7^Hemoglobin^LN\r"
    assert t.roundtrip(msg) == msg


def test_send_then_receive_fifo():
    t = LoopbackTransport()
    t.send(b"a")
    t.send(b"b")
    assert t.receive() == b"a"
    assert t.receive() == b"b"


def test_receive_empty_raises():
    with pytest.raises(TransportError, match="empty"):
        LoopbackTransport().receive()


def test_send_non_bytes_raises():
    with pytest.raises(TransportError):
        LoopbackTransport().send("not-bytes")  # type: ignore[arg-type]
