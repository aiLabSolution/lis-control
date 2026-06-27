"""Tolerant HL7 v2 parser primitives — LIS-14 / S1.2."""

import pytest

from edge_sim.hl7 import Encoding, Hl7Error, parse_message, unescape

ORU = (
    "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260626083000||ORU^R01|MSG00142|P|2.3\r"
    "PID|1||PID-0142||DOE^JANE||19900212|F\r"
    "OBX|1|NM|HGB^Hemoglobin^99RAC||14.2|g/dL|13.0-17.0|N|||F"
)


def test_msh_field_numbering():
    msg = parse_message(ORU)
    msh = msg.first("MSH")
    assert msh.field(1) == "|"  # MSH-1 is the field separator itself
    assert msh.field(2) == "^~\\&"  # MSH-2 encoding chars
    assert msh.field(3) == "RAC-050"  # MSH-3 sending app
    assert msh.field(9) == "ORU^R01"  # MSH-9 message type
    assert msh.field(10) == "MSG00142"  # MSH-10 control id
    assert msh.field(12) == "2.3"  # MSH-12 version


def test_non_msh_field_numbering_and_components():
    msg = parse_message(ORU)
    obx = msg.first("OBX")
    assert obx.field(1) == "1"
    assert obx.field(2) == "NM"
    assert obx.field(5) == "14.2"
    assert obx.component(3, 1) == "HGB"
    assert obx.component(3, 2) == "Hemoglobin"
    assert obx.component(3, 3) == "99RAC"
    assert obx.component(6, 1) == "g/dL"


def test_tolerant_missing_trailing_fields_return_empty():
    msg = parse_message("MSH|^~\\&|A|B\rOBX|1|NM|X^Y^Z")
    obx = msg.first("OBX")
    assert obx.field(5) == ""  # absent -> ""
    assert obx.component(6, 1) == ""
    assert obx.field(99) == ""


def test_encoding_inferred_from_msh():
    msg = parse_message(ORU)
    assert msg.encoding == Encoding(field="|", component="^", repetition="~", escape="\\", subcomponent="&")


@pytest.mark.parametrize("terminator", ["\r", "\n", "\r\n"])
def test_segment_terminator_tolerance(terminator):
    raw = terminator.join(["MSH|^~\\&|A|B|C|D|||ORU^R01|M1|P|2.3", "OBX|1|NM|HGB^H^99RAC||1|g/dL"])
    msg = parse_message(raw)
    assert msg.first("MSH") is not None
    assert msg.first("OBX").component(3, 1) == "HGB"


def test_repetitions_split():
    msg = parse_message("MSH|^~\\&|A\rPID|1||id1~id2~id3")
    assert msg.first("PID").repetitions(3) == ["id1", "id2", "id3"]


def test_all_and_first():
    msg = parse_message(ORU + "\rOBX|2|NM|HCT^H^99RAC||42|%")
    assert len(msg.all("OBX")) == 2
    assert msg.first("OBX").field(1) == "1"


def test_unescape_standard_sequences():
    enc = Encoding()
    assert unescape("a\\F\\b", enc) == "a|b"
    assert unescape("x\\S\\y", enc) == "x^y"
    assert unescape("p\\T\\q", enc) == "p&q"
    assert unescape("m\\R\\n", enc) == "m~n"
    assert unescape("e\\E\\f", enc) == "e\\f"
    assert unescape("\\X41\\", enc) == "A"  # hex escape
    assert unescape("no escapes", enc) == "no escapes"


def test_empty_message_raises():
    with pytest.raises(Hl7Error):
        parse_message("   ")


def test_escaped_component_separator_survives_field_split():
    """A \\S\\-escaped caret in a field is data, not a component delimiter."""
    msg = parse_message("MSH|^~\\&|A\rOBX|1|NM|C^T^S||v|10\\S\\9/L")
    obx = msg.first("OBX")
    # component(6,1) is the raw first component; unescape then restores the caret.
    assert unescape(obx.component(6, 1), msg.encoding) == "10^9/L"
