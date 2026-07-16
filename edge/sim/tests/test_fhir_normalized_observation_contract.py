"""ADR-0015 Decision 5 bridge FHIR ↔ simulator DTO conformance."""

import json
from pathlib import Path

import pytest

from edge_sim._schema import SchemaError
from edge_sim.ingest import to_ingest_dto, validate_dto
from edge_sim.normalize import NormalizedObservation


SIM_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "contracts"
    / "normalized-observation.json"
)
BRIDGE_MIRROR = (
    Path(__file__).resolve().parents[2]
    / "drivers"
    / "src"
    / "test"
    / "resources"
    / "contracts"
    / "normalized-observation.json"
)


def _fixture_observation():
    expected = json.loads(SIM_FIXTURE.read_text())
    observation = NormalizedObservation(
        set_id="contract-fixture",
        value=expected["value"],
        raw_code=expected["rawCode"],
        raw_unit=expected["rawUnit"],
        loinc=expected["loinc"],
        ucum_value=expected["ucumValue"],
        status=expected["status"],
    )
    return expected, observation


def test_public_dto_serialization_matches_bridge_contract_fixture():
    expected, observation = _fixture_observation()

    actual = to_ingest_dto(observation)

    validate_dto(actual)
    assert actual == expected
    # Umbrella CI intentionally checks out without submodules. When the bridge
    # is initialized (developer/slice worktrees), pin its standalone resource
    # byte-for-byte to this canonical simulator fixture.
    if BRIDGE_MIRROR.exists():
        assert SIM_FIXTURE.read_bytes() == BRIDGE_MIRROR.read_bytes()


@pytest.mark.parametrize("drift", ["add", "remove", "rename"])
def test_contract_rejects_any_public_dto_field_drift(drift):
    _, observation = _fixture_observation()
    drifted = to_ingest_dto(observation)

    if drift == "add":
        drifted["newField"] = "unexpected"
    elif drift == "remove":
        drifted.pop("rawUnit")
    else:
        drifted["raw_code"] = drifted.pop("rawCode")

    with pytest.raises(SchemaError):
        validate_dto(drifted)
