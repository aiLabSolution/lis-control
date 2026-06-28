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
from .astm import (
    ACK,
    ENQ,
    EOT,
    NAK,
    AstmError,
    AstmFrame,
    AstmReceiver,
    SessionResult,
    build_frame,
    checksum,
    parse_frame,
    run_session,
)
from .hl7 import Encoding, Hl7Error, Message, Segment, parse_message, unescape
from .mllp import CR, EB, SB, MllpDecoder, MllpError, deframe, frame
from .normalize import (
    STATUS_NORMALIZED,
    STATUS_PARTIAL,
    STATUS_UNMAPPED,
    NormalizedObservation,
    Normalizer,
    TerminologyMap,
)
from .oru import OruParseError, OruReport, RawObservation, parse_oru_r01
from .replay import ReplayResult, replay
from .transport import AstmTransport, LoopbackTransport, MllpTransport, Transport, TransportError

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
    "AstmTransport",
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
    # HL7 v2 parser + ORU^R01 + LOINC/UCUM normalization (LIS-14 / S1.2)
    "Encoding",
    "Segment",
    "Message",
    "Hl7Error",
    "parse_message",
    "unescape",
    "OruReport",
    "RawObservation",
    "OruParseError",
    "parse_oru_r01",
    "NormalizedObservation",
    "TerminologyMap",
    "Normalizer",
    "STATUS_NORMALIZED",
    "STATUS_PARTIAL",
    "STATUS_UNMAPPED",
    # ASTM E1381 codec + session (LIS-23 / S2.1)
    "ENQ",
    "ACK",
    "NAK",
    "EOT",
    "AstmError",
    "AstmFrame",
    "checksum",
    "build_frame",
    "parse_frame",
    "AstmReceiver",
    "SessionResult",
    "run_session",
]
