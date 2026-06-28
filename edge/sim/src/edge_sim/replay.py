"""Replay engine: push a captured message through a transport and report whether
it survived the round-trip byte-for-byte — and, for an ``ORU^R01``, the normalized
Result it produces.

Two levels (verification pyramid level 2, plan §1):

- :func:`replay` — the byte-faithful round-trip primitive (LIS-9 / S0.7): a
  captured message replayed through a :class:`~edge_sim.transport.Transport`,
  asserting the bytes come back unchanged.
- :func:`replay_normalized` / :func:`replay_from_archive` /
  :func:`deterministic_round_trip` — the **deterministic replay round-trip**
  (LIS-16 / S1.4): drive the received bytes through the parse + LOINC/UCUM
  normalization pipeline to a normalized Result, fingerprinted by a reproducible
  ``result_digest`` and checkable against the fixture's asserted ``expected`` rows.
  Replaying from the :class:`~edge_sim.archive.RawMessageArchive` re-derives a
  Result from the verbatim source bytes, so a stored Result is reproducible and
  auditable from its evidence (the round-trip the ``expected`` block was placed for).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .archive import RawMessageArchive, archive_fixture
from .fixtures import Fixture
from .normalize import NormalizedObservation, Normalizer
from .oru import parse_oru_r01
from .transport import Transport

__all__ = [
    "ReplayResult",
    "replay",
    "NormalizedReplay",
    "replay_normalized",
    "replay_from_archive",
    "deterministic_round_trip",
    "check_against_expected",
]


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


@dataclass(frozen=True)
class NormalizedReplay:
    """Outcome of a deterministic replay: the wire round-trip plus the normalized
    Result the replayed ``ORU^R01`` produced."""

    digest: str  # SHA-256 of the replayed source bytes (== its archive key)
    transport: str
    sent: bytes
    received: bytes
    message_type: str
    patient_id: str
    specimen_id: str
    observations: tuple[NormalizedObservation, ...]
    result_digest: str  # reproducible fingerprint of the normalized rows

    @property
    def round_trip_ok(self) -> bool:
        """True when the bytes survived the transport unchanged."""
        return self.sent == self.received


def replay_normalized(
    message: bytes, transport: Transport, normalizer: Normalizer | None = None
) -> NormalizedReplay:
    """Replay raw ``message`` bytes through ``transport``, then parse + normalize the
    received ``ORU^R01`` into a :class:`NormalizedReplay`.

    The pipeline is pure, so a given message always yields the same ``result_digest``
    — that reproducibility is what makes the round-trip "deterministic".
    """
    sent = bytes(message)
    received = transport.roundtrip(sent)
    report = parse_oru_r01(received)
    rows = tuple((normalizer or Normalizer()).normalize_report(report))
    return NormalizedReplay(
        digest=hashlib.sha256(sent).hexdigest(),
        transport=transport.name,
        sent=sent,
        received=received,
        message_type=report.message_type,
        patient_id=report.patient_id,
        specimen_id=report.specimen_id,
        observations=rows,
        result_digest=_result_digest(rows),
    )


def replay_from_archive(
    archive: RawMessageArchive,
    digest: str,
    transport: Transport,
    normalizer: Normalizer | None = None,
) -> NormalizedReplay:
    """Reload the archived message ``digest`` (integrity-verified) and replay it.

    Re-derives the normalized Result from the verbatim stored source bytes — the
    auditable "reproduce a Result from its evidence" path.
    """
    entry = archive.load(digest)  # raises ArchiveIntegrityError on a tampered blob
    return replay_normalized(entry.raw, transport, normalizer)


def deterministic_round_trip(
    fixture: Fixture,
    transport: Transport,
    *,
    archive: RawMessageArchive,
    received_at: str,
    normalizer: Normalizer | None = None,
) -> NormalizedReplay:
    """The full S1.4 vertical for a fixture: archive its captured message, then
    replay it *from the archive* — capture → archive → reload → wire round-trip →
    parse → normalize → normalized Result."""
    entry = archive_fixture(archive, fixture, received_at=received_at)
    return replay_from_archive(archive, entry.digest, transport, normalizer)


def check_against_expected(replay: NormalizedReplay, expected: dict) -> list[str]:
    """Compare a :class:`NormalizedReplay` to a fixture manifest's ``expected`` block.

    Returns a list of human-readable mismatch descriptions — empty means the
    normalized Result matches the asserted rows exactly. Only keys present in
    ``expected`` are checked (a manifest may assert a subset).
    """
    problems: list[str] = []
    for key, actual in (
        ("message_type", replay.message_type),
        ("patient_id", replay.patient_id),
        ("specimen_id", replay.specimen_id),
    ):
        if key in expected and expected[key] != actual:
            problems.append(f"{key}: expected {expected[key]!r}, got {actual!r}")

    exp_obs = expected.get("observations")
    if exp_obs is not None:
        if len(exp_obs) != len(replay.observations):
            problems.append(
                f"observations: expected {len(exp_obs)}, got {len(replay.observations)}"
            )
        for i, (want, got) in enumerate(zip(exp_obs, replay.observations)):
            for field in ("set_id", "value", "raw_code", "raw_unit", "loinc", "ucum_value", "status"):
                if field in want and want[field] != getattr(got, field):
                    problems.append(
                        f"obs[{i}].{field}: expected {want[field]!r}, "
                        f"got {getattr(got, field)!r}"
                    )
    return problems


def _result_digest(observations: tuple[NormalizedObservation, ...]) -> str:
    """A reproducible SHA-256 over the normalized rows (canonical JSON), so an
    identical Result always fingerprints identically and binds raw → Result."""
    canon = [
        {
            "set_id": o.set_id,
            "value": o.value,
            "raw_code": o.raw_code,
            "raw_unit": o.raw_unit,
            "loinc": o.loinc,
            "ucum_value": o.ucum_value,
            "status": o.status,
        }
        for o in observations
    ]
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
