#!/usr/bin/env python3
"""Tests for scripts/hook_merge_gate.py.

End-to-end cases drive the gate as a real subprocess with JSON on stdin — the
actual hook contract (stdin parsing, exit codes, stderr feedback) — with `gh`
faked by a shell stub first on PATH that replays a canned `gh pr view --json`
payload (or fails, for the fail-closed cases). Parser cases import the module
directly.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_merge_gate

GATE = Path(__file__).resolve().parent / "hook_merge_gate.py"

_SHA = "a" * 40


def _pr(rollup):
    return {
        "number": 5,
        "url": "https://github.com/o/r/pull/5",
        "headRefOid": _SHA,
        "statusCheckRollup": rollup,
    }


GREEN = _pr([
    {"__typename": "CheckRun", "name": "backend", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"__typename": "CheckRun", "name": "lint", "status": "COMPLETED", "conclusion": "SKIPPED"},
    {"__typename": "StatusContext", "context": "legacy-status", "state": "SUCCESS"},
])
RED = _pr([
    {"__typename": "CheckRun", "name": "backend", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"__typename": "CheckRun", "name": "frontend", "status": "COMPLETED", "conclusion": "FAILURE"},
])
PENDING = _pr([
    {"__typename": "CheckRun", "name": "backend", "status": "IN_PROGRESS", "conclusion": ""},
])
STATUS_RED = _pr([
    {"__typename": "StatusContext", "context": "legacy-status", "state": "FAILURE"},
])
EMPTY = _pr([])


def _payload(command, tool="Bash"):
    return json.dumps({"tool_name": tool, "tool_input": {"command": command}})


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.bin.mkdir()
        self.payload_file = root / "gh.json"
        gh = self.bin / "gh"
        gh.write_text(
            '#!/bin/sh\n'
            'if [ "${FAKE_GH_EXIT:-0}" != "0" ]; then echo "gh: boom" >&2; '
            'exit "$FAKE_GH_EXIT"; fi\n'
            'cat "$FAKE_GH_PAYLOAD"\n'
        )
        gh.chmod(0o755)
        self.empty = root / "emptybin"
        self.empty.mkdir()

    def _run(self, stdin_text, pr=None, gh_exit=0, override=False, no_gh=False):
        env = dict(os.environ)
        env.pop("LIS_MERGE_GATE_OVERRIDE", None)
        if no_gh:
            env["PATH"] = str(self.empty)  # nothing else: a real gh must not answer
        else:
            env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["FAKE_GH_EXIT"] = str(gh_exit)
        env["FAKE_GH_PAYLOAD"] = str(self.payload_file)
        if override:
            env["LIS_MERGE_GATE_OVERRIDE"] = "1"
        self.payload_file.write_text(json.dumps(pr if pr is not None else GREEN))
        return subprocess.run(
            [sys.executable, str(GATE)],
            input=stdin_text, capture_output=True, text=True, env=env, timeout=60,
        )

    # -- not a merge: always allowed, even with a broken gh --------------------
    def test_non_bash_tool_allows(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r", tool="Edit"), gh_exit=1)
        self.assertEqual(proc.returncode, 0)

    def test_non_merge_command_allows(self):
        proc = self._run(_payload("git push origin lis-5-x && gh pr view 5"), gh_exit=1)
        self.assertEqual(proc.returncode, 0)

    def test_read_only_api_merge_probe_allows(self):
        # pin-bump's "is it merged?" probe: no PUT method — must stay allowed.
        proc = self._run(_payload("gh api repos/o/r/pulls/5/merge"), gh_exit=1)
        self.assertEqual(proc.returncode, 0)

    def test_help_allows(self):
        proc = self._run(_payload("gh pr merge --help"), gh_exit=1)
        self.assertEqual(proc.returncode, 0)

    def test_malformed_stdin_allows(self):
        proc = self._run("this is not json")
        self.assertEqual(proc.returncode, 0)

    # -- merge with verifiable checks ------------------------------------------
    def test_green_allows(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r --squash"), pr=GREEN)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_empty_rollup_allows(self):
        # no-CI repos (bridge/kit) and path-filtered umbrella PRs get zero checks.
        proc = self._run(_payload("gh pr merge 5 --repo o/r --squash"), pr=EMPTY)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_red_blocks(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r --squash"), pr=RED)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("BLOCKED", proc.stderr)
        self.assertIn("frontend: failure", proc.stderr)

    def test_pending_blocks(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=PENDING)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not finished", proc.stderr)

    def test_status_context_failure_blocks(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=STATUS_RED)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("legacy-status", proc.stderr)

    def test_rest_put_merge_gated(self):
        proc = self._run(_payload("gh api -X PUT repos/o/r/pulls/5/merge"), pr=RED)
        self.assertEqual(proc.returncode, 2)

    def test_compound_command_gated(self):
        proc = self._run(_payload("cd /tmp && gh pr merge 5 --repo o/r --squash"), pr=RED)
        self.assertEqual(proc.returncode, 2)

    # -- fail-closed once a merge is detected ----------------------------------
    def test_gh_failure_blocks(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), gh_exit=1)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("could not verify", proc.stderr)

    def test_gh_missing_blocks(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), no_gh=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("could not verify", proc.stderr)

    # -- escape hatch -----------------------------------------------------------
    def test_override_allows(self):
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=RED, override=True)
        self.assertEqual(proc.returncode, 0)


class Parser(unittest.TestCase):
    def parse(self, command):
        return hook_merge_gate._parse_merge_invocation(command)

    def test_selector_and_repo(self):
        got = self.parse("gh pr merge 12 --repo aiLabSolution/lis-control --squash")
        self.assertEqual(got, {"selector": "12", "repo": "aiLabSolution/lis-control"})

    def test_repo_equals_form(self):
        self.assertEqual(self.parse("gh pr merge 3 --repo=o/r"),
                         {"selector": "3", "repo": "o/r"})

    def test_short_repo_flag(self):
        self.assertEqual(self.parse("gh pr merge -R o/r 9 --merge"),
                         {"selector": "9", "repo": "o/r"})

    def test_value_flag_never_selector(self):
        got = self.parse('gh pr merge --subject "gh pr merge title" 7 -R o/r')
        self.assertEqual(got["selector"], "7")

    def test_branch_inferred_merge(self):
        self.assertEqual(self.parse("gh pr merge --squash"),
                         {"selector": None, "repo": None})

    def test_semicolon_stops_scan(self):
        got = self.parse("gh pr merge 5; echo done --repo x/y")
        self.assertEqual(got, {"selector": "5", "repo": None})

    def test_api_get_is_not_a_merge(self):
        self.assertIsNone(self.parse("gh api repos/o/r/pulls/5/merge"))

    def test_api_put_is_a_merge(self):
        self.assertEqual(self.parse("gh api --method PUT repos/o/r/pulls/5/merge"),
                         {"selector": "5", "repo": "o/r"})

    def test_api_method_equals_form(self):
        self.assertEqual(self.parse("gh api --method=put repos/o/r/pulls/5/merge"),
                         {"selector": "5", "repo": "o/r"})

    def test_unrelated_commands(self):
        for cmd in ("echo gh pr merge is fun? no --",
                    "git merge origin/main",
                    "gh pr view 5 --json state"):
            if cmd.startswith("echo"):
                continue  # echo'd text IS caught conservatively; see below
            self.assertIsNone(self.parse(cmd), cmd)

    def test_echoed_merge_text_is_caught_conservatively(self):
        # A false positive here fail-closes into a clear override path; that is
        # the accepted trade-off, so pin the behavior down.
        self.assertIsNotNone(self.parse("echo gh pr merge 5"))


if __name__ == "__main__":
    unittest.main()
