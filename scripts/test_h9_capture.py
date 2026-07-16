#!/usr/bin/env python3
"""Network-free tests for the passive Lifotronic H9 capture tool (LIS-229)."""

import hashlib
import importlib
import io
import json
import os
import pty
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
hc = importlib.import_module("h9_capture")


def h9_frame(block_type, application_length):
    payload = bytearray(b"A" * application_length)
    payload[0] = ord(block_type)
    return bytes([hc.STX]) + bytes(payload) + bytes([hc.ETX])


class TestExactByteArchive(unittest.TestCase):
    def test_archive_preserves_raw_bytes_and_writes_sha256_sidecar(self):
        raw = b"noise\x02S" + (b"A" * 119) + b"\x03tail"
        with tempfile.TemporaryDirectory() as outdir:
            entry = hc.archive_capture(
                raw,
                outdir,
                capture_started_at="2026-07-16T08:00:00.000Z",
                capture_ended_at="2026-07-16T08:00:01.000Z",
                source="/dev/serial/by-id/h9-bench",
                read_events=[
                    {
                        "received_at": "2026-07-16T08:00:00.500Z",
                        "offset": 0,
                        "byte_count": len(raw),
                    }
                ],
                bench={"model": "Lifotronic H9", "firmware": "A0"},
            )

            digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(entry.digest, digest)
            self.assertEqual(entry.raw_path.read_bytes(), raw)
            sidecar = json.loads(entry.sidecar_path.read_text(encoding="utf-8"))
            self.assertEqual(sidecar["digest"], digest)
            self.assertEqual(sidecar["byte_count"], len(raw))
            self.assertEqual(sidecar["source"], "/dev/serial/by-id/h9-bench")
            self.assertEqual(sidecar["transport"], "SERIAL")
            self.assertEqual(sidecar["protocol"], "LIFOTRONIC_H9")
            self.assertEqual(sidecar["serial"], {
                "baud": 115200,
                "data_bits": 8,
                "parity": "none",
                "stop_bits": 1,
                "flow_control": "none",
                "open_mode": "read-only",
            })
            self.assertEqual(sidecar["read_events"][0]["byte_count"], len(raw))

    def test_sidecar_records_frame_boundaries_without_copying_payload_text(self):
        raw = h9_frame("Q", 109)
        with tempfile.TemporaryDirectory() as outdir:
            entry = hc.archive_capture(
                raw,
                outdir,
                capture_started_at="2026-07-16T08:00:00.000Z",
                capture_ended_at="2026-07-16T08:00:01.000Z",
                source="/dev/ttyUSB0",
                read_events=[],
                bench={},
            )

            sidecar = json.loads(entry.sidecar_path.read_text(encoding="utf-8"))
            self.assertEqual(sidecar["frames"][0]["block_type"], "Q")
            self.assertEqual(sidecar["frames"][0]["application_length"], 109)
            self.assertNotIn("payload", sidecar["frames"][0])

    def test_content_addressed_entry_is_immutable_when_same_bytes_are_seen_again(self):
        raw = h9_frame("C", 64)
        with tempfile.TemporaryDirectory() as outdir:
            first = hc.archive_capture(
                raw,
                outdir,
                capture_started_at="2026-07-16T08:00:00.000Z",
                capture_ended_at="2026-07-16T08:00:01.000Z",
                source="first-port",
                read_events=[],
                bench={"firmware": "first"},
            )
            again = hc.archive_capture(
                raw,
                outdir,
                capture_started_at="2099-01-01T00:00:00.000Z",
                capture_ended_at="2099-01-01T00:00:01.000Z",
                source="second-port",
                read_events=[],
                bench={"firmware": "second"},
            )

            self.assertEqual(again.digest, first.digest)
            sidecar = json.loads(first.sidecar_path.read_text(encoding="utf-8"))
            self.assertEqual(sidecar["source"], "first-port")
            self.assertEqual(sidecar["bench"]["firmware"], "first")

    def test_existing_corrupt_sidecar_is_rejected_instead_of_trusted(self):
        raw = h9_frame("Q", 109)
        with tempfile.TemporaryDirectory() as outdir:
            entry = hc.archive_capture(
                raw,
                outdir,
                capture_started_at="2026-07-16T08:00:00.000Z",
                capture_ended_at="2026-07-16T08:00:01.000Z",
                source="first-port",
                read_events=[],
                bench={},
            )
            entry.sidecar_path.write_text("{corrupt", encoding="utf-8")

            with self.assertRaises(hc.ArchiveIntegrityError):
                hc.archive_capture(
                    raw,
                    outdir,
                    capture_started_at="2026-07-16T09:00:00.000Z",
                    capture_ended_at="2026-07-16T09:00:01.000Z",
                    source="second-port",
                    read_events=[],
                    bench={},
                )


class TestFrameAnalysis(unittest.TestCase):
    def test_recovers_a0_measurement_qc_and_calibration_lengths(self):
        raw = (
            b"leading-noise"
            + h9_frame("S", 126)  # 120 + one six-byte chromatogram point
            + h9_frame("Q", 109)
            + h9_frame("C", 64)
            + b"trailing-noise"
        )

        analysis = hc.analyze_stream(raw)

        self.assertEqual([f["block_type"] for f in analysis["frames"]], ["S", "Q", "C"])
        self.assertEqual([f["application_length"] for f in analysis["frames"]], [126, 109, 64])
        self.assertTrue(all(f["length_valid"] for f in analysis["frames"]))
        self.assertEqual(analysis["noise_byte_count"], len(b"leading-noise" + b"trailing-noise"))

    def test_in_frame_etx_byte_does_not_end_a_structurally_valid_measurement_early(self):
        payload = bytearray(b"A" * 120)
        payload[0] = ord("S")
        payload[42] = hc.ETX
        raw = bytes([hc.STX]) + bytes(payload) + bytes([hc.ETX])

        analysis = hc.analyze_stream(raw)

        self.assertEqual(len(analysis["frames"]), 1)
        self.assertEqual(analysis["frames"][0]["application_length"], 120)
        self.assertTrue(analysis["frames"][0]["length_valid"])


class TestPassiveSerialCapture(unittest.TestCase):
    def test_live_capture_reads_a_pty_without_any_write_call(self):
        master_fd, slave_fd = pty.openpty()
        slave_path = os.ttyname(slave_fd)
        os.close(slave_fd)
        raw = h9_frame("Q", 109)
        result = {}
        error = []
        with tempfile.TemporaryDirectory() as outdir:
            def run_capture():
                try:
                    result["entry"] = hc.capture_serial(
                        slave_path,
                        outdir,
                        frame_limit=1,
                        duration_seconds=2,
                        bench={"model": "Lifotronic H9"},
                    )
                except Exception as exc:  # surfaced in the test thread below
                    error.append(exc)

            thread = threading.Thread(target=run_capture)
            thread.start()
            time.sleep(0.1)
            real_write = os.write
            try:
                with mock.patch.object(
                    hc.os,
                    "write",
                    side_effect=AssertionError("capture emitted bytes"),
                ):
                    real_write(master_fd, raw)
                    thread.join(timeout=5)
            finally:
                os.close(master_fd)

            self.assertFalse(thread.is_alive())
            self.assertEqual(error, [])
            self.assertEqual(result["entry"].raw_path.read_bytes(), raw)
            self.assertEqual(list(os.scandir(outdir))[0].name, result["entry"].digest[:2])

    def test_frame_limit_waits_for_quiet_period_and_keeps_a_late_tail(self):
        master_fd, slave_fd = pty.openpty()
        slave_path = os.ttyname(slave_fd)
        os.close(slave_fd)
        payload = bytearray(b"A" * 126)
        payload[0] = ord("S")
        payload[120] = hc.ETX  # valid-looking 120-byte prefix, not the real terminator
        raw = bytes([hc.STX]) + bytes(payload) + bytes([hc.ETX])
        prefix = raw[:122]
        tail = raw[122:]
        result = {}
        error = []

        with tempfile.TemporaryDirectory() as outdir:
            def run_capture():
                try:
                    result["entry"] = hc.capture_serial(
                        slave_path,
                        outdir,
                        frame_limit=1,
                        settle_seconds=0.2,
                        duration_seconds=2,
                    )
                except Exception as exc:
                    error.append(exc)

            thread = threading.Thread(target=run_capture)
            thread.start()
            time.sleep(0.1)
            real_write = os.write
            try:
                real_write(master_fd, prefix)
                time.sleep(0.05)
                self.assertTrue(thread.is_alive())
                real_write(master_fd, tail)
                thread.join(timeout=5)
            finally:
                os.close(master_fd)

            self.assertFalse(thread.is_alive())
            self.assertEqual(error, [])
            archived = result["entry"].raw_path.read_bytes()
            self.assertEqual(archived, raw)
            self.assertEqual(hc.analyze_stream(archived)["frames"][0]["application_length"], 126)


class TestReplayCli(unittest.TestCase):
    def test_replay_reports_digest_and_frame_summary_without_a_serial_device(self):
        raw = h9_frame("S", 120)
        with tempfile.NamedTemporaryFile(suffix=".msg") as capture:
            capture.write(raw)
            capture.flush()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = hc.main(["--replay", capture.name])

        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn(hashlib.sha256(raw).hexdigest(), output)
        self.assertIn("S application=120B valid=yes", output)

    def test_replay_rejects_a_content_addressed_file_whose_bytes_do_not_match_its_name(self):
        with tempfile.TemporaryDirectory() as outdir:
            capture = os.path.join(outdir, f"{'0' * 64}.msg")
            with open(capture, "wb") as raw_file:
                raw_file.write(h9_frame("C", 64))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = hc.main(["--replay", capture])

        self.assertEqual(rc, 1)
        self.assertIn("INTEGRITY ERROR", stdout.getvalue())

    def test_replay_rejects_a_content_addressed_capture_with_corrupt_sidecar(self):
        raw = h9_frame("C", 64)
        with tempfile.TemporaryDirectory() as outdir:
            entry = hc.archive_capture(
                raw,
                outdir,
                capture_started_at="2026-07-16T08:00:00.000Z",
                capture_ended_at="2026-07-16T08:00:01.000Z",
                source="bench-port",
                read_events=[],
                bench={},
            )
            entry.sidecar_path.write_text("{corrupt", encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = hc.main(["--replay", str(entry.raw_path)])

        self.assertEqual(rc, 1)
        self.assertIn("INTEGRITY ERROR", stdout.getvalue())


class TestLiveCliSafety(unittest.TestCase):
    def test_live_capture_requires_an_explicit_output_directory(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit):
            hc.main(["--port", "/dev/ttyUSB0", "--duration", "0.01"])

        self.assertIn("--outdir is required", stderr.getvalue())

    def test_live_capture_rejects_an_output_directory_inside_the_repository(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        stderr = io.StringIO()
        with mock.patch.object(
            hc,
            "capture_serial",
            side_effect=AssertionError("capture must not start"),
        ):
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                hc.main(
                    [
                        "--port",
                        "/dev/ttyUSB0",
                        "--outdir",
                        os.path.join(repo_root, "h9-capture"),
                    ]
                )

        self.assertIn("outside the repository", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
