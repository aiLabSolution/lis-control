"""HL7 v2 ``ACK^R01`` construction for the MLLP listener (LIS-13 / S1.1).

Scope is deliberately narrow: read the inbound ``MSH`` and build a correct
acknowledgment in both **original** (AA/AE/AR) and **enhanced/commit**
(CA/CE/CR) modes. The full tolerant ORU^R01 parser + normalization is a later
slice (S1.2 / LIS-14); this module knows only enough of ``MSH`` to acknowledge.
"""

import pytest

from edge_sim.ack import (
    AckCode,
    AckMode,
    Hl7AckError,
    build_ack,
    parse_msh,
    wants_accept_ack,
)

ORU = (
    "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260625120000||ORU^R01|MSG00042|P|2.3\r"
    "PID|1||PID-0001||DOE^JANE\r"
    "OBR|1||SPEC-0001|CBC^Complete Blood Count^L\r"
    "OBX|1|NM|718-7^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N|||F"
).encode("ascii")


def test_parse_msh_extracts_routing_and_ids():
    m = parse_msh(ORU)
    assert m.field_sep == "|"
    assert m.encoding_chars == "^~\\&"
    assert m.sending_app == "RAC-050"
    assert m.sending_facility == "RAYTO"
    assert m.receiving_app == "LIS"
    assert m.receiving_facility == "LAB"
    assert m.message_code == "ORU"
    assert m.trigger_event == "R01"
    assert m.control_id == "MSG00042"
    assert m.processing_id == "P"
    assert m.version == "2.3"


def test_parse_msh_requires_msh_segment():
    with pytest.raises(Hl7AckError):
        parse_msh(b"PID|1||x\r")


def test_parse_msh_tolerates_missing_trailing_fields():
    m = parse_msh(b"MSH|^~\\&|A|B|C|D")
    assert m.control_id == ""
    assert m.version == ""
    assert m.accept_ack_type == ""


def test_build_ack_original_aa_routing_and_msa():
    ack = build_ack(ORU, timestamp="20260625120001", control_id="ACK00042")
    segs = ack.decode("ascii").split("\r")
    msh = segs[0].split("|")
    assert msh[0] == "MSH"
    assert msh[1] == "^~\\&"
    # routing is swapped relative to the inbound message
    assert msh[2] == "LIS"
    assert msh[3] == "LAB"
    assert msh[4] == "RAC-050"
    assert msh[5] == "RAYTO"
    assert msh[6] == "20260625120001"
    assert msh[8] == "ACK^R01"  # trigger event echoed
    assert msh[9] == "ACK00042"
    assert msh[10] == "P"
    assert msh[11] == "2.3"
    msa = segs[1].split("|")
    assert msa[0] == "MSA"
    assert msa[1] == "AA"
    assert msa[2] == "MSG00042"  # MSA-2 echoes the inbound control id


def test_build_ack_v23_omits_message_structure_component():
    # MSH-12 = 2.3 -> two-component MSH-9 (no message-structure ID).
    ack = build_ack(ORU, timestamp="x")
    msh9 = ack.decode("ascii").split("\r")[0].split("|")[8]
    assert msh9 == "ACK^R01"


def test_build_ack_v25_includes_message_structure_component():
    # From v2.3.1 onward MSH-9 carries the message-structure ID: ACK^R01^ACK.
    oru_v25 = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260625120000||ORU^R01^ORU_R01|MSG99|P|2.5.1\r"
        "OBX|1|NM|718-7^Hemoglobin^LN||13.5|g/dL|12.0-16.0|N|||F"
    ).encode("ascii")
    ack = build_ack(oru_v25, timestamp="x")
    msh9 = ack.decode("ascii").split("\r")[0].split("|")[8]
    assert msh9 == "ACK^R01^ACK"


def test_build_ack_defaults_encoding_chars_when_blank():
    # A (non-conformant) blank inbound MSH-2 must not yield a blank MSH-2 on the ACK.
    inbound = b"MSH||RAC-050|RAYTO|LIS|LAB|20260625120000||ORU^R01|MSG77|P|2.3"
    ack = build_ack(inbound, timestamp="x")
    msh = ack.decode("ascii").split("\r")[0].split("|")
    assert msh[1] == "^~\\&"


def test_build_ack_defaults_control_id_to_inbound():
    ack = build_ack(ORU, timestamp="x")
    msh = ack.decode("ascii").split("\r")[0].split("|")
    assert msh[9] == "MSG00042"


def test_build_ack_error_codes_carry_text():
    for code in (AckCode.AE, AckCode.AR):
        ack = build_ack(ORU, code=code, text="parse error", timestamp="x")
        msa = ack.decode("ascii").split("\r")[1].split("|")
        assert msa[1] == code.value
        assert msa[3] == "parse error"


def test_build_ack_enhanced_defaults_to_commit_accept():
    ack = build_ack(ORU, mode=AckMode.ENHANCED, timestamp="x")
    msa = ack.decode("ascii").split("\r")[1].split("|")
    assert msa[1] == "CA"


def test_build_ack_enhanced_commit_error_and_reject():
    for code in (AckCode.CE, AckCode.CR):
        ack = build_ack(ORU, mode=AckMode.ENHANCED, code=code, timestamp="x")
        msa = ack.decode("ascii").split("\r")[1].split("|")
        assert msa[1] == code.value


def test_build_ack_rejects_code_mode_mismatch():
    with pytest.raises(Hl7AckError):
        build_ack(ORU, mode=AckMode.ENHANCED, code=AckCode.AA, timestamp="x")
    with pytest.raises(Hl7AckError):
        build_ack(ORU, mode=AckMode.ORIGINAL, code=AckCode.CA, timestamp="x")


@pytest.mark.parametrize(
    "accept_ack_type,success,expected",
    [
        ("AL", True, True),
        ("AL", False, True),
        ("NE", True, False),
        ("NE", False, False),
        ("SU", True, True),
        ("SU", False, False),
        ("ER", True, False),
        ("ER", False, True),
        ("", True, True),  # original mode: always acknowledge
        (None, False, True),
    ],
)
def test_wants_accept_ack_honours_msh15(accept_ack_type, success, expected):
    assert wants_accept_ack(accept_ack_type, success) is expected
