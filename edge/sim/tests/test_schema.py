"""Mini JSON-Schema validator: enforces the fixture-manifest contract.

The validator interprets the shipped ``fixture.schema.json`` so that schema stays
the single, language-neutral source of truth for the fixture contract.
"""

import json
from pathlib import Path

import pytest

from edge_sim._schema import SchemaError, validate

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "schema" / "fixture.schema.json"


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


def _valid():
    return {
        "id": "x",
        "analyzer": {"vendor": "ACME", "model": "SIM-1"},
        "protocol": "hl7v2",
        "transport": "loopback",
        "direction": "analyzer-to-host",
        "message": {"path": "m.hl7", "encoding": "ascii", "framing": "raw"},
        "source": {"reference": "synthetic"},
        "synthetic": True,
    }


def test_accepts_valid(schema):
    validate(_valid(), schema)  # must not raise


def test_rejects_missing_required(schema):
    d = _valid()
    del d["protocol"]
    with pytest.raises(SchemaError, match="protocol"):
        validate(d, schema)


def test_rejects_wrong_type(schema):
    d = _valid()
    d["synthetic"] = "yes"  # string where boolean required
    with pytest.raises(SchemaError, match="synthetic"):
        validate(d, schema)


def test_rejects_bad_enum(schema):
    d = _valid()
    d["protocol"] = "smoke-signals"
    with pytest.raises(SchemaError, match="protocol"):
        validate(d, schema)


def test_rejects_additional_property(schema):
    d = _valid()
    d["surprise"] = 1
    with pytest.raises(SchemaError, match="surprise"):
        validate(d, schema)


def test_rejects_nested_missing(schema):
    d = _valid()
    del d["analyzer"]["model"]
    with pytest.raises(SchemaError, match="model"):
        validate(d, schema)
