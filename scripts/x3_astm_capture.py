#!/usr/bin/env python3
"""MAGLUMI X3 native-ASTM bench-capture listener (LIS-75).

Capture-first bench tool. Stands up a TCP listener that plays the *host* side of
the SNIBE MAGLUMI X3's native `Online` ASTM E1394-97 interface: it answers the
analyzer's control-token handshake with ACKs so the analyzer's LIS indicator goes
green, and — unconditionally, regardless of whether the ACK cadence is perfect —
archives every received byte to disk so a wire capture survives even a mid-session
link drop.

Why this exists (see thoughts/references/SNIBE_MAGLUMI_X3_LIS_driver_knowledgebase.md):
  - The production bridge does NOT yet have a receive path that does the X3's
    simplified 4-point (ENQ/STX/ETX/EOT) ACK handshake. That path is LIS-174.
    This tool is deliberately standalone (stdlib only, no bridge, no Java) so the
    bench can get real X3 bytes on disk *before* LIS-174 is built — the capture
    then specifies LIS-174 rather than depending on it.
  - Getting raw bytes on disk is the deliverable. A live decode/summary is a bonus.

The analysis layer (framing classification, R-record timestamp field index, assay
codes / units / reference ranges, peer identity) is pure and importable, so it is
unit-tested against the KB §6 fixtures with no hardware (see test_x3_astm_capture.py).

Roles: the X3 is the TCP *client*; we are the listener/server. Port is
site-configurable — pick one and set it on the analyzer's `Online` screen too.

Usage:
  # Listen on :12010, archive into ./x3-capture, handle connections until Ctrl-C:
  python3 scripts/x3_astm_capture.py --port 12010 --outdir ./x3-capture

  # Documented simplified handshake is the default. If the site enabled
  # `Enable Checksum` and the simplified attempt desyncs after the first frame,
  # restart in classic-E1381 framed ACK mode:
  python3 scripts/x3_astm_capture.py --port 12010 --mode framed

  # Post-bench: re-run the analysis over an archived raw capture (no socket):
  python3 scripts/x3_astm_capture.py --replay ./x3-capture/raw-*.bin

Safety: capture-only. This tool never accepts QC as valid, never writes to the
analyzer, and does not answer order-download (Q) queries — order-download is
LIS-177 scope, out of scope for the LIS-75 capture.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import socket
import sys

# --- ASTM E1394 / E1381 control bytes ---------------------------------------
ENQ = 0x05
ACK = 0x06
STX = 0x02
ETX = 0x03
ETB = 0x17
EOT = 0x04
CR = 0x0D
LF = 0x0A
NAK = 0x15

_CTRL_NAME = {
    ENQ: "ENQ",
    ACK: "ACK",
    STX: "STX",
    ETX: "ETX",
    ETB: "ETB",
    EOT: "EOT",
    CR: "CR",
    LF: "LF",
    NAK: "NAK",
}

# Control tokens that get one ACK each in the documented simplified handshake.
_SIMPLIFIED_ACK_ON = {ENQ, STX, ETX, ETB, EOT}
# Classic E1381: establishment (ENQ), each frame terminator (ETX/ETB), no bare-STX
# ACK. EOT is harmless to ACK and kept for robustness.
_FRAMED_ACK_ON = {ENQ, ETX, ETB, EOT}

_DIGITS_ONLY = re.compile(r"^\d+$")


# --- pure analysis layer (no sockets; unit-tested) --------------------------
def iter_records(payload: bytes) -> list[str]:
    """Strip control-code framing and return the ASTM record lines as text.

    Tolerant of both the simplified envelope (ENQ STX ... ETX EOT) and a
    checksummed E1381 frame (STX <fn> ... ETX <cs><cs> CR LF): control bytes are
    dropped, a leading single-digit frame number right after STX is dropped, a
    trailing 2-char checksum before a record separator is dropped, and records
    are split on CR (0x0D). Never indexes by absolute offset.
    """
    text = payload.decode("latin-1")  # 1:1 byte->char, never raises
    # Drop framing control chars but keep CR as the record separator for now.
    for ctrl in (chr(ENQ), chr(STX), chr(ETX), chr(ETB), chr(EOT), chr(ACK), chr(NAK)):
        text = text.replace(ctrl, "")
    text = text.replace(chr(LF), "")  # LF (framed CRLF) is never a record sep here
    lines: list[str] = []
    for raw_line in text.split(chr(CR)):
        line = raw_line.strip()
        # A checksummed frame number is a single digit glued to the record type,
        # e.g. "1H|..." — strip a leading digit only when a record letter follows.
        m = re.match(r"^\d([A-Z]\|)", line)
        if m:
            line = line[1:]
        # Keep only real ASTM records (type letter + field delimiter). This drops
        # blank lines, a lone frame-number artifact, and a trailing 2-char hex
        # checksum remnant that a checksummed frame leaves after the final CR.
        if re.match(r"^[A-Za-z]\|", line):
            lines.append(line)
    return lines


def parse_record(line: str) -> dict:
    """Parse one ASTM record line into a structured dict.

    ASTM field N is 1-based; `fields[0]` is the record type letter. Components are
    `^`-separated, repeats `\\`-separated. We keep the raw split and expose the
    1-based `field(n)` helper via the returned `fields` list.
    """
    fields = line.split("|")
    rtype = fields[0][:1] if fields and fields[0] else ""
    rec = {"type": rtype, "fields": fields, "raw": line}
    if rtype == "H":
        rec["delimiters"] = fields[1] if len(fields) > 1 else ""
        rec["sender"] = _f(fields, 5)  # H-5 transmitter/analyzer name (stable)
        rec["receiver"] = _f(fields, 10)  # H-10 receiver/host name ("Lis")
        rec["version"] = _first_matching(fields, lambda v: "E1394" in v or "HL7" in v)
    elif rtype == "P":
        rec["patient_id"] = _f(fields, 4) or _f(fields, 3)
        rec["name"] = _f(fields, 6)
    elif rtype == "O":
        rec["sample_id"] = _f(fields, 3)
        rec["assays"] = _assays(_f(fields, 5))
    elif rtype == "R":
        rec["assay"] = _strip_caret(_f(fields, 3))
        rec["value"] = _f(fields, 4)
        rec["unit"] = _f(fields, 5)
        rec["ref_range"] = _f(fields, 6)
        rec["flag"] = _f(fields, 7)
        idx = find_result_timestamp_field(fields)
        rec["timestamp_field_index"] = idx
        rec["timestamp"] = _f(fields, idx) if idx else ""
    elif rtype == "Q":
        rec["sample_id"] = _f(fields, 3)  # keep the leading '^' component marker
        rec["request"] = _f(fields, 5)
    return rec


def _f(fields: list[str], one_based: int) -> str:
    """1-based ASTM field accessor, empty string if absent."""
    if one_based is None or one_based < 1 or one_based > len(fields):
        return ""
    return fields[one_based - 1].strip()


def _first_matching(fields: list[str], pred) -> str:
    for v in fields:
        if pred(v):
            return v.strip()
    return ""


def _strip_caret(v: str) -> str:
    """`^^^TSH` -> `TSH`; leaves a bare code untouched."""
    return v.split("^")[-1] if v else v


def _assays(o5: str) -> list[str]:
    """`^^^TSH\\^^^FT4` -> ['TSH', 'FT4']."""
    if not o5:
        return []
    return [_strip_caret(part) for part in o5.split("\\") if part]


def find_result_timestamp_field(fields: list[str]) -> int | None:
    """1-based index of the R-record completion timestamp, found by content.

    The vendor's byte examples drift (field 11 vs 12 vs 13 — KB §6.6), so we do
    NOT hard-index. We scan for the first field after R-7 (the abnormal flag) that
    is an all-numeric 8- or 14-digit ASTM timestamp. Returns None if none found.
    """
    for i in range(8, len(fields) + 1):  # 1-based, skip type..flag (fields 1-7)
        v = _f(fields, i)
        if v and _DIGITS_ONLY.match(v) and len(v) in (8, 14):
            return i
    return None


def classify_framing(raw: bytes) -> dict:
    """Classify the wire framing from raw captured bytes.

    Returns a dict with `mode` in {'simplified','checksummed','raw','unknown'} plus
    the boolean signals that drove it. The operator confirms against the analyzer's
    `Enable Checksum` toggle state (KB §4).
    """
    has_enq = ENQ in raw
    has_stx = STX in raw
    has_etx = ETX in raw or ETB in raw
    has_lf = LF in raw
    frame_number = _has_frame_number(raw)
    checksum = _has_checksum(raw)
    evidence: list[str] = []

    if not (has_enq or has_stx):
        # Payload begins straight at a record with no control establishment.
        starts_record = bool(re.match(r"^\s*[HPORQLC]\|", raw.decode("latin-1")))
        mode = "raw" if starts_record else "unknown"
        evidence.append("no ENQ/STX control establishment observed")
        return {
            "mode": mode,
            "has_enq": has_enq,
            "has_stx": has_stx,
            "has_etx": has_etx,
            "has_lf": has_lf,
            "frame_number": frame_number,
            "checksum": checksum,
            "evidence": evidence,
        }

    if frame_number or checksum or has_lf:
        mode = "checksummed"
        if frame_number:
            evidence.append("single-digit frame number follows STX")
        if checksum:
            evidence.append("2-char hex checksum follows ETX/ETB")
        if has_lf:
            evidence.append("LF (0x0A) present — CRLF frame terminators")
    else:
        mode = "simplified"
        evidence.append("bare STX (no frame number), no checksum, no LF")
    return {
        "mode": mode,
        "has_enq": has_enq,
        "has_stx": has_stx,
        "has_etx": has_etx,
        "has_lf": has_lf,
        "frame_number": frame_number,
        "checksum": checksum,
        "evidence": evidence,
    }


def _has_frame_number(raw: bytes) -> bool:
    """True if a byte right after an STX is an ASCII digit followed by a record letter."""
    for i, b in enumerate(raw[:-2]):
        if b == STX:
            nxt, nxt2 = raw[i + 1], raw[i + 2]
            if 0x30 <= nxt <= 0x37 and 0x41 <= nxt2 <= 0x5A:  # 0-7 then A-Z
                return True
    return False


def _has_checksum(raw: bytes) -> bool:
    """True if an ETX/ETB is followed by two ASCII hex chars (a checksum)."""
    hexset = set(b"0123456789ABCDEFabcdef")
    for i, b in enumerate(raw[:-2]):
        if b in (ETX, ETB):
            if raw[i + 1] in hexset and raw[i + 2] in hexset:
                return True
    return False


class CaptureAnalysis:
    """Structured findings from a captured X3 session — the bench evidence core."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.framing = classify_framing(raw)
        self.records = [parse_record(l) for l in iter_records(raw)]

    def header(self) -> dict | None:
        return next((r for r in self.records if r["type"] == "H"), None)

    def results(self) -> list[dict]:
        return [r for r in self.records if r["type"] == "R"]

    def orders(self) -> list[dict]:
        return [r for r in self.records if r["type"] == "O"]

    def queries(self) -> list[dict]:
        return [r for r in self.records if r["type"] == "Q"]

    def timestamp_field_indices(self) -> list[int]:
        return sorted({r["timestamp_field_index"] for r in self.results() if r["timestamp_field_index"]})

    def summary(self) -> str:
        lines: list[str] = []
        f = self.framing
        lines.append(f"Framing: {f['mode'].upper()}  ({'; '.join(f['evidence'])})")
        lines.append(
            f"  signals: ENQ={f['has_enq']} STX={f['has_stx']} ETX/ETB={f['has_etx']} "
            f"LF={f['has_lf']} frame#={f['frame_number']} checksum={f['checksum']}"
        )
        h = self.header()
        if h:
            lines.append(
                f"Identity (H): sender/Analyzer-ID={h['sender']!r}  "
                f"receiver/Host-ID={h['receiver']!r}  version={h['version']!r}  "
                f"delimiters={h['delimiters']!r}"
            )
        for o in self.orders():
            lines.append(f"Order (O): sample_id={o['sample_id']!r}  assays={o['assays']}")
        for q in self.queries():
            lines.append(f"Query (Q): sample_id={q['sample_id']!r} (preserve leading '^')  request={q['request']!r}")
            lines.append("  NOTE: order-download (Q->answer) is LIS-177 scope, not answered by this capture tool.")
        for r in self.results():
            lines.append(
                f"Result (R): {r['assay']}={r['value']} {r['unit']}  "
                f"range={r['ref_range']!r}  flag={r['flag']!r}  "
                f"ts={r['timestamp']!r} @ field {r['timestamp_field_index']}"
            )
        idxs = self.timestamp_field_indices()
        if idxs:
            lines.append(f"R-timestamp field position(s) observed: {idxs}  (AC4 — KB §6.6 off-by-one)")
        return "\n".join(lines)


# --- socket layer -----------------------------------------------------------
def _now() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="milliseconds")


def _hex(b: bytes) -> str:
    return b.hex(" ")


def _decode_chunk(chunk: bytes) -> str:
    """Human-readable rendering: control tokens named, printable text shown."""
    out: list[str] = []
    for byte in chunk:
        if byte in _CTRL_NAME:
            out.append(f"<{_CTRL_NAME[byte]}>")
        elif 0x20 <= byte < 0x7F:
            out.append(chr(byte))
        else:
            out.append(f"\\x{byte:02x}")
    return "".join(out)


class CaptureServer:
    def __init__(self, host: str, port: int, outdir: str, mode: str, once: bool):
        self.host = host
        self.port = port
        self.outdir = outdir
        self.mode = mode
        self.once = once
        self.ack_on = _FRAMED_ACK_ON if mode == "framed" else _SIMPLIFIED_ACK_ON
        os.makedirs(outdir, exist_ok=True)

    def serve(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(1)
            print(
                f"[{_now_iso()}] X3 ASTM capture listening on {self.host}:{self.port} "
                f"(ACK mode={self.mode}); archiving to {self.outdir}. Ctrl-C to stop.",
                flush=True,
            )
            while True:
                conn, peer = srv.accept()
                try:
                    self._handle(conn, peer)
                except Exception as exc:  # never let one session kill the listener
                    print(f"[{_now_iso()}] session error from {peer}: {exc}", file=sys.stderr, flush=True)
                finally:
                    conn.close()
                if self.once:
                    break

    def _handle(self, conn: socket.socket, peer) -> None:
        stamp = _now()
        raw_path = os.path.join(self.outdir, f"raw-{stamp}.bin")
        log_path = os.path.join(self.outdir, f"annotated-{stamp}.log")
        session = bytearray()
        print(f"[{_now_iso()}] connection from {peer} -> raw:{raw_path} log:{log_path}", flush=True)
        with open(raw_path, "ab") as raw_f, open(log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"# X3 ASTM capture session {stamp} from {peer}, ACK mode={self.mode}\n")
            log_f.flush()
            conn.settimeout(120)
            while True:
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    log_f.write(f"[{_now_iso()}] recv timeout — closing session\n")
                    break
                if not chunk:
                    log_f.write(f"[{_now_iso()}] peer closed connection\n")
                    break
                # Archive raw bytes FIRST and durably — this is the deliverable.
                raw_f.write(chunk)
                raw_f.flush()
                os.fsync(raw_f.fileno())
                session.extend(chunk)
                log_f.write(f"[{_now_iso()}] RECV {len(chunk)}B  hex={_hex(chunk)}\n")
                log_f.write(f"                 decode={_decode_chunk(chunk)}\n")
                log_f.flush()
                # ACK each control token that our mode acknowledges. Record content
                # is ASCII (never 0x02-0x05/0x17), so byte-scanning is unambiguous.
                saw_eot = False
                for byte in chunk:
                    if byte in self.ack_on:
                        conn.sendall(bytes([ACK]))
                        log_f.write(f"                 SEND <ACK> (for <{_CTRL_NAME.get(byte, hex(byte))}>)\n")
                        log_f.flush()
                    if byte == EOT:
                        saw_eot = True
                    if byte == NAK:
                        log_f.write(f"                 !! NAK received from analyzer\n")
                        log_f.flush()
                if saw_eot:
                    self._emit_summary(bytes(session), log_f)
                    # An X3 session ends at EOT; keep the socket for a possible next
                    # message but reset the per-message accumulator's summary point.
        # Connection closed: final summary if we never saw an explicit EOT.
        if session:
            self._emit_summary(bytes(session), None, path=log_path, force_console=True)

    def _emit_summary(self, session: bytes, log_f, path: str | None = None, force_console: bool = False) -> None:
        analysis = CaptureAnalysis(session)
        block = "\n".join(
            [
                "",
                "================= CAPTURE SUMMARY =================",
                analysis.summary(),
                "===================================================",
                "",
            ]
        )
        if log_f is not None:
            log_f.write(block + "\n")
            log_f.flush()
        elif path is not None:
            with open(path, "a", encoding="utf-8") as f:
                f.write(block + "\n")
        print(block, flush=True)


def _replay(path: str) -> int:
    with open(path, "rb") as f:
        raw = f.read()
    analysis = CaptureAnalysis(raw)
    print(f"# replay analysis of {path} ({len(raw)} bytes)\n")
    print(analysis.summary())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    p.add_argument("--port", type=int, default=12010, help="TCP port to listen on (default 12010)")
    p.add_argument("--outdir", default="./x3-capture", help="archive directory (default ./x3-capture)")
    p.add_argument(
        "--mode",
        choices=["simplified", "framed"],
        default="simplified",
        help="ACK cadence: 'simplified' (documented SNIBE: ACK ENQ/STX/ETX/EOT) or "
        "'framed' (classic E1381: ACK ENQ + frame terminators, not bare STX). "
        "Try simplified first; if the link drops after the first frame and the "
        "summary reports checksummed framing, restart with --mode framed.",
    )
    p.add_argument("--once", action="store_true", help="handle a single connection then exit")
    p.add_argument("--replay", metavar="RAWFILE", help="analyze an archived raw capture and exit (no socket)")
    args = p.parse_args(argv)

    if args.replay:
        return _replay(args.replay)

    server = CaptureServer(args.host, args.port, args.outdir, args.mode, args.once)
    try:
        server.serve()
    except KeyboardInterrupt:
        print(f"\n[{_now_iso()}] stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
