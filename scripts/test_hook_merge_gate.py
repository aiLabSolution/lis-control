#!/usr/bin/env python3
"""Tests for scripts/hook_merge_gate.py.

End-to-end cases drive the gate as a real subprocess with JSON on stdin — the
actual hook contract (stdin parsing, exit codes, stderr feedback) — with `gh`
faked by a shell stub first on PATH that replays a canned `gh pr view --json`
payload (or fails, for the fail-closed cases). Parser cases import the module
directly.
"""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_merge_gate
import local_ci

GATE = Path(__file__).resolve().parent / "hook_merge_gate.py"
LOCAL_CI = Path(__file__).resolve().parent / "local_ci.py"

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


def _payload(command, tool="Bash", cwd=None):
    payload = {"tool_name": tool, "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = cwd
    return json.dumps(payload)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.control = root / "control"
        scripts = self.control / "scripts"
        scripts.mkdir(parents=True)
        self.gate = scripts / "hook_merge_gate.py"
        self.gate.write_text(GATE.read_text())
        (scripts / "local_ci.py").write_text(LOCAL_CI.read_text())
        self.registry = self.control / "local_ci.json"
        self._write_registry("hosted")
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

    def _write_registry(self, mode, repositories=None):
        repositories = repositories or {"o/r": {"gate_required": True}}
        self.registry.write_text(json.dumps({
            "version": 1,
            "mode": mode,
            "repositories": repositories,
            "checks": [{
                "name": "hook-fixture",
                "repository": next(iter(repositories)),
                "paths": ["**"],
                "command": ["true"],
                "class": "fast",
                "timeout_seconds": 30,
            }],
        }))

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
            [sys.executable, str(self.gate)],
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

    # -- local-ci summary gate -------------------------------------------------
    def test_local_gate_required_repo_allows_green_summary_status_on_exact_head(self):
        self._write_registry("local")
        pr = _pr([
            {"__typename": "CheckRun", "name": "backend", "status": "COMPLETED",
             "conclusion": "SUCCESS"},
            {"__typename": "StatusContext", "context": "local-ci/summary",
             "state": "SUCCESS"},
        ])
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=pr)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_local_gate_required_repo_blocks_missing_summary_with_engine_command(self):
        self._write_registry("local")
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=GREEN)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("local-ci/summary", proc.stderr)
        self.assertIn(_SHA[:12], proc.stderr)
        self.assertIn(str(self.control / "scripts" / "local_ci.py"), proc.stderr)
        self.assertIn("https://github.com/o/r/pull/5", proc.stderr)
        self.assertIn("local_ci.py 5 --repo o/r", proc.stderr)
        self.assertIn("--repo o/r", proc.stderr)
        self.assertIn("--checkout /absolute/path/to/o-r-pr-5-checkout", proc.stderr)

    def test_local_gate_required_repo_blocks_empty_rollup(self):
        self._write_registry("local")
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=EMPTY)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing successful StatusContext", proc.stderr)

    def test_local_gate_required_repo_blocks_non_green_summary(self):
        self._write_registry("local")
        pr = _pr([
            {"__typename": "CheckRun", "name": "backend", "status": "COMPLETED",
             "conclusion": "SUCCESS"},
            {"__typename": "StatusContext", "context": "local-ci/summary",
             "state": "PENDING"},
        ])
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=pr)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("local-ci/summary is pending", proc.stderr)
        self.assertIn("--checkout /absolute/path/to/o-r-pr-5-checkout", proc.stderr)

    def test_local_check_run_named_summary_does_not_satisfy_status_requirement(self):
        self._write_registry("local")
        pr = _pr([
            {"__typename": "CheckRun", "name": "local-ci/summary",
             "status": "COMPLETED", "conclusion": "SUCCESS"},
        ])
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=pr)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing successful StatusContext", proc.stderr)

    def test_local_not_gate_required_repo_preserves_empty_rollup_pass(self):
        self._write_registry("local", {"o/r": {"gate_required": False}})
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=EMPTY)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_pr_url_resolves_repo_independently_of_payload_cwd(self):
        self._write_registry("local", {
            "wrong/repo": {"gate_required": False},
            "O/R": {"gate_required": True},
        })
        proc = self._run(
            _payload("gh pr merge 5 --repo o/r", cwd="/unrelated/component/worktree"),
            pr=GREEN,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("local-ci/summary", proc.stderr)

    def test_branch_inferred_merge_resolves_repo_from_pr_url(self):
        self._write_registry("local")
        proc = self._run(_payload("gh pr merge --squash"), pr=GREEN)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("local-ci/summary", proc.stderr)

    def test_partial_engine_evidence_cannot_unlock_local_merge_gate(self):
        self._write_registry("local")
        first = local_ci.CheckConfig(
            "first", "o/r", ("scripts/**",), ("true",), "fast", 30
        )
        second = local_ci.CheckConfig(
            "second", "o/r", ("scripts/**",), ("true",), "fast", 30
        )
        registry = local_ci.Registry(
            1,
            "local",
            {"o/r": local_ci.RepositoryConfig("o/r", True)},
            (first, second),
        )
        pr = local_ci.PullRequest(
            _SHA,
            "https://github.com/o/r/pull/5",
            "o/r",
            ("scripts/changed.py",),
            "b" * 40,
            "lis-285-test",
        )
        statuses = []

        @contextlib.contextmanager
        def locked(_path):
            yield

        def record_run(_checkout, selected, _pr, _host, _control_root):
            statuses.append({
                "__typename": "StatusContext",
                "context": f"local-ci/{selected.name}",
                "state": "SUCCESS",
            })
            return local_ci.CheckResult(selected.name, True, 0.1, "passed", None)

        with mock.patch("local_ci.resolve_pr", return_value=pr), mock.patch(
            "local_ci.verify_checkout"
        ), mock.patch("local_ci.preflight_memory"), mock.patch(
            "local_ci.global_lock", side_effect=locked
        ), mock.patch("local_ci.run_check", side_effect=record_run), mock.patch(
            "local_ci.post_status"
        ) as post, mock.patch("local_ci.publish_gist") as gist, mock.patch(
            "local_ci.socket.gethostname", return_value="ci-host"
        ), mock.patch("local_ci.time.monotonic", side_effect=[1.0, 2.0]):
            result = local_ci.run_engine(
                self.control,
                registry,
                "5",
                "o/r",
                Path(self.tmp.name) / "lock",
                ("first",),
                self.control,
            )

        self.assertEqual(result, 0)
        self.assertFalse(
            any(
                call.args[3] == "local-ci/summary"
                for call in post.call_args_list
            )
        )
        gist.assert_not_called()
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=_pr(statuses))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing successful StatusContext", proc.stderr)

    def test_missing_registry_fails_open_only_for_summary_check(self):
        self.registry.unlink()
        empty = self._run(_payload("gh pr merge 5 --repo o/r"), pr=EMPTY)
        red = self._run(_payload("gh pr merge 5 --repo o/r"), pr=RED)
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(red.returncode, 2)
        self.assertIn("frontend: failure", red.stderr)

    def test_unparseable_registry_fails_open_only_for_summary_check(self):
        self.registry.write_text("{not-json")
        empty = self._run(_payload("gh pr merge 5 --repo o/r"), pr=EMPTY)
        red = self._run(_payload("gh pr merge 5 --repo o/r"), pr=RED)
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(red.returncode, 2)
        self.assertIn("frontend: failure", red.stderr)

    def test_schema_invalid_registries_fail_open_only_for_summary_check(self):
        self._write_registry("local")
        valid = json.loads(self.registry.read_text())
        unknown_top_level = dict(valid, surprise=True)
        empty_checks = dict(valid, checks=[])
        unknown_check_field = json.loads(json.dumps(valid))
        unknown_check_field["checks"][0]["surprise"] = True

        for label, value in (
            ("unknown top-level field", unknown_top_level),
            ("empty checks", empty_checks),
            ("unknown check field", unknown_check_field),
        ):
            with self.subTest(label=label):
                self.registry.write_text(json.dumps(value))
                empty = self._run(_payload("gh pr merge 5 --repo o/r"), pr=EMPTY)
                red = self._run(_payload("gh pr merge 5 --repo o/r"), pr=RED)
                self.assertEqual(empty.returncode, 0, empty.stderr)
                self.assertEqual(red.returncode, 2)
                self.assertIn("frontend: failure", red.stderr)

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

    def test_rest_put_flag_first_gated(self):
        # adversarial-review P1: value flags before the endpoint must not hide it.
        proc = self._run(
            _payload("gh api -X PUT -f merge_method=squash repos/o/r/pulls/5/merge"),
            pr=RED,
        )
        self.assertEqual(proc.returncode, 2)

    def test_compound_command_gated(self):
        proc = self._run(_payload("cd /tmp && gh pr merge 5 --repo o/r --squash"), pr=RED)
        self.assertEqual(proc.returncode, 2)

    def test_bash_c_wrapper_gated(self):
        proc = self._run(_payload('bash -c "gh pr merge 5 --repo o/r"'), pr=RED)
        self.assertEqual(proc.returncode, 2)

    def test_cd_then_branch_inferred_blocks_even_when_green(self):
        # the hook would resolve the PR from the pre-cd cwd → wrong PR; fail closed.
        proc = self._run(_payload("cd /tmp && gh pr merge --squash"), pr=GREEN)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot tell which PR", proc.stderr)

    def test_cd_across_wrapper_boundary_blocks_even_when_green(self):
        # round-2 P2: the wrong-PR hazard one wrapper level down.
        proc = self._run(_payload("cd /tmp && bash -c 'gh pr merge --squash'"), pr=GREEN)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot tell which PR", proc.stderr)

    def test_glued_xput_rest_gated(self):
        # round-2 P1: pflag-glued method value (`-XPUT` is curl muscle memory).
        proc = self._run(_payload("gh api -XPUT repos/o/r/pulls/5/merge"), pr=RED)
        self.assertEqual(proc.returncode, 2)

    def test_wrapper_with_long_flag_gated(self):
        proc = self._run(
            _payload("bash --login -c 'gh pr merge 5 --repo o/r'"), pr=RED
        )
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
    def test_override_command_prefix_allows(self):
        # the route a session can actually take: the assignment token in the command.
        proc = self._run(
            _payload("LIS_MERGE_GATE_OVERRIDE=1 gh pr merge 5 --repo o/r"), pr=RED
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_override_env_form_allows(self):
        proc = self._run(
            _payload("env LIS_MERGE_GATE_OVERRIDE=1 gh pr merge 5 --repo o/r"), pr=RED
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_override_process_env_allows(self):
        # hook-process env (Claude Code startup env) — secondary path, still honored.
        proc = self._run(_payload("gh pr merge 5 --repo o/r"), pr=RED, override=True)
        self.assertEqual(proc.returncode, 0)

    def test_override_still_allows_missing_local_summary(self):
        self._write_registry("local")
        proc = self._run(
            _payload("LIS_MERGE_GATE_OVERRIDE=1 gh pr merge 5 --repo o/r"),
            pr=EMPTY,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class Parser(unittest.TestCase):
    def parse(self, command):
        return hook_merge_gate._parse_merge_invocations(command)

    def parse_one(self, command):
        targets = self.parse(command)
        self.assertEqual(len(targets), 1, targets)
        return targets[0]

    def test_selector_and_repo(self):
        got = self.parse_one("gh pr merge 12 --repo aiLabSolution/lis-control --squash")
        self.assertEqual(got, {"selector": "12", "repo": "aiLabSolution/lis-control"})

    def test_repo_equals_form(self):
        self.assertEqual(self.parse_one("gh pr merge 3 --repo=o/r"),
                         {"selector": "3", "repo": "o/r"})

    def test_short_repo_flag(self):
        self.assertEqual(self.parse_one("gh pr merge -R o/r 9 --merge"),
                         {"selector": "9", "repo": "o/r"})

    def test_glued_short_repo_flag(self):
        self.assertEqual(self.parse_one("gh pr merge 3 -R=o/r"),
                         {"selector": "3", "repo": "o/r"})

    def test_value_flag_never_selector(self):
        got = self.parse_one('gh pr merge --subject "gh pr merge title" 7 -R o/r')
        self.assertEqual(got["selector"], "7")

    def test_author_email_value_flag(self):
        got = self.parse_one("gh pr merge -A a@b.example 7 --repo o/r")
        self.assertEqual(got["selector"], "7")

    def test_branch_inferred_merge(self):
        self.assertEqual(self.parse_one("gh pr merge --squash"),
                         {"selector": None, "repo": None})

    def test_cd_marks_branch_inferred_ambiguous(self):
        got = self.parse_one("cd ../lis-control-lis-54 && gh pr merge --squash")
        self.assertTrue(got.get("ambiguous_cwd"))

    def test_cd_with_explicit_selector_not_ambiguous(self):
        got = self.parse_one("cd /tmp && gh pr merge 5 --repo o/r")
        self.assertNotIn("ambiguous_cwd", got)

    def test_semicolon_stops_scan(self):
        got = self.parse_one("gh pr merge 5; echo done --repo x/y")
        self.assertEqual(got, {"selector": "5", "repo": None})

    def test_every_merge_in_compound_collected(self):
        got = self.parse("gh pr merge 5 --repo o/r && gh pr merge 6 --repo o/r")
        self.assertEqual([t["selector"] for t in got], ["5", "6"])

    def test_help_yields_no_target(self):
        self.assertEqual(self.parse("gh pr merge --help"), [])

    def test_api_get_is_not_a_merge(self):
        self.assertEqual(self.parse("gh api repos/o/r/pulls/5/merge"), [])

    def test_api_put_is_a_merge(self):
        self.assertEqual(self.parse_one("gh api --method PUT repos/o/r/pulls/5/merge"),
                         {"selector": "5", "repo": "o/r"})

    def test_api_method_equals_form(self):
        self.assertEqual(self.parse_one("gh api --method=put repos/o/r/pulls/5/merge"),
                         {"selector": "5", "repo": "o/r"})

    def test_api_value_flags_before_endpoint(self):
        got = self.parse_one(
            'gh api -X PUT -H "Accept: application/vnd.github+json" '
            "-f merge_method=squash repos/o/r/pulls/5/merge"
        )
        self.assertEqual(got, {"selector": "5", "repo": "o/r"})

    def test_wrapper_shell_recursed(self):
        self.assertEqual(self.parse_one("/bin/bash -lc 'gh pr merge 5 --repo o/r'"),
                         {"selector": "5", "repo": "o/r"})

    def test_glued_method_put(self):
        self.assertEqual(self.parse_one("gh api -XPUT repos/o/r/pulls/5/merge"),
                         {"selector": "5", "repo": "o/r"})

    def test_glued_method_equals_put(self):
        self.assertEqual(self.parse_one("gh api -X=PUT repos/o/r/pulls/5/merge"),
                         {"selector": "5", "repo": "o/r"})

    def test_glued_method_get_is_not_a_merge(self):
        self.assertEqual(self.parse("gh api -XGET repos/o/r/pulls/5/merge"), [])

    def test_glued_repo_value_captured(self):
        # round-2 P1: `-Rother/red` must gate other/red, not the cwd repo.
        got = self.parse_one("gh pr merge 5 -Rother/red --squash")
        self.assertEqual(got, {"selector": "5", "repo": "other/red"})

    def test_dangling_value_flag_does_not_hide_next_merge(self):
        got = self.parse("gh pr merge 5 --repo o/r -t; gh pr merge 6 --repo o/r")
        self.assertEqual([t["selector"] for t in got], ["5", "6"])

    def test_dangling_api_flag_does_not_hide_next_api_merge(self):
        got = self.parse("gh api -f; gh api -X PUT repos/o/r/pulls/5/merge")
        self.assertEqual([t["selector"] for t in got], ["5"])

    def test_cd_across_wrapper_marks_ambiguous(self):
        got = self.parse_one("cd /tmp && bash -c 'gh pr merge --squash'")
        self.assertTrue(got.get("ambiguous_cwd"))

    def test_wrapper_long_flag_before_c(self):
        self.assertEqual(self.parse_one("bash --login -c 'gh pr merge 5 --repo o/r'"),
                         {"selector": "5", "repo": "o/r"})

    def test_query_string_endpoint_still_a_merge(self):
        self.assertEqual(self.parse_one('gh api -X PUT "repos/o/r/pulls/5/merge?f=1"'),
                         {"selector": "5", "repo": "o/r"})

    def test_unrelated_commands(self):
        for cmd in ("git merge origin/main",
                    "gh pr view 5 --json state",
                    "scripts/setup-githooks.sh"):
            self.assertEqual(self.parse(cmd), [], cmd)

    def test_echoed_merge_text_is_caught_conservatively(self):
        # A false positive here fail-closes into a clear override path; that is
        # the accepted trade-off, so pin the behavior down.
        self.assertTrue(self.parse("echo gh pr merge 5"))


if __name__ == "__main__":
    unittest.main()
