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


def _valid_capture():
    return {
        "session_id": "synthetic-test-session",
        "source_kind": "bench-capture",
        "raw_digest": "sha256:" + ("0" * 64),
        "captured_at": "2020-01-01",
        "instrument": {"model": "SIM-1", "serial": "SIM-SERIAL"},
        "chassis_connected": False,
        "upload_trigger": "manual-lis-online",
        "tool": {"name": "sim-tool"},
    }


def test_if_then_requires_capture_when_not_synthetic(schema):
    d = _valid()
    d["synthetic"] = False
    with pytest.raises(SchemaError, match="capture"):
        validate(d, schema)


def test_synthetic_true_without_capture_still_valid(schema):
    d = _valid()
    d["synthetic"] = True
    validate(d, schema)  # must not raise


def test_synthetic_false_with_capture_valid(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    validate(d, schema)  # must not raise


def test_capture_pattern_rejects_malformed_digest(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["raw_digest"] = "not-a-digest"
    with pytest.raises(SchemaError, match="raw_digest"):
        validate(d, schema)


def test_capture_type_union_allows_null_firmware(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["instrument"]["firmware"] = None
    validate(d, schema)  # must not raise


def test_capture_type_union_rejects_integer_firmware(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["instrument"]["firmware"] = 123
    with pytest.raises(SchemaError, match="firmware"):
        validate(d, schema)


# -- capture.source_kind "bench-recombined" + capture.recombination (LIS-319) --


def test_source_kind_bench_recombined_accepted_by_enum(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["source_kind"] = "bench-recombined"
    d["capture"]["raw_path"] = "evidence/tmp/raw.bin"
    d["capture"]["recombination"] = {"normalized_fields": {"O": [2]}}
    validate(d, schema)  # must not raise


def test_recombination_block_validates(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["source_kind"] = "bench-recombined"
    d["capture"]["raw_path"] = "evidence/tmp/raw.bin"
    d["capture"]["recombination"] = {
        "normalized_fields": {"O": [2]},
        "note": "O-record sequence renumbered across flattened envelopes",
    }
    validate(d, schema)  # must not raise


def test_recombination_requires_normalized_fields(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["source_kind"] = "bench-recombined"
    d["capture"]["raw_path"] = "evidence/tmp/raw.bin"
    d["capture"]["recombination"] = {"note": "missing the required field"}
    with pytest.raises(SchemaError, match="normalized_fields"):
        validate(d, schema)


def test_recombination_rejects_additional_property(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["source_kind"] = "bench-recombined"
    d["capture"]["raw_path"] = "evidence/tmp/raw.bin"
    d["capture"]["recombination"] = {"normalized_fields": {"O": [2]}, "surprise": 1}
    with pytest.raises(SchemaError, match="surprise"):
        validate(d, schema)


def test_normalized_fields_rejects_non_array_value_via_items_type(schema):
    """normalized_fields' record-type properties (e.g. "O") are declared
    ``{"type": "array", "items": {"type": "integer"}}`` -- a non-array value
    must be rejected."""
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["source_kind"] = "bench-recombined"
    d["capture"]["raw_path"] = "evidence/tmp/raw.bin"
    d["capture"]["recombination"] = {"normalized_fields": {"O": "not-an-array"}}
    with pytest.raises(SchemaError, match="O"):
        validate(d, schema)


def test_normalized_fields_rejects_non_integer_array_items(schema):
    d = _valid()
    d["synthetic"] = False
    d["capture"] = _valid_capture()
    d["capture"]["source_kind"] = "bench-recombined"
    d["capture"]["raw_path"] = "evidence/tmp/raw.bin"
    d["capture"]["recombination"] = {"normalized_fields": {"O": ["two"]}}
    with pytest.raises(SchemaError):
        validate(d, schema)


def test_if_then_else_without_then_or_else_passes():
    # A bare "if" with no matching "then"/"else" branch is a no-op — the schema
    # itself only declares "then", but the validator must support both being
    # absent (used here to isolate the mechanism from the fixture schema).
    fragment = {"if": {"properties": {"flag": {"const": True}}}}
    validate({"flag": False}, fragment)
    validate({"flag": True}, fragment)


def test_if_then_else_applies_matching_branch():
    fragment = {
        "if": {"properties": {"flag": {"const": True}}},
        "then": {"required": ["a"]},
        "else": {"required": ["b"]},
    }
    validate({"flag": True, "a": 1}, fragment)
    with pytest.raises(SchemaError, match="a"):
        validate({"flag": True}, fragment)
    validate({"flag": False, "b": 2}, fragment)
    with pytest.raises(SchemaError, match="b"):
        validate({"flag": False}, fragment)
