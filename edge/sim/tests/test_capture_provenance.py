"""Graduated-fixture provenance rules (schema v2, LIS-319): loader-enforced
checks that sit on top of plain schema validation for any ``synthetic: false``
manifest -- channel-identity provenance, exact unconfirmed-channel-setting
declarations, digest-verified (bench-capture/bench-recombined) or
explicitly-offline (bench-derived) raw artifacts, and (bench-capture /
bench-recombined) record-level containment tying the message bytes to the
digest-verified raw capture.

All manifests built here use synthetic placeholder values only (never the real
bench measurement numbers/timestamps) -- the one exception is the final test,
which loads the real graduated fixture directory as-is to prove the real
evidence-bin digest AND record containment verify (the slice's AC2 proof, and
now the LIS-319 provenance-classification fix's live proof).
"""

import hashlib
import json
from pathlib import Path

import pytest

from edge_sim.fixtures import FixtureError, load_fixture

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
SNIBELIS_MAGLUMI_X3_RESULT_UPLOAD = FIXTURES_ROOT / "snibelis-maglumi-x3-result-upload"

# A tiny synthetic ASTM E1394-shaped session: the raw artifact is the same
# records, session-control-framed (ENQ STX ... CR-joined ... CR ETX EOT); the
# message is the same records LF-joined with no framing. This lets the
# "happy path" bench-capture/bench-recombined builders below satisfy the new
# record-containment check by construction.
_SYNTHETIC_RECORDS = [
    b"H|\\^&|||SIM^SIM-1|||||||P|E1394-97|20200101000000",
    b"P|1",
    b"O|1|SPEC-0001||^^^GLU",
    b"R|1|^^^GLU|100|mg/dL|70-110|N||||||20200101000000",
    b"L|1|N",
]
_MESSAGE_BYTES = b"\n".join(_SYNTHETIC_RECORDS) + b"\n"
_RAW_BYTES = b"\x05\x02" + b"\r".join(_SYNTHETIC_RECORDS) + b"\r\x03\x04"


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
        "protocol": "astm-e1394",
        "transport": "loopback",
        "direction": "analyzer-to-host",
        "message": {"path": "message.astm", "encoding": "ascii", "framing": "raw"},
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


def _bench_capture_manifest(repo_root: Path, raw_bytes: bytes = _RAW_BYTES, **capture_overrides) -> dict:
    digest = _write_raw(repo_root, "evidence/tmp/raw.bin", raw_bytes)
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


def _bench_recombined_manifest(repo_root: Path, raw_bytes: bytes = _RAW_BYTES, **capture_overrides) -> dict:
    digest = _write_raw(repo_root, "evidence/tmp/raw.bin", raw_bytes)
    capture = {
        "session_id": "synthetic-test-session-0003",
        "source_kind": "bench-recombined",
        "raw_path": "evidence/tmp/raw.bin",
        "raw_digest": digest,
        "captured_at": "2020-01-01",
        "instrument": {"model": "SIM-1", "serial": "SIM-SERIAL-0003"},
        "chassis_connected": False,
        "upload_trigger": "manual-lis-online",
        "tool": {"name": "sim-capture-tool"},
        "recombination": {"normalized_fields": {"O": [2]}, "note": "synthetic recombination for test"},
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


def _write_fixture(fixture_dir: Path, manifest: dict, message_bytes: bytes = _MESSAGE_BYTES) -> None:
    (fixture_dir / manifest["message"]["path"]).write_bytes(message_bytes)
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


# -- (6) record-level containment (LIS-319: provenance-classification fix) ----


def test_bench_capture_message_record_absent_from_raw_rejected(tmp_path):
    """The provenance-inheritance attack: a bench-capture manifest whose
    message bytes include a record the raw capture never produced must be
    refused, not silently accepted because the digest happens to verify."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    attack_records = _SYNTHETIC_RECORDS + [b"C|1|1|ATTACKER-INJECTED-RECORD|G"]
    message_bytes = b"\n".join(attack_records) + b"\n"
    _write_fixture(fixture_dir, manifest, message_bytes=message_bytes)

    with pytest.raises(FixtureError, match="not found in raw capture"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_non_astm_protocol_bench_capture_containment_not_implemented(tmp_path):
    """Containment verification is only implemented for astm-e1394; any other
    protocol must fail closed rather than silently skip the check."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    manifest["protocol"] = "hl7v2"
    manifest["message"] = {"path": "m.hl7", "encoding": "ascii", "framing": "raw"}
    _write_fixture(fixture_dir, manifest, message_bytes=b"MSH|^~\\&|SIM|SIM|SIM|SIM|20200101000000||ORU^R01|1|P|2.5\r")

    with pytest.raises(FixtureError, match="containment verification is not implemented"):
        load_fixture(fixture_dir, repo_root=repo_root)


# Two synthetic single-assay ASTM envelopes captured back-to-back on a bench,
# mirroring the real snibelis-maglumi-x3-result-upload transformation: the
# real wire sends each assay as its own envelope; the message flattens them
# into one multi-order transmission with the O-record sequence field
# renumbered.
_ENVELOPE_1 = [
    b"H|\\^&|||SIM^SIM-1|||||||P|E1394-97|20200101000000",
    b"P|1",
    b"O|1|SPEC-A||^^^TEST1",
    b"R|1|^^^TEST1|10|U|1-20|N||||||20200101000001",
    b"L|1|N",
]
_ENVELOPE_2 = [
    b"H|\\^&|||SIM^SIM-1|||||||P|E1394-97|20200101000000",
    b"P|1",
    b"O|1|SPEC-B||^^^TEST2",
    b"R|1|^^^TEST2|20|U|1-30|N||||||20200101000002",
    b"L|1|N",
]
_RECOMBINED_RAW_BYTES = (
    b"\x05\x02" + b"\r".join(_ENVELOPE_1) + b"\r\x03\x04" + b"\x05\x02" + b"\r".join(_ENVELOPE_2) + b"\r\x03\x04"
)
_RECOMBINED_MESSAGE_RECORDS = [
    b"H|\\^&|||SIM^SIM-1|||||||P|E1394-97|20200101000000",
    b"P|1",
    b"O|1|SPEC-A||^^^TEST1",  # verbatim from envelope 1 -- sequence already "1"
    b"R|1|^^^TEST1|10|U|1-20|N||||||20200101000001",
    b"O|2|SPEC-B||^^^TEST2",  # renumbered from envelope 2's O|1|... -- field 2 masked
    b"R|1|^^^TEST2|20|U|1-30|N||||||20200101000002",
    b"L|1|N",
]
_RECOMBINED_MESSAGE_BYTES = b"\n".join(_RECOMBINED_MESSAGE_RECORDS) + b"\n"


def test_bench_recombined_masked_match_loads(tmp_path):
    """The positive case: a message that flattens two raw envelopes into one
    transmission, with the O-record sequence field renumbered, loads when
    normalized_fields declares that rewrite."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_recombined_manifest(repo_root, raw_bytes=_RECOMBINED_RAW_BYTES)
    _write_fixture(fixture_dir, manifest, message_bytes=_RECOMBINED_MESSAGE_BYTES)

    fx = load_fixture(fixture_dir, repo_root=repo_root)
    assert fx.manifest["capture"]["source_kind"] == "bench-recombined"
    assert fx.manifest["capture"]["recombination"]["normalized_fields"] == {"O": [2]}


def test_bench_recombined_without_recombination_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_recombined_manifest(repo_root, raw_bytes=_RECOMBINED_RAW_BYTES)
    del manifest["capture"]["recombination"]
    _write_fixture(fixture_dir, manifest, message_bytes=_RECOMBINED_MESSAGE_BYTES)

    with pytest.raises(FixtureError, match="recombination"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_recombination_on_bench_capture_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    manifest["capture"]["recombination"] = {"normalized_fields": {"O": [2]}}
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="recombination"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_recombination_on_bench_derived_rejected(tmp_path):
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_derived_manifest()
    manifest["capture"]["recombination"] = {"normalized_fields": {"O": [2]}}
    _write_fixture(fixture_dir, manifest)

    with pytest.raises(FixtureError, match="recombination"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_bench_recombined_record_absent_even_after_masking_rejected(tmp_path):
    """A record that matches neither verbatim nor after masking the declared
    normalized_fields must still be refused -- normalized_fields is not a
    blanket license to accept any record of that type."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_recombined_manifest(repo_root, raw_bytes=_RECOMBINED_RAW_BYTES)
    bogus_records = _RECOMBINED_MESSAGE_RECORDS + [b"O|3|SPEC-C||^^^TEST3"]
    message_bytes = b"\n".join(bogus_records) + b"\n"
    _write_fixture(fixture_dir, manifest, message_bytes=message_bytes)

    with pytest.raises(FixtureError, match="not found in raw capture"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_normalized_fields_declaring_field_one_rejected_by_schema(tmp_path):
    """Field 1 is the record-type letter itself; declaring it as a
    'normalized' field would let the recombination silently swap record
    types, which is never legitimate. Since LIS-319 fix 1, the schema's items
    enum ([2]) now catches this before the loader's own containment check
    even runs -- 1 is not one of [2]."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_recombined_manifest(
        repo_root, raw_bytes=_RECOMBINED_RAW_BYTES, recombination={"normalized_fields": {"O": [1]}}
    )
    _write_fixture(fixture_dir, manifest, message_bytes=_RECOMBINED_MESSAGE_BYTES)

    with pytest.raises(FixtureError, match="not one of"):
        load_fixture(fixture_dir, repo_root=repo_root)


# -- (8) LIS-319 re-gate fix: normalized_fields restricted to the sequence ----
# -- field (A1/A2), and bench-capture requires exact multiset equality (C1) --


def test_normalized_fields_value_field_rejected_by_schema(tmp_path):
    """The A1/A2 re-gate loophole: capture.recombination.normalized_fields was
    unbounded, so declaring a value field (e.g. R.4, the measurement) let
    swapped or fabricated measurement content pass containment while
    claiming bench provenance. Loaded through the public loader, the schema
    (fix 1) now rejects this before the loader's containment check runs."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_recombined_manifest(
        repo_root, raw_bytes=_RECOMBINED_RAW_BYTES, recombination={"normalized_fields": {"R": [4]}}
    )
    _write_fixture(fixture_dir, manifest, message_bytes=_RECOMBINED_MESSAGE_BYTES)

    with pytest.raises(FixtureError, match="not one of"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_verify_record_containment_defense_in_depth_rejects_h_and_non_sequence_index(tmp_path):
    """Defense-in-depth (fix 1): the loader's own containment check
    independently rejects an "H" declaration or a non-2 field index in
    normalized_fields, even when called directly with a hand-built manifest
    dict that bypasses schema validation entirely -- proving the guard does
    not rely solely on the schema's items enum."""
    from edge_sim.fixtures import _verify_record_containment

    manifest_path = tmp_path / "manifest.json"
    (tmp_path / "message.astm").write_bytes(_MESSAGE_BYTES)
    base_manifest = {
        "protocol": "astm-e1394",
        "message": {"path": "message.astm", "encoding": "ascii", "framing": "raw"},
    }

    manifest = {**base_manifest, "capture": {"recombination": {"normalized_fields": {"H": [2]}}}}
    with pytest.raises(FixtureError, match="'H'"):
        _verify_record_containment(manifest, manifest_path, tmp_path, _RAW_BYTES, "bench-recombined")

    manifest = {**base_manifest, "capture": {"recombination": {"normalized_fields": {"O": [4]}}}}
    with pytest.raises(FixtureError, match="sequence field"):
        _verify_record_containment(manifest, manifest_path, tmp_path, _RAW_BYTES, "bench-recombined")

    # The legitimate declaration -- O.2 -- must not raise from this guard (it
    # may still fail containment matching itself, but not this check).
    manifest = {**base_manifest, "capture": {"recombination": {"normalized_fields": {"O": [2]}}}}
    _verify_record_containment(manifest, manifest_path, tmp_path, _RAW_BYTES, "bench-recombined")


def test_bench_capture_dropped_record_rejected(tmp_path):
    """The C1 re-gate loophole: bench-capture containment was a one-directional
    subset check, so a message that DROPS records (e.g. omits the P and L
    records) still loaded as 'verbatim (redacted) real bytes' as long as every
    record it DID contain was verbatim-contained in the raw capture. Fix 2
    requires the raw record multiset to be consumed exactly for
    'bench-capture'."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    dropped_records = [r for r in _SYNTHETIC_RECORDS if not r.startswith(b"P|") and not r.startswith(b"L|")]
    message_bytes = b"\n".join(dropped_records) + b"\n"
    _write_fixture(fixture_dir, manifest, message_bytes=message_bytes)

    with pytest.raises(FixtureError, match="unconsumed"):
        load_fixture(fixture_dir, repo_root=repo_root)


def test_bench_capture_exact_multiset_match_loads(tmp_path):
    """Positive case for fix 2: a bench-capture message that consumes the raw
    record multiset exactly (the common case -- one envelope, verbatim) still
    loads."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_capture_manifest(repo_root)
    _write_fixture(fixture_dir, manifest)

    fx = load_fixture(fixture_dir, repo_root=repo_root)
    assert fx.manifest["capture"]["source_kind"] == "bench-capture"


def test_bench_recombined_leftover_duplicate_records_still_loads(tmp_path):
    """Fix 2 applies only to 'bench-capture'; 'bench-recombined' keeps subset
    semantics because flattening multiple envelopes into one transmission
    legitimately drops duplicate H/P/L records. This mirrors
    test_bench_recombined_masked_match_loads, named here to make the subset
    exemption explicit against fix 2 (raw has 10 records across two envelopes;
    the flattened message consumes only 7, leaving 3 duplicate H/P/L records
    unconsumed)."""
    repo_root, fixture_dir = _make_repo(tmp_path)
    manifest = _bench_recombined_manifest(repo_root, raw_bytes=_RECOMBINED_RAW_BYTES)
    _write_fixture(fixture_dir, manifest, message_bytes=_RECOMBINED_MESSAGE_BYTES)

    fx = load_fixture(fixture_dir, repo_root=repo_root)
    assert fx.manifest["capture"]["source_kind"] == "bench-recombined"


# -- (7) the real graduated fixture --------------------------------------------


def test_real_graduated_fixture_loads_and_verifies_digest():
    """AC2 proof, updated for LIS-319: the actual
    snibelis-maglumi-x3-result-upload fixture now graduates as
    'bench-recombined' (it is a recombination of three real single-assay wire
    envelopes, not verbatim single-envelope bytes). Loaded with the default
    repo_root, it must digest-verify against the real evidence capture bin
    in-repo AND its message records must record-verifiably be contained in
    that raw capture (masking only the declared O.2 recombination field) --
    the live proof that the mechanical containment check accepts the real,
    legitimately-recombined fixture."""
    fx = load_fixture(SNIBELIS_MAGLUMI_X3_RESULT_UPLOAD)

    assert fx.manifest["capture"]["source_kind"] == "bench-recombined"
    assert fx.manifest["capture"]["session_id"] == "20260717-0101010034012301113"
    assert fx.manifest["capture"]["raw_digest"].startswith("sha256:")
    assert fx.manifest["capture"]["unconfirmed_channel_settings"] == ["tcp"]
    assert fx.manifest["capture"]["recombination"]["normalized_fields"] == {"O": [2]}
