"""S1.1 milestone — an MLLP ``ACK^R01`` round-trip against a simulated analyzer.

This is the headline acceptance for LIS-13: a simulated analyzer frames and
sends an ``ORU^R01`` over the MLLP wire; the host de-frames it, builds an
``ACK^R01`` (MSA-1 = AA), frames the ACK and sends it back; the analyzer
de-frames the ACK and confirms acceptance. Component-level proof (verification
pyramid level 2). Wire framing and ACK construction are exercised end to end —
no parser/normalization yet (that is S1.2 / LIS-14).
"""

from edge_sim.ack import AckCode, AckMode, build_ack, parse_msh, wants_accept_ack
from edge_sim.mllp import MllpDecoder, deframe, frame

ORU = (
    "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260625120000||ORU^R01|MSG00042|P|2.3\r"
    "PID|1||PID-0001||DOE^JANE\r"
    "OBX|1|NM|718-7^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N|||F"
).encode("ascii")


def test_ack_roundtrip_against_simulated_analyzer():
    # analyzer -> host: a framed ORU^R01 arrives on the wire
    host = MllpDecoder()
    (inbound,) = host.feed(frame(ORU))
    assert inbound == ORU  # de-framed byte-faithfully

    # host -> analyzer: build, frame, and send the acknowledgment back
    ack = build_ack(inbound, code=AckCode.AA, timestamp="20260625120001", control_id="ACK00042")
    wire_back = frame(ack)

    # analyzer de-frames the ACK and confirms acceptance
    analyzer = MllpDecoder()
    (ack_back,) = analyzer.feed(wire_back)
    msh = parse_msh(ack_back)
    assert msh.message_code == "ACK"
    assert msh.trigger_event == "R01"
    msa = ack_back.decode("ascii").split("\r")[1].split("|")
    assert msa[1] == "AA"
    assert msa[2] == parse_msh(ORU).control_id  # MSA-2 echoes the inbound control id


def test_enhanced_mode_skips_ack_when_never_requested():
    # MSH-15 = NE (never) under enhanced acknowledgment -> the host stays silent
    inbound = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260625120000||ORU^R01|MSG00043|P|2.3|||NE|NE\r"
        "OBX|1|NM|718-7^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N|||F"
    ).encode("ascii")
    msh = parse_msh(inbound)
    assert msh.accept_ack_type == "NE"
    assert wants_accept_ack(msh.accept_ack_type, success=True) is False


def test_enhanced_mode_commit_accept_roundtrip():
    inbound = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260625120000||ORU^R01|MSG00044|P|2.3|||AL|AL\r"
        "OBX|1|NM|718-7^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N|||F"
    ).encode("ascii")
    msh = parse_msh(inbound)
    assert wants_accept_ack(msh.accept_ack_type, success=True) is True
    ack = build_ack(inbound, mode=AckMode.ENHANCED, timestamp="x")
    # the commit acknowledgment round-trips through MLLP framing intact
    assert deframe(frame(ack)) == ack
    msa = ack.decode("ascii").split("\r")[1].split("|")
    assert msa[1] == "CA"
