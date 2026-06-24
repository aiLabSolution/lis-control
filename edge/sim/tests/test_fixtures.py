"""Conformance-fixture loader: manifest + raw bytes -> a validated Fixture."""

import json
from pathlib import Path

import pytest

from edge_sim.fixtures import FixtureError, load_fixture, load_fixtures

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
EXAMPLE = FIXTURES_ROOT / "_example"


def _valid_manifest():
    return {
        "id": "tmp",
        "analyzer": {"vendor": "ACME", "model": "SIM-1"},
        "protocol": "hl7v2",
        "transport": "loopback",
        "direction": "analyzer-to-host",
        "message": {"path": "m.hl7", "encoding": "ascii", "framing": "raw"},
        "source": {"reference": "synthetic"},
        "synthetic": True,
    }


def test_load_example():
    fx = load_fixture(EXAMPLE)
    assert fx.id == "example-hl7v2-oru-r01"
    assert fx.vendor == "ACME"
    assert fx.model == "SIM-1"
    assert fx.protocol == "hl7v2"
    assert fx.synthetic is True
    assert fx.message_bytes.startswith(b"MSH|")
    assert b"\r" in fx.message_bytes  # HL7 uses CR as the segment terminator


def test_discover_includes_example():
    ids = {fx.id for fx in load_fixtures(FIXTURES_ROOT)}
    assert "example-hl7v2-oru-r01" in ids


def test_missing_manifest(tmp_path):
    with pytest.raises(FixtureError, match="manifest"):
        load_fixture(tmp_path)


def test_missing_message_file(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps(_valid_manifest()))
    with pytest.raises(FixtureError, match="message"):
        load_fixture(tmp_path)


def test_invalid_manifest_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"id": "bad"}))
    with pytest.raises(FixtureError):
        load_fixture(tmp_path)


def test_malformed_json_rejected(tmp_path):
    (tmp_path / "manifest.json").write_text("{not json")
    with pytest.raises(FixtureError, match="JSON"):
        load_fixture(tmp_path)
