#!/usr/bin/env python3
"""Network-free tests for scripts/h60s_mllp_capture.py (LIS-181).

Every wire assertion is anchored to a VERBATIM source — the EDAN H60S LIS
Communication Protocol manual (v1.1, 2022-07-29) examples, or the checked-in edge/sim
host-query fixtures — copied here as constants (the scripts-tests CI job checks out
the umbrella WITHOUT submodules, so edge/sim/ is not on disk at test time; the same
reason x3's tests inline the KB fixtures). Anchoring to the source, not the tool's own
output, keeps these from being a vacuous self-consistency check.

The one live socket test proves the MLLP listener archives raw bytes to disk and,
with --ack, returns an MSA|AA that echoes the inbound MSH-10.
"""
import importlib
import os
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
hc = importlib.import_module("h60s_mllp_capture")

SB, EB, CR = bytes([hc.SB]), bytes([hc.EB]), bytes([hc.CR])


def mllp(*segments: str) -> bytes:
    """Wrap HL7 segments in one MLLP frame: SB payload EB CR, CR between segments."""
    body = ("\r".join(segments) + "\r").encode("utf-8")
    return SB + body + EB + CR


# --- manual §6.1 "Send test results" ORU example (H60, verbatim) -------------
MANUAL_ORU_MSH = "MSH|^~\\&|H60|EDANLAB|||20220701171827||ORU^R01|8|P|2.3.1|||||UTF8"
MANUAL_ORU_PID = "PID|6||null ^ 0|||M|||||||||||||||"
MANUAL_ORU_OBR = "OBR||1||EDANLAB^H60^Sample|||20200531141107||0|||||19700101080000|||||||"
MANUAL_ORU_OBX_WBC = "OBX||NM|1|WBC|0.00|10^9/L|4.0-10.0||||F"

# --- manual §6.1 LIS ACK example (verbatim) ----------------------------------
MANUAL_ACK_MSH = "MSH|^~\\&|||H60|EDANLAB|20220808111350||ACK|1|P|2.4"
MANUAL_ACK_MSA = "MSA|AA|1"

# --- manual §3.2.6 QRD example (verbatim) ------------------------------------
MANUAL_QRD = "QRD|198904180943|R|I|Q4412|||10|RD|0123456-1|RES"

# --- edge/sim/fixtures/edan-h60s-host-query-qry-r02/message.hl7 (verbatim) ---
#     Pre-bench SYNTHETIC clean-HL7 layout (MSH-3=H60S, MSH-4=EDAN) — the layout
#     LIS-20 refuted northbound. The tool must flag it as 'clean' (refuted).
SIM_H60S_QRY = [
    "MSH|^~\\&|H60S|EDAN|LIS|LAB|20260628093500||QRY^R02|H60SQ0231|P|2.4",
    "QRD|20260628093500|R|I|Q0231-01||||SPEC-0231|RES",
    "QRF|SPEC-0231",
]

# --- edge/sim/fixtures/edan-h99s-worklist-query-qry-r02/message.hl7 (verbatim)
#     H90-family EDANLAB layout (MSH-3=H90, MSH-4=EDANLAB, MSH-16=3).
SIM_H99S_QRY = [
    "MSH|^~\\&|H90|EDANLAB|LIS|LAB|20260703112800||QRY^R02|H99SQ1|P|2.4||||3",
    "QRD|20260703112800|R|I|Q-1||||DEV01260000000000002|OTH",
]


class MshFieldOffsetTests(unittest.TestCase):
    """MSH-1 is the field separator, so MSH-n access must not be off by one."""

    def test_msh_identity_fields_from_manual_oru(self):
        s = hc.Segment(MANUAL_ORU_MSH)
        self.assertTrue(s.is_msh)
        self.assertEqual(s.field(1), "|")
        self.assertEqual(s.field(3), "H60")       # sending application
        self.assertEqual(s.field(4), "EDANLAB")   # sending facility (fixed)
        self.assertEqual(s.field(9), "ORU^R01")   # message type
        self.assertEqual(s.field(10), "8")        # control id
        self.assertEqual(s.field(12), "2.3.1")    # version drift vs table's 2.4
        # The example's trailing UTF8 lands at MSH-17, though the field table calls
        # char set MSH-18 — another manual example-vs-table drift (characterize first).
        self.assertEqual(s.field(17), "UTF8")

    def test_msh16_worklist_flag_from_h99s_fixture(self):
        s = hc.Segment(SIM_H99S_QRY[0])
        self.assertEqual(s.field(9), "QRY^R02")
        self.assertEqual(s.field(16), "3")  # worklist flag (undocumented in H60 manual)

    def test_non_msh_segment_field_offset(self):
        obx = hc.Segment(MANUAL_ORU_OBX_WBC)
        self.assertFalse(obx.is_msh)
        self.assertEqual(obx.field(2), "NM")   # value type
        self.assertEqual(obx.field(3), "1")    # suspect mark
        self.assertEqual(obx.field(4), "WBC")  # analyte name (EDANLAB: OBX-4, not OBX-3)
        self.assertEqual(obx.field(5), "0.00")
        self.assertEqual(obx.field(6), "10^9/L")
        self.assertEqual(obx.field(11), "F")

    def test_pid_and_obr_positions_from_manual(self):
        pid = hc.Segment(MANUAL_ORU_PID)
        self.assertEqual(pid.field(3), "null ^ 0")  # age^unit lives in PID-3
        obr = hc.Segment(MANUAL_ORU_OBR)
        self.assertEqual(obr.field(2), "1")
        self.assertEqual(obr.field(4), "EDANLAB^H60^Sample")

    def test_absent_field_is_empty_string(self):
        self.assertEqual(hc.Segment("QRF|SPEC-0231").field(9), "")


class DeframeTests(unittest.TestCase):
    def test_single_frame_roundtrip(self):
        frame = mllp(*SIM_H99S_QRY)
        payloads = hc.deframe(frame)
        self.assertEqual(len(payloads), 1)
        self.assertIn(b"QRY^R02", payloads[0])
        self.assertNotIn(hc.SB, payloads[0])
        self.assertNotIn(hc.EB, payloads[0])

    def test_two_frames_in_one_capture(self):
        raw = mllp("MSH|^~\\&|H60|EDANLAB|||1||ORU^R01|1|P|2.4") + mllp(*SIM_H99S_QRY)
        self.assertEqual(len(hc.deframe(raw)), 2)

    def test_unterminated_tail_is_not_lost(self):
        # Link drop mid-frame: SB opened, no EB CR. The partial payload survives.
        raw = SB + "MSH|^~\\&|H60|EDANLAB|||1||QRY^R02|9|P|2.4\r".encode()
        payloads = hc.deframe(raw)
        self.assertEqual(len(payloads), 1)
        self.assertIn(b"QRY^R02", payloads[0])

    def test_raw_hl7_without_mllp_framing(self):
        raw = ("\r".join(SIM_H99S_QRY) + "\r").encode()
        payloads = hc.deframe(raw)
        self.assertEqual(len(payloads), 1)

    def test_leading_noise_before_first_sb_ignored(self):
        raw = b"garbage" + mllp("MSH|^~\\&|H60|EDANLAB|||1||QRY^R02|9|P|2.4")
        payloads = hc.deframe(raw)
        self.assertEqual(len(payloads), 1)
        self.assertNotIn(b"garbage", payloads[0])


class LayoutClassificationTests(unittest.TestCase):
    def test_h99s_fixture_is_edanlab(self):
        a = hc.CaptureAnalysis(mllp(*SIM_H99S_QRY))
        self.assertEqual(a.layout()["profile"], "edanlab")

    def test_manual_oru_is_edanlab(self):
        a = hc.CaptureAnalysis(mllp(MANUAL_ORU_MSH, MANUAL_ORU_OBX_WBC))
        self.assertEqual(a.layout()["profile"], "edanlab")

    def test_h60s_synthetic_fixture_is_clean_refuted(self):
        # The pre-bench H60S host-query fixture uses MSH-4=EDAN -> 'clean' (refuted).
        a = hc.CaptureAnalysis(mllp(*SIM_H60S_QRY))
        lay = a.layout()
        self.assertEqual(lay["profile"], "clean")
        self.assertTrue(any("REFUTED" in e for e in lay["evidence"]))

    def test_unknown_facility(self):
        a = hc.CaptureAnalysis(mllp("MSH|^~\\&|H60|ACME|||1||QRY^R02|1|P|2.4"))
        self.assertEqual(a.layout()["profile"], "unknown")


class QrdSubjectCandidateTests(unittest.TestCase):
    def test_manual_qrd_example_positions_verbatim(self):
        # The manual's own QRD example puts the subject-looking value in QRD-9, not
        # QRD-8 — the ambiguity the bench must resolve. Assert the exact positions.
        cand = hc.qrd_subject_candidates(hc.Segment(MANUAL_QRD))
        self.assertEqual(cand["query_id_qrd4"], "Q4412")
        self.assertEqual(cand["who_subject_qrd8"], "RD")
        self.assertEqual(cand["what_subject_qrd9"], "0123456-1")
        self.assertEqual(cand["dept_data_code_qrd10"], "RES")

    def test_sim_h60s_fixture_puts_subject_in_qrd8(self):
        cand = hc.qrd_subject_candidates(hc.Segment(SIM_H60S_QRY[1]))
        self.assertEqual(cand["query_id_qrd4"], "Q0231-01")
        self.assertEqual(cand["who_subject_qrd8"], "SPEC-0231")
        self.assertEqual(cand["what_subject_qrd9"], "RES")

    def test_sim_h99s_fixture_puts_barcode_in_qrd8(self):
        cand = hc.qrd_subject_candidates(hc.Segment(SIM_H99S_QRY[1]))
        self.assertEqual(cand["who_subject_qrd8"], "DEV01260000000000002")


class SummaryTests(unittest.TestCase):
    def test_query_summary_flags_ambiguity_and_lis149_scope(self):
        summary = hc.CaptureAnalysis(mllp(*SIM_H99S_QRY)).summary()
        self.assertIn("UNCONFIRMED", summary)
        self.assertIn("LIS-149", summary)
        self.assertIn("DEV01260000000000002", summary)

    def test_oru_summary_reports_analyte_from_obx4(self):
        summary = hc.CaptureAnalysis(mllp(MANUAL_ORU_MSH, MANUAL_ORU_OBX_WBC)).summary()
        self.assertIn("WBC", summary)
        self.assertIn("EDANLAB", summary)

    def test_empty_capture(self):
        self.assertIn("0 MLLP frames", hc.CaptureAnalysis(b"").summary())


class AckBuilderTests(unittest.TestCase):
    def test_ack_echoes_control_id_and_is_mllp_framed(self):
        # H60-identified inbound query: MSH-3=H60, MSH-4=EDANLAB, MSH-10=H60Q9.
        inbound = hc.Segment("MSH|^~\\&|H60|EDANLAB|LIS|LAB|20260706120000||QRY^R02|H60Q9|P|2.4")
        ack = hc.build_ack(inbound, control_id="42")
        self.assertEqual(ack[0], hc.SB)
        self.assertEqual(ack[-2], hc.EB)
        self.assertEqual(ack[-1], hc.CR)
        parsed = hc.CaptureAnalysis(ack)
        msa = parsed._all("MSA")[0]
        self.assertEqual(msa.field(1), "AA")
        self.assertEqual(msa.field(2), "H60Q9")  # echoes inbound MSH-10
        # LIS ACK swaps the analyzer identity into the receiving fields (manual §6.1).
        msh = parsed.msh()
        self.assertEqual(msh.field(5), "H60")
        self.assertEqual(msh.field(6), "EDANLAB")
        self.assertEqual(msh.field(9), "ACK")

    def test_manual_ack_example_parses(self):
        parsed = hc.CaptureAnalysis(mllp(MANUAL_ACK_MSH, MANUAL_ACK_MSA))
        self.assertEqual(parsed.msh().field(9), "ACK")
        self.assertEqual(parsed._all("MSA")[0].field(2), "1")


class LiveSocketTests(unittest.TestCase):
    """One end-to-end test over a real loopback socket."""

    def _run_server(self, outdir, send_ack):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        server = hc.MllpCaptureServer("127.0.0.1", port, outdir, send_ack=send_ack, once=True)
        # Reuse the pre-bound socket so the client can connect deterministically.
        def serve():
            conn, peer = srv.accept()
            try:
                server._handle(conn, peer)
            finally:
                conn.close()
                srv.close()
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        return port, t

    def test_capture_archives_raw_bytes(self):
        with tempfile.TemporaryDirectory() as outdir:
            port, t = self._run_server(outdir, send_ack=False)
            frame = mllp(*SIM_H99S_QRY)
            with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
                c.sendall(frame)
                c.shutdown(socket.SHUT_WR)
            t.join(timeout=5)
            self.assertFalse(t.is_alive())
            raws = [f for f in os.listdir(outdir) if f.startswith("raw-")]
            self.assertEqual(len(raws), 1)
            with open(os.path.join(outdir, raws[0]), "rb") as f:
                self.assertEqual(f.read(), frame)  # every byte archived verbatim
            logs = [f for f in os.listdir(outdir) if f.startswith("annotated-")]
            with open(os.path.join(outdir, logs[0]), encoding="utf-8") as f:
                self.assertIn("CAPTURE SUMMARY", f.read())

    def test_ack_mode_returns_msa_aa_echoing_control_id(self):
        with tempfile.TemporaryDirectory() as outdir:
            port, t = self._run_server(outdir, send_ack=True)
            frame = mllp(*SIM_H99S_QRY)  # MSH-10 = H99SQ1
            with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
                c.sendall(frame)
                c.settimeout(5)
                resp = c.recv(4096)
            t.join(timeout=5)
            parsed = hc.CaptureAnalysis(resp)
            self.assertEqual(parsed.msh().field(9), "ACK")
            self.assertEqual(parsed._all("MSA")[0].field(2), "H99SQ1")


if __name__ == "__main__":
    unittest.main()
