"""LIS-13: the listener's negative acknowledgment (AE/AR + populated ERR) for a
rejected inbound message, end-to-end over MLLP.

The Stage-1 result-ingestion listener (``edge_sim.milestone.acknowledge``) returns:

* **AA** — a well-formed ``ORU^R01`` with ≥1 ``OBX`` result;
* **AR** + ``ERR`` — an *unsupported message type* (anything but ``ORU^R01``);
* **AE** + ``ERR`` — a supported type that cannot be processed (no ``OBX`` results).

A frame with no recoverable ``MSH`` cannot be acknowledged at all — there is no
control id to echo or routing to swap — so the MLLP de-framer silently resynchronises
(see ``test_mllp.py`` + ADR-0005); ``acknowledge`` raises ``Hl7AckError`` for that case.
"""

import pytest

from edge_sim.ack import Hl7AckError, parse_msh
from edge_sim.milestone import acknowledge
from edge_sim.mllp import MllpDecoder, deframe, frame

ORU = (
    "MSH|^~\\&|H60S|EDAN|LIS|LAB|20260628093000||ORU^R01|H60S00231|P|2.4\r"
    "PID|1||PID-0231||DOE^JOHN\r"
    "OBR|1||SPEC-0231|CBC^Complete Blood Count^99EDAN\r"
    "OBX|1|NM|6690-2^WBC^LN||6.8|10^9/L|4.0-10.0|N|||F"
).encode("ascii")

QRY = (
    "MSH|^~\\&|H60S|EDAN|LIS|LAB|20260628093500||QRY^R02|H60SQ0231|P|2.4\r"
    "QRD|20260628093500|R|I|Q0231-01||||SPEC-0231|RES"
).encode("ascii")

ORU_NO_OBX = (
    "MSH|^~\\&|H60S|EDAN|LIS|LAB|20260628093000||ORU^R01|H60S0|P|2.4\r"
    "OBR|1||SPEC-0231|CBC^Complete Blood Count^99EDAN"
).encode("ascii")

ACK_TS = "20260628093001"


def _segments(payload: bytes) -> list[str]:
    return payload.decode("ascii").split("\r")


def test_acknowledge_accepts_a_valid_oru():
    d = acknowledge(ORU, ack_timestamp=ACK_TS)
    assert d.accepted is True
    assert d.code == "AA"
    assert d.error_condition == ""
    segs = _segments(d.ack)
    assert len(segs) == 2  # MSH + MSA only — no ERR on an accept
    assert segs[1].split("|")[1] == "AA"


def test_acknowledge_rejects_unsupported_message_type_with_ar_and_err():
    d = acknowledge(QRY, ack_timestamp=ACK_TS)
    assert d.accepted is False
    assert d.code == "AR"
    assert d.error_condition == "200"
    segs = _segments(d.ack)
    assert segs[1].split("|")[1] == "AR"
    assert segs[1].split("|")[2] == "H60SQ0231"  # MSA-2 echoes inbound control id
    assert segs[2].startswith("ERR|")
    assert "200&" in segs[2] and "HL70357" in segs[2]


def test_acknowledge_errors_on_oru_without_observations_with_ae_and_err():
    d = acknowledge(ORU_NO_OBX, ack_timestamp=ACK_TS)
    assert d.accepted is False
    assert d.code == "AE"
    assert d.error_condition == "101"
    segs = _segments(d.ack)
    assert segs[1].split("|")[1] == "AE"
    assert segs[2].startswith("ERR|")
    assert "101&" in segs[2]


def test_acknowledge_is_deterministic_with_a_pinned_timestamp():
    assert acknowledge(QRY, ack_timestamp=ACK_TS).ack == acknowledge(QRY, ack_timestamp=ACK_TS).ack


def test_acknowledge_raises_when_there_is_no_msh_to_acknowledge():
    with pytest.raises(Hl7AckError):
        acknowledge(b"OBX|1|NM|6690-2^WBC^LN||6.8|10^9/L||N|||F")


def test_listener_naks_an_unsupported_message_over_mllp_roundtrip():
    """End-to-end: an analyzer frames an ADT (mis-routed to the result port); the
    host de-frames it, emits an AR NAK with a populated ERR, frames it back; the
    analyzer de-frames the NAK and reads the rejection."""
    adt = (
        "MSH|^~\\&|H60S|EDAN|LIS|LAB|20260628093500||ADT^A01|H60SA1|P|2.4\r"
        "PID|1||PID-0231||DOE^JOHN"
    ).encode("ascii")

    # analyzer -> host: a framed message arrives on the wire
    host = MllpDecoder()
    (inbound,) = host.feed(frame(adt))
    assert inbound == adt

    # host decides + builds the NAK, framed back onto the wire
    decision = acknowledge(inbound, ack_timestamp=ACK_TS)
    assert decision.code == "AR"
    assert deframe(decision.ack_wire) == decision.ack

    # analyzer de-frames the NAK and sees the rejection + ERR
    analyzer = MllpDecoder()
    (nak_back,) = analyzer.feed(decision.ack_wire)
    assert parse_msh(nak_back).message_code == "ACK"
    segs = _segments(nak_back)
    assert segs[1].split("|")[1] == "AR"
    assert segs[1].split("|")[2] == "H60SA1"  # MSA-2 echoes the inbound control id
    assert segs[2].startswith("ERR|")
    assert "200&" in segs[2]
