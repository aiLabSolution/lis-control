"""Raw-message archive — LIS-16 / S1.4.

A durable, append-only, content-addressed store of raw inbound analyzer messages
kept *exactly as received* off the wire (the application payload, pre-parse). It is
the edge-side evidence record behind the core append-only Result store (S0.5 /
LIS-7): the raw wire bytes that produced a normalized Result are retained verbatim,
so any Result can be re-derived deterministically from its source message (S1.4's
deterministic replay round-trip, :mod:`edge_sim.replay`) and audited byte-for-byte
(ISO 15189 evidence chain, plan §1).

Design:

- **Content-addressed.** The archive key is the SHA-256 of the raw bytes, so an
  identical message always archives to the same entry: re-archiving is idempotent
  and a digest both names *and* verifies its message.
- **Append-only + immutable.** An entry is written once and never mutated; the
  first archival's provenance metadata wins. Mirrors the core store's append-only
  spine (no last-writer-wins).
- **Integrity-checked.** :meth:`RawMessageArchive.load` re-hashes the stored bytes
  and rejects any mismatch, so a corrupted or tampered archive is evident rather
  than silently trusted.
- **Filesystem-backed, dependency-free.** Raw bytes live in ``<digest>.msg`` beside
  a ``<digest>.json`` metadata sidecar, sharded by digest prefix. A production
  archive swaps the directory for object storage; the contract is identical.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .fixtures import Fixture

__all__ = [
    "ArchiveEntry",
    "ArchiveError",
    "ArchiveIntegrityError",
    "RawMessageArchive",
    "archive_fixture",
]

# Metadata sidecar schema version, so a future field change is detectable.
_META_VERSION = 1


class ArchiveError(Exception):
    """Base class for archive faults."""


class ArchiveIntegrityError(ArchiveError):
    """Raised when stored bytes no longer hash to their digest (corruption/tamper)."""


@dataclass(frozen=True)
class ArchiveEntry:
    """One archived raw message: the bytes plus their provenance metadata.

    ``digest`` is the SHA-256 of ``raw`` and the entry's identity in the archive.
    """

    digest: str
    raw: bytes
    received_at: str  # ISO-8601 instant the message was received (caller-stamped)
    source: str  # provenance: bench-capture id, listener id, or synthetic note
    byte_count: int
    protocol: str = ""
    transport: str = ""
    framing: str = ""
    encoding: str = ""
    fixture_id: str = ""

    def _meta(self) -> dict:
        """The sidecar payload — everything but the raw bytes (held in ``.msg``)."""
        return {
            "v": _META_VERSION,
            "digest": self.digest,
            "byte_count": self.byte_count,
            "received_at": self.received_at,
            "source": self.source,
            "protocol": self.protocol,
            "transport": self.transport,
            "framing": self.framing,
            "encoding": self.encoding,
            "fixture_id": self.fixture_id,
        }


class RawMessageArchive:
    """An append-only, content-addressed archive of raw messages under ``root``.

    The directory is created lazily on first write, so pointing at a not-yet-existing
    path is fine; pointing at an existing archive re-opens it (entries are durable).
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    # --- paths -------------------------------------------------------------
    def _shard(self, digest: str) -> Path:
        return self._root / digest[:2]

    def _msg_path(self, digest: str) -> Path:
        return self._shard(digest) / f"{digest}.msg"

    def _meta_path(self, digest: str) -> Path:
        return self._shard(digest) / f"{digest}.json"

    # --- write -------------------------------------------------------------
    def archive(
        self,
        raw: bytes,
        *,
        received_at: str,
        source: str,
        protocol: str = "",
        transport: str = "",
        framing: str = "",
        encoding: str = "",
        fixture_id: str = "",
    ) -> ArchiveEntry:
        """Archive ``raw`` and return its :class:`ArchiveEntry`.

        Idempotent: archiving the same bytes again returns the existing entry
        (with its original, immutable provenance) and writes nothing new.
        """
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError(f"raw message must be bytes, got {type(raw).__name__}")
        raw = bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()

        if self._msg_path(digest).is_file():
            # Append-only: the first archival's metadata is authoritative.
            return self.load(digest)

        entry = ArchiveEntry(
            digest=digest,
            raw=raw,
            received_at=received_at,
            source=source,
            byte_count=len(raw),
            protocol=protocol,
            transport=transport,
            framing=framing,
            encoding=encoding,
            fixture_id=fixture_id,
        )
        self._shard(digest).mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(self._msg_path(digest), raw)
        _atomic_write_bytes(
            self._meta_path(digest),
            json.dumps(entry._meta(), indent=2, sort_keys=True).encode("utf-8"),
        )
        return entry

    # --- read --------------------------------------------------------------
    def load(self, digest: str) -> ArchiveEntry:
        """Load the entry for ``digest``, verifying the stored bytes still hash to it.

        Raises :class:`KeyError` if absent, :class:`ArchiveIntegrityError` if the
        stored bytes have been corrupted or tampered with.
        """
        msg_path = self._msg_path(digest)
        if not msg_path.is_file():
            raise KeyError(f"no archived message for digest {digest}")
        raw = msg_path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != digest:
            raise ArchiveIntegrityError(
                f"archive corruption: bytes under {digest} hash to {actual}"
            )
        meta = json.loads(self._meta_path(digest).read_text())
        return ArchiveEntry(
            digest=digest,
            raw=raw,
            received_at=meta.get("received_at", ""),
            source=meta.get("source", ""),
            byte_count=meta.get("byte_count", len(raw)),
            protocol=meta.get("protocol", ""),
            transport=meta.get("transport", ""),
            framing=meta.get("framing", ""),
            encoding=meta.get("encoding", ""),
            fixture_id=meta.get("fixture_id", ""),
        )

    def digests(self) -> list[str]:
        """Every archived digest, sorted (stable iteration for deterministic replay)."""
        if not self._root.is_dir():
            return []
        return sorted(p.stem for p in self._root.rglob("*.msg"))

    def __contains__(self, digest: str) -> bool:
        return self._msg_path(digest).is_file()

    def __iter__(self):
        for digest in self.digests():
            yield self.load(digest)

    def __len__(self) -> int:
        return len(self.digests())


def archive_fixture(
    archive: RawMessageArchive,
    fixture: Fixture,
    *,
    received_at: str,
    source: str | None = None,
) -> ArchiveEntry:
    """Archive ``fixture``'s captured message, carrying its manifest provenance.

    The fixture's ``source.reference`` is used as the archive ``source`` unless an
    explicit one is given (e.g. a live capture session id).
    """
    return archive.archive(
        fixture.message_bytes,
        received_at=received_at,
        source=fixture.source_reference if source is None else source,
        protocol=fixture.protocol,
        transport=fixture.transport,
        framing=fixture.framing,
        encoding=fixture.encoding,
        fixture_id=fixture.id,
    )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp file + rename) so a crashed
    write never leaves a half-written, wrong-hash blob in the archive."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
