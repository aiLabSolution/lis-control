"""LIS edge analyzer **simulator harness** + conformance-fixture skeleton.

Stage 0 deliverable (LIS-9 / S0.7): the component-test substrate that replays
captured analyzer messages against the pipeline. See ``edge/sim/README.md`` and
``docs/adr/0004-analyzer-simulator-harness-and-conformance-fixtures.md``.
"""

from ._schema import SchemaError, validate
from .fixtures import (
    DEFAULT_FIXTURES_ROOT,
    SCHEMA_PATH,
    Fixture,
    FixtureError,
    load_fixture,
    load_fixtures,
)
from .replay import ReplayResult, replay
from .transport import LoopbackTransport, Transport, TransportError

__all__ = [
    "Fixture",
    "FixtureError",
    "load_fixture",
    "load_fixtures",
    "DEFAULT_FIXTURES_ROOT",
    "SCHEMA_PATH",
    "Transport",
    "LoopbackTransport",
    "TransportError",
    "ReplayResult",
    "replay",
    "SchemaError",
    "validate",
]
