"""Stage-1 milestone E2E — first result through the pipe (LIS-17 / S1.5).

The milestone exit gate (``LIS_IMPLEMENTATION_PLAN.md`` §1): a clean standard-HL7
``ORU^R01`` replayed over MLLP produces a normalized **Result** (raw code/unit
preserved; LOINC + UCUM populated; final) *and* the listener returns a correct
``ACK^R01`` with MSA-1 = ``AA`` — asserted by this one automated E2E test, plus the
core ingest contract DTO the edge would hand to ``ResultIngestService.ingest``.

Vehicle: the RAYTO RAC-050 CBC seed (a standard-HL7 analyzer whose OBX-11 carries
Table-0085 finality ``F``). The EDAN H60S fixture was the original vehicle, but the
2026-07-06 bench proved the H60S speaks the EDAN H90-family profile (code in OBX-4,
no OBX-11 finality → results held back); its held-back behaviour is covered by
``test_edan_h99s.py`` and ``test_edan_h60s.py``.
"""

from pathlib import Path

from edge_sim.fixtures import load_fixture
from edge_sim.ingest import validate_dto
from edge_sim.mllp import deframe
from edge_sim.milestone import RESULT_STATUS_FINAL, result_status, run_milestone
from edge_sim.normalize import STATUS_NORMALIZED

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RAYTO = FIXTURES_ROOT / "rayto-rac050-oru-r01"
ACK_TS = "20260626083001"


def test_milestone_normalized_result_and_ack():
    """The 🎯 milestone: standard-HL7 ORU^R01 over MLLP -> normalized Result + ACK (AA)."""
    fx = load_fixture(RAYTO)
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)

    # --- the message survived MLLP framing and was accepted ------------------
    assert out.round_trip_ok is True
    assert out.accepted is True
    assert out.ack_code == "AA"  # MSA-1 = AA (application accept)
    assert out.ack_message_code == "ACK"
    assert out.ack_trigger_event == "R01"  # ACK^R01

    # --- the normalized Result --------------------------------------------------
    assert out.report.message_type == "ORU^R01"
    assert out.report.patient_id == "PID-0142"
    assert out.report.specimen_id == "SPEC-0142"
    assert out.report.sending_app == "RAC-050"

    assert len(out.observations) == 4
    # raw analyzer code/unit preserved beside the resolved LOINC/UCUM, every row.
    assert [o.raw_code for o in out.observations] == ["HGB", "HCT", "WBC", "PLT"]
    assert [o.raw_unit for o in out.observations] == ["g/dL", "%", "K/uL", "K/uL"]
    assert [o.loinc for o in out.observations] == ["718-7", "4544-3", "6690-2", "777-3"]
    assert [o.ucum_value for o in out.observations] == ["g/dL", "%", "10*3/uL", "10*3/uL"]
    # LOINC + UCUM populated on every row (fully normalized).
    assert all(o.loinc and o.ucum_value for o in out.observations)
    assert all(o.status == STATUS_NORMALIZED for o in out.observations)

    # --- finality: every observation is a *final* result (OBX-11 = F) --------
    assert out.all_final is True
    assert out.result_statuses == (RESULT_STATUS_FINAL,) * 4


def test_milestone_matches_fixture_expected_rows():
    """The normalized rows match the fixture manifest's asserted ``expected`` block."""
    fx = load_fixture(RAYTO)
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    exp = fx.expected["observations"]
    assert len(out.observations) == len(exp)
    for want, got in zip(exp, out.observations):
        assert got.set_id == want["set_id"]
        assert got.value == want["value"]
        assert got.raw_code == want["raw_code"]
        assert got.raw_unit == want["raw_unit"]
        assert got.loinc == want["loinc"]
        assert got.ucum_value == want["ucum_value"]
        assert got.status == want["status"]


def test_milestone_ack_is_framed_back_on_the_wire():
    """The listener's ACK is MLLP-framed; de-framing it yields the ACK payload."""
    fx = load_fixture(RAYTO)
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    assert out.ack_wire[0] == 0x0B and out.ack_wire[-2:] == bytes([0x1C, 0x0D])
    assert deframe(out.ack_wire) == out.ack
    segs = out.ack.decode("ascii").split("\r")
    assert segs[1].split("|")[1] == "AA"  # MSA-1
    assert segs[1].split("|")[2] == "MSG00142"  # MSA-2 echoes inbound MSH-10


def test_milestone_ack_is_deterministic_with_pinned_timestamp():
    fx = load_fixture(RAYTO)
    a = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    b = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    assert a.ack == b.ack
    assert a.ack_wire == b.ack_wire


def test_milestone_emits_core_ingest_contract_payload():
    """The edge emits the core ADR-0003 NormalizedObservation DTO per (final) observation."""
    fx = load_fixture(RAYTO)
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    payload = out.ingest_payload()
    assert payload[0] == {
        "value": "14.2",
        "rawCode": "HGB",
        "rawUnit": "g/dL",
        "loinc": "718-7",
        "ucumValue": "g/dL",
        "status": "NORMALIZED",
    }
    # all four observations are final, so all four DTOs are emitted.
    assert len(payload) == 4
    assert all(set(d) == {"value", "rawCode", "rawUnit", "loinc", "ucumValue", "status"} for d in payload)
    # every emitted DTO conforms to the committed ingest-contract schema.
    for dto in payload:
        validate_dto(dto)


def _flip_last_obx11_to_preliminary(message: bytes) -> bytes:
    """Flip the last OBX-11 from F (final) to P (preliminary) — the PLT row."""
    i = message.rfind(b"|||F")
    assert i != -1
    return message[:i] + b"|||P" + message[i + 4:]


def test_milestone_holds_back_non_final_observations_from_ingest():
    """The safety gate: a non-final (preliminary) observation is NOT handed to the
    core ingest seam — only final results flow to the append-only store."""
    fx = load_fixture(RAYTO)
    mutated = _flip_last_obx11_to_preliminary(fx.message_bytes)
    out = run_milestone(mutated, ack_timestamp=ACK_TS)

    # finality is observed correctly: 3 final + 1 preliminary (PLT).
    assert out.all_final is False
    assert out.result_statuses == (RESULT_STATUS_FINAL,) * 3 + ("preliminary",)

    # the preliminary PLT observation is held back from the ingest payload.
    payload = out.ingest_payload()
    assert len(payload) == 3
    assert all(d["rawCode"] != "PLT" for d in payload)
    assert [d["rawCode"] for d in payload] == ["HGB", "HCT", "WBC"]


def test_result_status_maps_obx11_codes():
    assert result_status("F") == "final"
    assert result_status("P") == "preliminary"
    assert result_status("C") == "corrected"
    assert result_status("X") == "cancelled"
    assert result_status("") == "unknown"
    assert result_status("z") == "unknown"
