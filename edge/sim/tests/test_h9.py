"""Lifotronic H9 proprietary stream codec conformance (LIS-230) and semantic
parser conformance (LIS-231)."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from edge_sim.h9 import (
    EAG_HOLD_CODE,
    ERROR_E1_CODE,
    ERROR_E2_CODE,
    IFCC_HELD_CODE,
    KIND_ANOMALY,
    KIND_CALIBRATION,
    KIND_RESULT,
    KIND_WARNING,
    LOINC_HBA1C_IFCC,
    NGSP_HOLD_CODE,
    RESULT_TYPE_CALIBRATION,
    RESULT_TYPE_PATIENT,
    RESULT_TYPE_QC,
    Classification,
    H9FrameBuffer,
    H9ParseError,
    QuarantineReason,
    classify,
    parse,
    parse_calibration_summary,
    parse_qc_summary,
)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "lifotronic-h9-synthetic"
    / "measurement-n2.hex"
)
SYNTHETIC_FRAME_SHA256 = (
    "8b0adef3d27c61a626df4f5abbf69b1086a301255d3ff29e0d8311cf5a323dbe"
)


def load_synthetic_frame() -> bytes:
    return bytes.fromhex(FIXTURE.read_text(encoding="ascii"))


def test_synthetic_fixture_frames_byte_exact_against_pinned_digest():
    frame = load_synthetic_frame()
    codec = H9FrameBuffer()

    completed = codec.feed(frame)

    assert completed == [frame]
    assert len(frame) == 132
    assert hashlib.sha256(frame).hexdigest() == SYNTHETIC_FRAME_SHA256


def test_concatenated_measurement_qc_and_calibration_frames_each_parse():
    measurement = build_measurement("S", 0)
    qc = build_qc_summary()
    calibration = build_calibration_summary()
    codec = H9FrameBuffer()

    completed = codec.feed(measurement + qc + calibration)

    assert completed == [measurement, qc, calibration]


def test_measurement_split_at_every_boundary_reassembles_with_binary_codes():
    frame = load_synthetic_frame()

    for split in range(1, len(frame)):
        codec = H9FrameBuffer()
        completed = codec.feed(frame[:split]) + codec.feed(frame[split:])
        assert completed == [frame], f"split at byte {split}"


def test_invalid_discriminator_is_quarantined_and_next_frame_recovers():
    malformed = b"\x02X"
    valid = build_qc_summary()
    codec = H9FrameBuffer()

    completed = codec.feed(malformed + valid)

    quarantined = codec.drain_quarantined()
    assert len(quarantined) == 1
    assert quarantined[0].reason is QuarantineReason.INVALID_DISCRIMINATOR
    assert quarantined[0].raw_bytes == malformed
    assert completed == [valid]


def test_stx_in_discriminator_position_becomes_next_candidate_frame_start():
    valid = build_qc_summary()
    codec = H9FrameBuffer()

    completed = codec.feed(b"\x02" + valid)

    quarantined = codec.drain_quarantined()
    assert len(quarantined) == 1
    assert quarantined[0].reason is QuarantineReason.INVALID_DISCRIMINATOR
    assert quarantined[0].raw_bytes == b"\x02\x02"
    assert completed == [valid]


def test_timeout_quarantines_exact_partial_bytes_then_recovers():
    partial = build_measurement("S", 2)[:80]
    valid = build_qc_summary()
    codec = H9FrameBuffer()
    codec.feed(partial)

    codec.timeout()

    quarantined = codec.drain_quarantined()
    assert len(quarantined) == 1
    assert quarantined[0].reason is QuarantineReason.TIMEOUT
    assert quarantined[0].raw_bytes == partial
    assert codec.pending_bytes == b""
    assert codec.feed(valid) == [valid]


def test_curve_count_limit_quarantines_at_header_and_recovers():
    over_limit = build_measurement("S", 2)
    valid = build_measurement("S", 1)
    codec = H9FrameBuffer(max_curve_points=1, max_frame_bytes=1024)

    codec.feed(over_limit)

    quarantined = codec.drain_quarantined()
    assert len(quarantined) == 1
    assert quarantined[0].reason is QuarantineReason.CURVE_COUNT_EXCEEDED
    assert quarantined[0].raw_bytes == over_limit[:118]
    assert codec.feed(valid) == [valid]


def test_total_frame_limit_quarantines_declared_oversize_at_header():
    over_limit = build_measurement("S", 1)
    codec = H9FrameBuffer(max_frame_bytes=125)

    codec.feed(over_limit)

    quarantined = codec.drain_quarantined()
    assert len(quarantined) == 1
    assert quarantined[0].reason is QuarantineReason.FRAME_TOO_LARGE
    assert quarantined[0].raw_bytes == over_limit[:118]


def test_incorrect_curve_count_recovers_swallowed_next_frame_prefix():
    incorrect_count = bytearray(build_measurement("S", 1))
    put(incorrect_count, 115, "002")
    valid = build_qc_summary()
    codec = H9FrameBuffer()

    completed = codec.feed(bytes(incorrect_count) + valid)

    quarantined = codec.drain_quarantined()
    assert len(quarantined) == 1
    assert quarantined[0].reason is QuarantineReason.INVALID_STRUCTURE
    assert completed == [valid]


def test_measurement_shaped_qc_and_calibration_use_curve_count_formula():
    qc = build_measurement("Q", 1)
    calibration = build_measurement("C", 2)
    assert H9FrameBuffer().feed(qc + calibration) == [qc, calibration]


def test_invalid_summary_fields_do_not_accept_short_terminators():
    qc = bytearray(build_qc_summary())
    put(qc, 36, "XX.X")
    qc_codec = H9FrameBuffer()
    assert qc_codec.feed(qc) == []
    assert qc_codec.pending_bytes == bytes(qc)

    calibration = bytearray(build_calibration_summary())
    put(calibration, 50, "?1.0000")
    calibration_codec = H9FrameBuffer()
    assert calibration_codec.feed(calibration) == []
    assert calibration_codec.pending_bytes == bytes(calibration)


def test_invalid_measurement_decimal_and_date_are_quarantined():
    decimal = bytearray(build_measurement("S", 1))
    put(decimal, 118, "X.0000")
    invalid_date = bytearray(build_measurement("S", 0))
    put(invalid_date, 29, "260231120000")
    codec = H9FrameBuffer()

    assert codec.feed(bytes(decimal) + bytes(invalid_date)) == []

    quarantined = codec.drain_quarantined()
    assert [item.reason for item in quarantined] == [
        QuarantineReason.INVALID_STRUCTURE,
        QuarantineReason.INVALID_STRUCTURE,
    ]


def test_invalid_code_length_is_structural_failure():
    malformed = bytearray(build_measurement("S", 0))
    put(malformed, 8, "X5")
    codec = H9FrameBuffer()

    assert codec.feed(malformed) == []
    assert codec.drain_quarantined()[0].reason is QuarantineReason.INVALID_STRUCTURE


def test_missing_etx_resynchronizes_at_next_frame_start():
    missing_etx = build_measurement("S", 0)[:-1]
    valid = build_qc_summary()
    codec = H9FrameBuffer()

    completed = codec.feed(missing_etx + valid)

    assert completed == [valid]
    assert codec.drain_quarantined()[0].reason is QuarantineReason.INVALID_STRUCTURE


def test_leading_noise_extra_etx_and_maximum_n_are_supported():
    first = build_qc_summary()
    second = build_calibration_summary()
    maximum = build_measurement("S", 999)
    codec = H9FrameBuffer()

    completed = codec.feed(b"\x55\x00\x03" + first + b"\x03" + second + maximum)

    assert completed == [first, second, maximum]


def put(target: bytearray, offset: int, value: str) -> None:
    target[offset : offset + len(value)] = value.encode("ascii")


def build_measurement(block: str, curve_points: int) -> bytes:
    frame = bytearray(120 + (6 * curve_points))
    frame[0] = 0x02
    frame[1] = ord(block)
    put(frame, 2, "00")
    put(frame, 4, "01")
    put(frame, 6, "01")
    put(frame, 8, "15")
    put(frame, 10, "000000000012345")
    frame[25] = ord("-")
    put(frame, 26, "01")
    frame[28] = ord("0")
    put(frame, 29, "260716120000")
    put(frame, 41, "001002003")
    put(frame, 50, "1.00002.00003.0000")
    put(frame, 68, "001.000002.000003.000")
    put(frame, 89, "01.0002.0003.00")
    put(frame, 104, "048.00")
    put(frame, 110, "06.00")
    put(frame, 115, f"{curve_points:03d}")
    for point in range(curve_points):
        put(frame, 118 + (6 * point), f"{point % 10}.{point:04d}")
    frame[118 + (6 * curve_points)] = 0x00
    frame[119 + (6 * curve_points)] = 0x03
    return bytes(frame)


def build_qc_summary() -> bytes:
    frame = bytearray(109)
    frame[0:2] = b"\x02Q"
    put(frame, 2, "15")
    put(frame, 4, "000000000000001")
    put(frame, 19, "15")
    put(frame, 21, "000000000000002")
    put(frame, 36, "05.0")
    put(frame, 40, "10.0")
    put(frame, 44, "1.00")
    put(frame, 48, "2.00")
    put(frame, 52, "261231")
    put(frame, 58, "261231")
    put(frame, 64, "02")
    put(frame, 66, "05.00")
    put(frame, 71, "10.00")
    put(frame, 76, "05.00")
    put(frame, 81, "10.00")
    put(frame, 86, "1.0000")
    put(frame, 92, "2.0000")
    put(frame, 98, "01.00")
    put(frame, 103, "02.00")
    frame[108] = 0x03
    return bytes(frame)


def build_calibration_summary() -> bytes:
    frame = bytearray(64)
    frame[0:2] = b"\x02C"
    put(frame, 2, "15")
    put(frame, 4, "000000000000001")
    put(frame, 19, "15")
    put(frame, 21, "000000000000002")
    put(frame, 36, "05.0")
    put(frame, 40, "10.0")
    put(frame, 44, "1.0000")
    put(frame, 50, "+1.0000")
    put(frame, 57, "261231")
    frame[63] = 0x03
    return bytes(frame)


# ─────────────────────────────────────────────────────────────────────────────
# Semantic parser conformance (LIS-231) — mirrors the Java H9ResultParserTest.
# Every assertion anchors to the KB §6.2/§7.1/§8 layout (the source of truth),
# not merely to the Java runtime output (LIS-90, port-every-assertion rule).
# ─────────────────────────────────────────────────────────────────────────────

VENOUS = 0x00
DILUTED = 0x01
QC_MATERIAL = 0x02
CALIBRATOR = 0x03
NO_ERROR = 0x00
E1 = 0x01
E2 = 0x02


def measurement(block: str, curve_points: int, blood_type: int, error: int) -> bytes:
    frame = bytearray(build_measurement(block, curve_points))
    frame[28] = blood_type
    frame[118 + (6 * curve_points)] = error
    return bytes(frame)


def only_result(group, test_code: str):
    rows = [r for r in group.results if r.test_code == test_code]
    assert len(rows) == 1, f"expected exactly one row with code {test_code}"
    return rows[0]


def observations(group):
    return [r for r in group.results if r.kind == KIND_RESULT]


# ── Sample ID ────────────────────────────────────────────────────────────────


def test_leading_zero_sample_id_preserved_verbatim_as_accession():
    group = parse(measurement("S", 0, VENOUS, NO_ERROR))
    assert group.accession == "000000000012345"  # never coerced to 12345


# ── Date / timestamp validation ──────────────────────────────────────────────


def test_impossible_date_is_rejected_not_coerced():
    frame = bytearray(measurement("S", 0, VENOUS, NO_ERROR))
    put(frame, 29, "261316120000")  # month 13
    with pytest.raises(H9ParseError):
        parse(bytes(frame))


def test_valid_timestamp_normalized_to_fourteen_digits():
    group = parse(measurement("S", 0, VENOUS, NO_ERROR))
    assert only_result(group, LOINC_HBA1C_IFCC).timestamp == "20260716120000"


# ── Blood-type / block classification (D6) ───────────────────────────────────


def test_venous_and_diluted_classify_as_patient():
    assert parse(measurement("S", 0, VENOUS, NO_ERROR)).result_type == RESULT_TYPE_PATIENT
    assert parse(measurement("S", 0, DILUTED, NO_ERROR)).result_type == RESULT_TYPE_PATIENT


def test_qc_material_blood_type_classifies_out_of_patient_stream():
    assert parse(measurement("S", 0, QC_MATERIAL, NO_ERROR)).result_type == RESULT_TYPE_QC


def test_calibrator_blood_type_classifies_as_calibration_even_on_block_s():
    group = parse(measurement("S", 0, CALIBRATOR, NO_ERROR))
    assert group.result_type == RESULT_TYPE_CALIBRATION
    assert observations(group) == []


def test_block_q_and_c_classify_by_block():
    assert parse(measurement("Q", 0, VENOUS, NO_ERROR)).result_type == RESULT_TYPE_QC
    assert parse(measurement("C", 0, VENOUS, NO_ERROR)).result_type == RESULT_TYPE_CALIBRATION


def test_ascii_classification_code_also_decodes():
    frame = bytearray(measurement("S", 0, VENOUS, NO_ERROR))
    frame[28] = ord("3")  # ASCII '3' == calibrator, just like binary 0x03
    assert parse(bytes(frame)).result_type == RESULT_TYPE_CALIBRATION


def test_blood_type_out_of_range_is_rejected():
    frame = bytearray(measurement("S", 0, VENOUS, NO_ERROR))
    frame[28] = 0x09
    with pytest.raises(H9ParseError):
        parse(bytes(frame))


def test_unsupported_version_profile_is_quarantined_not_decoded():
    # A newer-firmware frame of the same block/length/curve shape but a different
    # declared version must be quarantined (KB §6.2/§12.1), never decoded with A0
    # offsets that may not apply.
    frame = bytearray(measurement("S", 0, VENOUS, NO_ERROR))
    put(frame, 2, "07")  # version 07 ≠ approved A0 version 00
    with pytest.raises(H9ParseError):
        parse(bytes(frame))


def test_unsupported_parameter_format_profile_is_quarantined():
    frame = bytearray(measurement("S", 0, VENOUS, NO_ERROR))
    put(frame, 6, "09")  # parameter-description format 09 ≠ approved A0 format 01
    with pytest.raises(H9ParseError):
        parse(bytes(frame))


def test_classify_is_fail_closed():
    # Calibration wins over QC wins over patient on a discriminator conflict.
    assert classify("S", _bt(CALIBRATOR)) is Classification.CALIBRATION
    assert classify("S", _bt(QC_MATERIAL)) is Classification.QC
    assert classify("S", _bt(VENOUS)) is Classification.PATIENT


def _bt(code: int):
    from edge_sim.h9 import BloodType

    return {
        VENOUS: BloodType.VENOUS,
        DILUTED: BloodType.DILUTED,
        QC_MATERIAL: BloodType.QC_MATERIAL,
        CALIBRATOR: BloodType.CALIBRATOR,
    }[code]


# ── E1 / E2 test-error propagation ───────────────────────────────────────────


def test_e1_and_e2_flags_propagate_as_warning_not_observation():
    e1_group = parse(measurement("S", 0, VENOUS, E1))
    warnings = [r for r in e1_group.results if r.kind == KIND_WARNING]
    assert len(warnings) == 1 and warnings[0].test_code == ERROR_E1_CODE

    e2_group = parse(measurement("S", 0, VENOUS, E2))
    e2_warnings = [r for r in e2_group.results if r.kind == KIND_WARNING]
    assert len(e2_warnings) == 1 and e2_warnings[0].test_code == ERROR_E2_CODE


def test_flagged_patient_measurement_emits_no_accept_ready_observation_and_holds_ifcc():
    # Fail-closed: an aspiration-flagged (e1/E2) measurement never produces an
    # accept-ready IFCC Observation (the OE importer ignores DiagnosticReport warning
    # conclusions). The IFCC is a visible ANOMALY hold carrying the raw value.
    group = parse(measurement("S", 0, VENOUS, E1))
    assert observations(group) == []
    held = only_result(group, IFCC_HELD_CODE)
    assert held.kind == KIND_ANOMALY
    assert "48.00" in held.value  # raw IFCC preserved as evidence
    assert held.units is None


def test_flagged_qc_measurement_is_also_held_not_accepted():
    group = parse(measurement("S", 0, QC_MATERIAL, E2))
    assert group.result_type == RESULT_TYPE_QC
    assert observations(group) == []
    assert only_result(group, IFCC_HELD_CODE).kind == KIND_ANOMALY


def test_no_error_flag_yields_no_warning_row():
    group = parse(measurement("S", 0, VENOUS, NO_ERROR))
    assert not [r for r in group.results if r.kind == KIND_WARNING]


# ── IFCC terminology mapping ─────────────────────────────────────────────────


def test_ifcc_maps_to_loinc_59261_and_mmol_mol():
    ifcc = only_result(parse(measurement("S", 0, VENOUS, NO_ERROR)), LOINC_HBA1C_IFCC)
    assert ifcc.test_code == "59261-8"
    assert ifcc.units == "mmol/mol"
    assert ifcc.value == "48.00"
    assert ifcc.is_numeric is True


def test_patient_frame_emits_exactly_one_clinical_observation():
    obs = observations(parse(measurement("S", 0, VENOUS, NO_ERROR)))
    assert len(obs) == 1 and obs[0].test_code == "59261-8"


# ── No Observation for calibration or warning-only content ───────────────────


def test_no_observation_emitted_for_calibration_summary():
    group = parse(build_calibration_summary())
    assert group.result_type == RESULT_TYPE_CALIBRATION
    assert observations(group) == []
    assert group.results[0].kind == KIND_CALIBRATION


# ── Ambiguous NGSP / eAG → visible hold, never a value ────────────────────────


def test_ngsp_and_eag_are_visible_holds_not_guessed_values():
    group = parse(measurement("S", 0, VENOUS, NO_ERROR))
    ngsp = only_result(group, NGSP_HOLD_CODE)
    eag = only_result(group, EAG_HOLD_CODE)
    assert ngsp.kind == KIND_ANOMALY and eag.kind == KIND_ANOMALY

    codes = [r.test_code for r in observations(group)]
    for withheld in ("4548-4", "17856-6", "27353-2", "53553-4"):
        assert withheld not in codes


def test_ngsp_hold_carries_raw_ratio_as_non_clinical_evidence():
    ngsp = only_result(parse(measurement("S", 0, VENOUS, NO_ERROR)), NGSP_HOLD_CODE)
    assert "02.00" in ngsp.value  # raw peak-area ratio, preserved as evidence
    assert "non-clinical" in ngsp.value.lower()
    assert ngsp.units is None


# ── QC summary field extraction ──────────────────────────────────────────────


def test_qc_summary_extracts_low_high_lot_target_value_mean_sd_cv():
    qc = parse_qc_summary(build_qc_summary())
    assert qc.low_lot == "000000000000001"  # leading zeros preserved
    assert qc.high_lot == "000000000000002"
    assert qc.low_target == "5.0"
    assert qc.high_target == "10.0"
    assert qc.low_target_sd == "1.00"
    assert qc.tested_count == 2
    assert qc.low_current == "5.00"
    assert qc.high_current == "10.00"
    assert qc.low_average == "5.00"
    assert qc.low_observed_sd == "1.0000"
    assert qc.low_cv == "1.00"
    assert qc.high_cv == "2.00"
    assert qc.low_expiry == date(2026, 12, 31)


def test_qc_summary_classified_as_qc_with_lot_and_level():
    group = parse(build_qc_summary())
    assert group.result_type == RESULT_TYPE_QC
    low = next(r for r in group.results if r.control_level == "LOW")
    assert low.is_control is True
    assert low.lot_number == "000000000000001"
    assert low.test_code == "59261-8"


# ── Calibration summary field extraction ─────────────────────────────────────


def test_calibration_summary_extracts_lot_concentrations_kb_date():
    cal = parse_calibration_summary(build_calibration_summary())
    assert cal.low_lot == "000000000000001"
    assert cal.high_lot == "000000000000002"
    assert cal.low_concentration == "5.0"
    assert cal.high_concentration == "10.0"
    assert cal.factor_k == "1.0000"
    assert cal.offset_b == "1.0000"
    assert cal.calibration_date == date(2026, 12, 31)


def test_calibration_summary_negative_offset_b_preserves_sign():
    frame = bytearray(build_calibration_summary())
    put(frame, 50, "-2.5000")
    assert parse_calibration_summary(bytes(frame)).offset_b == "-2.5000"


# ── Frame dispatch / structural guards ───────────────────────────────────────


def test_unknown_block_is_rejected():
    frame = bytearray(measurement("S", 0, VENOUS, NO_ERROR))
    frame[1] = ord("X")
    with pytest.raises(H9ParseError):
        parse(bytes(frame))


def test_unrecognized_length_is_rejected():
    frame = bytearray(50)
    frame[0] = 0x02
    frame[1] = ord("S")
    frame[49] = 0x03
    with pytest.raises(H9ParseError):
        parse(bytes(frame))


def test_frame_without_stx_etx_is_rejected():
    with pytest.raises(H9ParseError):
        parse(b"SQ")


# ── Cross-language anchor to the shared synthetic fixture ─────────────────────


def test_shared_synthetic_fixture_classifies_fail_closed_as_calibration():
    # The exact frame the framer and the Java parser anchor to (block S,
    # blood-type 0x03, error E2). The calibrator blood-type wins fail-closed, so
    # no patient Observation is produced — the two-level contract in one frame.
    frame = load_synthetic_frame()
    assert hashlib.sha256(frame).hexdigest() == SYNTHETIC_FRAME_SHA256
    group = parse(frame)
    assert group.result_type == RESULT_TYPE_CALIBRATION
    assert observations(group) == []
    assert group.accession == "000000000012345"  # leading zeros survive even here
