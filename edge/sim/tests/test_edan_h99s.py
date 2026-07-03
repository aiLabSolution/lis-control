"""LIS-78 follow-up — EDAN **H90-series** (H99S) ``ORU^R01`` parse profile.

The EDAN H90-series repurposes standard HL7 field positions (KB
``EDAN\\WI\\82-01.54.460907`` §5), so the generic tolerant parser reads the wrong
fields for it:

* **OBX code** rides in **OBX-4** (OBX-3 is a suspect flag ``0``/``1``, §5.4) — the
  generic parser reads OBX-3, so every numeric row resolves to code ``0`` and none
  map to LOINC. This is the unconditional blocker this profile closes.
* **Sample id** rides in **OBR-2** (OBR-3 = reviewing doctor, §5.3a).
* **Patient number** rides in **PID-2** (PID-3 = ``Age^unit``, §5.2).

Proven against the synthetic seed ``edan-h99s-oru-r01`` (device code ``507``,
MSH-3 ``H90^^507``) — no hardware. The profile is gated on the message announcing
itself as H90-series (``MSH-3.1 == H90`` or ``MSH-4 == EDANLAB``) so standard-HL7
analyzers — including the EDAN *H60S* seed (MSH-3 ``H60S`` / MSH-4 ``EDAN``, code
in OBX-3) — are untouched.
"""

from pathlib import Path

from edge_sim.cli import main as cli_main
from edge_sim.fixtures import load_fixture
from edge_sim.milestone import run_milestone
from edge_sim.normalize import KIND_ANOMALY, KIND_BLANK, KIND_RESULT, Normalizer, STATUS_NORMALIZED
from edge_sim.oru import RESULT_TYPE_BLANK, parse_oru_r01

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
H99S = FIXTURES_ROOT / "edan-h99s-oru-r01"
H60S = FIXTURES_ROOT / "edan-h60s-oru-r01"


def _report(fixture_dir):
    return parse_oru_r01(load_fixture(fixture_dir).message_bytes)


def _normalized(fixture_dir):
    return Normalizer().normalize_report(_report(fixture_dir))


# --- the blocker: analyte code read from OBX-4, not OBX-3 -------------------


def test_h99s_code_read_from_obx4_not_obx3_suspect_flag():
    """OBX-3 is the suspect flag ``0`` for every H99S row; the analyte code is in
    OBX-4. The profile must read OBX-4, so no row resolves to ``0``."""
    report = _report(H99S)
    codes = [o.raw_code for o in report.observations]
    assert codes == ["WBC", "RBC", "HGB", "HCT", "MCV", "PLT"]
    assert "0" not in codes


def test_h99s_panel_normalizes_fully_to_loinc():
    """With the code read from OBX-4, the whole CBC panel maps to LOINC/UCUM
    (the map already knows the EDAN codes/units), matching ``expected.observations``."""
    expected = {o["obx4_code"]: o for o in load_fixture(H99S).expected["observations"]}
    results = {r.raw_code: r for r in _normalized(H99S) if r.kind == KIND_RESULT}
    assert set(results) == set(expected)
    for code, exp in expected.items():
        row = results[code]
        assert row.loinc == exp["target_loinc"], code
        assert row.ucum_value == exp["target_ucum"], code
        assert row.value == exp["value"], code
        assert row.status == STATUS_NORMALIZED, code


# --- identifier repurposing: OBR-2 sample id, PID-2 patient no. -------------


def test_h99s_specimen_id_read_from_obr2():
    """EDAN carries the sample id in OBR-2 (OBR-3 = reviewing doctor)."""
    report = _report(H99S)
    assert report.specimen_id == "H99S-SPEC-01"
    assert report.specimen_id == load_fixture(H99S).expected["specimen_id"]


def test_h99s_patient_id_read_from_pid2_not_pid3_age():
    """EDAN carries the patient number in PID-2; PID-3 is ``Age^unit`` and must not
    shadow it."""
    report = _report(H99S)
    assert report.patient_id == "H99S-PT-01"
    assert report.patient_id == load_fixture(H99S).expected["patient_id"]


def test_h99s_pid3_age_is_not_used_as_patient_id():
    """A populated PID-3 age (e.g. ``35^Year``) must never win over the PID-2
    patient number for an H90-series message."""
    msg = (
        "MSH|^~\\&|H90^^507|EDANLAB|||20260701||ORU^R01|1|P|2.4||||0||UTF8\r"
        "PID|6|H99S-PT-77|35^Year||DOE^JOHN||19900101|M\r"
        "OBR|1|H99S-SPEC-77||EDANLAB^H90|||20260701\r"
        "OBX||NM|0|WBC|7.1|10\\S\\9/L|4.0-10.0|0|0|0||7.1^10\\S\\9/L"
    ).encode("utf-8")
    report = parse_oru_r01(msg)
    assert report.patient_id == "H99S-PT-77"      # PID-2, not "35"
    assert report.specimen_id == "H99S-SPEC-77"   # OBR-2, not blank
    assert report.observations[0].raw_code == "WBC"  # OBX-4, not "0"


# --- detection is gated correctly ------------------------------------------


def test_detection_by_msh4_edanlab_alone():
    """MSH-4 == EDANLAB is sufficient to trigger the profile even if MSH-3 is bare."""
    msg = (
        "MSH|^~\\&|H90|EDANLAB|||20260701||ORU^R01|1|P|2.4||||0||UTF8\r"
        "PID|6|PT-EDANLAB|^0\r"
        "OBX||NM|0|HGB|130|g/L|110-160|0|0|0||130^g/L"
    ).encode("utf-8")
    report = parse_oru_r01(msg)
    assert report.observations[0].raw_code == "HGB"
    assert report.patient_id == "PT-EDANLAB"


def test_h60s_standard_hl7_is_not_treated_as_h90_series():
    """No regression: the EDAN H60S seed (MSH-3 H60S / MSH-4 EDAN, code in OBX-3)
    must NOT be routed through the H90-series profile — its code stays in OBX-3 and
    its ids resolve from PID-3 / OBR-3."""
    report = _report(H60S)
    codes = [o.raw_code for o in report.observations]
    assert codes == ["WBC", "RBC", "HGB", "HCT", "MCV", "PLT"]  # from OBX-3, unchanged
    assert report.patient_id == "PID-0231"   # PID-3, not PID-2
    assert report.specimen_id == "SPEC-0231"  # OBR-3, not OBR-2
    results = {r.raw_code: r for r in _normalized(H60S) if r.kind == KIND_RESULT}
    assert all(r.status == STATUS_NORMALIZED for r in results.values())


def test_h99s_blank_sample_placeholder_is_not_patient_result_material():
    """Bench-shaped H99S blank/QC material carries ``---`` in NM rows. The
    simulator mirrors the bridge policy: valid sibling rows are classified as
    blank operational material and placeholder numeric rows are anomalies."""
    msg = (
        "MSH|^~\\&|H90^861429-M26416640001^507|EDANLAB|||20260703135352||ORU^R01|5|P|2.4||||0||UTF8\r"
        "PID|3||^0|||||0|0\r"
        "OBR||1||EDANLAB^H90|26|General|20260703125023|19700101080000|||1|||20260703124939|^^Blank sample||\r"
        "OBX||NM|0|WBC|5.0|10\\S\\9/L|4.00-20.00|0|0|0||5.0^10\\S\\9/L\r"
        "OBX||NM|0|MCV|---|fL|82.5-97.4|0|0|0||0.0^fL"
    ).encode("utf-8")

    report = parse_oru_r01(msg)
    rows = {row.raw_code: row for row in Normalizer().normalize_report(report)}

    assert report.result_type == RESULT_TYPE_BLANK
    assert rows["WBC"].kind == KIND_BLANK
    assert rows["MCV"].kind == KIND_ANOMALY
    assert rows["MCV"].value == "---"


# --- end to end -------------------------------------------------------------


def test_h99s_milestone_normalizes_all_six_analytes():
    """Through the Stage-1 milestone pipeline the six H99S analytes parse and
    normalize to LOINC — the code is read from OBX-4, so none collapse to ``0``.

    NOTE: EDAN uses OBX-11 as a "modified?" flag, not HL7 Table-0085 finality
    (KB §5.4), so these rows carry no ``F`` and the finality-gated ``ingest_payload``
    holds them back. Closing EDAN OBX-11 finality is a separate profile step; the
    production bridge → OpenELIS path is not finality-gated this way. See the fixture
    manifest ``parser_gaps``.
    """
    out = run_milestone(load_fixture(H99S).message_bytes)
    results = [o for o in out.observations if o.kind == KIND_RESULT]
    assert {o.raw_code for o in results} == {"WBC", "RBC", "HGB", "HCT", "MCV", "PLT"}
    assert all(o.loinc for o in results)          # every analyte mapped to a LOINC
    assert out.ingest_payload() == []             # OBX-11 finality gap (documented above)


def test_cli_normalize_renders_h99s_panel(capsys):
    rc = cli_main(["normalize", "edan-h99s-oru-r01"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "patient=H99S-PT-01" in out
    assert "specimen=H99S-SPEC-01" in out
    assert out.count("[NORMALIZED]") == 6
