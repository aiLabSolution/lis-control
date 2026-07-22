"""Conformance fixtures: a captured (or synthetic) analyzer message plus a
language-neutral manifest describing it.

A fixture directory holds a ``manifest.json`` (validated against
``fixtures/schema/fixture.schema.json``) and the raw message bytes it points at.
Fixtures are the contract: this Python harness consumes them today; a future
driver (whatever language the S1.0 substrate decision picks) consumes the same
files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ._schema import SchemaError, validate

__all__ = [
    "Fixture",
    "FixtureError",
    "load_fixture",
    "load_fixtures",
    "DEFAULT_FIXTURES_ROOT",
    "SCHEMA_PATH",
]

# fixtures.py lives at src/edge_sim/; the fixtures tree is a sibling of src/.
DEFAULT_FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures"
SCHEMA_PATH = DEFAULT_FIXTURES_ROOT / "schema" / "fixture.schema.json"
# edge/sim/fixtures -> edge/sim -> edge -> repo root.
DEFAULT_REPO_ROOT = DEFAULT_FIXTURES_ROOT.parents[2]

_MANIFEST_NAME = "manifest.json"
_UNCONFIRMED_CHANNEL_KEYS = ("rs232", "tcp")

# Session control bytes an ASTM E1394 wire capture wraps around record bytes:
# ENQ STX ETX EOT ACK NAK. Filtering these out of a raw capture and splitting
# the remainder on CR yields the record multiset -- valid for the X3 simplified
# framing (bare STX, no frame numbers/checksums); a checksummed capture will
# fail containment loudly, which is the correct fail-closed behavior until the
# parser is extended (LIS-319).
_ASTM_SESSION_CONTROL_BYTES = frozenset({0x05, 0x02, 0x03, 0x04, 0x06, 0x15})


class FixtureError(Exception):
    """Raised when a fixture is missing, malformed, or fails manifest validation."""


@dataclass(frozen=True)
class Fixture:
    """A loaded, validated conformance fixture."""

    id: str
    description: str
    vendor: str
    model: str
    protocol: str
    transport: str
    direction: str
    encoding: str
    framing: str
    synthetic: bool
    source_reference: str
    message_path: Path
    message_bytes: bytes
    channel: dict = field(default_factory=dict)
    terminology: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)


def _load_schema(schema_path: Path) -> dict:
    try:
        return json.loads(schema_path.read_text())
    except FileNotFoundError as exc:  # pragma: no cover - shipped asset
        raise FixtureError(f"fixture schema not found at {schema_path}") from exc


def _resolve_repo_relative(raw_path: str, repo_root: Path, manifest_path: Path) -> Path:
    """Resolve ``raw_path`` (a ``capture.raw_path`` value) against ``repo_root``,
    rejecting absolute paths and ``..`` traversal."""
    rel = Path(raw_path)
    if rel.is_absolute():
        raise FixtureError(
            f"{manifest_path}: capture.raw_path must be repo-root-relative, got absolute path {raw_path!r}"
        )
    if ".." in rel.parts:
        raise FixtureError(f"{manifest_path}: capture.raw_path must not contain '..' traversal, got {raw_path!r}")
    return repo_root / rel


def _canonical_message_records(message_bytes: bytes) -> list[bytes]:
    """Canonicalize application-payload bytes into a list of records: CRLF
    normalized to LF, split on LF, empty lines dropped."""
    normalized = message_bytes.replace(b"\r\n", b"\n")
    return [line for line in normalized.split(b"\n") if line]


def _canonical_raw_records(raw_bytes: bytes) -> list[bytes]:
    """Canonicalize a raw ASTM session capture into a list of records: session
    control bytes (:data:`_ASTM_SESSION_CONTROL_BYTES`) filtered out, split on
    CR (0x0D), empty lines dropped."""
    filtered = bytes(b for b in raw_bytes if b not in _ASTM_SESSION_CONTROL_BYTES)
    return [line for line in filtered.split(b"\r") if line]


def _record_type_letter(record: bytes) -> str:
    """The ASTM record-type letter is field 1 (the text before the first
    ``|``)."""
    return record.split(b"|", 1)[0].decode("ascii", errors="replace")


def _mask_record_fields(record: bytes, field_indices: list[int]) -> bytes:
    """Return ``record`` with the given 1-based field indices blanked out.
    Field 1 is the record-type letter; callers must reject that index before
    calling this (see the field-1 guard in :func:`_verify_record_containment`)."""
    parts = record.split(b"|")
    for idx in field_indices:
        if 1 <= idx <= len(parts):
            parts[idx - 1] = b""
    return b"|".join(parts)


def _verify_record_containment(
    manifest: dict,
    manifest_path: Path,
    fixture_dir: Path,
    raw_bytes: bytes,
    source_kind: str,
) -> None:
    """Verify every message record is byte-verbatim present in the raw
    capture's record multiset (LIS-319): the mechanical link that ties a
    graduated fixture's ``message`` bytes to its digest-verified
    ``capture.raw_path``, so a transformed or unrelated fixture cannot inherit
    "bench-capture"/"bench-recombined" provenance just by citing a real
    ``raw_path``.

    Only implemented for ``protocol`` "astm-e1394"; any other protocol fails
    closed (raises) rather than skipping the check -- extend this function
    before graduating a fixture with a different protocol under either of
    these source kinds.

    For ``source_kind`` "bench-capture", containment must be strictly
    verbatim. For "bench-recombined", a record that isn't verbatim may still
    match if masking -- on BOTH sides -- the fields declared in
    ``capture.recombination.normalized_fields`` for its record type makes the
    two equal (field 1, the record-type letter, may never be declared there).
    """
    protocol = manifest.get("protocol")
    if protocol != "astm-e1394":
        raise FixtureError(
            f"{manifest_path}: containment verification is not implemented for protocol "
            f"{protocol!r}; it must be extended before graduating a {source_kind!r} fixture "
            "with this protocol (fail-closed, not skipped)"
        )

    message = manifest["message"]
    message_path = fixture_dir / message["path"]
    if not message_path.is_file():
        raise FixtureError(f"message file {message_path} referenced by {manifest_path} not found")
    message_bytes = message_path.read_bytes()

    message_records = _canonical_message_records(message_bytes)
    raw_records = _canonical_raw_records(raw_bytes)

    normalized_fields: dict = {}
    if source_kind == "bench-recombined":
        recombination = manifest.get("capture", {}).get("recombination") or {}
        normalized_fields = recombination.get("normalized_fields", {})
        for record_type, indices in normalized_fields.items():
            if 1 in indices:
                raise FixtureError(
                    f"{manifest_path}: capture.recombination.normalized_fields[{record_type!r}] "
                    "must not declare field 1 (the record-type letter)"
                )

    available = list(raw_records)
    for record in message_records:
        if record in available:
            available.remove(record)
            continue

        record_type = _record_type_letter(record)
        indices = normalized_fields.get(record_type) if source_kind == "bench-recombined" else None
        matched_index = None
        if indices:
            masked = _mask_record_fields(record, indices)
            for i, candidate in enumerate(available):
                if _record_type_letter(candidate) != record_type:
                    continue
                if _mask_record_fields(candidate, indices) == masked:
                    matched_index = i
                    break
        if matched_index is not None:
            available.pop(matched_index)
            continue

        snippet = record[:40].decode("ascii", errors="replace")
        if indices:
            attempted = f"verbatim and normalized-field matching (fields {indices}) both attempted"
        elif source_kind == "bench-recombined":
            attempted = f"verbatim matching only attempted (no normalized_fields declared for record type {record_type!r})"
        else:
            attempted = "verbatim matching only attempted"
        raise FixtureError(
            f"{manifest_path}: message record {snippet!r} not found in raw capture record "
            f"multiset ({attempted})"
        )


def _verify_raw_artifact(capture: dict, manifest_path: Path, repo_root: Path, source_kind: str) -> bytes:
    """Resolve, existence-check, and digest-verify ``capture.raw_path`` against
    ``capture.raw_digest``; return the raw artifact's bytes. Shared by
    "bench-capture" and "bench-recombined", which both require and
    digest-verify a raw_path."""
    raw_path = capture.get("raw_path")
    if not raw_path:
        raise FixtureError(f"{manifest_path}: capture.raw_path is required for source_kind {source_kind!r}")
    raw_file = _resolve_repo_relative(raw_path, repo_root, manifest_path)
    if not raw_file.is_file():
        raise FixtureError(f"{manifest_path}: capture.raw_path {raw_path!r} not found at {raw_file}")
    raw_bytes = raw_file.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    if digest != capture.get("raw_digest"):
        raise FixtureError(
            f"{manifest_path}: capture.raw_digest mismatch for {raw_path!r}: "
            f"manifest says {capture.get('raw_digest')!r}, computed {digest!r}"
        )
    return raw_bytes


def _check_graduated_provenance(manifest: dict, manifest_path: Path, repo_root: Path) -> None:
    """Enforce the graduated-fixture provenance contract (schema v2, LIS-319) on
    top of plain schema validation, for any manifest with ``synthetic: false``:

    a. ``channel.identity`` must EXIST, and its ``provenance`` must be
       "bench-capture" -- a graduated fixture with no identity block at all
       would otherwise load with zero identity attestation.
    b. The set of {"rs232", "tcp"} channel sub-blocks whose provenance is NOT
       "bench-capture" must exactly equal ``capture.unconfirmed_channel_settings``
       (a missing declaration and a stale extra declaration are both errors).
    c. source_kind "bench-capture": ``derivation`` and ``recombination`` are
       both forbidden (those are the "bench-derived"/"bench-recombined"
       contracts, not this one); ``raw_path`` is required, must resolve inside
       the repo, must exist, and its sha256 must equal ``raw_digest`` -- this
       makes the digest verified on every load, not prose. On top of that, the
       message bytes must be strictly, verbatim record-contained in the raw
       capture (:func:`_verify_record_containment`) -- a graduated fixture
       cannot inherit "bench-capture" provenance for bytes the raw capture
       never produced.
    d. source_kind "bench-derived": ``derivation`` is required, ``raw_path``
       and ``recombination`` are both forbidden; the digest is NOT verified
       here (the pristine original lives only in the offline evidence store)
       -- CI cannot verify it by design, and there is no raw_path to check
       containment against either.
    e. source_kind "bench-recombined": like "bench-capture", ``raw_path`` is
       required and digest-verified, and ``derivation`` is forbidden; unlike
       "bench-capture", ``recombination`` is REQUIRED (declaring which fields
       the recombination legitimately rewrote). Message-record containment is
       still verified against the raw capture, but a record may additionally
       match after masking the declared ``normalized_fields`` on both sides
       (:func:`_verify_record_containment`).
    """
    if manifest.get("synthetic", True):
        return

    channel = manifest.get("channel", {})
    identity = channel.get("identity")
    if identity is None:
        raise FixtureError(
            f"{manifest_path}: channel.identity is required for a non-synthetic "
            "fixture (a graduated fixture must attest analyzer/host identity "
            "provenance)"
        )
    if identity.get("provenance") != "bench-capture":
        raise FixtureError(
            f"{manifest_path}: channel.identity.provenance must be 'bench-capture' for a "
            f"non-synthetic fixture, got {identity.get('provenance')!r}"
        )

    capture = manifest.get("capture", {})
    declared = set(capture.get("unconfirmed_channel_settings", []))
    actual_unconfirmed = {
        key
        for key in _UNCONFIRMED_CHANNEL_KEYS
        if key in channel and channel[key].get("provenance") != "bench-capture"
    }
    if actual_unconfirmed != declared:
        problems = []
        missing = actual_unconfirmed - declared
        stale = declared - actual_unconfirmed
        if missing:
            problems.append(f"undeclared unconfirmed channel setting(s) {sorted(missing)}")
        if stale:
            problems.append(f"stale capture.unconfirmed_channel_settings entry/entries {sorted(stale)}")
        raise FixtureError(f"{manifest_path}: " + "; ".join(problems))

    source_kind = capture.get("source_kind")
    recombination = capture.get("recombination")
    if source_kind == "bench-capture":
        if "derivation" in capture:
            raise FixtureError(
                f"{manifest_path}: capture.derivation is forbidden for source_kind "
                "'bench-capture' (that's the 'bench-derived' contract)"
            )
        if recombination is not None:
            raise FixtureError(
                f"{manifest_path}: capture.recombination is forbidden for source_kind "
                "'bench-capture' (that's the 'bench-recombined' contract)"
            )
        raw_bytes = _verify_raw_artifact(capture, manifest_path, repo_root, source_kind)
        _verify_record_containment(manifest, manifest_path, manifest_path.parent, raw_bytes, source_kind)
    elif source_kind == "bench-recombined":
        if "derivation" in capture:
            raise FixtureError(
                f"{manifest_path}: capture.derivation is forbidden for source_kind "
                "'bench-recombined' (that's the 'bench-derived' contract)"
            )
        if recombination is None:
            raise FixtureError(
                f"{manifest_path}: capture.recombination is required for source_kind 'bench-recombined'"
            )
        raw_bytes = _verify_raw_artifact(capture, manifest_path, repo_root, source_kind)
        _verify_record_containment(manifest, manifest_path, manifest_path.parent, raw_bytes, source_kind)
    elif source_kind == "bench-derived":
        if "derivation" not in capture:
            raise FixtureError(f"{manifest_path}: capture.derivation is required for source_kind 'bench-derived'")
        if capture.get("raw_path"):
            raise FixtureError(f"{manifest_path}: capture.raw_path is forbidden for source_kind 'bench-derived'")
        if recombination is not None:
            raise FixtureError(
                f"{manifest_path}: capture.recombination is forbidden for source_kind "
                "'bench-derived' (that's the 'bench-recombined' contract)"
            )
        # bench-derived artifacts are re-synthesized; the pristine original lives
        # only in the offline validation evidence store, never committed here --
        # so CI cannot verify raw_digest for this source_kind, by design.


def load_fixture(
    directory: Path | str,
    schema_path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> Fixture:
    """Load and validate the fixture in ``directory``.

    ``repo_root`` anchors ``capture.raw_path`` resolution for the graduated-fixture
    provenance checks (see :func:`_check_graduated_provenance`); it defaults to
    :data:`DEFAULT_REPO_ROOT` and is overridable so tests can point it at a
    scratch directory.
    """
    directory = Path(directory)
    manifest_path = directory / _MANIFEST_NAME
    if not manifest_path.is_file():
        raise FixtureError(f"no {_MANIFEST_NAME} in fixture directory {directory}")

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise FixtureError(f"invalid JSON in {manifest_path}: {exc}") from exc

    schema = _load_schema(schema_path or SCHEMA_PATH)
    try:
        validate(manifest, schema)
    except SchemaError as exc:
        raise FixtureError(f"{manifest_path}: {exc}") from exc

    _check_graduated_provenance(manifest, manifest_path, repo_root if repo_root is not None else DEFAULT_REPO_ROOT)

    message = manifest["message"]
    message_path = directory / message["path"]
    if not message_path.is_file():
        raise FixtureError(f"message file {message_path} referenced by {manifest_path} not found")

    return Fixture(
        id=manifest["id"],
        description=manifest.get("description", ""),
        vendor=manifest["analyzer"]["vendor"],
        model=manifest["analyzer"]["model"],
        protocol=manifest["protocol"],
        transport=manifest["transport"],
        direction=manifest["direction"],
        encoding=message["encoding"],
        framing=message["framing"],
        synthetic=manifest["synthetic"],
        source_reference=manifest["source"]["reference"],
        message_path=message_path,
        message_bytes=message_path.read_bytes(),
        channel=manifest.get("channel", {}),
        terminology=manifest.get("terminology", {}),
        expected=manifest.get("expected", {}),
        manifest=manifest,
    )


def load_fixtures(
    root: Path | str = DEFAULT_FIXTURES_ROOT,
    schema_path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> list[Fixture]:
    """Discover and load every fixture under ``root`` (any subdirectory that
    contains a ``manifest.json``), sorted by id."""
    root = Path(root)
    if not root.is_dir():
        raise FixtureError(f"fixtures root not found or not a directory: {root}")
    fixtures = [
        load_fixture(child, schema_path, repo_root=repo_root)
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / _MANIFEST_NAME).is_file()
    ]
    return sorted(fixtures, key=lambda fx: fx.id)
