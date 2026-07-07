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
itself as EDAN (``MSH-3.1 == H90`` or ``MSH-4 == EDANLAB``) so standard-HL7
analyzers are untouched. The EDAN *H60S* also routes through this profile: the
2026-07-06 physical bench (LIS-20) proved the real H60S emits the same EDANLAB
layout (MSH-3 ``H60^7907`` / MSH-4 ``EDANLAB``, code in OBX-4), and its graduated
fixture is asserted below.

LIS-149 AC3 (return leg) adds a second identifier wrinkle on top of the above: a
**worklist-driven** result (the analyzer accepted an order-download, see
``edan-h99s-worklist-query-qry-r02``) reports against its OWN sample counter in
OBR-2 (meaningless off-instrument) while the scanned barcode — the join key the
worklist ORF echoed — rides in OBR-20 (KB §3.2.3; worked example §6.1;
corroborated by the real H60S bench, where OBR-20 == OBR-2). The **direct-attach**
shape (no worklist, ``edan-h99s-oru-r01``) has no OBR-20 at all and must keep
keying on OBR-2, so ``_specimen_id`` prefers a stripped-non-blank OBR-20 and falls
back to OBR-2 only when it is absent/blank. OBR-20 is also the Seamaty SD1's QC
type/level field (``qc_type``); for EDAN it means something else entirely, so
``qc_type`` is forced blank there — non-EDAN analyzers are untouched. NOT yet
captured on real H99S wire (only blank/connection-test ORUs so far); spec-backed
+ H60S-corroborated. The sim has no OE order-menu lookup — unlike the production
bridge (``BarcodeAccessionResolver``), the barcode IS the join key here.
"""

from pathlib import Path

from edge_sim.cli import main as cli_main
from edge_sim.fixtures import load_fixture
from edge_sim.milestone import run_milestone
from edge_sim.normalize import KIND_ANOMALY, KIND_BLANK, KIND_RESULT, Normalizer, STATUS_NORMALIZED
from edge_sim.oru import RESULT_TYPE_BLANK, parse_oru_r01

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
H99S = FIXTURES_ROOT / "edan-h99s-oru-r01"
H99S_WORKLIST = FIXTURES_ROOT / "edan-h99s-oru-r01-worklist"
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


def test_h60s_is_edanlab_h90_family_after_bench_graduation():
    """The 2026-07-06 physical H60S bench (LIS-20) proved the real EDAN H60S speaks
    the H90-family EDANLAB profile — NOT the clean-HL7 layout the original seed
    assumed. The fixture is graduated to the real wire (MSH-4 'EDANLAB', analyte code
    in OBX-4, patient number in PID-2, sample id in OBR-2), so the parser routes it
    through the EDAN profile just like the H99S."""
    report = _report(H60S)
    assert report.sending_facility == "EDANLAB"
    codes = [o.raw_code for o in report.observations]
    assert codes == ["WBC", "RBC", "HGB", "HCT", "MCV", "PLT"]  # read from OBX-4, not OBX-3
    assert report.patient_id == "PID-0231"   # PID-2 (EDAN), not PID-3
    assert report.specimen_id == "SPEC-0231"  # OBR-2 (EDAN), not OBR-3
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


def test_h60s_milestone_normalizes_all_six_analytes_held_back():
    """The graduated EDAN H60S fixture (real EDANLAB wire, 2026-07-06 bench) runs the
    Stage-1 milestone: all six analytes read from OBX-4 normalize to LOINC and the ACK
    is AA — but, exactly like the H99S, the EDAN OBX-11 carries no Table-0085 finality,
    so the finality-gated ``ingest_payload`` holds them back. The production bridge →
    OpenELIS path is not finality-gated this way; the same bench confirmed the live FHIR
    path stages these MAPPED once OE has pushed the analyzer's code→LOINC map.
    """
    out = run_milestone(load_fixture(H60S).message_bytes)
    assert out.accepted is True
    assert out.ack_code == "AA"
    results = [o for o in out.observations if o.kind == KIND_RESULT]
    assert {o.raw_code for o in results} == {"WBC", "RBC", "HGB", "HCT", "MCV", "PLT"}
    assert all(o.loinc for o in results)          # every analyte mapped to a LOINC (OBX-4)
    assert out.ingest_payload() == []             # EDAN OBX-11 finality gap (held back)


def test_cli_normalize_renders_h99s_panel(capsys):
    rc = cli_main(["normalize", "edan-h99s-oru-r01"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "patient=H99S-PT-01" in out
    assert "specimen=H99S-SPEC-01" in out
    assert out.count("[NORMALIZED]") == 6


# --- LIS-149 AC3 return leg: EDAN OBR-20 barcode reconcile -------------------


def test_h99s_worklist_driven_specimen_id_prefers_obr20_barcode_over_obr2_counter():
    """A worklist-driven EDAN result carries the analyzer's OWN sample counter in
    OBR-2 (``13``, meaningless off-instrument) and the scanned barcode — the join
    key the worklist ORF echoed (KB §3.2.3; worked example §6.1) — in OBR-20.
    ``specimen_id`` must key on the barcode, not the counter, or a worklist-driven
    result orphans; ``barcode`` surfaces the same value separately."""
    report = _report(H99S_WORKLIST)
    fx_expected = load_fixture(H99S_WORKLIST).expected
    assert report.specimen_id == "DEV01260000000000005"
    assert report.specimen_id == fx_expected["specimen_id"]
    assert report.specimen_id != fx_expected["obr2_sample_counter"]  # not the OBR-2 counter
    assert report.barcode == "DEV01260000000000005"


def test_h99s_worklist_panel_normalizes_fully_to_loinc():
    """The worklist-driven shape carries the same CBC panel as the direct-attach
    seed (OBX-4 code repurposing is orthogonal to the OBR-2/OBR-20 identifier
    wrinkle) — it must normalize identically."""
    expected = {o["obx4_code"]: o for o in load_fixture(H99S_WORKLIST).expected["observations"]}
    results = {r.raw_code: r for r in _normalized(H99S_WORKLIST) if r.kind == KIND_RESULT}
    assert set(results) == set(expected)
    for code, exp in expected.items():
        row = results[code]
        assert row.loinc == exp["target_loinc"], code
        assert row.ucum_value == exp["target_ucum"], code
        assert row.status == STATUS_NORMALIZED, code


def test_h99s_direct_attach_carries_no_barcode():
    """The direct-attach shape (no worklist; OBR-2 IS the accession) has no OBR-20
    at all, so ``barcode`` stays blank — the flag distinguishing it from a
    worklist-driven result. Must NOT regress: ``specimen_id`` still reads OBR-2."""
    report = _report(H99S)
    assert report.specimen_id == "H99S-SPEC-01"
    assert report.barcode == ""


def test_h99s_edan_qc_type_is_blank_even_with_obr20_populated():
    """OBR-20 is the Seamaty SD1's QC type/level field (``qc_type``); for EDAN it is
    the scanned barcode instead and must never be misread as a QC type/level — even
    when the message is itself QC-classified (MSH-16=2)."""
    msg = (
        "MSH|^~\\&|H90^^507|EDANLAB|||20260706094500||ORU^R01|9|P|2.4||||2||UTF8\r"
        "PID|6|17|^0||DOE^JOHN||19900101|M\r"
        "OBR|1|13||EDANLAB^H90|||20260706094500|||||||||||||DEV01260000000000005\r"
        "OBX||NM|0|WBC|7.1|10\\S\\9/L|4.0-10.0|0|0|0||7.1^10\\S\\9/L"
    ).encode("utf-8")
    report = parse_oru_r01(msg)
    assert report.qc_type == ""
    assert report.barcode == "DEV01260000000000005"  # OBR-20 still surfaces as the barcode


def test_non_edan_obr20_still_reads_as_qc_type_and_carries_no_barcode():
    """A non-EDAN analyzer (Seamaty SD1 shape) keeps OBR-20 as its QC type/level —
    this profile must not touch it — and never populates ``barcode`` (EDAN-only
    field), even though the message is itself QC-classified (MSH-16=2)."""
    msg = (
        "MSH|^~\\&|SMT|SD1|||20201207144113||ORU^R01|1|P|2.3.1||||2||ASCII\r"
        "PID|1|SD1-0042|||DELA CRUZ^JUAN||1990|M\r"
        "OBR|1||SD1-SPEC-0007|SD1||||||||||||||||QC-NORMAL\r"
        "OBX|1|NM|GLU|GLU|95|mg/dL|70-110|N|||F"
    ).encode("ascii")
    report = parse_oru_r01(msg)
    assert report.qc_type == "QC-NORMAL"
    assert report.barcode == ""


def test_h99s_edan_whitespace_obr20_falls_back_to_obr2():
    """A whitespace-only OBR-20 must be treated as absent (like a blank field), not
    as an empty/present barcode — falling back to the OBR-2 sample id exactly like
    the direct-attach shape."""
    msg = (
        "MSH|^~\\&|H90^^507|EDANLAB|||20260706094500||ORU^R01|9|P|2.4||||0||UTF8\r"
        "PID|6|17|^0||DOE^JOHN||19900101|M\r"
        "OBR|1|H99S-SPEC-99||EDANLAB^H90|||20260706094500|||||||||||||   \r"
        "OBX||NM|0|WBC|7.1|10\\S\\9/L|4.0-10.0|0|0|0||7.1^10\\S\\9/L"
    ).encode("utf-8")
    report = parse_oru_r01(msg)
    assert report.specimen_id == "H99S-SPEC-99"
    assert report.barcode == ""


def test_h60s_obr20_now_surfaces_as_barcode_and_blanks_qc_type():
    """The graduated H60S fixture's OBR-20 happens to equal OBR-2 (both
    ``SPEC-0231``) so ``specimen_id`` is UNCHANGED by this profile — but OBR-20 is
    now surfaced separately as ``barcode`` (also ``SPEC-0231``), and ``qc_type``
    (which used to read OBR-20 verbatim, i.e. ``SPEC-0231``) flips to blank like
    every other EDAN message."""
    report = _report(H60S)
    assert report.specimen_id == "SPEC-0231"  # unchanged: OBR-20 == OBR-2 here
    assert report.barcode == "SPEC-0231"  # NEW: OBR-20 now surfaces as barcode
    assert report.qc_type == ""  # NEW: was "SPEC-0231" before this profile


def test_cli_normalize_renders_h99s_worklist_panel(capsys):
    rc = cli_main(["normalize", "edan-h99s-oru-r01-worklist"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "specimen=DEV01260000000000005" in out
    assert out.count("[NORMALIZED]") == 6
