"""Byte-preserving Lifotronic H9 proprietary stream framer (LIS-230)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

STX = 0x02
ETX = 0x03
DEFAULT_MAX_CURVE_POINTS = 999
DEFAULT_MAX_FRAME_BYTES = 8192

__all__ = [
    "DEFAULT_MAX_CURVE_POINTS",
    "DEFAULT_MAX_FRAME_BYTES",
    "ETX",
    "H9FrameBuffer",
    "QuarantinedFrame",
    "QuarantineReason",
    "STX",
]


class QuarantineReason(str, Enum):
    INVALID_DISCRIMINATOR = "invalid-discriminator"
    INVALID_STRUCTURE = "invalid-structure"
    CURVE_COUNT_EXCEEDED = "curve-count-exceeded"
    FRAME_TOO_LARGE = "frame-too-large"
    TIMEOUT = "timeout"


class _State(Enum):
    SEEK_STX = "seek-stx"
    READ_DISCRIMINATOR = "read-discriminator"
    READ_BODY = "read-body"
    COMPLETE = "complete"


@dataclass(frozen=True)
class QuarantinedFrame:
    raw_bytes: bytes
    reason: QuarantineReason
    quarantined_at: datetime


class H9FrameBuffer:
    """Incremental H9 framer selected explicitly by an H9 simulator channel."""

    def __init__(
        self,
        *,
        max_curve_points: int = DEFAULT_MAX_CURVE_POINTS,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    ) -> None:
        if max_curve_points < 0:
            raise ValueError("max_curve_points must not be negative")
        if max_frame_bytes < 2:
            raise ValueError("max_frame_bytes must be at least 2")
        self.max_curve_points = max_curve_points
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()
        self._expected_bytes: int | None = None
        self._quarantined: list[QuarantinedFrame] = []
        self._state = _State.SEEK_STX

    @property
    def pending_bytes(self) -> bytes:
        return bytes(self._buffer)

    def feed(self, data: bytes) -> list[bytes]:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"data must be bytes, got {type(data).__name__}")
        completed: list[bytes] = []
        for value in data:
            self._process_byte(value, completed)
        return completed

    def drain_quarantined(self) -> list[QuarantinedFrame]:
        quarantined = self._quarantined
        self._quarantined = []
        return quarantined

    def timeout(self) -> None:
        if self._buffer:
            self._quarantine(QuarantineReason.TIMEOUT)

    def _process_byte(self, value: int, completed: list[bytes]) -> None:
        if self._state is _State.SEEK_STX:
            if value == STX:
                self._buffer.append(value)
                self._state = _State.READ_DISCRIMINATOR
            return
        self._buffer.append(value)
        if self._state is _State.READ_DISCRIMINATOR:
            if value not in b"SQC":
                self._quarantine_and_resync(
                    QuarantineReason.INVALID_DISCRIMINATOR, completed
                )
            else:
                self._state = _State.READ_BODY
            return
        if len(self._buffer) > self.max_frame_bytes:
            self._quarantine_and_resync(QuarantineReason.FRAME_TOO_LARGE, completed)
            return
        if len(self._buffer) == 64 and self._buffer[1] == ord("C"):
            frame = bytes(self._buffer)
            if _valid_calibration_summary(frame):
                self._state = _State.COMPLETE
                self._reset()
                completed.append(frame)
                return
        if len(self._buffer) == 109 and self._buffer[1] == ord("Q"):
            frame = bytes(self._buffer)
            if _valid_qc_summary(frame):
                self._state = _State.COMPLETE
                self._reset()
                completed.append(frame)
                return
        if len(self._buffer) == 118:
            count = _number(self._buffer, 115, 3)
            if count is None:
                self._quarantine_and_resync(QuarantineReason.INVALID_STRUCTURE, completed)
                return
            if count > self.max_curve_points:
                self._quarantine_and_resync(QuarantineReason.CURVE_COUNT_EXCEEDED, completed)
                return
            self._expected_bytes = 120 + (6 * count)
            if self._expected_bytes > self.max_frame_bytes:
                self._quarantine_and_resync(QuarantineReason.FRAME_TOO_LARGE, completed)
                return
        if self._expected_bytes is not None and len(self._buffer) == self._expected_bytes:
            frame = bytes(self._buffer)
            if _valid_measurement(frame):
                self._state = _State.COMPLETE
                self._reset()
                completed.append(frame)
            else:
                self._quarantine_and_resync(QuarantineReason.INVALID_STRUCTURE, completed)

    def _reset(self) -> None:
        self._buffer.clear()
        self._expected_bytes = None
        self._state = _State.SEEK_STX

    def _quarantine(self, reason: QuarantineReason) -> None:
        self._quarantined.append(
            QuarantinedFrame(bytes(self._buffer), reason, datetime.now(UTC))
        )
        self._reset()

    def _quarantine_and_resync(
        self, reason: QuarantineReason, completed: list[bytes]
    ) -> None:
        rejected = bytes(self._buffer)
        restart = _last_plausible_frame_start(rejected)
        self._quarantine(reason)
        if restart is not None:
            for value in rejected[restart:]:
                self._process_byte(value, completed)


def _valid_measurement(frame: bytes) -> bool:
    if len(frame) < 120 or (len(frame) - 120) % 6:
        return False
    curve_points = (len(frame) - 120) // 6
    if (
        frame[-1] != ETX
        or frame[1] not in b"SQC"
        or not _digits(frame, 2, 6)
        or not _bounded_number(frame, 8, 2, 15)
        or not _digits(frame, 10, 15)
        or frame[25] != ord("-")
        or not _digits(frame, 26, 2)
        or not _classification_code(frame[28])
        or not _valid_datetime(frame, 29)
        or not _digits(frame, 41, 9)
        or not _decimal(frame, 50, "#.####")
        or not _decimal(frame, 56, "#.####")
        or not _decimal(frame, 62, "#.####")
        or not _decimal(frame, 68, "###.###")
        or not _decimal(frame, 75, "###.###")
        or not _decimal(frame, 82, "###.###")
        or not _decimal(frame, 89, "##.##")
        or not _decimal(frame, 94, "##.##")
        or not _decimal(frame, 99, "##.##")
        or not _decimal(frame, 104, "###.##")
        or not _decimal(frame, 110, "##.##")
        or _number(frame, 115, 3) != curve_points
    ):
        return False
    if any(
        not _decimal(frame, 118 + (6 * point), "#.####")
        for point in range(curve_points)
    ):
        return False
    return _error_code(frame[118 + (6 * curve_points)])


def _last_plausible_frame_start(rejected: bytes) -> int | None:
    for index in range(len(rejected) - 1, 0, -1):
        if rejected[index] == STX and (
            index == len(rejected) - 1 or rejected[index + 1] in b"SQC"
        ):
            return index
    return None


def _valid_qc_summary(frame: bytes) -> bool:
    return (
        len(frame) == 109
        and frame[-1] == ETX
        and _bounded_number(frame, 2, 2, 15)
        and _digits(frame, 4, 15)
        and _bounded_number(frame, 19, 2, 15)
        and _digits(frame, 21, 15)
        and _decimal(frame, 36, "##.#")
        and _decimal(frame, 40, "##.#")
        and _decimal(frame, 44, "#.##")
        and _decimal(frame, 48, "#.##")
        and _valid_date(frame, 52)
        and _valid_date(frame, 58)
        and _digits(frame, 64, 2)
        and _decimal(frame, 66, "##.##")
        and _decimal(frame, 71, "##.##")
        and _decimal(frame, 76, "##.##")
        and _decimal(frame, 81, "##.##")
        and _decimal(frame, 86, "#.####")
        and _decimal(frame, 92, "#.####")
        and _decimal(frame, 98, "##.##")
        and _decimal(frame, 103, "##.##")
    )


def _valid_calibration_summary(frame: bytes) -> bool:
    return (
        len(frame) == 64
        and frame[-1] == ETX
        and _bounded_number(frame, 2, 2, 15)
        and _digits(frame, 4, 15)
        and _bounded_number(frame, 19, 2, 15)
        and _digits(frame, 21, 15)
        and _decimal(frame, 36, "##.#")
        and _decimal(frame, 40, "##.#")
        and _decimal(frame, 44, "#.####")
        and frame[50] in b"+-"
        and _decimal(frame, 51, "#.####")
        and _valid_date(frame, 57)
    )


def _digits(frame: bytes | bytearray, offset: int, length: int) -> bool:
    return all(ord("0") <= value <= ord("9") for value in frame[offset : offset + length])


def _number(frame: bytes | bytearray, offset: int, length: int) -> int | None:
    field = frame[offset : offset + length]
    if len(field) != length or not _digits(frame, offset, length):
        return None
    return int(bytes(field))


def _bounded_number(frame: bytes, offset: int, length: int, maximum: int) -> bool:
    value = _number(frame, offset, length)
    return value is not None and value <= maximum


def _decimal(frame: bytes, offset: int, mask: str) -> bool:
    field = frame[offset : offset + len(mask)]
    return len(field) == len(mask) and all(
        (expected == "#" and ord("0") <= actual <= ord("9"))
        or (expected != "#" and actual == ord(expected))
        for actual, expected in zip(field, mask, strict=True)
    )


def _classification_code(value: int) -> bool:
    return 0x00 <= value <= 0x03 or ord("0") <= value <= ord("3")


def _error_code(value: int) -> bool:
    return 0x00 <= value <= 0x02 or ord("0") <= value <= ord("2")


def _valid_datetime(frame: bytes, offset: int) -> bool:
    if not _digits(frame, offset, 12):
        return False
    try:
        datetime(
            2000 + int(frame[offset : offset + 2]),
            int(frame[offset + 2 : offset + 4]),
            int(frame[offset + 4 : offset + 6]),
            int(frame[offset + 6 : offset + 8]),
            int(frame[offset + 8 : offset + 10]),
            int(frame[offset + 10 : offset + 12]),
        )
        return True
    except ValueError:
        return False


def _valid_date(frame: bytes, offset: int) -> bool:
    if not _digits(frame, offset, 6):
        return False
    try:
        datetime(
            2000 + int(frame[offset : offset + 2]),
            int(frame[offset + 2 : offset + 4]),
            int(frame[offset + 4 : offset + 6]),
        )
        return True
    except ValueError:
        return False
