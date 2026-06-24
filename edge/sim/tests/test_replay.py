"""Replay engine + the harness replay self-test.

The replay self-test is the Stage 0 deliverable's proof-of-life: every shipped
fixture round-trips losslessly through the identity (loopback) transport. Framed
transports added in later slices must preserve the same application-payload
round-trip.
"""

from pathlib import Path

from edge_sim.fixtures import load_fixture, load_fixtures
from edge_sim.replay import ReplayResult, replay
from edge_sim.transport import LoopbackTransport, Transport

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
EXAMPLE = FIXTURES_ROOT / "_example"


def test_replay_roundtrips_example():
    fx = load_fixture(EXAMPLE)
    res = replay(fx, LoopbackTransport())
    assert isinstance(res, ReplayResult)
    assert res.round_trip_ok is True
    assert res.sent == fx.message_bytes
    assert res.received == fx.message_bytes
    assert res.fixture_id == fx.id
    assert res.transport == "loopback"


class _CorruptingTransport(Transport):
    """A transport that mutates the payload — proves the self-test can fail."""

    name = "corrupting"

    def send(self, payload: bytes) -> None:
        self._buf = payload + b"X"

    def receive(self) -> bytes:
        return self._buf


def test_replay_detects_corruption():
    fx = load_fixture(EXAMPLE)
    res = replay(fx, _CorruptingTransport())
    assert res.round_trip_ok is False


def test_replay_self_test_all_fixtures():
    fixtures = load_fixtures(FIXTURES_ROOT)
    assert fixtures, "no fixtures discovered under the fixtures root"
    for fx in fixtures:
        assert replay(fx, LoopbackTransport()).round_trip_ok, fx.id
