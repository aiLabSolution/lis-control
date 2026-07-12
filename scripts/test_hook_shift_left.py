"""Tests for hook_shift_left.py (PostToolUse shift-left hook).

Every test points LIS_HOOK_REPO_ROOT at a throwaway temp tree — never the real
repo root. Rule 1 of the hook re-runs the whole scripts/ unittest suite, so a
test that dispatched a scripts/*.py path against the real root would recurse
into this very module. Check subprocesses (unittest suite, uv, prettier) are
exercised via tiny fixtures / recording stub executables inside the temp tree.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "hook_shift_left.py"

PASSING_TEST = (
    "import unittest\n"
    "class T(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    "        self.assertTrue(True)\n"
)
FAILING_TEST = (
    "import unittest\n"
    "class T(unittest.TestCase):\n"
    "    def test_no(self):\n"
    "        self.fail('boom-marker')\n"
)


def run_hook(root, file_path=None, stdin_raw=None, path_env=None):
    env = os.environ.copy()
    env["LIS_HOOK_REPO_ROOT"] = str(root)
    if path_env is not None:
        env["PATH"] = path_env
    if stdin_raw is None:
        stdin_raw = json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": str(file_path)},
            "tool_response": {"success": True},
        })
    return subprocess.run([sys.executable, str(HOOK)], input=stdin_raw,
                          capture_output=True, text=True, env=env, timeout=120)


def write_exe(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class HookTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def make_recording_stub(self, exe_path: Path, exit_code=0, stderr_msg=""):
        """Executable that records its cwd + argv, so tests can assert both the
        invocation (args, working directory) and its absence (no record file)."""
        record = self.root / f"{exe_path.name}-record.txt"
        lines = ["#!/bin/sh",
                 '{ pwd; for a in "$@"; do printf \'%s\\n\' "$a"; done; } > '
                 + f'"{record}"']
        if stderr_msg:
            lines.append(f'echo "{stderr_msg}" >&2')
        lines.append(f"exit {exit_code}")
        write_exe(exe_path, "\n".join(lines) + "\n")
        return record


class ScriptsSuiteDispatchTests(HookTestCase):
    def test_passing_suite_exits_0(self):
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "test_pass.py").write_text(PASSING_TEST)
        target = self.root / "scripts" / "helper.py"
        target.write_text("x = 1\n")
        result = run_hook(self.root, target)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failing_suite_exits_2_with_output(self):
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "test_fail.py").write_text(FAILING_TEST)
        target = self.root / "scripts" / "test_fail.py"
        result = run_hook(self.root, target)
        self.assertEqual(result.returncode, 2)
        self.assertIn("boom-marker", result.stderr)

    def test_nested_scripts_path_does_not_run_suite(self):
        # Dispatch is scripts/*.py (one level, mirroring what discover collects);
        # the failing fixture proves the suite was not run.
        (self.root / "scripts" / "sub").mkdir(parents=True)
        (self.root / "scripts" / "test_fail.py").write_text(FAILING_TEST)
        target = self.root / "scripts" / "sub" / "tool.py"
        target.write_text("x = 1\n")
        result = run_hook(self.root, target)
        self.assertEqual(result.returncode, 0, result.stderr)


class EdgeSimDispatchTests(HookTestCase):
    def setUp(self):
        super().setUp()
        self.sim_dir = self.root / "edge" / "sim"
        self.sim_dir.mkdir(parents=True)
        self.target = self.sim_dir / "test_thing.py"
        self.target.write_text("# fixture\n")
        self.bindir = self.root / "bin"
        self.bindir.mkdir()

    def test_missing_uv_exits_0(self):
        result = run_hook(self.root, self.target, path_env=str(self.bindir))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_uv_invoked_with_ci_command_and_cwd(self):
        record = self.make_recording_stub(self.bindir / "uv")
        result = run_hook(self.root, self.target, path_env=str(self.bindir))
        self.assertEqual(result.returncode, 0, result.stderr)
        recorded = record.read_text().splitlines()
        self.assertEqual(Path(recorded[0]).resolve(), self.sim_dir.resolve())
        self.assertEqual(recorded[1:],
                         ["run", "--frozen", "--python", "3.12", "pytest", "-q"])

    def test_uv_failure_exits_2_with_tail(self):
        self.make_recording_stub(self.bindir / "uv", exit_code=1,
                                 stderr_msg="1 failed sim-marker")
        result = run_hook(self.root, self.target, path_env=str(self.bindir))
        self.assertEqual(result.returncode, 2)
        self.assertIn("sim-marker", result.stderr)


class PrettierDispatchTests(HookTestCase):
    def setUp(self):
        super().setUp()
        self.drivers = self.root / "edge" / "drivers"
        self.prettier = self.drivers / "node_modules" / ".bin" / "prettier"
        self.target = self.drivers / "src" / "Foo.java"
        self.target.parent.mkdir(parents=True)
        self.target.write_text("class Foo {}\n")

    def test_java_file_invokes_prettier_write_with_drivers_cwd(self):
        record = self.make_recording_stub(self.prettier)
        result = run_hook(self.root, self.target)
        self.assertEqual(result.returncode, 0, result.stderr)
        recorded = record.read_text().splitlines()
        self.assertEqual(Path(recorded[0]).resolve(), self.drivers.resolve())
        self.assertEqual(recorded[1], "--write")
        self.assertEqual(Path(recorded[2]).resolve(), self.target.resolve())

    def test_node_modules_absent_exits_0_silently(self):
        result = run_hook(self.root, self.target)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_prettier_failure_exits_2_with_stderr(self):
        self.make_recording_stub(self.prettier, exit_code=2,
                                 stderr_msg="SyntaxError prettier-marker")
        result = run_hook(self.root, self.target)
        self.assertEqual(result.returncode, 2)
        self.assertIn("prettier-marker", result.stderr)

    def test_non_prettier_suffix_not_invoked(self):
        record = self.make_recording_stub(self.prettier)
        target = self.drivers / "src" / "Foo.py"
        target.write_text("x = 1\n")
        result = run_hook(self.root, target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(record.exists())


class NoDispatchTests(HookTestCase):
    def setUp(self):
        super().setUp()
        # Armed tree: a failing scripts suite and a recording prettier stub —
        # any accidental dispatch either flips the exit code or leaves a record.
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "test_fail.py").write_text(FAILING_TEST)
        self.record = self.make_recording_stub(
            self.root / "edge" / "drivers" / "node_modules" / ".bin" / "prettier")

    def test_non_matching_path_spawns_nothing(self):
        target = self.root / "docs" / "notes.txt"
        target.parent.mkdir()
        target.write_text("hi\n")
        result = run_hook(self.root, target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.record.exists())

    def test_path_outside_repo_root_exits_0(self):
        result = run_hook(self.root, "/etc/hosts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.record.exists())


class RobustnessTests(HookTestCase):
    def test_garbage_stdin_exits_0(self):
        result = run_hook(self.root, stdin_raw="not json {{{")
        self.assertEqual(result.returncode, 0)

    def test_empty_stdin_exits_0(self):
        result = run_hook(self.root, stdin_raw="")
        self.assertEqual(result.returncode, 0)

    def test_missing_file_path_exits_0(self):
        result = run_hook(self.root, stdin_raw=json.dumps(
            {"tool_name": "Write", "tool_input": {}}))
        self.assertEqual(result.returncode, 0)

    def test_non_dict_payload_exits_0(self):
        result = run_hook(self.root, stdin_raw="[1, 2, 3]")
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
