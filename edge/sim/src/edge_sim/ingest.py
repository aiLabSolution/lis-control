"""Edge → core Result-ingest contract — LIS-17 / S1.5.

The edge (this Python harness) parses and normalizes an analyzer message; the
**core** persists the normalized observation into its append-only Result store via
``org.openelisglobal.result.ingest.ResultIngestService.ingest(NormalizedObservation)``
(core ADR-0003, pinned by LIS-15 / S1.3). The two processes are different languages,
so the seam between them is a **language-neutral value object**, not a shared class:
core ADR-0003 defines its ``NormalizedObservation`` as ``value`` plus the
analyzer-native ``rawCode`` / ``rawUnit`` beside the normalized ``loinc`` /
``ucumValue`` and a normalization ``status`` — the exact raw-beside-normalized shape
this harness's :class:`~edge_sim.normalize.NormalizedObservation` already carries.

This module is the edge half of that wiring: it serializes an edge
:class:`~edge_sim.normalize.NormalizedObservation` to the **ingest contract DTO** —
the JSON object the edge hands to the core ingest seam over whatever transport the
S1.0 substrate decision eventually picks (deliberately still open; ADR-0003). Keeping
the mapping in one named, tested place makes the contract an auditable artifact (ISO
15189 evidence) rather than an ad-hoc dict built at a call site.

The contract carries the **normalization** status (``NORMALIZED`` / ``PARTIAL`` /
``UNMAPPED``); the HL7 *result-lifecycle* finality (OBX-11 ``F`` = final) is an edge
concept surfaced by :mod:`edge_sim.milestone` but **not** part of the S1.3 core
contract (core ``result.status`` is the normalization status per core ADR-0003).
"""

from __future__ import annotations

import json
from pathlib import Path

from ._schema import validate as _schema_validate
from .normalize import NormalizedObservation

__all__ = [
    "INGEST_CONTRACT_FIELDS",
    "INGEST_CONTRACT_SCHEMA_PATH",
    "contract_schema",
    "validate_dto",
    "to_ingest_dto",
    "to_ingest_payload",
]

# The field names of core ADR-0003's NormalizedObservation value object, in the
# order the contract documents them. camelCase mirrors the core Java type; the edge
# emits exactly these keys so the JSON is consumed without a rename layer.
INGEST_CONTRACT_FIELDS = ("value", "rawCode", "rawUnit", "loinc", "ucumValue", "status")

# The committed, language-neutral JSON-Schema for the DTO — the SHARED artifact the
# edge and core both bind to (so a field rename on either side fails fast instead of
# drifting silently). ingest.py lives at src/edge_sim/; the fixtures tree is a sibling
# of src/ (same anchor as fixtures.DEFAULT_FIXTURES_ROOT).
INGEST_CONTRACT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "schema" / "ingest-contract.schema.json"
)


def contract_schema() -> dict:
    """Load the committed ingest-contract JSON-Schema."""
    return json.loads(INGEST_CONTRACT_SCHEMA_PATH.read_text())


def validate_dto(dto: dict) -> None:
    """Validate one ingest DTO against the committed contract schema.

    Raises :class:`edge_sim._schema.SchemaError` on a missing/extra/mistyped field —
    the guard that keeps the edge's emitted shape pinned to core ADR-0003."""
    _schema_validate(dto, contract_schema())


def to_ingest_dto(obs: NormalizedObservation) -> dict:
    """Map one edge :class:`~edge_sim.normalize.NormalizedObservation` onto the core
    ingest contract DTO (core ADR-0003).

    The analyzer-native ``rawCode`` / ``rawUnit`` ride **beside** the normalized
    ``loinc`` / ``ucumValue`` so the core persists the raw evidence next to the
    normalized form (no last-writer-wins on normalization). ``set_id`` is an edge
    message-ordering detail, not part of the persistence contract, so it is dropped.
    """
    return {
        "value": obs.value,
        "rawCode": obs.raw_code,
        "rawUnit": obs.raw_unit,
        "loinc": obs.loinc,
        "ucumValue": obs.ucum_value,
        "status": obs.status,
    }


def to_ingest_payload(observations) -> list[dict]:
    """Serialize an iterable of normalized observations to the ingest contract
    payload — one DTO per observation, in order (one observation → one ``result``
    row, insert-only; core ADR-0003)."""
    return [to_ingest_dto(o) for o in observations]
