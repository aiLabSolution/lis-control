#!/usr/bin/env python3
"""EDAN H60S HL7/MLLP host-query bench-capture listener (LIS-181).

Capture-first bench tool for the H60S *bidirectional* (host-query) leg. It stands
up a TCP listener that plays the *host*/LIS side of the EDAN H60S's MLLP interface
and — unconditionally, whether or not it answers anything — archives every received
byte to disk so a wire capture survives even a mid-session link drop. It then
de-frames the MLLP envelope, parses the HL7 v2 segments, and prints the field
positions that the H60S bench must confirm before any host-query implementation is
trusted.

Why this exists (see docs/runbooks/edan-h60s-host-query-bench.md and the vendor
manual EDAN/H60S/LIS/LIS-Communication-Protocol-h60.pdf, v1.1 2022-07-29):
  - LIS-20 (northbound bench, PR #91) proved the physical H60S speaks the EDANLAB /
    H90-family profile: MSH-3=`H60`, MSH-4=`EDANLAB`, analyte name in OBX-4 (not
    OBX-3), sample id in OBR-2, patient number in PID-2. The pre-bench *synthetic*
    host-query fixture (edge/sim/fixtures/edan-h60s-host-query-qry-r02) still
    encodes the refuted clean-HL7 layout (MSH-3=`H60S`, MSH-4=`EDAN`, subject in
    QRD-8). So the query wire format is a characterize-first UNKNOWN, not a given.
  - The vendor manual's QRD field table and its worked example DISAGREE about which
    QRD field carries the query subject (QRD-8 patient# / QRD-9 sample# / QRD-10
    "used as sample IDs on H60-series devices"), and the manual ships NO worked
    QRY/ORF example. Only a real capture settles it. This tool captures it.
  - This is deliberately standalone (stdlib only, no bridge, no Java) so the bench
    can get real H60S query bytes on disk *before* the shared host-query responder
    (LIS-149 / LIS-118) is green. The capture then specifies the H60S profile branch
    rather than depending on it.

Roles (manual §2.1 / §1.2.1.3): the H60S is the TCP *client*; we listen/serve. The
analyzer connects and sends its QRY^R02 unprompted, so pure capture needs no
response. Default MLLP port is 7999 (ADR-0015 / EDAN H60-series LIS training doc;
the analyzer's LIS port is set per manual Annex 2), site-configurable.

Scope / safety: CAPTURE-ONLY. This tool never answers a host-query with an ORF^R04
worklist — building the worklist means resolving an OpenELIS pending order, which is
LIS-149 / LIS-118 scope and is intentionally NOT done here. With --ack it may return
a minimal HL7 ACK (MSA|AA, echoing MSH-10) purely to keep the analyzer's link alive
and observe its behaviour; that is an acknowledgement, NOT a worklist answer, and the
analyzer is expected to report "no orders" or wait for an ORF that never comes. The
QRY capture is the deliverable regardless.

The analysis layer (MLLP de-framing, HL7 segment parsing, EDANLAB-vs-clean layout
classification, QRD subject-field candidates) is pure and importable, so it is
unit-tested against the sim fixtures and the manual's verbatim examples with no
hardware (see test_h60s_mllp_capture.py).

Usage:
  # Listen on :7999, archive into ./h60s-capture, capture-only, until Ctrl-C:
  python3 scripts/h60s_mllp_capture.py --port 7999 --outdir ./h60s-capture

  # Also return a minimal HL7 ACK (MSA|AA) to keep the link alive / observe retries
  # (still NOT an ORF worklist):
  python3 scripts/h60s_mllp_capture.py --port 7999 --ack

  # Post-bench: re-run the analysis over an archived raw capture (no socket):
  python3 scripts/h60s_mllp_capture.py --replay ./h60s-capture/raw-*.bin
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import socket
import sys

# --- MLLP control bytes (manual §1.2.1.2: 0x0B <HL7> 0x1C 0x0D) --------------
SB = 0x0B  # start block  <VT>
EB = 0x1C  # end block     <FS>
CR = 0x0D  # carriage return — MLLP frame terminator AND HL7 segment separator
LF = 0x0A

_CTRL_NAME = {SB: "SB", EB: "EB", CR: "CR", LF: "LF"}

# EDAN H90-family / EDANLAB profile marker (manual §3.2.1: MSH-4 fixed "EDANLAB").
_EDANLAB = "EDANLAB"


# --- pure analysis layer (no sockets; unit-tested) --------------------------
def deframe(raw: bytes) -> list[bytes]:
    """Return the application payloads carried by MLLP frames in ``raw``.

    An MLLP frame is ``SB payload EB CR`` (manual §1.2.1.2). We split on the SB
    (0x0B) start-block and, within each, take everything up to the EB (0x1C); the
    trailing CR after EB is the frame terminator and is dropped with the EB. This
    is tolerant of a capture that begins mid-frame or omits the final EB (a link
    drop): any leading bytes before the first SB are ignored, and an unterminated
    tail after the last SB is still returned so a truncated query is not lost.

    If the capture carries NO SB at all (raw HL7 with no MLLP framing), the whole
    buffer is returned as a single payload so the parser still runs.
    """
    if SB not in raw:
        return [raw] if raw.strip() else []
    payloads: list[bytes] = []
    # Each SB opens a frame; the payload runs to the next EB (or end of buffer).
    for chunk in raw.split(bytes([SB]))[1:]:
        eb = chunk.find(EB)
        payload = chunk[:eb] if eb != -1 else chunk
        payload = payload.rstrip(bytes([CR, LF]))
        if payload.strip():
            payloads.append(payload)
    return payloads


def split_segments(payload: bytes) -> list[str]:
    """Split an HL7 payload into segment strings on CR (0x0D), tolerant of CRLF.

    Decodes as UTF-8 (manual §3.1 / MSH-18) with a latin-1 fallback so a capture
    with unexpected bytes never raises. Blank segments are dropped.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    return [seg.strip() for seg in text.split("\r") if seg.strip()]


class Segment:
    """One parsed HL7 segment with 1-based field access.

    HL7's MSH is special: MSH-1 IS the field separator, so a naive ``split('|')``
    puts MSH-2 (encoding chars) at list index 1 and MSH-3 at index 2. We hide that
    offset in ``field()`` so callers can ask for MSH-3 / MSH-4 by their real number.
    """

    def __init__(self, line: str):
        self.raw = line
        self.parts = line.split("|")
        self.type = self.parts[0][:3] if self.parts and self.parts[0] else ""
        self.is_msh = self.type == "MSH"

    def field(self, n: int) -> str:
        """1-based HL7 field accessor; empty string if absent.

        For MSH, MSH-1 is the field separator '|' and MSH-n (n>=2) lives at
        ``parts[n-1]``. For every other segment, field-n lives at ``parts[n]``.
        """
        if n < 1:
            return ""
        if self.is_msh:
            if n == 1:
                return "|"
            idx = n - 1
        else:
            idx = n
        return self.parts[idx].strip() if 0 <= idx < len(self.parts) else ""


def classify_layout(msh: Segment | None) -> dict:
    """Classify the analyzer's HL7 field layout from the MSH segment.

    Returns ``profile`` in {'edanlab','clean','unknown'} plus the evidence. The
    EDANLAB / H90-family profile (manual §3.2.1, confirmed by LIS-20) is signalled
    by MSH-4 == 'EDANLAB'. The refuted pre-bench 'clean' layout used MSH-4 == 'EDAN'
    with an 'H60S' sending app. The operator confirms against the analyzer nameplate
    and firmware; a mismatch here vs the northbound ORU capture is a finding, not a
    silent assumption.
    """
    if msh is None:
        return {"profile": "unknown", "evidence": ["no MSH segment in payload"],
                "sending_app": "", "sending_facility": ""}
    app = msh.field(3)
    facility = msh.field(4)
    evidence: list[str] = [f"MSH-3(sending app)={app!r}", f"MSH-4(sending facility)={facility!r}"]
    if facility.upper() == _EDANLAB:
        profile = "edanlab"
        evidence.append("MSH-4=EDANLAB -> EDAN H90-family/EDANLAB profile (LIS-20 confirmed)")
    elif facility.upper() == "EDAN":
        profile = "clean"
        evidence.append("MSH-4=EDAN -> pre-bench clean-HL7 layout (REFUTED northbound by LIS-20)")
    else:
        profile = "unknown"
        evidence.append("MSH-4 is neither EDANLAB nor EDAN -> record verbatim, do not assume")
    return {"profile": profile, "evidence": evidence,
            "sending_app": app, "sending_facility": facility}


def qrd_subject_candidates(qrd: Segment) -> dict:
    """Return every QRD field that the manual implicates as the query subject.

    The vendor manual (§3.2.6) is internally inconsistent about which QRD field
    carries the barcode/sample/patient the analyzer is asking about:
      - QRD-8  Who Subject Filter   -> patient number (matched first)
      - QRD-9  What Subject Filter  -> sample number
      - QRD-10 What Department Data -> "used as sample IDs on H60-series devices"
    and the sim fixtures put the subject in QRD-8 with RES/OTH in QRD-9. So we do
    NOT pick a winner — we surface all three (plus the QRD-4 query id the answer
    must echo) and leave the tiebreak to the bench capture.
    """
    return {
        "query_id_qrd4": qrd.field(4),
        "who_subject_qrd8": qrd.field(8),
        "what_subject_qrd9": qrd.field(9),
        "dept_data_code_qrd10": qrd.field(10),
        "results_level_qrd12": qrd.field(12),
    }


class CaptureAnalysis:
    """Structured findings from a captured H60S session — the bench evidence core.

    One capture may carry several MLLP frames (e.g. a connection test then a query),
    so ``segments`` is the flattened segment list across all frames in ``raw``.
    """

    def __init__(self, raw: bytes):
        self.raw = raw
        self.frames = deframe(raw)
        self.segments: list[Segment] = []
        for payload in self.frames:
            self.segments.extend(Segment(s) for s in split_segments(payload))

    def _first(self, seg_type: str) -> Segment | None:
        return next((s for s in self.segments if s.type == seg_type), None)

    def _all(self, seg_type: str) -> list[Segment]:
        return [s for s in self.segments if s.type == seg_type]

    def msh(self) -> Segment | None:
        return self._first("MSH")

    def message_type(self) -> str:
        m = self.msh()
        return m.field(9) if m else ""

    def control_id(self) -> str:
        m = self.msh()
        return m.field(10) if m else ""

    def layout(self) -> dict:
        return classify_layout(self.msh())

    def query_defs(self) -> list[Segment]:
        return self._all("QRD")

    def observations(self) -> list[Segment]:
        return self._all("OBX")

    def summary(self) -> str:
        lines: list[str] = []
        if not self.frames:
            return "No HL7 payload recovered from capture (0 MLLP frames)."
        lines.append(f"MLLP frames recovered: {len(self.frames)}  segments: {len(self.segments)}")
        m = self.msh()
        if m:
            lines.append(
                f"MSH: type={m.field(9)!r} controlId(MSH-10)={m.field(10)!r} "
                f"version(MSH-12)={m.field(12)!r} appAckType(MSH-16)={m.field(16)!r} "
                f"charset(MSH-18)={m.field(18)!r}"
            )
        lay = self.layout()
        lines.append(f"LAYOUT verdict: {lay['profile'].upper()}  ({'; '.join(lay['evidence'])})")

        mtype = self.message_type()
        if mtype.startswith("QRY") or self.query_defs():
            for qrd in self.query_defs():
                cand = qrd_subject_candidates(qrd)
                lines.append(
                    "QRY/QRD subject (which field holds the barcode is UNCONFIRMED — manual "
                    "table vs example disagree):"
                )
                lines.append(f"    QRD-4 query id (answer must echo) = {cand['query_id_qrd4']!r}")
                lines.append(f"    QRD-8 Who/patient-number           = {cand['who_subject_qrd8']!r}")
                lines.append(f"    QRD-9 What/sample-number           = {cand['what_subject_qrd9']!r}")
                lines.append(f"    QRD-10 dept-data / H60 sample id   = {cand['dept_data_code_qrd10']!r}")
                lines.append(f"    QRD-12 results level               = {cand['results_level_qrd12']!r}")
            lines.append(
                "    NOTE: answering with an ORF^R04 worklist requires resolving an OpenELIS "
                "pending order — that is LIS-149 / LIS-118 scope, NOT done by this capture tool."
            )
        for qrf in self._all("QRF"):
            lines.append(f"QRF: {qrf.raw!r}  (query filter — refines QRD; record verbatim)")
        for pid in self._all("PID"):
            lines.append(
                f"PID: patientId(PID-2)={pid.field(2)!r} age^unit(PID-3)={pid.field(3)!r} "
                f"name(PID-5)={pid.field(5)!r}"
            )
        for obr in self._all("OBR"):
            lines.append(f"OBR: sampleId(OBR-2)={obr.field(2)!r} serviceId(OBR-4)={obr.field(4)!r}")
        obx = self.observations()
        if obx:
            lines.append(f"OBX rows: {len(obx)} (analyte in OBX-4 per EDANLAB profile)")
            for o in obx[:8]:
                lines.append(
                    f"    OBX suspect(OBX-3)={o.field(3)!r} analyte(OBX-4)={o.field(4)!r} "
                    f"value(OBX-5)={o.field(5)!r} units(OBX-6)={o.field(6)!r} status(OBX-11)={o.field(11)!r}"
                )
            if len(obx) > 8:
                lines.append(f"    ... {len(obx) - 8} more OBX rows")
        for msa in self._all("MSA"):
            lines.append(f"MSA: ackCode(MSA-1)={msa.field(1)!r} echoControlId(MSA-2)={msa.field(2)!r}")
        return "\n".join(lines)


# --- ACK builder (minimal; NOT an ORF worklist) -----------------------------
def build_ack(inbound_msh: Segment | None, control_id: str) -> bytes:
    """Build a minimal MLLP-framed HL7 ACK (MSA|AA) echoing the inbound MSH-10.

    Per the manual's worked example the LIS ACK swaps the analyzer identity into
    the receiving-application/facility fields (MSH-5/6) and echoes the inbound
    control id in MSA-2. This is an acknowledgement ONLY — it carries no ORF^R04
    order rows. It exists so `--ack` can keep the analyzer's link alive and let the
    bench observe retry/timeout behaviour; it never answers a host-query.
    """
    recv_app = inbound_msh.field(3) if inbound_msh else "H60"
    recv_fac = inbound_msh.field(4) if inbound_msh else _EDANLAB
    echo = inbound_msh.field(10) if inbound_msh else ""
    msh = f"MSH|^~\\&|LIS|LAB|{recv_app}|{recv_fac}|{_now_hl7()}||ACK|{control_id}|P|2.4"
    msa = f"MSA|AA|{echo}"
    body = (msh + "\r" + msa + "\r").encode("utf-8")
    return bytes([SB]) + body + bytes([EB, CR])


# --- socket layer -----------------------------------------------------------
def _now() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="milliseconds")


def _now_hl7() -> str:
    return _dt.datetime.now().strftime("%Y%m%d%H%M%S")


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


class MllpCaptureServer:
    def __init__(self, host: str, port: int, outdir: str, send_ack: bool, once: bool):
        self.host = host
        self.port = port
        self.outdir = outdir
        self.send_ack = send_ack
        self.once = once
        self._seq = 0  # monotonic per-connection counter for unique archive names
        os.makedirs(outdir, exist_ok=True)

    def serve(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(1)
            print(
                f"[{_now_iso()}] H60S MLLP capture listening on {self.host}:{self.port} "
                f"(ack={'on' if self.send_ack else 'off, capture-only'}); "
                f"archiving to {self.outdir}. Ctrl-C to stop.",
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
        self._seq += 1
        stamp = f"{_now()}-{self._seq:03d}"
        raw_path = os.path.join(self.outdir, f"raw-{stamp}.bin")
        log_path = os.path.join(self.outdir, f"annotated-{stamp}.log")
        buf = bytearray()  # bytes not yet split into a completed frame
        print(f"[{_now_iso()}] connection from {peer} -> raw:{raw_path} log:{log_path}", flush=True)
        with open(raw_path, "ab") as raw_f, open(log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"# H60S MLLP capture session {stamp} from {peer}, ack={self.send_ack}\n")
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
                buf.extend(chunk)
                log_f.write(f"[{_now_iso()}] RECV {len(chunk)}B  hex={_hex(chunk)}\n")
                log_f.write(f"                 decode={_decode_chunk(chunk)}\n")
                log_f.flush()
                # A complete MLLP frame ends with EB CR (0x1C 0x0D). Handle each
                # completed frame, leaving any partial tail in the buffer.
                while True:
                    end = buf.find(bytes([EB, CR]))
                    if end == -1:
                        break
                    frame = bytes(buf[: end + 2])
                    del buf[: end + 2]
                    self._on_frame(frame, conn, log_f)
            # Connection closed with an un-framed tail (link drop mid-frame): still
            # summarize it so a truncated query is not lost.
            if buf.strip():
                self._on_frame(bytes(buf), conn, log_f)

    def _on_frame(self, frame: bytes, conn: socket.socket, log_f) -> None:
        analysis = CaptureAnalysis(frame)
        if self.send_ack:
            msh = analysis.msh()
            ack = build_ack(msh, control_id=analysis.control_id() or "1")
            try:
                conn.sendall(ack)
                log_f.write(f"                 SEND <ACK> (MSA|AA, echo MSH-10={analysis.control_id()!r}) "
                            f"— acknowledgement only, NOT an ORF worklist\n")
            except OSError as exc:
                log_f.write(f"                 ACK send failed: {exc}\n")
        self._emit_summary(analysis, log_f)

    def _emit_summary(self, analysis: CaptureAnalysis, log_f) -> None:
        block = "\n".join(
            [
                "",
                "================= CAPTURE SUMMARY =================",
                analysis.summary(),
                "===================================================",
                "",
            ]
        )
        log_f.write(block + "\n")
        log_f.flush()
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
    p.add_argument("--port", type=int, default=7999, help="TCP port to listen on (default 7999 per ADR-0015; set the analyzer's port to match, manual Annex 2)")
    p.add_argument("--outdir", default="./h60s-capture", help="archive directory (default ./h60s-capture)")
    p.add_argument(
        "--ack",
        action="store_true",
        help="return a minimal HL7 ACK (MSA|AA, echoing MSH-10) to keep the analyzer link alive "
        "and observe retries. This is an acknowledgement ONLY — it is NOT an ORF^R04 worklist "
        "answer (that is LIS-149 scope). Default: capture-only, send nothing.",
    )
    p.add_argument("--once", action="store_true", help="handle a single connection then exit")
    p.add_argument("--replay", metavar="RAWFILE", help="analyze an archived raw capture and exit (no socket)")
    args = p.parse_args(argv)

    if args.replay:
        return _replay(args.replay)

    server = MllpCaptureServer(args.host, args.port, args.outdir, args.ack, args.once)
    try:
        server.serve()
    except KeyboardInterrupt:
        print(f"\n[{_now_iso()}] stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
