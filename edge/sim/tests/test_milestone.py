"""Stage-1 milestone E2E — first result through the pipe (LIS-17 / S1.5).

The milestone exit gate (``LIS_IMPLEMENTATION_PLAN.md`` §1): a captured **EDAN H60S**
``ORU^R01`` replayed over MLLP produces a normalized **Result** (raw code/unit
preserved; LOINC + UCUM populated; final) *and* the listener returns a correct
``ACK^R01`` with MSA-1 = ``AA`` — asserted by this one automated E2E test, plus the
core ingest contract DTO the edge would hand to ``ResultIngestService.ingest``.
"""

from pathlib import Path

from edge_sim.fixtures import load_fixture
from edge_sim.mllp import deframe
from edge_sim.milestone import RESULT_STATUS_FINAL, result_status, run_milestone
from edge_sim.normalize import STATUS_NORMALIZED

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
EDAN = FIXTURES_ROOT / "edan-h60s-oru-r01"
ACK_TS = "20260628093001"


def test_milestone_edan_h60s_normalized_result_and_ack():
    """The 🎯 milestone: EDAN H60S ORU^R01 over MLLP -> normalized Result + ACK (AA)."""
    fx = load_fixture(EDAN)
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)

    # --- the message survived MLLP framing and was accepted ------------------
    assert out.round_trip_ok is True
    assert out.accepted is True
    assert out.ack_code == "AA"  # MSA-1 = AA (application accept)
    assert out.ack_message_code == "ACK"
    assert out.ack_trigger_event == "R01"  # ACK^R01 (v2.4 carries ^ACK structure)

    # --- the normalized Result --------------------------------------------------
    assert out.report.message_type == "ORU^R01"
    assert out.report.patient_id == "PID-0231"
    assert out.report.specimen_id == "SPEC-0231"
    assert out.report.sending_app == "H60S"

    assert len(out.observations) == 6
    # raw analyzer code/unit preserved beside the resolved LOINC/UCUM, every row.
    assert [o.raw_code for o in out.observations] == ["WBC", "RBC", "HGB", "HCT", "MCV", "PLT"]
    assert [o.raw_unit for o in out.observations] == ["10^9/L", "10^12/L", "g/L", "%", "fL", "10^9/L"]
    assert [o.loinc for o in out.observations] == ["6690-2", "789-8", "718-7", "4544-3", "787-2", "777-3"]
    assert [o.ucum_value for o in out.observations] == ["10*9/L", "10*12/L", "g/L", "%", "fL", "10*9/L"]
    # LOINC + UCUM populated on every row (fully normalized).
    assert all(o.loinc and o.ucum_value for o in out.observations)
    assert all(o.status == STATUS_NORMALIZED for o in out.observations)

    # --- finality: every observation is a *final* result (OBX-11 = F) --------
    assert out.all_final is True
    assert out.result_statuses == (RESULT_STATUS_FINAL,) * 6


def test_milestone_matches_fixture_expected_rows():
    """The normalized rows match the fixture manifest's asserted ``expected`` block."""
    fx = load_fixture(EDAN)
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
    fx = load_fixture(EDAN)
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    assert out.ack_wire[0] == 0x0B and out.ack_wire[-2:] == bytes([0x1C, 0x0D])
    assert deframe(out.ack_wire) == out.ack
    segs = out.ack.decode("ascii").split("\r")
    assert segs[1].split("|")[1] == "AA"  # MSA-1
    assert segs[1].split("|")[2] == "H60S00231"  # MSA-2 echoes inbound MSH-10


def test_milestone_ack_is_deterministic_with_pinned_timestamp():
    fx = load_fixture(EDAN)
    a = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    b = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    assert a.ack == b.ack
    assert a.ack_wire == b.ack_wire


def test_milestone_emits_core_ingest_contract_payload():
    """The edge emits the core ADR-0003 NormalizedObservation DTO per observation."""
    fx = load_fixture(EDAN)
    out = run_milestone(fx.message_bytes, ack_timestamp=ACK_TS)
    payload = out.ingest_payload()
    assert payload[0] == {
        "value": "6.8",
        "rawCode": "WBC",
        "rawUnit": "10^9/L",
        "loinc": "6690-2",
        "ucumValue": "10*9/L",
        "status": "NORMALIZED",
    }
    # one DTO per observation, raw beside normalized on every row.
    assert len(payload) == 6
    assert all(set(d) == {"value", "rawCode", "rawUnit", "loinc", "ucumValue", "status"} for d in payload)


def test_result_status_maps_obx11_codes():
    assert result_status("F") == "final"
    assert result_status("P") == "preliminary"
    assert result_status("C") == "corrected"
    assert result_status("X") == "cancelled"
    assert result_status("") == "unknown"
    assert result_status("z") == "unknown"
