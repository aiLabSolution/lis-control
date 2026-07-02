"""Conformance fixtures: a captured (or synthetic) analyzer message plus a
language-neutral manifest describing it.

A fixture directory holds a ``manifest.json`` (validated against
``fixtures/schema/fixture.schema.json``) and the raw message bytes it points at.
Fixtures are the contract: this Python harness consumes them today; a future
driver (whatever language the S1.0 substrate decision picks) consumes the same
files.
"""

from __future__ import annotations

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

_MANIFEST_NAME = "manifest.json"


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


def load_fixture(directory: Path | str, schema_path: Path | None = None) -> Fixture:
    """Load and validate the fixture in ``directory``."""
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


def load_fixtures(root: Path | str = DEFAULT_FIXTURES_ROOT, schema_path: Path | None = None) -> list[Fixture]:
    """Discover and load every fixture under ``root`` (any subdirectory that
    contains a ``manifest.json``), sorted by id."""
    root = Path(root)
    if not root.is_dir():
        raise FixtureError(f"fixtures root not found or not a directory: {root}")
    fixtures = [
        load_fixture(child, schema_path)
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / _MANIFEST_NAME).is_file()
    ]
    return sorted(fixtures, key=lambda fx: fx.id)
