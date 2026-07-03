"""SnibeLis/MAGLUMI X3 result-upload normalization — LIS-32 / S3.1.

The E2E happy path for an immunoassay result via SnibeLis: a captured ASTM E1394
result upload (H/P/O/R/L, ``^^^``-prefixed assay ids) is parsed, its raw analyzer
fields preserved, and each analyte normalized to a LOINC/UCUM Result row using the
channel's own terminology data (never a shared seed) — the same raw-beside-normalized
row the bridge POSTs to ``/analyzer/fhir``. Unknown assays/units are retained and
flagged for engineer review, never dropped (KB §7). Session/framing conformance is
LIS-108 (``test_snibelis.py``); this module owns parse → normalize.

All fixtures here are synthetic (LIS-75 blocks a real SnibeLis capture); a live
capture graduates them via LIS-38.
"""

from pathlib import Path

from edge_sim.archive import RawMessageArchive
from edge_sim.e1394 import parse_e1394
from edge_sim.normalize import (
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
    """The two-analyte thyroid panel normalizes end-to-end: raw code/unit/value
    preserved beside the resolved LOINC + UCUM, status NORMALIZED (LIS-32 AC)."""
    replay = _replay(RESULT_UPLOAD, tmp_path)

    rows = replay.observations
    assert [(r.raw_code, r.loinc, r.ucum_value, r.status) for r in rows] == [
        ("TSH", "3016-3", "u[IU]/mL", STATUS_NORMALIZED),
        ("FT4", "14920-3", "pmol/L", STATUS_NORMALIZED),
    ]
    # raw analyzer value/unit are carried through unchanged beside the normalized form.
    assert [(r.value, r.raw_unit) for r in rows] == [("2.31", "uIU/mL"), ("14.8", "pmol/L")]
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
    (ISO 15189 4.13)."""
    fixture = load_fixture(RESULT_UPLOAD)
    msg = parse_e1394(fixture.message_bytes)
    results = msg.patients[0].orders[0].results
    assert [r.reference_range for r in results] == ["0.27 to 4.20", "12 to 22"]
    assert [r.abnormal_flags for r in results] == ["N", "N"]
    assert [r.completion_time for r in results] == ["20260703101530", "20260703101530"]
    # the completion timestamp survives the transport-neutral report the normalizer reads.
    report_ct = [o.completion_time for o in _report_observations(fixture)]
    assert report_ct == ["20260703101530", "20260703101530"]


def test_parse_recovers_multi_assay_order_list():
    """The multi-assay O-5 (``^^^TSH\\^^^FT4``) is split into the ordered assay
    list with ``^^^`` stripped (KB §5.3/§7)."""
    fixture = load_fixture(RESULT_UPLOAD)
    msg = parse_e1394(fixture.message_bytes)
    assert msg.patients[0].orders[0].assays == ("TSH", "FT4")


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


def _report_observations(fixture):
    """The transport-neutral observations the normalizer consumes, via the same
    ASTM report the replay path builds."""
    from edge_sim.replay import _astm_report  # noqa: PLC0415 - test-only introspection

    return _astm_report(parse_e1394(fixture.message_bytes)).observations
