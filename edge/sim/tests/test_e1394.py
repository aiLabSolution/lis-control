"""ASTM E1394 record parser → typed record tree — LIS-24 / S2.2.

Acceptance: a captured DiaSys ``H>P>O>R>L`` record set parses to a typed tree
(header → patient → order → result → terminator), tolerant of spec deviation.
The E1381 framing beneath it is LIS-23 / S2.1; normalizing a parsed result to a
Result row is S2.4 / LIS-24's successor (LIS-26).
"""

from pathlib import Path

import pytest

from edge_sim.e1394 import Delimiters, E1394Error, parse_e1394
from edge_sim.fixtures import load_fixture
from edge_sim.transport import AstmTransport

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
DIASYS = FIXTURES_ROOT / "diasys-r920-astm-result"


# --- delimiters + record access --------------------------------------------


def test_delimiters_derived_from_header():
    d = Delimiters.from_header("H|\\^&|||DiaSys^R920|||||||P|1")
    assert d.field == "|"
    assert d.repeat == "\\"
    assert d.component == "^"
    assert d.escape == "&"


def test_delimiters_default_when_no_header():
    d = Delimiters.from_header("not a header")
    assert (d.field, d.repeat, d.component, d.escape) == ("|", "\\", "^", "&")


# --- the acceptance: parse the DiaSys fixture to a typed tree ----------------


def test_parse_diasys_fixture_to_typed_tree():
    fx = load_fixture(DIASYS)
    msg = parse_e1394(fx.message_bytes)

    # Header
    assert msg.header is not None
    assert msg.header.sender_name == "DiaSys"
    assert msg.header.sender_model == "R920"
    assert msg.header.version == "1"

    # Patient
    assert len(msg.patients) == 1
    patient = msg.patients[0]
    assert patient.patient_id == "PID-0077"
    assert patient.name == "DOE^JOHN"

    # Order
    assert len(patient.orders) == 1
    order = patient.orders[0]
    assert order.specimen_id == "SPEC-0077"
    assert order.test_code == "GLU"

    # Result
    assert len(order.results) == 1
    result = order.results[0]
    assert result.test_code == "GLU"
    assert result.value == "5.2"
    assert result.units == "mmol/L"
    assert result.abnormal_flags == "N"
    assert result.status == "F"

    # Terminator + flattened convenience view
    assert msg.terminator_code == "N"
    assert [r.test_code for r in msg.results] == ["GLU"]


def test_parse_after_deframing_through_astm_transport():
    """S2.1 + S2.2 compose: de-frame the fixture via the E1381 transport, then
    parse the records — same tree as parsing the raw payload."""
    fx = load_fixture(DIASYS)
    payload = AstmTransport().roundtrip(fx.message_bytes)
    assert payload == fx.message_bytes  # byte-faithful de-frame (LIS-23)
    msg = parse_e1394(payload)
    assert msg.results[0].value == "5.2"


# --- tolerant of spec deviation (plan §2) ----------------------------------


def test_universal_test_id_without_components():
    """A bare test code (no ^^^ components) still resolves."""
    msg = parse_e1394("H|\\^&\rO|1|S1||GLU|R\rR|1|GLU|9.9|mg/dL||H||F\rL|1|N")
    assert msg.results[0].test_code == "GLU"
    assert msg.results[0].abnormal_flags == "H"


def test_result_before_order_creates_implicit_parents():
    # spec deviation: an R with no preceding P/O must not crash.
    msg = parse_e1394("R|1|^^^GLU|5.2|mmol/L||N||F")
    assert len(msg.results) == 1
    assert msg.results[0].test_code == "GLU"


def test_unknown_record_types_are_kept_not_fatal():
    msg = parse_e1394(
        "H|\\^&\rP|1||PID-1\rC|1|I|free-text comment|G\rO|1|S1||^^^NA|R\r"
        "R|1|^^^NA|140|mmol/L||N||F\rM|1|vendor-specific\rL|1|N"
    )
    assert {r.type for r in msg.records} >= {"H", "P", "C", "O", "R", "M", "L"}
    assert msg.results[0].test_code == "NA"  # C/M records don't disturb the tree


def test_missing_header_parses_with_defaults():
    msg = parse_e1394("P|1||PID-9\rR|1|^^^K|4.1|mmol/L||N||F\rL|1|N")
    assert msg.header is None
    assert msg.patients[0].patient_id == "PID-9"
    assert msg.results[0].test_code == "K"


def test_short_records_do_not_crash():
    msg = parse_e1394("H|\\^&\rR|1\rL|1")
    assert msg.results[0].value == ""  # absent field -> ""
    assert msg.results[0].test_code == ""


def test_blank_input_raises():
    with pytest.raises(E1394Error):
        parse_e1394("   ")


def test_cli_parse_astm(capsys):
    from edge_sim.cli import main

    rc = main(["parse-astm", "diasys-r920-astm-result"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DiaSys/R920" in out
    assert "PID-0077" in out
    assert "R GLU 5.2 mmol/L" in out
