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
    duration_seconds: float = 0,
    bench: dict | None = None,
) -> ArchiveEntry:
    """Read a live serial stream passively and archive every received byte."""

    capture_started_at = _utc_now()
    deadline = time.monotonic() + duration_seconds if duration_seconds > 0 else None
    raw = bytearray()
    read_events: list[dict] = []
    archive_root = Path(outdir)
    archive_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending_stamp = capture_started_at.replace(":", "").replace("-", "")
    pending_path = archive_root / f".h9-pending-{pending_stamp}-{os.getpid()}.part"
    with open(pending_path, "xb") as pending:
        os.chmod(pending_path, 0o600)
        try:
            with open_serial_read_only(port) as fd:
                while True:
                    if frame_limit and len(analyze_stream(raw)["frames"]) >= frame_limit:
                        break
                    timeout = 0.25
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
    frames: list[dict] = []
    noise_byte_count = 0
    cursor = 0
    while cursor < len(raw):
        start = raw.find(bytes([STX]), cursor)
        if start < 0:
            noise_byte_count += len(raw) - cursor
            break
        noise_byte_count += start - cursor
        if start + 1 >= len(raw):
            noise_byte_count += len(raw) - start
            break

        block_type = chr(raw[start + 1]) if 0x20 <= raw[start + 1] < 0x7F else "?"
        first_etx = raw.find(bytes([ETX]), start + 2)
        end = first_etx
        candidate = first_etx
        while candidate >= 0:
            application_length = candidate - start - 1
            if _valid_application_length(block_type, application_length):
                end = candidate
                break
            candidate = raw.find(bytes([ETX]), candidate + 1)

        if end < 0:
            noise_byte_count += len(raw) - start
            break

        application_length = end - start - 1
        frame_bytes = raw[start : end + 1]
        frames.append(
            {
                "index": len(frames) + 1,
                "block_type": block_type,
                "start_offset": start,
                "end_offset_exclusive": end + 1,
                "frame_byte_count": len(frame_bytes),
                "application_length": application_length,
                "length_valid": _valid_application_length(block_type, application_length),
                "sha256": hashlib.sha256(frame_bytes).hexdigest(),
            }
        )
        cursor = end + 1

    return {"frames": frames, "noise_byte_count": noise_byte_count}


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
        "--outdir", default="./h9-capture", help="content-addressed archive root"
    )
    parser.add_argument(
        "--frames", type=int, default=0, help="stop after N structurally complete frames"
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
        _print_summary(raw)
        return 0

    if args.frames < 0 or args.duration < 0:
        _parser().error("--frames and --duration must be non-negative")
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
        args.outdir,
        frame_limit=args.frames,
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
