"""Lifotronic H9 proprietary stream codec conformance (LIS-230)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from edge_sim.h9 import H9FrameBuffer, QuarantineReason


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
