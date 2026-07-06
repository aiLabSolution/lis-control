"""LIS-17 (S1.5): the milestone Result is traceable to the archived raw message.

The Stage-1 milestone (``run_milestone``) normalizes an ``ORU^R01`` to a Result + ACK.
LIS-17's AC also asks that the result be **traceable to the archived raw message**. This
proves that provenance half **edge-side and automated**: the same captured bytes are
content-addressed into the raw-message archive (LIS-16), and the Result the milestone
produces is **byte-for-byte reproducible** from those *archived* bytes — re-derived over
the real MLLP wire — so the Result is auditable back to its stored evidence by digest.

The cross-process **persistence** leg (handing the ingest DTO to a live/Testcontainers
core and reading back ``clinlims.result``) stays deferred pending the S1.0 transport
substrate decision (core ADR-0003 / ADR-0013); core-side persistence itself is proven
separately by LIS-15's ``ResultIngestContractIntegrationTest``.
"""

import hashlib
from pathlib import Path

from edge_sim.archive import RawMessageArchive, archive_fixture
from edge_sim.fixtures import load_fixture
from edge_sim.milestone import run_milestone
from edge_sim.replay import _result_digest, replay_from_archive
from edge_sim.transport import MllpTransport

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
# Standard-HL7 final-result vehicle (the EDAN H60S fixture is EDANLAB/held-back post-bench).
RAYTO = FIXTURES_ROOT / "rayto-rac050-oru-r01"
WHEN = "2026-06-26T08:30:00+00:00"
ACK_TS = "20260626083001"


def test_milestone_result_is_traceable_to_the_archived_raw_message(tmp_path):
    fx = load_fixture(RAYTO)
    archive = RawMessageArchive(tmp_path)

    # Archive the raw analyzer message (content-addressed); the digest IS the provenance
    # key — the SHA-256 of the verbatim source bytes.
    entry = archive_fixture(archive, fx, received_at=WHEN)
    assert entry.digest == hashlib.sha256(fx.message_bytes).hexdigest()

    # The milestone normalizes the same message to a Result + ACK (accepted, AA).
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    assert out.accepted is True
    assert out.all_final is True

    # Re-derive the Result from the ARCHIVED bytes (over the real MLLP wire) — the
    # auditable "reproduce the Result from its stored evidence" path.
    replay = replay_from_archive(archive, entry.digest, MllpTransport())
    assert replay.round_trip_ok is True

    # Traceability: the milestone Result and the archive-replayed Result are identical,
    # so the milestone Result is reproducible from (traceable to) the archived raw
    # message — bound by the reproducible result fingerprint.
    assert _result_digest(out.observations) == replay.result_digest
    assert [(o.raw_code, o.loinc, o.ucum_value, o.value) for o in out.observations] == [
        (o.raw_code, o.loinc, o.ucum_value, o.value) for o in replay.observations
    ]


def test_archive_reload_is_integrity_checked_and_byte_faithful(tmp_path):
    """The archived raw message reloads byte-for-byte (the evidence is verbatim)."""
    fx = load_fixture(RAYTO)
    archive = RawMessageArchive(tmp_path)
    entry = archive_fixture(archive, fx, received_at=WHEN)
    assert archive.load(entry.digest).raw == fx.message_bytes
