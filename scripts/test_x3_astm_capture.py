#!/usr/bin/env python3
"""Network-free tests for scripts/x3_astm_capture.py (LIS-75).

Anchors every assertion to the SNIBE MAGLUMI X3 KB §6 verbatim wire fixtures
(thoughts/references/SNIBE_MAGLUMI_X3_LIS_driver_knowledgebase.md), not to the
tool's own output — a self-consistency check alone would be vacuous. The one live
socket test proves the ENQ/STX/ETX/EOT ACK handshake end-to-end over a socketpair,
which is what makes the analyzer's LIS indicator go green (AC1).
"""
import importlib
import os
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
xc = importlib.import_module("x3_astm_capture")

CR = "\r"
ENQ, STX, ETX, EOT, ACK, LF = (
    bytes([xc.ENQ]),
    bytes([xc.STX]),
    bytes([xc.ETX]),
    bytes([xc.EOT]),
    bytes([xc.ACK]),
    bytes([xc.LF]),
)

# --- KB §6.1 result upload (SnibeLis biochemistry worked session, verbatim) ---
KB_6_1_RECORDS = [
    r"H|\^&||PSWD|BC1200|||||Lis|P|E1394-97|20180326",
    "P|1",
    r"O|1|1234567||^^^ALT\^^^CK",
    "R|1|^^^ALT|123|pg/mL|0 to 200|N|||||20180326172956",
    "R|2|^^^CK|25.1|pg/mL|0 to 50|N|||||20180326172956",
    "L|1|N",
]

# --- KB §6.4 X3 immunoassay-shaped fixture (recommended v1 vector, verbatim) ---
KB_6_4_RECORDS = [
    r"H|\^&||PSWD|Maglumi User|||||Lis||P|E1394-97|20260703",
    "P|1||PID-SNB-108-001||DOE^MAGLUMI|||F",
    r"O|1|SNB-108-001||^^^TSH\^^^FT4|R",
    "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N|||||20260703101530",
    "R|2|^^^FT4|14.8|pmol/L|12 to 22|N|||||20260703101530",
    "L|1|N",
]

# --- KB §6.2 order query (verbatim) ---
KB_6_2_RECORDS = [
    r"H|\^&||PSWD|BC1200|||||Lis|P|E1394-97|20180323",
    "Q|1|^1234567||ALL|||||||O",
    "L|1|N",
]


def simplified_wire(records) -> bytes:
    """Build the simplified on-wire byte stream: ENQ STX <records\\r> ETX EOT."""
    body = "".join(rec + CR for rec in records)
    return ENQ + STX + body.encode("latin-1") + ETX + EOT


def checksummed_wire(records) -> bytes:
    """Build a checksummed E1381-ish frame: STX 1 <records\\r> ETX <cs><cs> CR LF."""
    body = "".join(rec + CR for rec in records)
    frame_text = "1" + body  # single-digit frame number after STX
    # A plausible 2-char hex checksum; value is irrelevant to classification.
    return ENQ + STX + frame_text.encode("latin-1") + ETX + b"A3" + CR.encode() + LF


class TestRecordParsing(unittest.TestCase):
    def test_header_identity_fields(self):
        rec = xc.parse_record(KB_6_4_RECORDS[0])
        self.assertEqual(rec["type"], "H")
        self.assertEqual(rec["sender"], "Maglumi User")  # H-5 transmitter name
        self.assertEqual(rec["receiver"], "Lis")  # H-10 receiver/host name
        self.assertEqual(rec["version"], "E1394-97")
        self.assertEqual(rec["delimiters"], r"\^&")

    def test_header_identity_survives_off_by_one(self):
        # §6.1 has one fewer padding pipe than §6.4, yet sender/receiver are stable.
        rec = xc.parse_record(KB_6_1_RECORDS[0])
        self.assertEqual(rec["sender"], "BC1200")
        self.assertEqual(rec["receiver"], "Lis")

    def test_order_sample_id_and_assays(self):
        rec = xc.parse_record(KB_6_4_RECORDS[2])
        self.assertEqual(rec["sample_id"], "SNB-108-001")  # O-3
        self.assertEqual(rec["assays"], ["TSH", "FT4"])  # O-5, '\'-repeat, '^^^' stripped

    def test_order_multi_assay_biochem(self):
        rec = xc.parse_record(KB_6_1_RECORDS[2])
        self.assertEqual(rec["sample_id"], "1234567")
        self.assertEqual(rec["assays"], ["ALT", "CK"])

    def test_order_assays_survive_field_drift(self):
        # KB §6.6: the O assay field drifts (4<->5). A real X3 O record that omits
        # the O-4 padding must still yield the assays (anchor on '^^^', not field 5),
        # not misread the priority field as the assay.
        rec = xc.parse_record(r"O|1|SNB-108-001|^^^TSH\^^^FT4|R")  # assay now at field 4
        self.assertEqual(rec["sample_id"], "SNB-108-001")
        self.assertEqual(rec["assays"], ["TSH", "FT4"])

    def test_result_fields(self):
        rec = xc.parse_record(KB_6_4_RECORDS[3])
        self.assertEqual(rec["assay"], "TSH")  # R-3, '^^^' stripped
        self.assertEqual(rec["value"], "2.31")  # R-4
        self.assertEqual(rec["unit"], "uIU/mL")  # R-5
        self.assertEqual(rec["ref_range"], "0.27 to 4.20")  # R-6
        self.assertEqual(rec["flag"], "N")  # R-7
        self.assertEqual(rec["timestamp"], "20260703101530")

    def test_query_preserves_leading_caret(self):
        rec = xc.parse_record(KB_6_2_RECORDS[1])
        # KB flags: Q-3 must keep the leading '^' component marker on the wire.
        self.assertEqual(rec["sample_id"], "^1234567")
        self.assertEqual(rec["request"], "ALL")


class TestTimestampFieldIndex(unittest.TestCase):
    """AC4 — pin the R-record completion-timestamp field position (KB §6.6 drift)."""

    def test_five_pad_lands_at_field_12(self):
        # KB §6.1/§6.4 verbatim R records use '|||||' (5 empties) -> field 12.
        fields = KB_6_4_RECORDS[3].split("|")
        self.assertEqual(xc.find_result_timestamp_field(fields), 12)

    def test_four_pad_lands_at_field_11(self):
        # X3 App.B examples (one fewer pad) land the timestamp at field 11.
        rec = "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N||||20260703101530"
        self.assertEqual(xc.find_result_timestamp_field(rec.split("|")), 11)

    def test_six_pad_lands_at_field_13(self):
        # Canonical ASTM table position (extra pad) -> field 13.
        rec = "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N||||||20260703101530"
        self.assertEqual(xc.find_result_timestamp_field(rec.split("|")), 13)

    def test_no_timestamp_returns_none(self):
        rec = "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N"
        self.assertIsNone(xc.find_result_timestamp_field(rec.split("|")))

    def test_eight_digit_field_does_not_shadow_the_completion_time(self):
        # A stray 8-digit date at field 9 must NOT be picked over the real 14-digit
        # completion timestamp at field 12 (KB §10 specifies a 14-digit scan).
        rec = "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N||20260703|||20260703101530"
        fields = rec.split("|")
        self.assertEqual(xc.find_result_timestamp_field(fields), 12)
        self.assertEqual(xc.parse_record(rec)["timestamp"], "20260703101530")

    def test_date_only_result_falls_back_to_eight_digit(self):
        # If no 14-digit field exists, an 8-digit date-only field is the fallback.
        rec = "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N|||||20260703"
        self.assertEqual(xc.find_result_timestamp_field(rec.split("|")), 12)


class TestFraming(unittest.TestCase):
    def test_simplified_classified(self):
        f = xc.classify_framing(simplified_wire(KB_6_1_RECORDS))
        self.assertEqual(f["mode"], "simplified")
        self.assertFalse(f["frame_number"])
        self.assertFalse(f["checksum"])
        self.assertFalse(f["has_lf"])

    def test_checksummed_classified(self):
        f = xc.classify_framing(checksummed_wire(KB_6_1_RECORDS))
        self.assertEqual(f["mode"], "checksummed")
        self.assertTrue(f["frame_number"])
        self.assertTrue(f["checksum"])
        self.assertTrue(f["has_lf"])

    def test_raw_noncompliant_classified(self):
        body = "".join(rec + CR for rec in KB_6_1_RECORDS).encode("latin-1")
        f = xc.classify_framing(body)  # starts at H| with no control establishment
        self.assertEqual(f["mode"], "raw")


class TestIterRecords(unittest.TestCase):
    def test_simplified_roundtrip(self):
        recs = xc.iter_records(simplified_wire(KB_6_4_RECORDS))
        self.assertEqual(recs, KB_6_4_RECORDS)

    def test_checksummed_strips_frame_number_and_checksum(self):
        # The frame number and trailing 2-char checksum must NOT leak as records.
        recs = xc.iter_records(checksummed_wire(KB_6_4_RECORDS))
        self.assertEqual(recs, KB_6_4_RECORDS)


class TestAnalysis(unittest.TestCase):
    def test_full_session_findings(self):
        a = xc.CaptureAnalysis(simplified_wire(KB_6_4_RECORDS))
        self.assertEqual(a.framing["mode"], "simplified")
        self.assertEqual(a.header()["sender"], "Maglumi User")
        self.assertEqual([r["assay"] for r in a.results()], ["TSH", "FT4"])
        self.assertEqual(a.timestamp_field_indices(), [12])
        self.assertIn("Framing: SIMPLIFIED", a.summary())
        self.assertIn("TSH=2.31 uIU/mL", a.summary())

    def test_query_session_notes_out_of_scope(self):
        a = xc.CaptureAnalysis(simplified_wire(KB_6_2_RECORDS))
        self.assertEqual(len(a.queries()), 1)
        self.assertIn("LIS-177", a.summary())  # order-download flagged out of scope


class TestAckModeSelection(unittest.TestCase):
    def _server(self, mode):
        return xc.CaptureServer(host="127.0.0.1", port=0, outdir=tempfile.mkdtemp(), mode=mode, once=True)

    def test_simplified_acks_bare_stx(self):
        self.assertIn(xc.STX, self._server("simplified").ack_on)
        self.assertIn(xc.ENQ, self._server("simplified").ack_on)
        self.assertIn(xc.EOT, self._server("simplified").ack_on)

    def test_framed_does_not_ack_bare_stx(self):
        ack_on = self._server("framed").ack_on
        self.assertNotIn(xc.STX, ack_on)
        self.assertIn(xc.ETX, ack_on)
        self.assertIn(xc.ENQ, ack_on)


class TestSocketHandshake(unittest.TestCase):
    """End-to-end proof of the simplified 4-point ACK handshake + raw archival."""

    def test_handshake_acks_and_archives(self):
        outdir = tempfile.mkdtemp()
        server = xc.CaptureServer(host="127.0.0.1", port=0, outdir=outdir, mode="simplified", once=True)
        srv_end, ana_end = socket.socketpair()
        t = threading.Thread(target=server._handle, args=(srv_end, ("test", 0)))
        t.start()
        try:
            ana_end.settimeout(5)
            body = "".join(rec + CR for rec in KB_6_4_RECORDS).encode("latin-1")

            # ENQ -> ACK, STX -> ACK (each waits for the ACK, as the real analyzer does)
            ana_end.sendall(ENQ)
            self.assertEqual(ana_end.recv(1), ACK)
            ana_end.sendall(STX)
            self.assertEqual(ana_end.recv(1), ACK)
            # Record block: NOT ACKed.
            ana_end.sendall(body)
            # ETX -> ACK, EOT -> ACK
            ana_end.sendall(ETX)
            self.assertEqual(ana_end.recv(1), ACK)
            ana_end.sendall(EOT)
            self.assertEqual(ana_end.recv(1), ACK)
            ana_end.close()
        finally:
            t.join(timeout=5)
            srv_end.close()

        # Raw archive must contain every byte the analyzer sent, byte-for-byte.
        raw_files = [f for f in os.listdir(outdir) if f.startswith("raw-")]
        self.assertEqual(len(raw_files), 1)
        with open(os.path.join(outdir, raw_files[0]), "rb") as f:
            archived = f.read()
        self.assertEqual(archived, ENQ + STX + body + ETX + EOT)

        # Annotated log must exist and contain the capture summary.
        log_files = [f for f in os.listdir(outdir) if f.startswith("annotated-")]
        self.assertEqual(len(log_files), 1)
        with open(os.path.join(outdir, log_files[0]), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("CAPTURE SUMMARY", log)
        self.assertIn("Framing: SIMPLIFIED", log)


class TestConcurrentConnections(unittest.TestCase):
    """Regression for the bench-observed failure (LIS-75, 2026-07-17): the X3
    operation software holds one idle status connection open (the green LIS dot)
    and opens a SEPARATE, parallel connection to deliver a message. A
    serve-one-connection-at-a-time loop blocks the delivery connection behind the
    idle one until the software's ~3s timeout fires ("Communication timeout
    between software and LIS!"). ``serve()`` must handle each connection on its
    own thread so a lingering idle connection never starves a delivery."""

    def test_idle_connection_does_not_block_a_parallel_delivery(self):
        outdir = tempfile.mkdtemp()
        server = xc.CaptureServer(host="127.0.0.1", port=0, outdir=outdir, mode="simplified", once=False)
        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_sock.bind(("127.0.0.1", 0))
        srv_sock.listen(16)
        port = srv_sock.getsockname()[1]

        # Drive the accept loop by hand (serve() blocks forever); this exercises
        # the same per-connection threading serve() uses.
        stop = threading.Event()

        def accept_loop():
            srv_sock.settimeout(0.25)
            while not stop.is_set():
                try:
                    conn, peer = srv_sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=server._serve_conn, args=(conn, peer), daemon=True).start()

        loop = threading.Thread(target=accept_loop, daemon=True)
        loop.start()
        try:
            # 1) An idle status connection that sends nothing and stays open.
            idle = socket.create_connection(("127.0.0.1", port), timeout=5)

            # 2) A parallel delivery connection completes the full handshake while
            #    the idle one is still open. Each control token must be ACKed
            #    promptly (well under the analyzer's ~3s timeout).
            data = socket.create_connection(("127.0.0.1", port), timeout=5)
            data.settimeout(3)
            body = "".join(rec + CR for rec in KB_6_4_RECORDS).encode("latin-1")
            data.sendall(ENQ)
            self.assertEqual(data.recv(1), ACK)
            data.sendall(STX)
            self.assertEqual(data.recv(1), ACK)
            data.sendall(body)
            data.sendall(ETX)
            self.assertEqual(data.recv(1), ACK)
            data.sendall(EOT)
            self.assertEqual(data.recv(1), ACK)
            data.close()
            idle.close()
        finally:
            stop.set()
            loop.join(timeout=5)
            srv_sock.close()

        # The delivery was archived byte-for-byte despite the idle connection.
        raw_files = [f for f in os.listdir(outdir) if f.startswith("raw-")]
        delivered = [f for f in raw_files if os.path.getsize(os.path.join(outdir, f)) > 0]
        self.assertEqual(len(delivered), 1)
        with open(os.path.join(outdir, delivered[0]), "rb") as f:
            self.assertEqual(f.read(), ENQ + STX + body + ETX + EOT)


class TestReplay(unittest.TestCase):
    def test_replay_reads_archived_capture(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(simplified_wire(KB_6_1_RECORDS))
            path = f.name
        try:
            rc = xc.main(["--replay", path])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
