"""Graduated-fixture provenance rules (schema v2, LIS-319): loader-enforced
checks that sit on top of plain schema validation for any ``synthetic: false``
manifest -- channel-identity provenance, exact unconfirmed-channel-setting
declarations, and digest-verified (bench-capture) or explicitly-offline
(bench-derived) raw artifacts.

All manifests built here use synthetic placeholder values only (never the real
bench measurement numbers/timestamps) -- the one exception is the final test,
which loads the real graduated fixture directory as-is to prove the real
evidence-bin digest verifies (the slice's AC2 proof).
"""

import hashlib
import json
from pathlib import Path

import pytest

from edge_sim.fixtures import FixtureError, load_fixture

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
SNIBELIS_MAGLUMI_X3_RESULT_UPLOAD = FIXTURES_ROOT / "snibelis-maglumi-x3-result-upload"

_MESSAGE_BYTES = b"MSH|^~\\&|SIM|SIM|SIM|SIM|20200101000000||ORU^R01|1|P|2.5\r"
_RAW_BYTES = b"synthetic-bench-capture-bytes-0001"


def _make_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Scratch repo_root with an (empty) fixture directory, returned alongside
    the repo_root itself."""
    repo_root = tmp_path
    fixture_dir = repo_root / "fixtures" / "tmp-fixture"
    fixture_dir.mkdir(parents=True)
    return repo_root, fixture_dir


def _write_raw(repo_root: Path, rel_path: str, content: bytes) -> str:
    """Write ``content`` at ``repo_root/rel_path`` and return its sha256 digest
    string ("sha256:<hex>")."""
    raw_file = repo_root / rel_path
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_bytes(content)
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _base_manifest(**overrides) -> dict:
    manifest = {
        "id": "tmp-fixture",
        "analyzer": {"vendor": "ACME", "model": "SIM-1"},
        "protocol": "hl7v2",
        "transport": "loopback",
        "direction": "analyzer-to-host",
        "message": {"path": "m.hl7", "encoding": "ascii", "framing": "raw"},
        "source": {"reference": "synthetic test fixture"},
        "synthetic": False,
        "channel": {
            "id": "tmp-channel",
            "isolation_group": "tmp",
            "identity": {"analyzer_id": "A", "host_id": "H", "provenance": "bench-capture"},
        },
    }
    manifest.update(overrides)
    return manifest


def _bench_capture_manifest(repo_root: Path, **capture_overrides) -> dict:
    digest = _write_raw(repo_root, "evidence/tmp/raw.bin", _RAW_BYTES)
    capture = {
        "session_id": "synthetic-test-session-0001",
        "source_kind": "bench-capture",
        "raw_path": "evidence/tmp/raw.bin",
        "raw_digest": digest,
        "captured_at": "2020-01-01",
        "instrument": {"model": "SIM-1", "serial": "SIM-SERIAL-0001"},
        "chassis_connected": False,
        "upload_trigger": "manual-lis-online",
        "tool": {"name": "sim-capture-tool"},
    }
    capture.update(capture_overrides)
    return _base_manifest(capture=capture)


def _bench_derived_manifest(**capture_overrides) -> dict:
    capture = {
        "session_id": "synthetic-test-session-0002",
        "source_kind": "bench-derived",
        "raw_digest": "sha256:" + ("a" * 64),
        "captured_at": "2020-01-01",
        "instrument": {"model": "SIM-1", "serial": "SIM-SERIAL-0002"},
        "chassis_connected": False,
        "upload_trigger": "auto",
        "tool": {"name": "sim-derive-tool"},
        "derivation": {"spec": "thoughts/tmp-derivation-spec.md", "ledger": "thoughts/tmp-sanitization.json"},
    }
    capture.update(capture_overrides)
    return _base_manifest(capture=capture)


def _write_fixture(fixture_dir: Path, manifest: dict) -> None:
    (fixture_dir / "m.hl7").write_bytes(_MESSAGE_BYTES)
    (fixture_dir / "manifest.json").write_text(json.dumps(manifest))


# -- (1) channel.identity.provenance must be "bench-capture" ------------------


def test_non_bench_capture_identity_provenance_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    manifest["channel"]["identity"]["provenance"] = "bridge-default-bench-pending"
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="identity"):
        load_fixture(fixture_dir, repo_root=repo_root)


# -- (1b) channel.identity must EXIST for a non-synthetic fixture ------------


def test_missing_identity_block_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    del manifest["channel"]["identity"]
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="identity"):
        load_fixture(fixture_dir, repo_root=repo_root)


# -- (1c) bench-capture forbids a derivation block ---------------------------


def test_bench_capture_with_derivation_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(
        repo_root,
        derivation={"spec": "thoughts/tmp-derivation-spec.md", "ledger": "thoughts/tmp-sanitization.json"},
    )
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="derivation"):
        load_fixture(fixture_dir, repo_root=repo_root)


# -- (2) unconfirmed_channel_settings must exactly match ----------------------


def test_undeclared_unconfirmed_channel_setting_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    manifest["channel"]["tcp"] = {"port": 12345, "provenance": "bridge-default-bench-pending"}
    # capture.unconfirmed_channel_settings intentionally left undeclared.
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="unconfirmed"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_stale_unconfirmed_channel_setting_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root, unconfirmed_channel_settings=["rs232"])
    # No rs232 block at all, and tcp/identity are both bench-capture -- the
    # declaration is stale.
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="unconfirmed"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_exact_unconfirmed_channel_setting_declaration_loads(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root, unconfirmed_channel_settings=["tcp"])
    manifest["channel"]["tcp"] = {"port": 12345, "provenance": "bridge-default-bench-pending"}
    _write_fixture(fixture_dir, manifest)

    fx = load_fixture(fixture_dir, repo_root=repo_root)
    assert fx.manifest["capture"]["unconfirmed_channel_settings"] == ["tcp"]


# -- (3) bench-capture digest verification ------------------------------------


def test_digest_mismatch_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    manifest["capture"]["raw_digest"] = "sha256:" + ("0" * 64)
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="digest"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_digest_match_loads(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    _write_fixture(fixture_dir, manifest)

    fx = load_fixture(fixture_dir, repo_root=repo_root)
    assert fx.manifest["capture"]["source_kind"] == "bench-capture"


# -- (4) bench-derived rules ---------------------------------------------------


def test_bench_derived_without_derivation_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_derived_manifest()
    del manifest["capture"]["derivation"]
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="derivation"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_bench_derived_with_raw_path_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_derived_manifest()
    manifest["capture"]["raw_path"] = "evidence/tmp/raw.bin"
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="raw_path"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_bench_derived_valid_loads_without_digest_verification(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_derived_manifest()
    _write_fixture(fixture_dir, manifest)

    fx = load_fixture(fixture_dir, repo_root=repo_root)
    assert fx.manifest["capture"]["source_kind"] == "bench-derived"
    # The digest is deliberately never checked against any in-repo file for
    # bench-derived -- there is no raw_path to check it against.
    assert "raw_path" not in fx.manifest["capture"]


# -- (5) raw_path traversal guards ---------------------------------------------


def test_absolute_raw_path_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    manifest["capture"]["raw_path"] = "/etc/passwd"
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="raw_path"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_raw_path_traversal_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    manifest["capture"]["raw_path"] = "../outside/raw.bin"
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="raw_path"):
        load_fixture(fixture_dir, repo_root=repo_root)


# -- (6) the real graduated fixture --------------------------------------------


def test_real_graduated_fixture_loads_and_verifies_digest():
    """AC2 proof: the actual snibelis-maglumi-x3-result-upload fixture, loaded
    with the default repo_root, must digest-verify against the real evidence
    capture bin in-repo."""
    fx = load_fixture(SNIBELIS_MAGLUMI_X3_RESULT_UPLOAD)

    assert fx.manifest["capture"]["source_kind"] == "bench-capture"
    assert fx.manifest["capture"]["session_id"] == "20260717-0101010034012301113"
    assert fx.manifest["capture"]["raw_digest"].startswith("sha256:")
    assert fx.manifest["capture"]["unconfirmed_channel_settings"] == ["tcp"]
