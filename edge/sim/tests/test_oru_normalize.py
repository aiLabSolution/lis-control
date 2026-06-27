"""LIS-14 / S1.2 — tolerant ORU^R01 parse + LOINC/UCUM normalization.

The acceptance proof: a RAYTO RAC-050 ``ORU^R01`` carrying analyzer-native
(local) observation codes and raw vendor units is parsed and normalized to a
LOINC/UCUM intermediate row, asserted against the fixture manifest's
``expected`` block (the conformance contract).
"""

from pathlib import Path

import pytest

from edge_sim.fixtures import load_fixture
from edge_sim.normalize import NormalizedObservation, Normalizer, TerminologyMap
from edge_sim.oru import OruParseError, parse_oru_r01

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RAC050 = FIXTURES_ROOT / "rayto-rac050-oru-r01"


# --- parse -----------------------------------------------------------------


def test_parse_rac050_oru_extracts_observations():
    fx = load_fixture(RAC050)
    report = parse_oru_r01(fx.message_bytes)

    assert report.message_type == "ORU^R01"
    assert report.sending_app == "RAC-050"
    assert report.message_control_id == "MSG00142"
    assert report.patient_id == "PID-0142"
    assert report.specimen_id == "SPEC-0142"
    assert len(report.observations) == 4

    hgb = report.observations[0]
    assert hgb.set_id == "1"
    assert hgb.value_type == "NM"
    assert hgb.raw_code == "HGB"
    assert hgb.raw_text == "Hemoglobin"
    assert hgb.raw_system == "99RAC"
    assert hgb.value == "14.2"
    assert hgb.raw_unit == "g/dL"
    assert hgb.status == "F"


# --- normalize (acceptance) ------------------------------------------------


def test_normalize_rac050_matches_manifest_expected():
    """The S1.2 exit gate: every observation maps to its expected LOINC/UCUM
    intermediate row, raw_code/raw_unit preserved beside loinc/ucum_value/status."""
    fx = load_fixture(RAC050)
    report = parse_oru_r01(fx.message_bytes)
    normalized = Normalizer().normalize_report(report)

    expected = fx.expected["observations"]
    assert len(normalized) == len(expected)
    for got, exp in zip(normalized, expected):
        assert isinstance(got, NormalizedObservation)
        assert got.set_id == exp["set_id"]
        assert got.raw_code == exp["raw_code"]          # analyzer-native code preserved
        assert got.raw_unit == exp["raw_unit"]          # raw vendor unit preserved
        assert got.value == exp["value"]
        assert got.loinc == exp["loinc"]                # normalized LOINC populated
        assert got.ucum_value == exp["ucum_value"]      # normalized UCUM populated
        assert got.status == exp["status"]


def test_normalize_transforms_vendor_unit_to_ucum():
    """K/uL (vendor) -> 10*3/uL (UCUM) is a genuine transformation, not identity."""
    fx = load_fixture(RAC050)
    wbc = Normalizer().normalize_report(parse_oru_r01(fx.message_bytes))[2]
    assert wbc.raw_unit == "K/uL"
    assert wbc.ucum_value == "10*3/uL"
    assert wbc.loinc == "6690-2"
    assert wbc.status == "NORMALIZED"


# --- tolerant-parse negatives (plan §1 exit gate) --------------------------


def test_unmapped_code_preserves_raw_and_flags_status():
    msg = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260626||ORU^R01|M1|P|2.3\r"
        "OBX|1|NM|ZZZ^Mystery^99RAC||1.0|g/dL|||||F"
    ).encode("ascii")
    obs = Normalizer().normalize_report(parse_oru_r01(msg))[0]
    assert obs.raw_code == "ZZZ"
    assert obs.loinc == ""          # no LOINC mapping
    assert obs.ucum_value == "g/dL"  # unit still maps
    assert obs.status == "PARTIAL"


def test_missing_unit_does_not_crash():
    msg = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260626||ORU^R01|M1|P|2.3\r"
        "OBX|1|NM|HGB^Hemoglobin^99RAC||14.2"  # truncated: no unit/range/status fields
    ).encode("ascii")
    report = parse_oru_r01(msg)
    obs = Normalizer().normalize_report(report)[0]
    assert obs.raw_code == "HGB"
    assert obs.value == "14.2"
    assert obs.raw_unit == ""
    assert obs.loinc == "718-7"
    assert obs.ucum_value == ""
    assert obs.status == "PARTIAL"


def test_non_oru_message_parses_without_crashing():
    """A non-ORU message (here an ACK) yields a report with no observations,
    not an exception — tolerant ingest."""
    msg = b"MSH|^~\\&|LIS|LAB|RAC-050|RAYTO|20260626||ACK^R01|M1|P|2.3\rMSA|AA|MSG00142"
    report = parse_oru_r01(msg)
    assert report.message_type == "ACK^R01"
    assert report.observations == ()


def test_missing_msh_raises():
    with pytest.raises(OruParseError):
        parse_oru_r01(b"OBX|1|NM|HGB^Hemoglobin^99RAC||14.2|g/dL")


def test_blank_obx_lines_skipped():
    msg = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260626||ORU^R01|M1|P|2.3\r"
        "OBX|1|NM|HGB^Hemoglobin^99RAC||14.2|g/dL|||||F\r"
        "\r"  # stray empty segment
        "OBX|2|NM|HCT^Hematocrit^99RAC||42.1|%|||||F"
    ).encode("ascii")
    report = parse_oru_r01(msg)
    assert len(report.observations) == 2


# --- CLI -------------------------------------------------------------------


def test_cli_normalize(capsys):
    from edge_sim.cli import main

    rc = main(["normalize", "rayto-rac050-oru-r01"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "rayto-rac050-oru-r01" in out
    assert "ORU^R01" in out
    assert "LOINC 718-7" in out  # HGB normalized
    assert "UCUM 10*3/uL" in out  # WBC/PLT unit normalized
    assert "[NORMALIZED]" in out

