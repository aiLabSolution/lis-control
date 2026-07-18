"""SnibeLis/MAGLUMI X3 result-upload normalization — LIS-32 / S3.1.

The E2E happy path for an immunoassay result via SnibeLis: a captured ASTM E1394
result upload (H/P/O/R/L, ``^^^``-prefixed assay ids) is parsed, its raw analyzer
fields preserved, and each analyte normalized to a LOINC/UCUM Result row using the
channel's own terminology data (never a shared seed) — the same raw-beside-normalized
row the bridge POSTs to ``/analyzer/fhir``. Unknown assays/units are retained and
flagged for engineer review, never dropped (KB §7). Session/framing conformance is
LIS-108 (``test_snibelis.py``); this module owns parse → normalize.

RESULT_UPLOAD is graduated to the LIS-75 bench capture (real FT3/FT4 II/TSH II
wire bytes, Pinote QA-approved LOINC/UCUM dictionary, LIS-38 AC1). The other
fixtures here (RESULT_UNMAPPED, CALIBRATION, QC) remain synthetic seeds pending
their own graduation (LIS-276).
"""

from pathlib import Path

from edge_sim.archive import RawMessageArchive
from edge_sim.e1394 import parse_e1394
from edge_sim.normalize import (
    KIND_CALIBRATION,
    KIND_QC,
    KIND_RESULT,
    STATUS_NORMALIZED,
    STATUS_PARTIAL,
    STATUS_UNMAPPED,
)
from edge_sim.fixtures import load_fixture
from edge_sim.replay import check_against_expected, deterministic_round_trip
from edge_sim.transport import LoopbackTransport

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RESULT_UPLOAD = FIXTURES_ROOT / "snibelis-maglumi-x3-result-upload"
RESULT_UNMAPPED = FIXTURES_ROOT / "snibelis-maglumi-x3-result-unmapped"
CALIBRATION = FIXTURES_ROOT / "snibelis-maglumi-x3-calibration"
QC = FIXTURES_ROOT / "snibe-maglumi-x3-qc-astm"


def _replay(fixture_dir, tmp_path):
    """Archive → reload → replay → parse → normalize with the fixture's terminology."""
    return deterministic_round_trip(
        load_fixture(fixture_dir),
        LoopbackTransport(),
        archive=RawMessageArchive(tmp_path),
        received_at="2026-07-03T00:00:00+00:00",
    )


# --- happy path: raw immunoassay result -> normalized LOINC/UCUM row --------


def test_result_upload_normalizes_each_assay_to_loinc_and_ucum(tmp_path):
    """The three-analyte thyroid panel (real LIS-75 bench values) normalizes
    end-to-end: raw code/unit/value preserved beside the resolved LOINC + UCUM,
    status NORMALIZED (LIS-32 AC)."""
    replay = _replay(RESULT_UPLOAD, tmp_path)

    rows = replay.observations
    assert [(r.raw_code, r.loinc, r.ucum_value, r.status) for r in rows] == [
        ("FT3", "3051-0", "pmol/L", STATUS_NORMALIZED),
        ("FT4 II", "14920-3", "ng/dL", STATUS_NORMALIZED),
        ("TSH II", "3016-3", "u[IU]/mL", STATUS_NORMALIZED),
    ]
    # raw analyzer value/unit are carried through unchanged beside the normalized form.
    assert [(r.value, r.raw_unit) for r in rows] == [
        ("5.43", "pmol/L"),
        ("1.58", "ng/dL"),
        ("2.78", "uIU/mL"),
    ]
    # every analyte is a patient RESULT (no QC/warning/calibration in the happy path).
    assert all(r.kind == KIND_RESULT for r in rows)


def test_result_upload_matches_expected_normalized_rows(tmp_path):
    """The manifest's asserted normalized rows match the produced Result exactly —
    the fixture is a deterministic-replay contract for a later bench comparison."""
    fixture = load_fixture(RESULT_UPLOAD)
    replay = _replay(RESULT_UPLOAD, tmp_path)
    assert check_against_expected(replay, fixture.expected) == []


def test_result_upload_is_reproducible(tmp_path):
    """Same bytes + same channel terminology -> identical result digest (the
    reproducibility a bench re-run is checked against)."""
    a = _replay(RESULT_UPLOAD, tmp_path / "a")
    b = _replay(RESULT_UPLOAD, tmp_path / "b")
    assert a.result_digest == b.result_digest


# --- raw provenance fields preserved on parse (R-6/R-7/R-13, KB §7) ---------


def test_parse_preserves_raw_reference_range_flag_and_completion_time():
    """The parsed ASTM result carries R-6 reference range, R-7 abnormal flag and
    R-13 completion time verbatim — provenance the normalized row is derived from
    (ISO 15189 4.13). Real X3 wire places the completion time at field 13, not
    the KB-documented field 12 off-by-one (LIS-75 AC4)."""
    fixture = load_fixture(RESULT_UPLOAD)
    msg = parse_e1394(fixture.message_bytes)
    results = msg.results
    assert [r.reference_range for r in results] == ["3.08 - 6.468", "0.9 - 1.75", "0.3 - 4.5"]
    assert [r.abnormal_flags for r in results] == ["N", "N", "N"]
    assert [r.completion_time for r in results] == [
        "20250320153245",
        "20250320152944",
        "20250320154408",
    ]
    # the completion timestamp survives the transport-neutral report the normalizer reads.
    report_ct = [o.completion_time for o in _report_observations(fixture)]
    assert report_ct == ["20250320153245", "20250320152944", "20250320154408"]


def test_parse_recovers_three_single_assay_orders():
    """The real X3 wire sends one assay per O-record (not the vendor-doc-example
    multi-assay O-5 with a ``\\``-repeat-delimited list) -- three orders under one
    patient, each with a single assay (LIS-75 AC5)."""
    fixture = load_fixture(RESULT_UPLOAD)
    msg = parse_e1394(fixture.message_bytes)
    orders = msg.patients[0].orders
    assert [o.assays for o in orders] == [("FT3",), ("FT4 II",), ("TSH II",)]


# --- missing mapping: retained + flagged, never dropped (LIS-32 AC) ---------


def test_unmapped_assay_and_unit_are_flagged_not_dropped(tmp_path):
    """An assay or unit absent from the channel mapping table normalizes to
    PARTIAL/UNMAPPED and is RETAINED (flagged for engineer review) — never silently
    dropped or guessed (KB §7). All three uploaded results survive."""
    fixture = load_fixture(RESULT_UNMAPPED)
    replay = _replay(RESULT_UNMAPPED, tmp_path)

    rows = replay.observations
    assert len(rows) == 3  # nothing dropped
    assert [(r.raw_code, r.loinc, r.ucum_value, r.status) for r in rows] == [
        ("TSH", "3016-3", "u[IU]/mL", STATUS_NORMALIZED),  # both resolved
        ("AFP", "", "ng/mL", STATUS_PARTIAL),  # unknown assay, known unit
        ("CEA", "", "", STATUS_UNMAPPED),  # neither resolved
    ]
    # the review flag is exactly "status is not NORMALIZED", and the raw code is
    # always preserved so an engineer can identify what needs mapping.
    needs_review = [r for r in rows if r.status != STATUS_NORMALIZED]
    assert [r.raw_code for r in needs_review] == ["AFP", "CEA"]
    assert all(r.raw_code for r in needs_review)


def test_unmapped_fixture_matches_expected_rows(tmp_path):
    fixture = load_fixture(RESULT_UNMAPPED)
    replay = _replay(RESULT_UNMAPPED, tmp_path)
    assert check_against_expected(replay, fixture.expected) == []


# --- calibration gate: kept out of the patient result stream (LIS-125) ------


def test_calibration_upload_routed_out_of_patient_stream(tmp_path):
    """A SnibeLis ASTM upload whose Sample ID carries the calibration convention
    (CAL- prefix) is classified CALIBRATION and every row is re-kinded
    KIND_CALIBRATION — so none of them is a patient RESULT. ASTM has no MSH-16
    wire field (KB §5), so the classifier keys on the Sample-ID convention the
    production bridge exposes as a per-analyzer CALIBRATION_SPECIMEN_ID_PREFIX
    rule (LIS-125)."""
    replay = _replay(CALIBRATION, tmp_path)

    rows = replay.observations
    assert len(rows) == 2  # both rows survive — routed out, never dropped
    assert all(r.kind == KIND_CALIBRATION for r in rows)
    # the patient result stream (what milestone.ingest_payload persists) is empty
    assert [r for r in rows if r.kind == KIND_RESULT] == []


def test_calibration_upload_preserves_normalized_provenance(tmp_path):
    """A calibration row is still normalized to LOINC/UCUM with raw code/unit/value
    preserved before it is routed out — the same raw-beside-normalized provenance a
    patient result carries, so a calibrator is auditable, not discarded blind."""
    replay = _replay(CALIBRATION, tmp_path)

    rows = replay.observations
    assert [(r.raw_code, r.loinc, r.ucum_value, r.status) for r in rows] == [
        ("TSH", "3016-3", "u[IU]/mL", STATUS_NORMALIZED),
        ("FT4", "14920-3", "pmol/L", STATUS_NORMALIZED),
    ]


def test_calibration_fixture_matches_expected_rows(tmp_path):
    """The manifest asserts an empty ``results`` (KIND_RESULT) subset and the two
    normalized rows under ``observations`` — a deterministic replay contract that
    a calibrator produces no patient result."""
    fixture = load_fixture(CALIBRATION)
    replay = _replay(CALIBRATION, tmp_path)
    assert check_against_expected(replay, fixture.expected) == []


# --- QC gate: kept out of the patient result stream (LIS-33) ---------------


def test_qc_upload_routed_out_of_patient_stream(tmp_path):
    """A native X3 ASTM upload with result-shaped R rows is classified as QC by
    host-side context (O.12=Q / Sample-ID convention), so the normalized rows are
    auditable but none are patient RESULT rows."""
    replay = _replay(QC, tmp_path)

    rows = replay.observations
    assert len(rows) == 2
    assert all(r.kind == KIND_QC for r in rows)
    assert [r for r in rows if r.kind == KIND_RESULT] == []


def test_qc_upload_preserves_normalized_provenance(tmp_path):
    """QC rows still carry raw-beside-normalized provenance before they are held
    for QC review; classification changes routing, not parser fidelity."""
    replay = _replay(QC, tmp_path)

    rows = replay.observations
    assert [(r.raw_code, r.loinc, r.ucum_value, r.status) for r in rows] == [
        ("TSH", "3016-3", "u[IU]/mL", STATUS_NORMALIZED),
        ("FT4", "14920-3", "pmol/L", STATUS_NORMALIZED),
    ]


def test_qc_fixture_matches_expected_rows(tmp_path):
    """The manifest asserts an empty patient-result subset and the two normalized
    QC rows — the simulator-side fixture required by LIS-33."""
    fixture = load_fixture(QC)
    replay = _replay(QC, tmp_path)
    assert check_against_expected(replay, fixture.expected) == []


def test_patient_upload_is_not_calibration(tmp_path):
    """Contrast: the same-shaped patient upload (Sample ID without the calibration
    prefix) stays all KIND_RESULT — the gate does not over-capture."""
    replay = _replay(RESULT_UPLOAD, tmp_path)
    assert all(r.kind == KIND_RESULT for r in replay.observations)


def test_patient_upload_is_not_qc(tmp_path):
    """Contrast: the same-shaped patient upload without O.12=Q or the QC Sample-ID
    convention stays all KIND_RESULT."""
    replay = _replay(RESULT_UPLOAD, tmp_path)
    assert all(r.kind == KIND_RESULT for r in replay.observations)


def test_astm_host_side_prefixes_require_the_hyphen_boundary():
    """Specimen ids that merely start with CAL or QC are patient specimens; the
    host-side conventions are CAL- and QC-, so the gates do not over-capture."""
    from edge_sim.oru import RESULT_TYPE_CALIBRATION, RESULT_TYPE_PATIENT, RESULT_TYPE_QC
    from edge_sim.replay import _astm_result_type  # noqa: PLC0415 - test-only introspection

    def result_type(specimen_id, action_code="R"):
        msg = (
            "H|\\^&||PSWD|Maglumi User|||||Lis||P|E1394-97|20260703\r"
            "P|1\r"
            f"O|1|{specimen_id}||^^^TSH|R||||||{action_code}\r"
            "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N\r"
            "L|1|N\r"
        )
        return _astm_result_type(parse_e1394(msg.encode("ascii")))

    assert result_type("CALCIUM-01") == RESULT_TYPE_PATIENT
    assert result_type("QCRUN-01") == RESULT_TYPE_PATIENT
    assert result_type("CAL-2026-07") == RESULT_TYPE_CALIBRATION
    assert result_type("QC-2026-07") == RESULT_TYPE_QC
    assert result_type("PATIENT-2026-07", action_code="Q") == RESULT_TYPE_QC


def _report_observations(fixture):
    """The transport-neutral observations the normalizer consumes, via the same
    ASTM report the replay path builds."""
    from edge_sim.replay import _astm_report  # noqa: PLC0415 - test-only introspection

    return _astm_report(parse_e1394(fixture.message_bytes)).observations
