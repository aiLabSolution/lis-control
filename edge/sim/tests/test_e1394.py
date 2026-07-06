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
PANEL = FIXTURES_ROOT / "diasys-r920-astm-panel"
ERBA = FIXTURES_ROOT / "erba-ec90-astm-panel"


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


# --- multi-R per O: one AstmResult node per analyte (LIS-24 AC) -------------


def test_multiple_results_under_one_order_each_become_a_node():
    """A panel with N ``R`` records under a single ``O`` yields N ``AstmResult``
    nodes on that one order — one per analyte — raw code/unit preserved (LIS-24 AC).
    The prior single-R fixture never exercised this."""
    msg = parse_e1394(
        "H|\\^&\rP|1||PID-1\rO|1|S1||^^^BMP|R\r"
        "R|1|^^^GLU|5.2|mmol/L||N||F\r"
        "R|2|^^^BUN|6.0|mmol/L||N||F\r"
        "R|3|^^^CREA|88|umol/L||H||F\rL|1|N"
    )
    assert len(msg.patients) == 1
    assert len(msg.patients[0].orders) == 1
    results = msg.patients[0].orders[0].results
    assert len(results) == 3  # three analytes -> three result nodes on one order
    assert [r.test_code for r in results] == ["GLU", "BUN", "CREA"]
    assert [r.value for r in results] == ["5.2", "6.0", "88"]
    assert [r.units for r in results] == ["mmol/L", "mmol/L", "umol/L"]
    assert [r.abnormal_flags for r in results] == ["N", "N", "H"]
    # the flattened convenience view lists every analyte in record order.
    assert [r.test_code for r in msg.results] == ["GLU", "BUN", "CREA"]


def test_parse_diasys_panel_fixture_multi_analyte():
    """The multi-analyte panel fixture parses to one order carrying four R nodes,
    and round-trips byte-faithfully through the E1381 transport (LIS-23 + LIS-24)."""
    fx = load_fixture(PANEL)
    msg = parse_e1394(fx.message_bytes)
    assert len(msg.patients[0].orders) == 1
    order = msg.patients[0].orders[0]
    assert len(order.results) == 4
    assert [r.test_code for r in order.results] == ["GLU", "BUN", "CREA", "K"]
    assert [r.units for r in order.results] == ["mmol/L", "mmol/L", "umol/L", "mmol/L"]
    assert AstmTransport().roundtrip(fx.message_bytes) == fx.message_bytes


def test_parse_erba_ec90_panel_fixture_multi_analyte():
    """LIS-26 ERBA EC90 re-scope: an ASTM panel parses as one isolated analyzer
    channel payload with final R records and raw code/unit preserved."""
    fx = load_fixture(ERBA)
    msg = parse_e1394(fx.message_bytes)
    assert msg.header is not None
    assert msg.header.sender_name == "ERBA"
    assert msg.header.sender_model == "EC90"
    assert len(msg.patients) == 1
    assert msg.patients[0].patient_id == "PID-026"
    order = msg.patients[0].orders[0]
    assert order.specimen_id == "SPEC-026"
    assert [r.test_code for r in order.results] == ["GLU", "NA", "K", "CL", "CA"]
    assert [r.units for r in order.results] == ["mg/dL", "mmol/L", "mmol/L", "mmol/L", "mg/dL"]
    assert [r.status for r in order.results] == ["F"] * 5
    assert AstmTransport().roundtrip(fx.message_bytes) == fx.message_bytes


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


def test_non_default_delimiters_declared_in_header():
    """Delimiters are taken from the ``H`` record: a message declaring ``!`` as the
    field delimiter and ``*`` as the component delimiter parses with those, not the
    conventional ``|``/``^``."""
    msg = parse_e1394(
        "H!\\*&!!!DiaSys*R920\rO!1!S1!!*GLU!R\rR!1!*GLU!5.2!mmol/L!!N!!F\rL!1!N"
    )
    assert msg.header is not None
    assert msg.header.sender_name == "DiaSys"
    assert msg.header.sender_model == "R920"  # component split on '*'
    assert msg.results[0].test_code == "GLU"
    assert msg.results[0].value == "5.2"
    assert msg.results[0].units == "mmol/L"


def test_trailing_empty_components_resolve_to_the_code():
    """A universal-test-id with *trailing* empty components (``GLU^^^``) resolves to
    the code, just like the leading-empty form (``^^^GLU``)."""
    msg = parse_e1394("H|\\^&\rR|1|GLU^^^|5.2|mmol/L||N||F\rL|1|N")
    assert msg.results[0].test_code == "GLU"


def test_trailing_empty_component_yields_empty_field():
    """A trailing empty component (``H``-5 ``DiaSys^``) yields an empty
    ``sender_model`` rather than crashing."""
    msg = parse_e1394("H|\\^&|||DiaSys^\rL|1|N")
    assert msg.header.sender_name == "DiaSys"
    assert msg.header.sender_model == ""


# --- SnibeLis/MAGLUMI immunoassay parse semantics (LIS-32 / S3.1) -----------


def test_result_preserves_r13_completion_time():
    """A SnibeLis MAGLUMI ``R`` record carries the test-completion timestamp in
    R-13 (``YYYYMMDDHHMMSS``); the parser preserves it verbatim for provenance
    (KB §7; ISO 15189 4.13). Earlier ASTM fixtures (DiaSys/ERBA) omitted R-13, so
    the field defaulted to ``""``; this pins that it is now captured beside the
    R-6 reference range and R-7 abnormal flag."""
    msg = parse_e1394(
        "H|\\^&||PSWD|Maglumi User|||||Lis||P|E1394-97|20260703\r"
        "P|1\rO|1|SNB-1||^^^TSH|R\r"
        "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N|||||20260703101530\rL|1|N"
    )
    result = msg.patients[0].orders[0].results[0]
    assert result.completion_time == "20260703101530"
    assert result.reference_range == "0.27 to 4.20"
    assert result.abnormal_flags == "N"


def test_result_reads_completion_time_at_spec_r13_position():
    """When the timestamp sits at the true ASTM R-13 position (one field later than
    the manual's example), it is read there directly — the spec position is
    preferred over the tolerant scan."""
    msg = parse_e1394(
        "H|\\^&\rP|1\rO|1|S1||^^^FT4|R\r"
        "R|1|^^^FT4|14.8|pmol/L|12 to 22|N||||||20260703101530\rL|1|N"
    )
    assert msg.patients[0].orders[0].results[0].completion_time == "20260703101530"


def test_result_completion_time_defaults_blank_when_absent():
    """An ``R`` record without any timestamp field yields ``""`` — not a crash, and
    the tolerant scan does not misread the value/range/flag fields."""
    msg = parse_e1394("H|\\^&\rP|1\rO|1|S1||^^^GLU|R\rR|1|^^^GLU|5.2|mmol/L||N||F\rL|1|N")
    assert msg.patients[0].orders[0].results[0].completion_time == ""


def test_order_splits_multi_assay_o5_on_repeat_delimiter():
    """SnibeLis packs a multi-assay order into O-5 as ``^^^A\\^^^B`` (``\\`` =
    ASTM repetition). The order exposes each analyzer-native assay code with the
    mandatory ``^^^`` prefix stripped, in transmission order (KB §5.3/§7, gotcha #6)."""
    msg = parse_e1394(
        "H|\\^&\rP|1\rO|1|SNB-108-001||^^^TSH\\^^^FT4|R\r"
        "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N|||||20260703101530\r"
        "R|2|^^^FT4|14.8|pmol/L|12 to 22|N|||||20260703101530\rL|1|N"
    )
    order = msg.patients[0].orders[0]
    assert order.assays == ("TSH", "FT4")


def test_order_single_assay_o5_is_a_one_tuple():
    """A single-assay O-5 (``^^^ALT``) exposes a one-element ``assays`` tuple."""
    msg = parse_e1394("H|\\^&\rP|1\rO|1|S1||^^^ALT|R\rL|1|N")
    assert msg.patients[0].orders[0].assays == ("ALT",)


def test_order_empty_o5_yields_no_assays():
    """An order with no O-5 universal test id yields an empty ``assays`` tuple."""
    msg = parse_e1394("H|\\^&\rP|1\rO|1|S1||\rL|1|N")
    assert msg.patients[0].orders[0].assays == ()


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
