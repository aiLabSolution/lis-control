"""Replay engine: push a fixture's captured message through a transport and
report whether it survived the round-trip byte-for-byte.

This is the harness's core component-test primitive (verification pyramid level 2,
plan §1): replaying a captured analyzer message and asserting a faithful
round-trip. Later slices extend it — once a parser/normalization service exists,
``Fixture.expected`` carries the asserted normalized Result for end-to-end checks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fixtures import Fixture
from .transport import Transport

__all__ = ["ReplayResult", "replay"]


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of replaying one fixture through one transport."""

    fixture_id: str
    transport: str
    sent: bytes
    received: bytes

    @property
    def round_trip_ok(self) -> bool:
        """True when the bytes received back match the bytes sent."""
        return self.sent == self.received


def replay(fixture: Fixture, transport: Transport) -> ReplayResult:
    """Replay ``fixture`` through ``transport`` and return the result."""
    sent = fixture.message_bytes
    received = transport.roundtrip(sent)
    return ReplayResult(
        fixture_id=fixture.id,
        transport=transport.name,
        sent=sent,
        received=received,
    )
