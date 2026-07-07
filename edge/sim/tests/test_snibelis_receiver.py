"""``SnibeLisReceiver`` -- the SnibeLis simplified-envelope receiver state
machine -- LIS-174 / D5.

Mirrors ``test_astm.py``'s coverage of ``AstmReceiver`` but for the documented
SnibeLis wire contract (KB §4): ACK at exactly ENQ/STX/ETX/EOT, never per
record; no NAK vocabulary at all (any violation raises so the caller can close
the dead link, per "missing ACK -> reconnect, never retransmit"); tolerant of
an optional LF after CR and of empty records; loops back to await a new ENQ
after EOT so one instance can serve multiple envelopes on one connection.
"""

import pytest

from edge_sim.astm import ACK, ENQ, EOT, ETX, STX
from edge_sim.snibelis import SnibeLisReceiver, SnibeLisReceiverError


def _feed_session(receiver: SnibeLisReceiver, body: bytes) -> list[bytes]:
    """Feed one full ENQ/STX/<body>/ETX/EOT session, one control token (or the
    whole record body) at a time, and return the ACK bytes returned at each of
    the four token points."""
    acks = []
    acks.append(receiver.feed(bytes([ENQ])))
    acks.append(receiver.feed(bytes([STX])))
    receiver.feed(body)
    acks.append(receiver.feed(bytes([ETX])))
    acks.append(receiver.feed(bytes([EOT])))
    return acks


def test_receiver_acks_enq_stx_etx_eot_in_order():
    receiver = SnibeLisReceiver()

    acks = _feed_session(receiver, b"H|\\^&\rP|1\rL|1|N\r")

    assert acks == [bytes([ACK])] * 4
    assert receiver.complete is True
    assert receiver.envelope_count == 1


def test_receiver_does_not_ack_individual_records():
    """Feeding the record body one byte at a time never yields a response --
    only ENQ/STX/ETX/EOT do."""
    receiver = SnibeLisReceiver()
    receiver.feed(bytes([ENQ]))
    receiver.feed(bytes([STX]))

    body = b"H|\\^&\rP|1\rO|1|SPEC||^^^TSH\rL|1|N\r"
    responses = [receiver.feed(bytes([b])) for b in body]

    assert all(r == b"" for r in responses)


def test_receiver_reconstructs_records_and_strips_trailing_empty_record():
    receiver = SnibeLisReceiver()
    _feed_session(receiver, b"H|\\^&\rP|1\rL|1|N\r")  # trailing CR -> one empty record

    assert receiver.records == ["H|\\^&", "P|1", "L|1|N"]
    assert receiver.payload == b"H|\\^&\rP|1\rL|1|N"


def test_receiver_skips_embedded_empty_records():
    receiver = SnibeLisReceiver()
    _feed_session(receiver, b"H|\\^&\r\rP|1\rL|1|N")  # a bare double-CR in the middle

    assert receiver.records == ["H|\\^&", "P|1", "L|1|N"]


def test_receiver_tolerates_lf_after_cr():
    receiver = SnibeLisReceiver()
    _feed_session(receiver, b"H|\\^&\r\nP|1\r\nL|1|N\r\n")

    assert receiver.records == ["H|\\^&", "P|1", "L|1|N"]


def test_receiver_rejects_e1381_frame_number_after_stx():
    """The very first byte after STX being a digit 0-7 is an E1381 frame
    number (``STX FN text ...``), not a SnibeLis record -- clean reject, no NAK."""
    receiver = SnibeLisReceiver()
    receiver.feed(bytes([ENQ]))
    receiver.feed(bytes([STX]))

    with pytest.raises(SnibeLisReceiverError, match="E1381 frame-number digit"):
        receiver.feed(b"1H|\\^&\r")


def test_receiver_rejects_out_of_order_control_bytes():
    receiver = SnibeLisReceiver()

    with pytest.raises(SnibeLisReceiverError, match="expected ENQ"):
        receiver.feed(bytes([STX]))


def test_receiver_rejects_wrong_byte_awaiting_stx():
    receiver = SnibeLisReceiver()
    receiver.feed(bytes([ENQ]))

    with pytest.raises(SnibeLisReceiverError, match="expected STX"):
        receiver.feed(bytes([EOT]))


def test_receiver_rejects_wrong_byte_awaiting_eot():
    receiver = SnibeLisReceiver()
    receiver.feed(bytes([ENQ]))
    receiver.feed(bytes([STX]))
    receiver.feed(b"H|\\^&\r")
    receiver.feed(bytes([ETX]))

    with pytest.raises(SnibeLisReceiverError, match="expected EOT"):
        receiver.feed(bytes([ENQ]))


def test_receiver_serves_multiple_envelopes_on_one_connection():
    """After EOT-ACK the receiver loops back to AWAIT_ENQ -- mirrors the bridge:
    a new ENQ starts a new envelope on the same link."""
    receiver = SnibeLisReceiver()

    _feed_session(receiver, b"H|\\^&\rP|1\rL|1|N\r")
    _feed_session(receiver, b"H|\\^&\rP|2\rL|1|N\r")

    assert receiver.envelope_count == 2
    assert receiver.envelopes[0] == b"H|\\^&\rP|1\rL|1|N"
    assert receiver.envelopes[1] == b"H|\\^&\rP|2\rL|1|N"
    assert receiver.records == ["H|\\^&", "P|2", "L|1|N"]  # most recent envelope


def test_zero_record_envelope_rejected_before_etx_ack():
    """Parity with the bridge's empty-envelope guard (bridge PR #21, e4e5577):
    ENQ/STX/(empty lines)/ETX must raise BEFORE the ETX-ACK, never complete."""
    receiver = SnibeLisReceiver()
    assert receiver.feed(bytes([ENQ])) == bytes([ACK])
    assert receiver.feed(bytes([STX])) == bytes([ACK])
    with pytest.raises(SnibeLisReceiverError, match="empty simplified envelope"):
        receiver.feed(b"\r" + bytes([ETX]))
    assert not receiver.complete
