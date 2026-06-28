"""Edge → core Result-ingest contract serialization (LIS-17 / S1.5).

The edge emits the language-neutral NormalizedObservation DTO (core ADR-0003) that
the core ``ResultIngestService.ingest`` consumes — value plus analyzer-native
rawCode/rawUnit beside the normalized loinc/ucumValue and the normalization status.
"""

from edge_sim.ingest import INGEST_CONTRACT_FIELDS, to_ingest_dto, to_ingest_payload
from edge_sim.normalize import (
    STATUS_NORMALIZED,
    STATUS_UNMAPPED,
    NormalizedObservation,
)

NORMALIZED = NormalizedObservation(
    set_id="1",
    value="6.8",
    raw_code="WBC",
    raw_unit="10^9/L",
    loinc="6690-2",
    ucum_value="10*9/L",
    status=STATUS_NORMALIZED,
)


def test_to_ingest_dto_maps_core_adr0003_fields():
    dto = to_ingest_dto(NORMALIZED)
    assert dto == {
        "value": "6.8",
        "rawCode": "WBC",
        "rawUnit": "10^9/L",
        "loinc": "6690-2",
        "ucumValue": "10*9/L",
        "status": "NORMALIZED",
    }
    # set_id is an edge ordering detail, not part of the persistence contract.
    assert "set_id" not in dto
    assert "setId" not in dto


def test_dto_keys_are_exactly_the_contract_fields():
    dto = to_ingest_dto(NORMALIZED)
    assert tuple(dto.keys()) == INGEST_CONTRACT_FIELDS


def test_partial_normalization_still_serializes():
    """A tolerant ingest: an unmapped observation carries empty loinc/ucum but
    still serializes (core persists it with status=UNMAPPED; core ADR-0003)."""
    unmapped = NormalizedObservation(
        set_id="9",
        value="1.0",
        raw_code="ZZZ",
        raw_unit="widgets",
        loinc="",
        ucum_value="",
        status=STATUS_UNMAPPED,
    )
    dto = to_ingest_dto(unmapped)
    assert dto["loinc"] == ""
    assert dto["ucumValue"] == ""
    assert dto["status"] == "UNMAPPED"
    assert dto["rawCode"] == "ZZZ"  # raw evidence preserved even when unmapped


def test_to_ingest_payload_preserves_order():
    a = NORMALIZED
    b = NormalizedObservation("2", "4.85", "RBC", "10^12/L", "789-8", "10*12/L", STATUS_NORMALIZED)
    payload = to_ingest_payload([a, b])
    assert [d["rawCode"] for d in payload] == ["WBC", "RBC"]
    assert len(payload) == 2
