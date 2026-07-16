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
from .e1394 import AstmMessage, parse_e1394
from .normalize import KIND_RESULT, KIND_WARNING, NormalizedObservation, Normalizer
from .oru import (
    OruParseError,
    OruReport,
    RawObservation,
    SpecimenGroup,
    mint_accession,
    normalized_patient_name,
    parse_oru_r01,
)
from .oru import RESULT_TYPE_CALIBRATION, RESULT_TYPE_PATIENT, RESULT_TYPE_QC
from .transport import Transport

# ASTM carries no wire QC/calibration typing field the way HL7 does in MSH-16
# (KB §5): a control or calibrator upload looks byte-identical to a patient
# result on the H/P/O/R stream. The documented convention is a Sample-ID (O-3)
# prefix — an order whose specimen id begins with the calibration prefix is a
# calibration upload and is routed out of the patient result stream (LIS-125).
# The production bridge makes this prefix a per-analyzer profile rule
# (CALIBRATION_SPECIMEN_ID_PREFIX); the sim bakes the documented default so the
# conformance fixture is deterministic — the same default-vs-profile split as
# the RAYTO terminology seed in normalize.py. The trailing hyphen keeps the
# prefix from swallowing a legitimate patient analyte whose id merely starts
# with the letters CAL (e.g. a specimen labelled for a Calcium panel).
_CALIBRATION_SPECIMEN_PREFIX = "CAL-"
_QC_SPECIMEN_PREFIX = "QC-"

__all__ = [
    "ReplayResult",
    "replay",
    "NormalizedReplay",
    "parse_analyzer_report",
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

    The pipeline is pure, so a given (message, terminology map) pair always yields
    the same ``result_digest`` — that reproducibility is what makes the round-trip
    "deterministic". The ``normalizer`` (the channel's terminology data) is therefore
    part of a Result's reproduction inputs, alongside the source bytes.
    """
    sent = bytes(message)
    received = transport.roundtrip(sent)
    report = parse_analyzer_report(received)
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
    auditable "reproduce a Result from its evidence" path. The archive stores raw
    bytes only: to reproduce a Result that was normalized with per-channel
    terminology data (``Normalizer.from_fixture``), the caller must supply that
    same ``normalizer`` — the channel profile is part of the evidence.
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
    parse → normalize → normalized Result.

    When no ``normalizer`` is given, the fixture's own terminology block supplies
    it (:meth:`Normalizer.from_fixture`) — the fixture is in hand here, so its
    channel/profile data travels with its message. A later
    :func:`replay_from_archive` must be given the same terminology to reproduce
    the same Result (see its docstring)."""
    entry = archive_fixture(archive, fixture, received_at=received_at)
    return replay_from_archive(
        archive,
        entry.digest,
        transport,
        normalizer or Normalizer.from_fixture(fixture),
    )


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

    # A manifest asserts its rows under either the flat ``observations`` key (a
    # result-only message — the RAYTO/EDAN shape) or, when the analyzer interleaves
    # in-band warnings, the routed ``results`` key (only the analyte result rows,
    # KIND_RESULT). Either is validated against the corresponding subset so a
    # warning-bearing fixture (e.g. the Seamaty SD1) still gets full row-level
    # conformance checking, not a silent pass (LIS-86 / S2.10).
    problems += _check_rows("observations", expected.get("observations"), replay.observations)
    results = tuple(o for o in replay.observations if o.kind == KIND_RESULT)
    problems += _check_rows("results", expected.get("results"), results)

    exp_warn = expected.get("warnings")
    if exp_warn is not None:
        warnings = tuple(o for o in replay.observations if o.kind == KIND_WARNING)
        if len(exp_warn) != len(warnings):
            problems.append(f"warnings: expected {len(exp_warn)}, got {len(warnings)}")
        for i, (want, got) in enumerate(zip(exp_warn, warnings)):
            for field in ("set_id", "value", "raw_code"):
                if field in want and want[field] != getattr(got, field):
                    problems.append(
                        f"warning[{i}].{field}: expected {want[field]!r}, got {getattr(got, field)!r}"
                    )
    return problems


def _check_rows(key: str, expected_rows, got_rows) -> list[str]:
    """Compare an asserted list of normalized rows to the produced rows (by the
    fields the contract pins). Returns the mismatch descriptions; empty if the
    ``expected`` key is absent (a manifest may assert a subset)."""
    if expected_rows is None:
        return []
    problems: list[str] = []
    if len(expected_rows) != len(got_rows):
        problems.append(f"{key}: expected {len(expected_rows)}, got {len(got_rows)}")
    for i, (want, got) in enumerate(zip(expected_rows, got_rows)):
        for field in ("set_id", "value", "raw_code", "raw_unit", "loinc", "ucum_value", "status"):
            if field in want and want[field] != getattr(got, field):
                problems.append(
                    f"{key}[{i}].{field}: expected {want[field]!r}, got {getattr(got, field)!r}"
                )
    return problems


def parse_analyzer_report(message: bytes) -> OruReport:
    """Parse a replayed analyzer payload into the transport-neutral report shape.

    Stage 1 only accepted HL7 ORU^R01. LIS-26 adds ASTM E1394 chemistry panels:
    once the E1381 transport has de-framed the payload, its R records map onto the
    same raw-observation fields the normalizer already understands.
    """
    try:
        return parse_oru_r01(message)
    except OruParseError:
        return _astm_report(parse_e1394(message))


def _astm_report(msg: AstmMessage) -> OruReport:
    groups: list[SpecimenGroup] = []
    group_index = 0
    for patient in msg.patients:
        for order in patient.orders:
            current_index = group_index
            group_index += 1
            observations = []
            for result in order.results:
                observations.append(
                    RawObservation(
                        set_id=result.seq,
                        value_type="NM",
                        raw_code=result.test_code,
                        raw_text=result.test_code,
                        raw_system="ASTM",
                        sub_id="",
                        value=result.value,
                        raw_unit=result.units,
                        reference_range=result.reference_range,
                        abnormal_flags=result.abnormal_flags,
                        status=result.status,
                        completion_time=result.completion_time,
                    )
                )
            if observations:
                specimen_id = order.specimen_id
                if not specimen_id.strip():
                    patient_id_for_mint = (patient.patient_id or "").strip()
                    specimen_id = mint_accession(
                        "ASTM",
                        patient_id_for_mint,
                        msg.header.raw if msg.header else "",
                        patient_id_for_mint,
                        normalized_patient_name(patient.name),
                        "\r".join([order.raw, *(result.raw for result in order.results)]),
                        str(current_index),
                    )
                groups.append(
                    SpecimenGroup(
                        patient_id=patient.patient_id,
                        patient_name=patient.name,
                        specimen_id=specimen_id,
                        order_code=order.test_code,
                        observations=tuple(observations),
                        result_type=_astm_order_result_type(order),
                    )
                )
    header = msg.header
    first = groups[0] if groups else SpecimenGroup(
        patient_id="",
        patient_name="",
        specimen_id="",
        order_code="",
        observations=(),
    )
    return OruReport(
        message_type="ASTM^E1394",
        sending_app=header.sender_name if header else "",
        sending_facility=header.sender_model if header else "",
        message_control_id="",
        patient_id=first.patient_id,
        patient_name=first.patient_name,
        specimen_id=first.specimen_id,
        order_code=first.order_code,
        observations=tuple(obs for group in groups for obs in group.observations),
        result_type=first.result_type,
        groups=tuple(groups),
    )


def _astm_result_type(msg: AstmMessage) -> str:
    """Classify an ASTM message as patient, QC, or calibration.

    ASTM has no MSH-16-style wire field, so calibration and QC are recognized
    from host-side context: the documented calibration Sample-ID convention, the
    X3 QC Sample-ID convention used by the synthetic fixture, or O.12=Q when the
    analyzer emits the ASTM action code.

    Kept as a compatibility helper for single-purpose messages; grouped report
    conversion calls :func:`_astm_order_result_type` for each O record so a mixed
    batch cannot contaminate sibling orders. Prefixes include a trailing hyphen
    so a patient id that merely begins with CAL/QC is not misclassified."""
    for patient in msg.patients:
        for order in patient.orders:
            result_type = _astm_order_result_type(order)
            if result_type != RESULT_TYPE_PATIENT:
                return result_type
    return RESULT_TYPE_PATIENT


def _astm_order_result_type(order) -> str:
    """Classify one ASTM O record without leaking its type to sibling orders."""
    specimen_id = (order.specimen_id or "").strip().upper()
    if specimen_id.startswith(_CALIBRATION_SPECIMEN_PREFIX):
        return RESULT_TYPE_CALIBRATION
    action_code = (order.action_code or "").strip().upper()
    if action_code == "Q" or specimen_id.startswith(_QC_SPECIMEN_PREFIX):
        return RESULT_TYPE_QC
    return RESULT_TYPE_PATIENT


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
