"""Off-scale qualified NM/SN values survive normalization — LIS-252.

Mirrors the bridge fix (``FhirBundleBuilder.parseQualifiedNumeric``): a
comparator-qualified analyzer value (``<0.008``, ``>1000``, ``<=0.01``,
``>=500``, the Unicode ``≤``/``≥`` forms, and the SN-structured ``<^0.008``) is a
numeric result, not a parser anomaly. Before the fix the sim demoted these to
``KIND_ANOMALY``, dropping them from the patient result stream — the same silent
loss the bridge had on its ASTM/HL7 legs.

The wire-level cases below use ASCII comparators only: ``parse_message`` decodes
the wire as latin-1 (UTF-8 support is deferred to the LIS-79 bench capture), so a
Unicode ``≤``/``≥`` byte sequence cannot round-trip through the wire yet. Unicode
normalization is asserted directly at the observation level, where a real UTF-8
codepoint is present, and end-to-end on the bridge (which owns the FHIR
Quantity.comparator representation).
"""

import pytest

from edge_sim.normalize import KIND_ANOMALY, KIND_RESULT, Normalizer
from edge_sim.oru import RawObservation, parse_oru_r01


def _message(value_type: str, value: str) -> bytes:
    # SNIBE MAGLUMI X3 HL7 fallback shape (OUL^R22), mirroring the bridge's
    # HL7ResultParserTest.QualifiedValues message.
    return (
        "MSH|^~\\&|MAGLUMI|LIS|||20260707101530||OUL^R22|123|P|2.5||NE|NE|UTF-8\r"
        "PID|1||PID-SNB-176-001||DOE^MAGLUMI||19800101|2\r"
        "OBR|1|||FT4^1\r"
        f"OBX|1|{value_type}|FT4||{value}|pmol/L|12 to 22|N|||F|||20260707101500\r"
    ).encode()


def _wire_row(value_type: str, value: str):
    report = parse_oru_r01(_message(value_type, value))
    rows = Normalizer().normalize_report(report)
    assert len(rows) == 1, "the qualified row must survive parse + normalize"
    return rows[0]


def _obs(value_type: str, value: str) -> RawObservation:
    return RawObservation(
        set_id="1",
        value_type=value_type,
        raw_code="FT4",
        raw_text="",
        raw_system="",
        sub_id="",
        value=value,
        raw_unit="pmol/L",
        reference_range="12 to 22",
        abnormal_flags="N",
        status="F",
    )


@pytest.mark.parametrize("value", ["<0.008", ">1000", "<=0.01", ">=500"])
def test_nm_comparator_values_stay_result(value):
    row = _wire_row("NM", value)
    assert row.kind == KIND_RESULT, f"{value} must stay a patient result, not an anomaly"
    assert row.value == value, "the raw qualified value is preserved beside the normalized fields"


@pytest.mark.parametrize("value", ["<^0.008", ">=^500"])
def test_sn_structured_comparator_values_stay_result(value):
    assert _wire_row("SN", value).kind == KIND_RESULT


@pytest.mark.parametrize("value", ["≤0.01", "≥500"])
def test_unicode_comparator_values_stay_result(value):
    # Observation-level: a real UTF-8 codepoint, bypassing the latin-1 wire decode.
    assert Normalizer().normalize_observation(_obs("NM", value)).kind == KIND_RESULT


def test_genuinely_nonnumeric_nm_still_anomaly():
    assert _wire_row("NM", "---").kind == KIND_ANOMALY, "genuine placeholders still fail visibly"


def test_plain_decimal_stays_result():
    assert _wire_row("NM", "14.8").kind == KIND_RESULT
