"""LIS edge analyzer **simulator harness** + conformance-fixture skeleton.

Stage 0 deliverable (LIS-9 / S0.7): the component-test substrate that replays
captured analyzer messages against the pipeline. See ``edge/sim/README.md`` and
``docs/adr/0004-analyzer-simulator-harness-and-conformance-fixtures.md``.
"""

from ._schema import SchemaError, validate
from .ack import AckCode, AckMode, Hl7AckError, Msh, build_ack, parse_msh, wants_accept_ack
from .fixtures import (
    DEFAULT_FIXTURES_ROOT,
    SCHEMA_PATH,
    Fixture,
    FixtureError,
    load_fixture,
    load_fixtures,
)
from .mllp import CR, EB, SB, MllpDecoder, MllpError, deframe, frame
from .replay import ReplayResult, replay
from .transport import LoopbackTransport, MllpTransport, Transport, TransportError

__all__ = [
    "Fixture",
    "FixtureError",
    "load_fixture",
    "load_fixtures",
    "DEFAULT_FIXTURES_ROOT",
    "SCHEMA_PATH",
    "Transport",
    "LoopbackTransport",
    "MllpTransport",
    "TransportError",
    "ReplayResult",
    "replay",
    "SchemaError",
    "validate",
    # MLLP wire codec (LIS-13 / S1.1)
    "SB",
    "EB",
    "CR",
    "frame",
    "deframe",
    "MllpDecoder",
    "MllpError",
    # HL7 v2 ACK^R01 (LIS-13 / S1.1)
    "AckCode",
    "AckMode",
    "Hl7AckError",
    "Msh",
    "parse_msh",
    "build_ack",
    "wants_accept_ack",
]
