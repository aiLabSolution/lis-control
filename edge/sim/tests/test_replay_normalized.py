"""Deterministic replay round-trip — LIS-16 / S1.4.

Extends the byte-level replay self-test (``test_replay.py``) to the full pipeline:
a captured message is archived, reloaded from the archive, replayed through a
transport, and parsed + normalized to a normalized Result. The round-trip is
asserted on three axes — the bytes survive the wire, the normalized Result is
reproducible (same ``result_digest`` every run), and it matches the fixture's
asserted ``expected`` rows.
"""

from pathlib import Path

import pytest

from edge_sim.archive import ArchiveIntegrityError, RawMessageArchive, archive_fixture
from edge_sim.fixtures import load_fixture
from edge_sim.replay import (
    NormalizedReplay,
    check_against_expected,
    deterministic_round_trip,
    replay_from_archive,
    replay_normalized,
)
from edge_sim.transport import LoopbackTransport, MllpTransport

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RAYTO = FIXTURES_ROOT / "rayto-rac050-oru-r01"
WHEN = "2026-06-28T08:30:00+00:00"


def test_replay_normalized_produces_expected_rows():
    fx = load_fixture(RAYTO)
    res = replay_normalized(fx.message_bytes, LoopbackTransport())

    assert isinstance(res, NormalizedReplay)
    assert res.round_trip_ok is True
    assert res.message_type == "ORU^R01"
    assert res.patient_id == "PID-0142"
    assert res.specimen_id == "SPEC-0142"
    assert [o.loinc for o in res.observations] == ["718-7", "4544-3", "6690-2", "777-3"]
    assert [o.status for o in res.observations] == ["NORMALIZED"] * 4


def test_replay_normalized_is_deterministic():
    fx = load_fixture(RAYTO)
    a = replay_normalized(fx.message_bytes, LoopbackTransport())
    b = replay_normalized(fx.message_bytes, LoopbackTransport())
    # Same source bytes -> identical normalized Result, every time.
    assert a.result_digest == b.result_digest
    assert a.observations == b.observations


def test_result_digest_is_content_bound():
    fx = load_fixture(RAYTO)
    base = replay_normalized(fx.message_bytes, LoopbackTransport())
    mutated = replay_normalized(
        fx.message_bytes.replace(b"|14.2|", b"|9.9|"), LoopbackTransport()
    )
    assert mutated.result_digest != base.result_digest


def test_replay_from_archive_round_trips(tmp_path):
    arc = RawMessageArchive(tmp_path)
    fx = load_fixture(RAYTO)
    entry = archive_fixture(arc, fx, received_at=WHEN)

    res = replay_from_archive(arc, entry.digest, LoopbackTransport())
    assert res.digest == entry.digest
    assert res.round_trip_ok is True
    assert check_against_expected(res, fx.expected) == []


def test_deterministic_round_trip_over_mllp_framing(tmp_path):
    arc = RawMessageArchive(tmp_path)
    fx = load_fixture(RAYTO)
    res = deterministic_round_trip(fx, MllpTransport(), archive=arc, received_at=WHEN)
    # Survives real MLLP frame/de-frame AND normalizes to the asserted rows.
    assert res.round_trip_ok is True
    assert res.transport == "mllp"
    assert check_against_expected(res, fx.expected) == []


def test_check_against_expected_reports_mismatch():
    fx = load_fixture(RAYTO)
    res = replay_normalized(fx.message_bytes, LoopbackTransport())
    bad = {"patient_id": "WRONG", "observations": fx.expected["observations"]}
    problems = check_against_expected(res, bad)
    assert any("patient_id" in p for p in problems)


def test_replay_from_archive_propagates_integrity_failure(tmp_path):
    arc = RawMessageArchive(tmp_path)
    fx = load_fixture(RAYTO)
    entry = archive_fixture(arc, fx, received_at=WHEN)
    next(tmp_path.rglob("*.msg")).write_bytes(b"corrupted")
    with pytest.raises(ArchiveIntegrityError):
        replay_from_archive(arc, entry.digest, LoopbackTransport())
