"""Byte-preserving Lifotronic H9 proprietary stream framer (LIS-230) and
semantic parser (LIS-231).

The framer (:class:`H9FrameBuffer`) reassembles the proprietary upload stream
into byte-exact frames; the parser (:func:`parse`) turns one framed frame into
a classified :class:`H9SpecimenGroup`. This is the Python conformance mirror of
the Java ``org.itech.ahb.fhir.H9ResultParser`` (two-level rule, LIS-90): both
anchor to the same real capture / synthetic fixture by SHA-256.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

STX = 0x02
ETX = 0x03
DEFAULT_MAX_CURVE_POINTS = 999
DEFAULT_MAX_FRAME_BYTES = 8192

__all__ = [
    "DEFAULT_MAX_CURVE_POINTS",
    "DEFAULT_MAX_FRAME_BYTES",
    "ETX",
    "STX",
    "BloodType",
    "Classification",
    "ErrorFlag",
    "H9CalibrationSummary",
    "H9FrameBuffer",
    "H9Measurement",
    "H9ParseError",
    "H9QcSummary",
    "H9Result",
    "H9SpecimenGroup",
    "QuarantineReason",
    "QuarantinedFrame",
    "parse",
    "parse_calibration_summary",
    "parse_measurement",
    "parse_qc_summary",
    "classify",
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


# ─────────────────────────────────────────────────────────────────────────────
# Semantic parser (LIS-231) — Python mirror of org.itech.ahb.fhir.H9ResultParser
# ─────────────────────────────────────────────────────────────────────────────

# H9 terminology (v1 recommendation, plan §8.3 — bench + terminology/validation
# sign-off gate *release*, not this build).
LOINC_HBA1C_IFCC = "59261-8"
UCUM_MMOL_MOL = "mmol/mol"
HBA1C_IFCC_NAME = "Hemoglobin A1c/Hemoglobin.total [IFCC]"
NGSP_HOLD_CODE = "H9-NGSP-WITHHELD"
EAG_HOLD_CODE = "H9-EAG-WITHHELD"
ERROR_E1_CODE = "H9-E1"
ERROR_E2_CODE = "H9-E2"
IFCC_HELD_CODE = "H9-IFCC-HELD"
CALIBRATION_CODE = "H9-CAL"
QC_LEVEL_LOW = "LOW"
QC_LEVEL_HIGH = "HIGH"

# Row disposition (mirrors the Java AnalyzerResult.Kind). Only RESULT rows become
# FHIR Observations downstream.
KIND_RESULT = "RESULT"
KIND_WARNING = "WARNING"
KIND_ANOMALY = "ANOMALY"
KIND_CALIBRATION = "CALIBRATION"

# Content disposition (mirrors the Java HL7ResultParser.ResultType).
RESULT_TYPE_PATIENT = "PATIENT"
RESULT_TYPE_QC = "QC"
RESULT_TYPE_CALIBRATION = "CALIBRATION"

# ── H9 field layout — single source of truth (KB §6.2/§7.1/§8) ───────────────
# The framer above keeps a parallel copy of these offsets inside its structural
# validators; each copy is pinned by its own test matrix so the two cannot drift
# silently. Mirrors the Java H9Fields. Bench-validatable (plan §5 S3 "Partial").
_QC_SUMMARY_BYTES = 109
_CAL_SUMMARY_BYTES = 64
_MEAS_BASE_BYTES = 120
_CURVE_POINT_WIDTH = 6
_BLOCK = 1

_MEAS_VERSION = 2
_MEAS_VERSION_WIDTH = 2
_MEAS_PARAM_FORMAT = 6
_MEAS_PARAM_FORMAT_WIDTH = 2
_MEAS_SAMPLE_ID = 10
_MEAS_SAMPLE_ID_WIDTH = 15
_MEAS_SEPARATOR = 25
_MEAS_LOADER_POSITION = 26
_MEAS_LOADER_POSITION_WIDTH = 2
_MEAS_BLOOD_TYPE = 28
_MEAS_DATETIME = 29
_MEAS_DATETIME_WIDTH = 12
_MEAS_HBA1C_RATIO = 94
_MEAS_HBA1C_RATIO_WIDTH = 5
_MEAS_IFCC = 104
_MEAS_IFCC_WIDTH = 6
_MEAS_ADAG = 110
_MEAS_ADAG_WIDTH = 5
_MEAS_CURVE_COUNT = 115
_MEAS_CURVE_COUNT_WIDTH = 3
_MEAS_CURVE_VALUES = 118

# The A0 protocol-version and parameter-description-format descriptors this offset
# table was authored against (KB §6.2 offsets 2 and 6). A measurement frame that
# declares any other profile is quarantined rather than decoded with positional
# offsets that may not apply to it (KB §12.1 "unknown version → Quarantine";
# §15.2 "quarantine for unsupported versions"). Both values are A0-provisional and
# bench-unconfirmed (KB §14); the S1 capture (LIS-229) confirms/corrects them here.
_APPROVED_MEAS_VERSION = "00"
_APPROVED_MEAS_PARAM_FORMAT = "01"

_QC_LOW_LOT = 4
_QC_LOT_WIDTH = 15
_QC_HIGH_LOT = 21
_QC_LOW_TARGET = 36
_QC_HIGH_TARGET = 40
_QC_TARGET_WIDTH = 4
_QC_LOW_TARGET_SD = 44
_QC_HIGH_TARGET_SD = 48
_QC_TARGET_SD_WIDTH = 4
_QC_LOW_EXPIRY = 52
_QC_HIGH_EXPIRY = 58
_QC_TESTED_COUNT = 64
_QC_TESTED_COUNT_WIDTH = 2
_QC_LOW_CURRENT = 66
_QC_HIGH_CURRENT = 71
_QC_LOW_AVERAGE = 76
_QC_HIGH_AVERAGE = 81
_QC_VALUE_WIDTH = 5
_QC_LOW_OBSERVED_SD = 86
_QC_HIGH_OBSERVED_SD = 92
_QC_OBSERVED_SD_WIDTH = 6
_QC_LOW_CV = 98
_QC_HIGH_CV = 103
_QC_CV_WIDTH = 5

_CAL_LOW_LOT = 4
_CAL_LOT_WIDTH = 15
_CAL_HIGH_LOT = 21
_CAL_LOW_CONCENTRATION = 36
_CAL_HIGH_CONCENTRATION = 40
_CAL_CONCENTRATION_WIDTH = 4
_CAL_FACTOR_K = 44
_CAL_FACTOR_K_WIDTH = 6
_CAL_OFFSET_B_SIGN = 50
_CAL_OFFSET_B = 51
_CAL_OFFSET_B_WIDTH = 6
_CAL_DATE = 57

_DATE_WIDTH = 6


class H9ParseError(ValueError):
    """An H9 frame that reached the semantic parser but cannot be safely
    interpreted — an impossible length/block, an out-of-range classification or
    error code, or an impossible date/time. Mirrors the Java H9ParseException."""


class BloodType(Enum):
    VENOUS = "venous"
    DILUTED = "diluted"
    QC_MATERIAL = "qc-material"
    CALIBRATOR = "calibrator"


class ErrorFlag(Enum):
    NONE = "none"
    E1_ASPIRATION_LOW = "e1"
    E2_ASPIRATION_HIGH = "e2"


class Classification(Enum):
    PATIENT = "patient"
    QC = "qc"
    CALIBRATION = "calibration"


@dataclass(frozen=True)
class H9Result:
    """One disposition row, protocol-agnostic (mirrors the Java AnalyzerResult)."""

    test_code: str
    test_name: str
    value: str | None
    units: str | None
    is_numeric: bool
    is_control: bool
    timestamp: str | None
    lot_number: str | None
    control_level: str | None
    kind: str


@dataclass(frozen=True)
class H9SpecimenGroup:
    """One specimen's worth of results — one group per frame, Sample SN as the
    accession (ADR-0018 shape). QC/calibration summaries carry no Sample SN."""

    accession: str | None
    results: tuple[H9Result, ...]
    result_type: str


@dataclass(frozen=True)
class H9Measurement:
    """A parsed H9 measurement frame (KB §6.2). The raw peak-area ratio and ADAG
    fields are retained verbatim as non-clinical evidence for the withheld
    NGSP/eAG holds and are never emitted as clinical values."""

    block: str
    sample_id: str
    loader_position: int
    blood_type: BloodType
    blood_type_raw: int
    completion_timestamp: str
    ifcc: str
    hba1c_peak_area_ratio_raw: str
    adag_raw: str
    curve_points: int
    error_flag: ErrorFlag
    error_raw: int


@dataclass(frozen=True)
class H9QcSummary:
    """A parsed fixed 109-byte QC summary frame (KB §7.1)."""

    low_lot: str
    high_lot: str
    low_target: str
    high_target: str
    low_target_sd: str
    high_target_sd: str
    low_expiry: date
    high_expiry: date
    tested_count: int
    low_current: str
    high_current: str
    low_average: str
    high_average: str
    low_observed_sd: str
    high_observed_sd: str
    low_cv: str
    high_cv: str


@dataclass(frozen=True)
class H9CalibrationSummary:
    """A parsed fixed 64-byte calibration summary frame (KB §8)."""

    low_lot: str
    high_lot: str
    low_concentration: str
    high_concentration: str
    factor_k: str
    offset_b: str
    calibration_date: date


def parse(frame: bytes) -> H9SpecimenGroup:
    """Parse one framed H9 frame (STX…ETX) into a classified specimen group.

    Raises :class:`H9ParseError` if the frame is not safely interpretable.
    """
    if frame is None:
        raise H9ParseError("H9 frame is None")
    if len(frame) < 2 or frame[0] != STX or frame[-1] != ETX:
        raise H9ParseError(f"H9 frame is not STX…ETX-delimited (length {len(frame)})")
    block = chr(frame[_BLOCK])
    length = len(frame)
    if block == "C" and length == _CAL_SUMMARY_BYTES:
        return _calibration_summary_group(parse_calibration_summary(frame))
    if block == "Q" and length == _QC_SUMMARY_BYTES:
        return _qc_summary_group(parse_qc_summary(frame))
    if (
        block in ("S", "Q", "C")
        and length >= _MEAS_BASE_BYTES
        and (length - _MEAS_BASE_BYTES) % _CURVE_POINT_WIDTH == 0
    ):
        return _measurement_group(parse_measurement(frame))
    raise H9ParseError(f"Unrecognized H9 frame: block='{block}' length={length}")


def classify(block: str, blood_type: BloodType) -> Classification:
    """Content disposition for a measurement frame (D6, fail-closed): a
    calibration signal wins over a QC signal wins over patient."""
    if block == "C" or blood_type is BloodType.CALIBRATOR:
        return Classification.CALIBRATION
    if block == "Q" or blood_type is BloodType.QC_MATERIAL:
        return Classification.QC
    return Classification.PATIENT


def _require_approved_profile(frame: bytes) -> None:
    """Reject a measurement frame whose declared version / parameter-format profile
    is not the A0 profile these offsets were authored against (KB §6.2/§12.1)."""
    version = _text(frame, _MEAS_VERSION, _MEAS_VERSION_WIDTH)
    param_format = _text(frame, _MEAS_PARAM_FORMAT, _MEAS_PARAM_FORMAT_WIDTH)
    if version != _APPROVED_MEAS_VERSION or param_format != _APPROVED_MEAS_PARAM_FORMAT:
        raise H9ParseError(
            "H9 measurement declares an unsupported version/parameter-format profile "
            f"(version='{version}', param-format='{param_format}'); this parser decodes only "
            f"the A0 profile version='{_APPROVED_MEAS_VERSION}'/param-format="
            f"'{_APPROVED_MEAS_PARAM_FORMAT}' (KB §6.2/§12.1) — quarantined, not decoded"
        )


def parse_measurement(frame: bytes) -> H9Measurement:
    curve_points = (len(frame) - _MEAS_BASE_BYTES) // _CURVE_POINT_WIDTH
    block = chr(frame[_BLOCK])
    # Fail-closed profile gate (KB §6.2/§12.1): the positional offsets below are the
    # A0 layout. A frame declaring any other version/parameter-format profile is
    # quarantined here — never decoded with offsets that may not apply — so a
    # newer-firmware frame of the same block/length/curve shape can never be mis-read
    # into the wrong accession or HbA1c value.
    _require_approved_profile(frame)
    if frame[_MEAS_SEPARATOR] != ord("-"):
        raise H9ParseError(f"H9 measurement missing '-' separator at offset {_MEAS_SEPARATOR}")
    # Sample SN preserved verbatim — the accession/barcode, leading zeros intact (D7).
    sample_id = _text(frame, _MEAS_SAMPLE_ID, _MEAS_SAMPLE_ID_WIDTH)
    loader_position = int(
        _digits_field(frame, _MEAS_LOADER_POSITION, _MEAS_LOADER_POSITION_WIDTH, "loader position")
    )
    blood_type_raw = frame[_MEAS_BLOOD_TYPE]
    blood_type = _decode_blood_type(blood_type_raw)
    timestamp = _normalize_completion_timestamp(frame)
    ifcc = _numeric(frame, _MEAS_IFCC, _MEAS_IFCC_WIDTH, "IFCC HbA1c")
    ratio_raw = _text(frame, _MEAS_HBA1C_RATIO, _MEAS_HBA1C_RATIO_WIDTH)
    adag_raw = _text(frame, _MEAS_ADAG, _MEAS_ADAG_WIDTH)
    declared = int(_digits_field(frame, _MEAS_CURVE_COUNT, _MEAS_CURVE_COUNT_WIDTH, "curve count"))
    if declared != curve_points:
        raise H9ParseError(
            f"H9 declared curve count {declared} != frame-length-derived {curve_points}"
        )
    error_raw = frame[_MEAS_CURVE_VALUES + (_CURVE_POINT_WIDTH * curve_points)]
    error_flag = _decode_error(error_raw)
    return H9Measurement(
        block=block,
        sample_id=sample_id,
        loader_position=loader_position,
        blood_type=blood_type,
        blood_type_raw=blood_type_raw,
        completion_timestamp=timestamp,
        ifcc=ifcc,
        hba1c_peak_area_ratio_raw=ratio_raw,
        adag_raw=adag_raw,
        curve_points=curve_points,
        error_flag=error_flag,
        error_raw=error_raw,
    )


def parse_qc_summary(frame: bytes) -> H9QcSummary:
    return H9QcSummary(
        low_lot=_text(frame, _QC_LOW_LOT, _QC_LOT_WIDTH),
        high_lot=_text(frame, _QC_HIGH_LOT, _QC_LOT_WIDTH),
        low_target=_numeric(frame, _QC_LOW_TARGET, _QC_TARGET_WIDTH, "low QC target"),
        high_target=_numeric(frame, _QC_HIGH_TARGET, _QC_TARGET_WIDTH, "high QC target"),
        low_target_sd=_numeric(frame, _QC_LOW_TARGET_SD, _QC_TARGET_SD_WIDTH, "low QC target SD"),
        high_target_sd=_numeric(frame, _QC_HIGH_TARGET_SD, _QC_TARGET_SD_WIDTH, "high QC target SD"),
        low_expiry=_parse_date(frame, _QC_LOW_EXPIRY, "low QC expiry"),
        high_expiry=_parse_date(frame, _QC_HIGH_EXPIRY, "high QC expiry"),
        tested_count=int(
            _digits_field(frame, _QC_TESTED_COUNT, _QC_TESTED_COUNT_WIDTH, "QC tested count")
        ),
        low_current=_numeric(frame, _QC_LOW_CURRENT, _QC_VALUE_WIDTH, "low QC current value"),
        high_current=_numeric(frame, _QC_HIGH_CURRENT, _QC_VALUE_WIDTH, "high QC current value"),
        low_average=_numeric(frame, _QC_LOW_AVERAGE, _QC_VALUE_WIDTH, "low QC average"),
        high_average=_numeric(frame, _QC_HIGH_AVERAGE, _QC_VALUE_WIDTH, "high QC average"),
        low_observed_sd=_numeric(frame, _QC_LOW_OBSERVED_SD, _QC_OBSERVED_SD_WIDTH, "low QC observed SD"),
        high_observed_sd=_numeric(frame, _QC_HIGH_OBSERVED_SD, _QC_OBSERVED_SD_WIDTH, "high QC observed SD"),
        low_cv=_numeric(frame, _QC_LOW_CV, _QC_CV_WIDTH, "low QC CV"),
        high_cv=_numeric(frame, _QC_HIGH_CV, _QC_CV_WIDTH, "high QC CV"),
    )


def parse_calibration_summary(frame: bytes) -> H9CalibrationSummary:
    sign = chr(frame[_CAL_OFFSET_B_SIGN])
    if sign not in ("+", "-"):
        raise H9ParseError(f"H9 calibration offset b sign must be '+' or '-', got '{sign}'")
    offset_b = _signed_numeric(sign, frame, _CAL_OFFSET_B, _CAL_OFFSET_B_WIDTH, "calibration offset b")
    return H9CalibrationSummary(
        low_lot=_text(frame, _CAL_LOW_LOT, _CAL_LOT_WIDTH),
        high_lot=_text(frame, _CAL_HIGH_LOT, _CAL_LOT_WIDTH),
        low_concentration=_numeric(
            frame, _CAL_LOW_CONCENTRATION, _CAL_CONCENTRATION_WIDTH, "low calibrator concentration"
        ),
        high_concentration=_numeric(
            frame, _CAL_HIGH_CONCENTRATION, _CAL_CONCENTRATION_WIDTH, "high calibrator concentration"
        ),
        factor_k=_numeric(frame, _CAL_FACTOR_K, _CAL_FACTOR_K_WIDTH, "calibration factor K"),
        offset_b=offset_b,
        calibration_date=_parse_date(frame, _CAL_DATE, "calibration date"),
    )


def _measurement_group(m: H9Measurement) -> H9SpecimenGroup:
    classification = classify(m.block, m.blood_type)
    if classification is Classification.CALIBRATION:
        row = H9Result(
            test_code=CALIBRATION_CODE,
            test_name="H9 calibrator measurement",
            value=(
                f"Calibrator measurement (block='{m.block}', blood-type={m.blood_type.value})"
                " — archive only, no patient Observation (KB §8, §12.1)"
            ),
            units=None,
            is_numeric=False,
            is_control=False,
            timestamp=m.completion_timestamp,
            lot_number=None,
            control_level=None,
            kind=KIND_CALIBRATION,
        )
        return H9SpecimenGroup(m.sample_id, (row,), RESULT_TYPE_CALIBRATION)

    is_control = classification is Classification.QC
    rows: list[H9Result] = [_ifcc_result_or_hold(m, is_control=is_control)]
    rows.extend(_error_notes(m))
    rows.extend(_withheld_holds(m))
    result_type = RESULT_TYPE_QC if is_control else RESULT_TYPE_PATIENT
    return H9SpecimenGroup(m.sample_id, tuple(rows), result_type)


def _ifcc_result_or_hold(m: H9Measurement, *, is_control: bool) -> H9Result:
    """Emit the IFCC HbA1c as an accept-ready RESULT only when the measurement carries
    no aspiration test-error. A flagged (e1/E2) measurement never becomes an
    Observation: the OpenELIS importer stages Observations without reading the
    DiagnosticReport warning conclusion, so an accept-ready RESULT beside an invisible
    warning could still be auto-accepted. Fail-closed, the IFCC is held as a visible
    anomaly carrying the raw value as non-clinical evidence, pending the validation-owner
    acceptance policy (KB §6.4; S7/LIS-235). Applies to patient and QC alike — an
    aspiration-flagged QC point is equally unreliable."""
    if m.error_flag is ErrorFlag.NONE:
        return _ifcc_result(m, is_control=is_control)
    return _note(
        IFCC_HELD_CODE,
        (
            f"HbA1c IFCC held: measurement carries aspiration test-error {m.error_flag.value}"
            f" (KB §6.4); the raw IFCC {m.ifcc} {UCUM_MMOL_MOL} is non-clinical evidence and"
            " must never be auto-accepted. Pending validation-owner acceptance policy (S7/LIS-235)."
        ),
        KIND_ANOMALY,
    )


def _ifcc_result(m: H9Measurement, *, is_control: bool) -> H9Result:
    return H9Result(
        test_code=LOINC_HBA1C_IFCC,
        test_name=HBA1C_IFCC_NAME,
        value=m.ifcc,
        units=UCUM_MMOL_MOL,
        is_numeric=True,
        is_control=is_control,
        timestamp=m.completion_timestamp,
        lot_number=None,
        control_level=None,
        kind=KIND_RESULT,
    )


def _error_notes(m: H9Measurement) -> list[H9Result]:
    if m.error_flag is ErrorFlag.NONE:
        return []
    if m.error_flag is ErrorFlag.E1_ASPIRATION_LOW:
        code, text = ERROR_E1_CODE, (
            "H9 test-error e1: sample aspiration too low (KB §6.4)"
            " — HbA1c flagged for review, not auto-accepted"
        )
    else:
        code, text = ERROR_E2_CODE, (
            "H9 test-error E2: sample aspiration too high (KB §6.4)"
            " — HbA1c flagged for review, not auto-accepted"
        )
    return [_note(code, text, KIND_WARNING)]


def _withheld_holds(m: H9Measurement) -> list[H9Result]:
    # NGSP and eAG are never emitted from the A0 wire in v1, but neither are they
    # silently dropped: each is a visible hold carrying the raw wire field as
    # explicitly non-clinical evidence (KB §6.5, §12.3, §8.3).
    ngsp = _note(
        NGSP_HOLD_CODE,
        (
            "NGSP % withheld in v1: the H9 A0 wire carries no calibrated NGSP field; the raw"
            f" HbA1c peak-area ratio ({m.hba1c_peak_area_ratio_raw.strip()}, non-clinical) must"
            " never be mapped as an NGSP result (KB §6.5, §8.3). Pending terminology + validation"
            " sign-off."
        ),
        KIND_ANOMALY,
    )
    eag = _note(
        EAG_HOLD_CODE,
        (
            f"eAG withheld in v1: the H9 A0 ADAG field ({m.adag_raw.strip()}, unit/config unknown)"
            " has no confirmed unit (KB §12.3, §8.3). Pending bench unit confirmation."
        ),
        KIND_ANOMALY,
    )
    return [ngsp, eag]


def _note(code: str, text: str, kind: str) -> H9Result:
    return H9Result(
        test_code=code,
        test_name="H9 note",
        value=text,
        units=None,
        is_numeric=False,
        is_control=False,
        timestamp=None,
        lot_number=None,
        control_level=None,
        kind=kind,
    )


def _qc_summary_group(qc: H9QcSummary) -> H9SpecimenGroup:
    # Low and high control levels are classified out of the patient stream and
    # routed through the QC gate (KB §12.1); lot + level travel with each row.
    # A QC summary carries no Sample SN, so the group has no patient accession.
    rows = (
        H9Result(
            test_code=LOINC_HBA1C_IFCC,
            test_name=f"{HBA1C_IFCC_NAME} (QC low)",
            value=qc.low_current,
            units=UCUM_MMOL_MOL,
            is_numeric=True,
            is_control=True,
            timestamp=None,
            lot_number=qc.low_lot,
            control_level=QC_LEVEL_LOW,
            kind=KIND_RESULT,
        ),
        H9Result(
            test_code=LOINC_HBA1C_IFCC,
            test_name=f"{HBA1C_IFCC_NAME} (QC high)",
            value=qc.high_current,
            units=UCUM_MMOL_MOL,
            is_numeric=True,
            is_control=True,
            timestamp=None,
            lot_number=qc.high_lot,
            control_level=QC_LEVEL_HIGH,
            kind=KIND_RESULT,
        ),
    )
    return H9SpecimenGroup(None, rows, RESULT_TYPE_QC)


def _calibration_summary_group(cal: H9CalibrationSummary) -> H9SpecimenGroup:
    # Calibration is archive-only: no Observation, ever (KB §8, §12.1).
    row = H9Result(
        test_code=CALIBRATION_CODE,
        test_name="H9 calibration summary",
        value=(
            f"Calibration summary — lots low={cal.low_lot}/high={cal.high_lot},"
            f" K={cal.factor_k}, b={cal.offset_b}, date={cal.calibration_date.isoformat()}"
            " — archive only, no patient Observation (KB §8, §12.1)"
        ),
        units=None,
        is_numeric=False,
        is_control=False,
        timestamp=None,
        lot_number=None,
        control_level=None,
        kind=KIND_CALIBRATION,
    )
    return H9SpecimenGroup(None, (row,), RESULT_TYPE_CALIBRATION)


def _text(frame: bytes, offset: int, width: int) -> str:
    return frame[offset : offset + width].decode("ascii")


def _digits_field(frame: bytes, offset: int, width: int, label: str) -> str:
    value = _text(frame, offset, width)
    if not (value and all("0" <= c <= "9" for c in value)):
        raise H9ParseError(f"H9 {label} is not all digits: '{value}'")
    return value


def _numeric(frame: bytes, offset: int, width: int, label: str) -> str:
    raw = _text(frame, offset, width)
    try:
        return _plain(Decimal(raw.strip()))
    except InvalidOperation as exc:
        raise H9ParseError(f"H9 {label} is not numeric: '{raw}'") from exc


def _signed_numeric(sign: str, frame: bytes, offset: int, width: int, label: str) -> str:
    raw = _text(frame, offset, width)
    try:
        return _plain(Decimal(sign + raw.strip()))
    except InvalidOperation as exc:
        raise H9ParseError(f"H9 {label} is not numeric: '{sign}{raw}'") from exc


def _plain(value: Decimal) -> str:
    # Plain (non-scientific) string, mirroring Java BigDecimal.toPlainString().
    return f"{value:f}"


def _decode_blood_type(raw: int) -> BloodType:
    value = _classification_value(raw)
    mapping = {
        0: BloodType.VENOUS,
        1: BloodType.DILUTED,
        2: BloodType.QC_MATERIAL,
        3: BloodType.CALIBRATOR,
    }
    if value not in mapping:
        raise H9ParseError(f"H9 blood-type code outside documented 0–3: 0x{raw:02X}")
    return mapping[value]


def _decode_error(raw: int) -> ErrorFlag:
    value = _error_value(raw)
    mapping = {
        0: ErrorFlag.NONE,
        1: ErrorFlag.E1_ASPIRATION_LOW,
        2: ErrorFlag.E2_ASPIRATION_HIGH,
    }
    if value not in mapping:
        raise H9ParseError(f"H9 test-error code outside documented 0–2: 0x{raw:02X}")
    return mapping[value]


def _classification_value(raw: int) -> int:
    if ord("0") <= raw <= ord("3"):
        return raw - ord("0")
    if 0x00 <= raw <= 0x03:
        return raw
    return -1


def _error_value(raw: int) -> int:
    if ord("0") <= raw <= ord("2"):
        return raw - ord("0")
    if 0x00 <= raw <= 0x02:
        return raw
    return -1


def _normalize_completion_timestamp(frame: bytes) -> str:
    raw = _digits_field(frame, _MEAS_DATETIME, _MEAS_DATETIME_WIDTH, "measurement date/time")
    year = 2000 + int(raw[0:2])
    month, day = int(raw[2:4]), int(raw[4:6])
    hour, minute, second = int(raw[6:8]), int(raw[8:10]), int(raw[10:12])
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise H9ParseError(f"H9 measurement carries an impossible date/time: {raw}") from exc
    return f"{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}{second:02d}"


def _parse_date(frame: bytes, offset: int, label: str) -> date:
    raw = _digits_field(frame, offset, _DATE_WIDTH, label)
    year = 2000 + int(raw[0:2])
    try:
        return date(year, int(raw[2:4]), int(raw[4:6]))
    except ValueError as exc:
        raise H9ParseError(f"H9 {label} is an impossible date: {raw}") from exc
