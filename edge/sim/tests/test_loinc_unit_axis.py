"""LOINC property axis vs. the unit the analyzer actually reports — LIS-299.

A LOINC code encodes a *property* (what kind of quantity it is), and that property
has to agree with the unit the analyzer put on the wire. Our stack never reads the
property: the value and its UCUM unit are carried opaquely, so a mismatch is silent
here and only becomes visible to a downstream consumer that keys on LOINC — which is
exactly what a receiving HIS does. A normal 1.58 ng/dL Free T4 filed under a
Moles/volume code (reference interval ~12-22 pmol/L) reads as grossly abnormal.

String-presence assertions cannot catch this class of defect: the sim suite passed
for months with both X3 thyroid analytes on the wrong axis, because every test only
checked that the mapped code was the code the fixture declared. This module asserts
the pairing itself, so a future terminology edit that reintroduces a wrong-axis code
fails here rather than at a customer's HIS.

Codes absent from ``LOINC_AXIS`` are skipped rather than failed — the table only
claims what has been verified against loinc.org. ``test_x3_thyroid_panel_is_covered``
keeps the X3 panel from silently dropping out of that coverage.
"""

import json
import os
from pathlib import Path

import pytest

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
UMBRELLA_ROOT = Path(__file__).resolve().parents[3]
SHIPPED_X3_PROFILES = (
    UMBRELLA_ROOT
    / "core/openelis/projects/analyzer-profiles/astm/snibe-maglumi-x3.json",
    UMBRELLA_ROOT
    / "deploy/kit/configs/analyzer-profiles/astm/snibe-maglumi-x3.json",
)
PROFILE_COVERAGE_MODE = "LIS_X3_PROFILE_COVERAGE"

LIS_75_X3_BENCH_DICTIONARY = [
    ("FT3", "pmol/L", "14928-6"),
    ("FT4 II", "ng/dL", "3024-7"),
    ("TSH II", "uIU/mL", "3016-3"),
]
EXPECTED_X3_UCUM = [
    ("FT3", "pmol/L"),
    ("FT4 II", "ng/dL"),
    ("TSH II", "u[IU]/mL"),
]

# LOINC code -> (property axis, long name). Verified against loinc.org, not recall.
# The mass/molar pairs below are the LIS-299 trap: within a pair the codes differ
# ONLY by axis, so a code is right or wrong depending on the unit beside it.
LOINC_AXIS = {
    "14928-6": ("SCnc", "Triiodothyronine (T3) Free [Moles/volume] in Serum or Plasma"),
    "3051-0": ("MCnc", "Triiodothyronine (T3) Free [Mass/volume] in Serum or Plasma"),
    "14920-3": ("SCnc", "Thyroxine (T4) free [Moles/volume] in Serum or Plasma"),
    "3024-7": ("MCnc", "Thyroxine (T4) free [Mass/volume] in Serum or Plasma"),
    "3016-3": ("ACnc", "Thyrotropin [Units/volume] in Serum or Plasma"),
}

# Raw analyzer unit (or its UCUM form) -> the property axis it can express.
# SCnc = substance/moles per volume, MCnc = mass per volume,
# ACnc = arbitrary (international) units per volume.
UNIT_AXIS = {
    "pmol/L": "SCnc",
    "nmol/L": "SCnc",
    "umol/L": "SCnc",
    "pg/mL": "MCnc",
    "ng/dL": "MCnc",
    "ng/mL": "MCnc",
    "ug/dL": "MCnc",
    "uIU/mL": "ACnc",
    "u[IU]/mL": "ACnc",
    "mIU/L": "ACnc",
}


def _observations():
    """Every (fixture, raw_code, unit, loinc) an X3-style manifest declares."""
    for manifest_path in sorted(FIXTURES_ROOT.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        for obs in manifest.get("expected", {}).get("observations", []):
            loinc = obs.get("loinc")
            unit = obs.get("raw_unit") or obs.get("ucum_value")
            if loinc and unit:
                yield manifest_path.parent.name, obs.get("raw_code"), unit, loinc


def _load_shipped_x3_profile(profile_path):
    """Read a pinned profile, making absence fatal in the deploy-kit job."""
    if not profile_path.is_file():
        if os.environ.get(PROFILE_COVERAGE_MODE) == "required":
            pytest.fail(f"required shipped X3 profile is missing: {profile_path}")
        pytest.skip(f"pinned component is not checked out: {profile_path}")
    return json.loads(profile_path.read_text())


def test_missing_shipped_profile_skips_unless_coverage_is_required(
    tmp_path, monkeypatch
):
    """The no-submodule job may skip; deploy-kit CI must fail on a missing pin."""
    missing_profile = tmp_path / "snibe-maglumi-x3.json"
    monkeypatch.delenv(PROFILE_COVERAGE_MODE, raising=False)
    with pytest.raises(pytest.skip.Exception):
        _load_shipped_x3_profile(missing_profile)

    monkeypatch.setenv(PROFILE_COVERAGE_MODE, "required")
    with pytest.raises(pytest.fail.Exception, match="required shipped X3 profile"):
        _load_shipped_x3_profile(missing_profile)


def _axis_mismatches(observations):
    mismatches = []
    for source, code, unit, loinc in observations:
        if loinc not in LOINC_AXIS or unit not in UNIT_AXIS:
            continue
        loinc_axis = LOINC_AXIS[loinc][0]
        unit_axis = UNIT_AXIS[unit]
        if loinc_axis != unit_axis:
            mismatches.append(
                f"{source}: {code} reports {unit} ({unit_axis}) but is mapped to "
                f"{loinc} which is {loinc_axis} — {LOINC_AXIS[loinc][1]}"
            )
    return mismatches


def test_every_known_loinc_matches_the_axis_of_its_reported_unit():
    """No fixture pairs a LOINC with a unit of a different property axis."""
    assert _axis_mismatches(_observations()) == []


@pytest.mark.parametrize("profile_path", SHIPPED_X3_PROFILES)
def test_shipped_x3_profile_matches_lis_75_bench_dictionary(profile_path):
    """Both shipped profiles carry the exact bench dictionary on the right axes."""
    profile = _load_shipped_x3_profile(profile_path)
    mappings = profile["default_test_mappings"]
    observed = [
        (mapping.get("test_code"), mapping.get("unit"), mapping.get("loinc"))
        for mapping in mappings
    ]

    assert observed == LIS_75_X3_BENCH_DICTIONARY
    assert _axis_mismatches(
        (profile_path.as_posix(), code, unit, loinc)
        for code, unit, loinc in observed
    ) == []
    assert [
        (mapping.get("test_code"), mapping.get("ucum")) for mapping in mappings
    ] == EXPECTED_X3_UCUM
    assert profile["profileMeta"]["version"] == "0.2.0"


def test_x3_thyroid_panel_is_covered():
    """Every X3 analyte is actually checked above, and is the expected triple.

    The axis check skips codes it cannot vouch for, which makes it fail *open*:
    without this test, dropping a code from LOINC_AXIS -- or adding a fourth
    analyte whose code is not in the table -- would silently leave the panel that
    motivated this module unchecked while the suite stayed green. So assert
    coverage against the raw panel, deliberately NOT through the same filter
    being guarded, before asserting the mappings themselves.
    """
    panel = {
        (code, unit, loinc)
        for fixture, code, unit, loinc in _observations()
        if fixture == "snibelis-maglumi-x3-result-upload"
    }
    uncovered = {
        (code, unit, loinc)
        for code, unit, loinc in panel
        if loinc not in LOINC_AXIS or unit not in UNIT_AXIS
    }
    assert uncovered == set(), (
        "X3 analytes are not covered by the axis check -- add each code's "
        "loinc.org property (and any new unit) to the tables above"
    )
    assert panel == set(LIS_75_X3_BENCH_DICTIONARY)


def test_mass_molar_counterparts_are_distinguishable():
    """The paired codes really do differ by axis only.

    This is what makes a bare find-and-replace on the code string unsafe: 14920-3 is
    correct wherever it sits beside pmol/L, and wrong only beside ng/dL.
    """
    for molar, mass in (("14928-6", "3051-0"), ("14920-3", "3024-7")):
        assert LOINC_AXIS[molar][0] == "SCnc"
        assert LOINC_AXIS[mass][0] == "MCnc"
