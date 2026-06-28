"""Raw-message archive — LIS-16 / S1.4.

The archive is the edge-side evidence record: the raw inbound bytes that produced
a normalized Result, kept verbatim, content-addressed, append-only, and
integrity-checked so any Result can be re-derived and audited from its source
message.
"""

import hashlib
from pathlib import Path

import pytest

from edge_sim.archive import (
    ArchiveEntry,
    ArchiveIntegrityError,
    RawMessageArchive,
    archive_fixture,
)
from edge_sim.fixtures import load_fixture

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RAYTO = FIXTURES_ROOT / "rayto-rac050-oru-r01"

RAW = b"MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260626083000||ORU^R01|MSG1|P|2.3\rOBX|1|NM|HGB||14.2|g/dL\r"
WHEN = "2026-06-28T08:30:00+00:00"


def test_archive_then_load_round_trips_raw_bytes(tmp_path):
    arc = RawMessageArchive(tmp_path)
    entry = arc.archive(RAW, received_at=WHEN, source="bench-01")

    assert isinstance(entry, ArchiveEntry)
    assert entry.raw == RAW
    assert entry.byte_count == len(RAW)
    assert entry.received_at == WHEN
    assert entry.source == "bench-01"

    reloaded = arc.load(entry.digest)
    assert reloaded.raw == RAW
    assert reloaded.received_at == WHEN
    assert reloaded.source == "bench-01"


def test_digest_is_sha256_of_raw_bytes(tmp_path):
    arc = RawMessageArchive(tmp_path)
    entry = arc.archive(RAW, received_at=WHEN, source="x")
    assert entry.digest == hashlib.sha256(RAW).hexdigest()


def test_archive_is_idempotent_and_content_addressed(tmp_path):
    arc = RawMessageArchive(tmp_path)
    first = arc.archive(RAW, received_at=WHEN, source="x")
    again = arc.archive(RAW, received_at="2099-01-01T00:00:00+00:00", source="y")

    # Same content -> same key; no second entry created.
    assert again.digest == first.digest
    assert len(arc) == 1
    # Append-only / immutable: the first archival's provenance wins.
    assert arc.load(first.digest).received_at == WHEN
    assert arc.load(first.digest).source == "x"


def test_distinct_messages_get_distinct_entries(tmp_path):
    arc = RawMessageArchive(tmp_path)
    a = arc.archive(RAW, received_at=WHEN, source="x")
    b = arc.archive(RAW + b"OBX|2|NM|HCT||42.1|%\r", received_at=WHEN, source="x")
    assert a.digest != b.digest
    assert len(arc) == 2
    assert set(arc.digests()) == {a.digest, b.digest}
    assert a.digest in arc


def test_load_verifies_integrity(tmp_path):
    arc = RawMessageArchive(tmp_path)
    entry = arc.archive(RAW, received_at=WHEN, source="x")

    # Tamper with the stored raw bytes behind the archive's back.
    blob = next(tmp_path.rglob("*.msg"))
    blob.write_bytes(RAW + b"TAMPERED")

    with pytest.raises(ArchiveIntegrityError):
        arc.load(entry.digest)


def test_load_unknown_digest_raises(tmp_path):
    arc = RawMessageArchive(tmp_path)
    with pytest.raises(KeyError):
        arc.load("0" * 64)


def test_archive_rejects_non_bytes(tmp_path):
    arc = RawMessageArchive(tmp_path)
    with pytest.raises(TypeError):
        arc.archive("not bytes", received_at=WHEN, source="x")  # type: ignore[arg-type]


def test_archive_is_durable_across_instances(tmp_path):
    RawMessageArchive(tmp_path).archive(RAW, received_at=WHEN, source="x")
    # A fresh handle on the same root sees the previously archived message.
    reopened = RawMessageArchive(tmp_path)
    assert len(reopened) == 1
    digest = hashlib.sha256(RAW).hexdigest()
    assert reopened.load(digest).raw == RAW


def test_archive_fixture_carries_manifest_provenance(tmp_path):
    arc = RawMessageArchive(tmp_path)
    fx = load_fixture(RAYTO)
    entry = archive_fixture(arc, fx, received_at=WHEN)

    assert entry.raw == fx.message_bytes
    assert entry.fixture_id == fx.id
    assert entry.protocol == fx.protocol
    assert entry.transport == fx.transport
    assert entry.framing == fx.framing
    assert entry.encoding == fx.encoding
    assert entry.source == fx.source_reference
