#!/usr/bin/env python3
"""Passive Lifotronic H9 RS-232 capture and exact-byte archive (LIS-229).

The capture path is deliberately receive-only. Live serial support opens the port
read-only and this module contains no protocol response or acknowledgement path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import termios
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_SIDECAR_VERSION = 1
STX = 0x02
ETX = 0x03


class ArchiveIntegrityError(RuntimeError):
    """Stored bytes do not match the digest naming their archive entry."""


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@contextmanager
def open_serial_read_only(port: str):
    """Open and configure a POSIX serial device as 115200 8N1, read-only."""

    flags = os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK
    fd = os.open(port, flags)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0  # no input translations or software flow control
        attrs[1] = 0  # the descriptor is read-only; keep output processing disabled
        attrs[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB)
        if hasattr(termios, "CRTSCTS"):
            attrs[2] &= ~termios.CRTSCTS
        attrs[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
        attrs[3] = 0  # raw/non-canonical, no echo
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        yield fd
    finally:
        os.close(fd)


def capture_serial(
    port: str,
    outdir: str | os.PathLike[str],
    *,
    frame_limit: int = 0,
    settle_seconds: float = 1.0,
    duration_seconds: float = 0,
    bench: dict | None = None,
) -> ArchiveEntry:
    """Read a live serial stream passively and archive every received byte.

    A reached frame limit is finalized only after ``settle_seconds`` of line
    quiet. The quiet window prevents a structurally valid in-frame ETX prefix
    from ending the capture before a later tail arrives.
    """

    if frame_limit < 0 or settle_seconds < 0 or duration_seconds < 0:
        raise ValueError("frame_limit, settle_seconds, and duration_seconds must be non-negative")

    capture_started_at = _utc_now()
    deadline = time.monotonic() + duration_seconds if duration_seconds > 0 else None
    raw = bytearray()
    read_events: list[dict] = []
    last_data_at: float | None = None
    archive_root = Path(outdir)
    archive_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending_stamp = capture_started_at.replace(":", "").replace("-", "")
    pending_path = archive_root / f".h9-pending-{pending_stamp}-{os.getpid()}.part"
    with open(pending_path, "xb") as pending:
        os.chmod(pending_path, 0o600)
        try:
            with open_serial_read_only(port) as fd:
                while True:
                    quiet_remaining: float | None = None
                    if (
                        frame_limit
                        and last_data_at is not None
                        and len(analyze_stream(raw)["frames"]) >= frame_limit
                    ):
                        quiet_remaining = settle_seconds - (time.monotonic() - last_data_at)
                        if quiet_remaining <= 0:
                            break
                    timeout = 0.25
                    if quiet_remaining is not None:
                        timeout = min(timeout, quiet_remaining)
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        timeout = min(timeout, remaining)
                    readable, _, _ = select.select([fd], [], [], timeout)
                    if not readable:
                        continue
                    try:
                        chunk = os.read(fd, 4096)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        break
                    offset = len(raw)
                    pending.write(chunk)
                    pending.flush()
                    os.fsync(pending.fileno())
                    raw.extend(chunk)
                    last_data_at = time.monotonic()
                    read_events.append(
                        {
                            "received_at": _utc_now(),
                            "offset": offset,
                            "byte_count": len(chunk),
                        }
                    )
        except KeyboardInterrupt:
            pass

    entry = archive_capture(
        raw,
        outdir,
        capture_started_at=capture_started_at,
        capture_ended_at=_utc_now(),
        source=port,
        read_events=read_events,
        bench={} if bench is None else bench,
    )
    pending_path.unlink()
    return entry


def _valid_application_length(block_type: str, length: int) -> bool:
    if block_type == "S":
        return length >= 120 and (length - 120) % 6 == 0
    if block_type == "Q":
        return length == 109
    if block_type == "C":
        return length == 64
    return False


def analyze_stream(raw: bytes) -> dict:
    """Locate H9 frames without changing or discarding the archived stream.

    Manual-A0 application lengths exclude STX/ETX: measurements are ``120+6N``
    bytes, QC summaries are 109 bytes, and calibration summaries are 64 bytes.
    """

    raw = bytes(raw)
    byte_count = len(raw)
    scores: list[tuple[int, int]] = [(0, 0)] * (byte_count + 1)
    choices: list[int | None] = [None] * byte_count

    # Dynamic programming chooses a non-overlapping set with the most valid
    # frames, then the most covered bytes. This prefers a longer valid S frame
    # over an embedded ETX at a shorter, coincidentally valid 120+6N prefix,
    # while still preferring two concatenated valid frames over one that swallows
    # both. Bytes outside the chosen frames remain explicit noise in the summary.
    for start in range(byte_count - 1, -1, -1):
        best_score = scores[start + 1]
        best_end: int | None = None
        if raw[start] == STX and start + 1 < byte_count:
            block_type = chr(raw[start + 1])
            if block_type == "S":
                lengths = range(120, byte_count - start - 1, 6)
            elif block_type == "Q":
                lengths = (109,)
            elif block_type == "C":
                lengths = (64,)
            else:
                lengths = ()
            for application_length in lengths:
                end = start + 1 + application_length
                if end >= byte_count or raw[end] != ETX:
                    continue
                tail_score = scores[end + 1]
                candidate_score = (
                    tail_score[0] + 1,
                    tail_score[1] + application_length + 2,
                )
                if candidate_score > best_score:
                    best_score = candidate_score
                    best_end = end
        scores[start] = best_score
        choices[start] = best_end

    frames: list[dict] = []
    cursor = 0
    while cursor < byte_count:
        end = choices[cursor]
        if end is None:
            cursor += 1
            continue
        application_length = end - cursor - 1
        frame_bytes = raw[cursor : end + 1]
        frames.append(
            {
                "index": len(frames) + 1,
                "block_type": chr(raw[cursor + 1]),
                "start_offset": cursor,
                "end_offset_exclusive": end + 1,
                "frame_byte_count": len(frame_bytes),
                "application_length": application_length,
                "length_valid": True,
                "sha256": hashlib.sha256(frame_bytes).hexdigest(),
            }
        )
        cursor = end + 1

    framed_byte_count = sum(frame["frame_byte_count"] for frame in frames)
    return {
        "frames": frames,
        "noise_byte_count": byte_count - framed_byte_count,
    }


@dataclass(frozen=True)
class ArchiveEntry:
    """Paths and digest for one content-addressed raw capture."""

    digest: str
    raw_path: Path
    sidecar_path: Path


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "wb") as output:
        os.chmod(temporary, 0o600)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _load_and_validate_sidecar(path: Path, raw: bytes, digest: str) -> dict:
    """Load required provenance and verify its raw-bound structural fields."""

    try:
        sidecar = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveIntegrityError(f"invalid archive sidecar {path}: {exc}") from exc
    if not isinstance(sidecar, dict):
        raise ArchiveIntegrityError(f"invalid archive sidecar {path}: root must be an object")

    required_types = {
        "v": int,
        "digest": str,
        "byte_count": int,
        "received_at": str,
        "capture_started_at": str,
        "capture_ended_at": str,
        "source": str,
        "protocol": str,
        "transport": str,
        "serial": dict,
        "bench": dict,
        "read_events": list,
        "frames": list,
        "noise_byte_count": int,
    }
    for key, expected_type in required_types.items():
        if not isinstance(sidecar.get(key), expected_type):
            raise ArchiveIntegrityError(
                f"invalid archive sidecar {path}: {key!r} must be {expected_type.__name__}"
            )
    if sidecar["v"] != _SIDECAR_VERSION:
        raise ArchiveIntegrityError(
            f"unsupported archive sidecar version {sidecar['v']} in {path}"
        )
    if sidecar["digest"] != digest or sidecar["byte_count"] != len(raw):
        raise ArchiveIntegrityError(
            f"archive sidecar {path} does not match raw digest/byte count"
        )
    analysis = analyze_stream(raw)
    if (
        sidecar["frames"] != analysis["frames"]
        or sidecar["noise_byte_count"] != analysis["noise_byte_count"]
    ):
        raise ArchiveIntegrityError(
            f"archive sidecar {path} frame map does not match raw bytes"
        )
    return sidecar


def archive_capture(
    raw: bytes,
    outdir: str | os.PathLike[str],
    *,
    capture_started_at: str,
    capture_ended_at: str,
    source: str,
    read_events: list[dict],
    bench: dict,
) -> ArchiveEntry:
    """Archive a raw serial stream verbatim with its SHA-256 JSON sidecar."""

    raw = bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    shard = Path(outdir) / digest[:2]
    raw_path = shard / f"{digest}.msg"
    sidecar_path = shard / f"{digest}.json"
    if raw_path.is_file():
        actual = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if actual != digest:
            raise ArchiveIntegrityError(
                f"archive corruption: bytes under {digest} hash to {actual}"
            )
        if sidecar_path.is_file():
            _load_and_validate_sidecar(sidecar_path, raw, digest)
            return ArchiveEntry(digest=digest, raw_path=raw_path, sidecar_path=sidecar_path)

    analysis = analyze_stream(raw)
    sidecar = {
        "v": _SIDECAR_VERSION,
        "digest": digest,
        "byte_count": len(raw),
        "received_at": read_events[0]["received_at"] if read_events else capture_started_at,
        "capture_started_at": capture_started_at,
        "capture_ended_at": capture_ended_at,
        "source": source,
        "protocol": "LIFOTRONIC_H9",
        "transport": "SERIAL",
        "framing": "STX-S/Q/C-ETX",
        "encoding": "binary",
        "serial": {
            "baud": 115200,
            "data_bits": 8,
            "parity": "none",
            "stop_bits": 1,
            "flow_control": "none",
            "open_mode": "read-only",
        },
        "bench": dict(bench),
        "read_events": list(read_events),
        "frames": analysis["frames"],
        "noise_byte_count": analysis["noise_byte_count"],
    }
    _write_atomic(raw_path, raw)
    _write_atomic(
        sidecar_path,
        json.dumps(sidecar, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )
    return ArchiveEntry(digest=digest, raw_path=raw_path, sidecar_path=sidecar_path)


def _print_summary(raw: bytes) -> None:
    digest = hashlib.sha256(raw).hexdigest()
    analysis = analyze_stream(raw)
    print(f"SHA-256: {digest}")
    print(f"Raw bytes: {len(raw)}")
    print(
        f"Frames: {len(analysis['frames'])}; "
        f"bytes outside frames: {analysis['noise_byte_count']}"
    )
    for frame in analysis["frames"]:
        valid = "yes" if frame["length_valid"] else "NO"
        print(
            f"  #{frame['index']} {frame['block_type']} "
            f"application={frame['application_length']}B valid={valid} "
            f"offsets={frame['start_offset']}..{frame['end_offset_exclusive'] - 1} "
            f"sha256={frame['sha256']}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Passive read-only Lifotronic H9 serial capture (115200 8N1, no flow control)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--port", help="POSIX serial device, preferably /dev/serial/by-id/..."
    )
    source.add_argument(
        "--replay", help="analyze an existing raw .msg/.bin capture offline"
    )
    parser.add_argument(
        "--outdir",
        help="required for live capture; controlled archive directory outside the repo",
    )
    parser.add_argument(
        "--frames", type=int, default=0, help="stop after N structurally complete frames"
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=1.0,
        help="quiet seconds after --frames is reached before finalizing (default: 1)",
    )
    parser.add_argument(
        "--duration", type=float, default=0, help="stop after N seconds (0 = Ctrl-C)"
    )
    parser.add_argument("--model", default="Lifotronic H9")
    parser.add_argument("--serial-number", default="")
    parser.add_argument("--firmware", default="")
    parser.add_argument("--host-mode", default="")
    parser.add_argument("--connector", default="", help="observed DB-9 gender/pinout note")
    parser.add_argument("--cable", default="", help="cable/adapter inventory note")
    parser.add_argument("--operator", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.replay:
        replay_path = Path(args.replay)
        raw = replay_path.read_bytes()
        print(f"Replay: {args.replay}")
        actual_digest = hashlib.sha256(raw).hexdigest()
        expected_digest = replay_path.stem.lower()
        is_content_addressed = (
            replay_path.suffix == ".msg"
            and len(expected_digest) == 64
            and all(char in "0123456789abcdef" for char in expected_digest)
        )
        if is_content_addressed and actual_digest != expected_digest:
            print(
                f"INTEGRITY ERROR: archive name expects {expected_digest}, "
                f"but bytes hash to {actual_digest}"
            )
            return 1
        if is_content_addressed:
            sidecar_path = replay_path.with_suffix(".json")
            if not sidecar_path.is_file():
                print(f"INTEGRITY ERROR: archive sidecar is missing: {sidecar_path}")
                return 1
            try:
                _load_and_validate_sidecar(sidecar_path, raw, actual_digest)
            except ArchiveIntegrityError as exc:
                print(f"INTEGRITY ERROR: {exc}")
                return 1
        _print_summary(raw)
        return 0

    if args.frames < 0 or args.settle < 0 or args.duration < 0:
        _parser().error("--frames, --settle, and --duration must be non-negative")
    if not args.outdir:
        _parser().error("--outdir is required for live capture")
    archive_root = Path(args.outdir).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[1]
    if archive_root == repository_root or repository_root in archive_root.parents:
        _parser().error("--outdir must be outside the repository checkout")
    bench = {
        "model": args.model,
        "serial_number": args.serial_number,
        "firmware": args.firmware,
        "host_mode": args.host_mode,
        "connector": args.connector,
        "cable": args.cable,
        "operator": args.operator,
    }
    print(
        f"Passive H9 capture from {args.port}: 115200 8N1, no flow control, "
        "read-only descriptor; press Ctrl-C to finalize."
    )
    print("Safety: use an RX+GND-only passive lead; do not connect the host TX conductor.")
    entry = capture_serial(
        args.port,
        archive_root,
        frame_limit=args.frames,
        settle_seconds=args.settle,
        duration_seconds=args.duration,
        bench=bench,
    )
    raw = entry.raw_path.read_bytes()
    _print_summary(raw)
    print(f"Raw archive: {entry.raw_path}")
    print(f"JSON sidecar: {entry.sidecar_path}")
    if not raw:
        print("No bytes were received; this does not satisfy the bench capture gate.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
