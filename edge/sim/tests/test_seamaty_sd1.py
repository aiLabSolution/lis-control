"""LIS-86 / S2.10 — Seamaty SD1 ``ORU^R01`` ingestion delta.

The SD1-specific deltas on the existing tolerant ``ORU^R01`` parse + LOINC/UCUM
normalize machinery (LIS-13 / LIS-14), proven against the landed synthetic
fixture ``seamaty-sd1-oru-r01`` (PR #28) — no hardware:

1. **PID-2 MRN fallback** — the SD1 carries the medical-record number in PID-2
   (manual §3.3); the tolerant parser reads PID-3, so the id parses empty until a
   PID-2 fallback lands. The fallback must not shadow a present PID-3 (no
   regression for PID-3 analyzers such as the EDAN H60S).
2. **Biochem LOINC/UCUM maps** — the dry-chem panel (BUN/CREA/AST/ALT/TP and the
   U/L enzyme unit) is seeded so the whole panel normalizes alongside GLU.
3. **In-band 'Alarm' OBX routing** — the SD1 emits instrument warnings in-band as
   an ST ``OBX`` (OBX-3='Alarm', warning code in OBX-4); these are routed as a
   flag/note, never as a numeric patient result row.
"""

from pathlib import Path

from edge_sim.fixtures import load_fixture
from edge_sim.milestone import run_milestone
from edge_sim.normalize import (
    KIND_RESULT,
    KIND_WARNING,
    Normalizer,
    STATUS_NORMALIZED,
    STATUS_UNMAPPED,
)
from edge_sim.oru import parse_oru_r01

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
SD1 = FIXTURES_ROOT / "seamaty-sd1-oru-r01"
EDAN = FIXTURES_ROOT / "edan-h60s-oru-r01"

# raw_code -> (expected LOINC, expected UCUM) for the SD1 dry-chem panel.
EXPECTED_PANEL = {
    "GLU": ("2345-7", "mg/dL"),
    "BUN": ("3094-0", "mg/dL"),
    "CREA": ("2160-0", "mg/dL"),
    "AST": ("1920-8", "U/L"),
    "ALT": ("1742-6", "U/L"),
    "TP": ("2885-2", "g/dL"),
}


def _normalized(fixture_dir):
    report = parse_oru_r01(load_fixture(fixture_dir).message_bytes)
    return Normalizer().normalize_report(report)


# --- AC1: PID-2 MRN fallback -----------------------------------------------


def test_sd1_patient_id_falls_back_to_pid2():
    """PID-3 is empty for the SD1; the MRN rides in PID-2 (manual §3.3)."""
    report = parse_oru_r01(load_fixture(SD1).message_bytes)
    assert report.patient_id == "SD1-0042"


def test_pid3_analyzer_still_resolves_from_pid3():
    """No regression: the EDAN H60S carries the id in PID-3; the PID-2 fallback
    must not change a PID-3 analyzer's resolved patient id."""
    report = parse_oru_r01(load_fixture(EDAN).message_bytes)
    assert report.patient_id == "PID-0231"


def test_pid3_preferred_over_pid2_when_both_present():
    """PID-3 is the canonical patient identifier; PID-2 is *only* a fallback, so a
    PID carrying both prefers PID-3."""
    msg = (
        "MSH|^~\\&|SMT|SD1|||20201207||ORU^R01|1|P|2.3.1\r"
        "PID|1|MRN-FROM-2|PID3-ID|||DOE^J\r"
        "OBX|1|NM|GLU|GLU|95|mg/dL|70-110|N|||F"
    ).encode("ascii")
    assert parse_oru_r01(msg).patient_id == "PID3-ID"


def test_sd1_patient_id_matches_manifest_expected():
    fx = load_fixture(SD1)
    assert parse_oru_r01(fx.message_bytes).patient_id == fx.expected["patient_id"]


# --- AC2: biochem LOINC/UCUM maps ------------------------------------------


def test_sd1_biochem_panel_normalizes_fully():
    """Every analyte in the SD1 dry-chem panel maps to LOINC and UCUM (NORMALIZED),
    alongside the already-mapped GLU."""
    results = [r for r in _normalized(SD1) if r.kind == KIND_RESULT]
    by_code = {r.raw_code: r for r in results}
    assert set(by_code) == set(EXPECTED_PANEL)
    for code, (loinc, ucum) in EXPECTED_PANEL.items():
        row = by_code[code]
        assert row.loinc == loinc, code
        assert row.ucum_value == ucum, code
        assert row.status == STATUS_NORMALIZED, code


def test_sd1_unit_ul_maps_to_ucum():
    """U/L (enzyme activity, AST/ALT) is a genuine new map, not identity-by-luck."""
    ast = next(r for r in _normalized(SD1) if r.raw_code == "AST")
    assert ast.raw_unit == "U/L"
    assert ast.ucum_value == "U/L"
    assert ast.loinc == "1920-8"
    assert ast.status == STATUS_NORMALIZED


def test_sd1_results_match_manifest_expected():
    """The conformance contract: normalized result rows match the fixture
    manifest's asserted ``expected.results`` exactly (raw preserved beside
    LOINC/UCUM/status)."""
    fx = load_fixture(SD1)
    results = [r for r in Normalizer().normalize_report(parse_oru_r01(fx.message_bytes))
               if r.kind == KIND_RESULT]
    expected = fx.expected["results"]
    assert len(results) == len(expected)
    for got, exp in zip(results, expected):
        assert got.set_id == exp["set_id"]
        assert got.raw_code == exp["raw_code"]
        assert got.value == exp["value"]
        assert got.raw_unit == exp["raw_unit"]
        assert got.loinc == exp["loinc"]
        assert got.ucum_value == exp["ucum_value"]
        assert got.status == exp["status"]


def test_unmapped_biochem_code_degrades_gracefully():
    """An intentionally-unknown analyte still parses, preserves its raw value/unit,
    and is flagged with a gap status rather than dropped — tolerant ingest."""
    msg = (
        "MSH|^~\\&|SMT|SD1|||20201207||ORU^R01|1|P|2.3.1\r"
        "PID|1|SD1-0042\r"
        "OBX|1|NM|ZZZ|ZZZ|1.23|widgets|0-1|H|||F"
    ).encode("ascii")
    obs = Normalizer().normalize_report(parse_oru_r01(msg))[0]
    assert obs.kind == KIND_RESULT
    assert obs.raw_code == "ZZZ"
    assert obs.value == "1.23"          # raw value preserved
    assert obs.raw_unit == "widgets"    # raw unit preserved
    assert obs.loinc == ""              # no LOINC -> gap
    assert obs.ucum_value == ""         # no UCUM -> gap
    assert obs.status == STATUS_UNMAPPED


# --- AC3: in-band 'Alarm' OBX routing --------------------------------------


def test_inband_alarm_obx_routed_as_warning_not_result():
    """The OBX-3='Alarm' ST warning is a flag/note (KIND_WARNING), distinguishable
    from — and excluded from — the numeric analyte result rows."""
    rows = _normalized(SD1)
    warnings = [r for r in rows if r.kind == KIND_WARNING]
    results = [r for r in rows if r.kind == KIND_RESULT]

    assert len(warnings) == 1
    assert len(results) == 6

    warning = warnings[0]
    assert warning.raw_code == "Alarm"
    assert "Reagent rotor" in warning.value   # the warning sentence is the note text
    assert warning.loinc == ""                # not a normalized analyte
    assert warning.ucum_value == ""
    assert all(r.raw_code != "Alarm" for r in results)


def test_alarm_warning_code_captured_from_obx4():
    """The warning code rides in OBX-4 (e.g. W3001); the parser captures it so the
    routed note carries the code, not just the sentence."""
    report = parse_oru_r01(load_fixture(SD1).message_bytes)
    alarm = next(o for o in report.observations if o.raw_code == "Alarm")
    assert alarm.sub_id == "W3001"


def test_milestone_excludes_alarm_from_ingest_result_rows():
    """End-to-end: through the Stage-1 milestone pipeline the alarm never reaches the
    core ingest result stream, while the six final analyte results do."""
    out = run_milestone(load_fixture(SD1).message_bytes)
    payload = out.ingest_payload()
    assert all(dto["rawCode"] != "Alarm" for dto in payload)
    assert {dto["rawCode"] for dto in payload} == {"GLU", "BUN", "CREA", "AST", "ALT", "TP"}
    # the warning is still surfaced as a note, just not as a result.
    assert any(w.raw_code == "Alarm" for w in out.warnings)
