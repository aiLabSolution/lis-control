"""Conformance-fixture loader: manifest + raw bytes -> a validated Fixture."""

import json
from pathlib import Path

import pytest

from edge_sim.fixtures import FixtureError, load_fixture, load_fixtures

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
EXAMPLE = FIXTURES_ROOT / "_example"
ERBA = FIXTURES_ROOT / "erba-ec90-astm-panel"
SNIBELIS_MAGLUMI_X3_FIXTURES = (
    FIXTURES_ROOT / "snibelis-maglumi-x3-result-upload",
    FIXTURES_ROOT / "snibelis-maglumi-x3-result-unmapped",
    FIXTURES_ROOT / "snibelis-maglumi-x3-query-request",
    FIXTURES_ROOT / "snibelis-maglumi-x3-calibration",
)
SNIBE_MAGLUMI_X3_HL7_FIXTURES = (
    FIXTURES_ROOT / "snibelis-maglumi-x3-oul-r22-result",
    FIXTURES_ROOT / "snibelis-maglumi-x3-oul-r22-qc",
)


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


def test_erba_fixture_carries_channel_config_and_terminology_data():
    fx = load_fixture(ERBA)

    assert fx.channel["id"] == "erba-ec90-serial-astm"
    assert fx.channel["isolation_group"] == "erba-ec90"
    # Line-setting values are unconfirmed bridge defaults until the bench
    # capture lands — the provenance marker keeps them from reading as fact.
    assert fx.channel["rs232"]["provenance"] == "bridge-default-bench-pending"
    assert fx.channel["rs232"]["baud_rate"] == 9600
    assert fx.channel["rs232"]["data_bits"] == 8
    assert fx.channel["rs232"]["parity"] == "NONE"
    assert fx.channel["rs232"]["stop_bits"] == 1
    assert fx.channel["rs232"]["db9"]["pinout"] == "bench-pending"

    assert fx.terminology["codes"]["NA"] == "2951-2"
    assert fx.terminology["codes"]["K"] == "2823-3"
    assert fx.terminology["units"]["mmol/L"] == "mmol/L"


@pytest.mark.parametrize("directory", SNIBELIS_MAGLUMI_X3_FIXTURES, ids=lambda p: p.name)
def test_snibelis_maglumi_x3_fixtures_carry_bridge_channel_settings(directory):
    fx = load_fixture(directory)

    # LIS-175 two-level mirror: the sim's per-analyzer channel block carries the
    # same dedicated-listener port and identity settings the bridge registers
    # under bridge.analyzers, so the two sides don't drift apart silently.
    assert fx.channel["tcp"]["port"] == 12021
    assert fx.channel["identity"]["analyzer_id"] == "Maglumi User"
    assert fx.channel["identity"]["host_id"] == "Lis"
    assert fx.channel["identity"]["bridge_registry_id"] == "SNIBE-MAGLUMI-X3-001"


@pytest.mark.parametrize("directory", SNIBE_MAGLUMI_X3_HL7_FIXTURES, ids=lambda p: p.name)
def test_snibe_maglumi_x3_hl7_fixtures_carry_shared_mllp_channel_settings(directory):
    fx = load_fixture(directory)

    assert fx.protocol == "hl7v2"
    assert fx.transport == "mllp"
    assert fx.framing == "mllp"
    assert fx.channel["tcp"]["port"] == 2575
    assert fx.channel["identity"]["analyzer_id"] == "MAGLUMI"
    assert fx.channel["identity"]["host_id"] == "LIS"
    assert fx.channel["identity"]["bridge_registry_id"] == "SNIBE-MAGLUMI-X3-001"


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
