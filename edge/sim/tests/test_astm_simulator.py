"""ASTM analyzer-side session harness — LIS-25 / S2.3."""

from pathlib import Path

from edge_sim.astm import ACK, NAK
from edge_sim.astm_simulator import (
    AstmCorruption,
    run_fixture_session,
)
from edge_sim.fixtures import load_fixture

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
DIASYS = FIXTURES_ROOT / "diasys-r920-astm-result"


def test_clean_fixture_session_acks_every_frame_and_parses_tree():
    fx = load_fixture(DIASYS)

    result = run_fixture_session(fx)

    assert result.complete is True
    assert result.aborted is False
    assert result.naks == 0
    assert result.retransmits == 0
    assert result.acked_frames == fx.expected["records"]
    assert [event.response for event in result.frame_events] == [bytes([ACK])] * fx.expected["records"]
    assert result.payload == fx.message_bytes
    assert result.message.results[0].test_code == "GLU"
    assert result.message.results[0].value == "5.2"
    assert result.message.terminator_code == "N"


def test_bad_checksum_corruption_naks_once_then_retransmits_and_parses_tree():
    fx = load_fixture(DIASYS)

    result = run_fixture_session(
        fx,
        corrupt=AstmCorruption.bad_checksum_once(frame_index=2),
    )

    assert result.complete is True
    assert result.aborted is False
    assert result.naks == 1
    assert result.retransmits == 1
    assert result.acked_frames == fx.expected["records"]
    assert [event.response for event in result.frame_events if event.frame_index == 2] == [
        bytes([NAK]),
        bytes([ACK]),
    ]
    assert result.payload == fx.message_bytes
    assert result.message.results[0].test_code == "GLU"


def test_drop_frame_corruption_times_out_then_retransmits():
    fx = load_fixture(DIASYS)

    result = run_fixture_session(
        fx,
        corrupt=AstmCorruption.drop_frame_once(frame_index=1),
    )

    assert result.complete is True
    assert result.aborted is False
    assert result.timeouts == 1
    assert result.retransmits == 1
    assert result.acked_frames == fx.expected["records"]
    assert [event.response for event in result.frame_events if event.frame_index == 1] == [
        b"",
        bytes([ACK]),
    ]


def test_stray_control_corruption_naks_then_retransmits():
    fx = load_fixture(DIASYS)

    result = run_fixture_session(
        fx,
        corrupt=AstmCorruption.stray_control_once(frame_index=3),
    )

    assert result.complete is True
    assert result.aborted is False
    assert result.naks == 1
    assert result.retransmits == 1
    assert [event.response for event in result.frame_events if event.frame_index == 3] == [
        bytes([NAK]),
        bytes([ACK]),
    ]
