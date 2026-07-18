#!/usr/bin/env python3
"""Stdlib-only tests for the LIS-281 local CI engine."""

import contextlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_ci


SHA = "a" * 40
REPO_ROOT = Path(__file__).resolve().parents[1]
PR = local_ci.PullRequest(
    sha=SHA,
    url="https://github.com/aiLabSolution/lis-control/pull/281",
    repository="aiLabSolution/lis-control",
    changed_paths=("scripts/local_ci.py",),
)


def completed(argv=(), returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def check(
    name="scripts-tests",
    paths=("scripts/**",),
    check_class="fast",
    timeout=300,
    memory=None,
):
    return local_ci.CheckConfig(
        name=name,
        repository="aiLabSolution/lis-control",
        paths=tuple(paths),
        command=("python3", "-m", "unittest"),
        check_class=check_class,
        timeout_seconds=timeout,
        min_memory_mib=memory,
    )


def registry(*checks):
    configured = tuple(checks or (check(),))
    return local_ci.Registry(
        version=1,
        mode="hosted",
        repositories={
            "ailabsolution/lis-control": local_ci.RepositoryConfig(
                "aiLabSolution/lis-control", True
            )
        },
        checks=configured,
    )


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="local-ci-registry-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "local_ci.json"
        self.value = {
            "version": 1,
            "repositories": {
                "aiLabSolution/lis-control": {"gate_required": True}
            },
            "checks": [
                {
                    "name": "scripts-tests",
                    "repository": "aiLabSolution/lis-control",
                    "paths": ["scripts/**"],
                    "class": "fast",
                    "timeout_seconds": 300,
                    "command": ["python3", "-m", "unittest"],
                }
            ],
        }

    def write(self):
        self.path.write_text(json.dumps(self.value), encoding="utf-8")
        return local_ci.load_registry(self.path)

    def test_mode_defaults_to_hosted(self):
        parsed = self.write()
        self.assertEqual(parsed.mode, "hosted")
        self.assertTrue(parsed.repositories["ailabsolution/lis-control"].gate_required)

    def test_local_mode_is_valid(self):
        self.value["mode"] = "local"
        self.assertEqual(self.write().mode, "local")

    def test_unknown_top_level_field_rejected_loudly(self):
        self.value["surprise"] = True
        with self.assertRaisesRegex(local_ci.RegistryError, "unknown field.*surprise"):
            self.write()

    def test_unknown_repository_field_rejected_loudly(self):
        self.value["repositories"]["aiLabSolution/lis-control"]["surprise"] = True
        with self.assertRaisesRegex(local_ci.RegistryError, "unknown field.*surprise"):
            self.write()

    def test_unknown_check_field_rejected_loudly(self):
        self.value["checks"][0]["surprise"] = True
        with self.assertRaisesRegex(local_ci.RegistryError, "unknown field.*surprise"):
            self.write()

    def test_unknown_mode_rejected(self):
        self.value["mode"] = "sometimes"
        with self.assertRaisesRegex(local_ci.RegistryError, "hosted.*local"):
            self.write()

    def test_heavy_check_requires_memory_threshold(self):
        self.value["checks"][0]["class"] = "heavy"
        with self.assertRaisesRegex(local_ci.RegistryError, "require min_memory_mib"):
            self.write()

    def test_duplicate_check_name_rejected(self):
        self.value["checks"].append(dict(self.value["checks"][0]))
        with self.assertRaisesRegex(local_ci.RegistryError, "duplicate check"):
            self.write()


class CommittedRegistryTests(unittest.TestCase):
    def test_committed_registry_is_hosted_and_wires_exactly_one_tracer(self):
        parsed = local_ci.load_registry(REPO_ROOT / "local_ci.json")
        self.assertEqual(parsed.mode, "hosted")
        self.assertEqual([item.name for item in parsed.checks], ["scripts-tests"])
        self.assertEqual(
            parsed.checks[0].command,
            (
                "python3",
                "-m",
                "unittest",
                "discover",
                "-s",
                "scripts",
                "-p",
                "test_*.py",
                "-v",
            ),
        )


class SelectionTests(unittest.TestCase):
    def test_regular_recursive_pattern_matches(self):
        self.assertTrue(local_ci.path_matches("scripts/**", "scripts/local_ci.py"))

    def test_recursive_pattern_matches_bare_submodule_gitlink(self):
        self.assertTrue(local_ci.path_matches("edge/drivers/**", "edge/drivers"))

    def test_unrelated_bare_path_does_not_match(self):
        self.assertFalse(local_ci.path_matches("edge/drivers/**", "edge/sim"))

    def test_gitlink_change_selects_mapped_check(self):
        bridge = check("bridge-tests", paths=("edge/drivers/**",))
        selected = local_ci.select_checks(
            registry(bridge), "aiLabSolution/lis-control", ("edge/drivers",)
        )
        self.assertEqual([item.name for item in selected], ["bridge-tests"])

    def test_repository_is_part_of_selection(self):
        selected = local_ci.select_checks(
            registry(), "aiLabSolution/OpenELIS-Global-2", ("scripts/local_ci.py",)
        )
        self.assertEqual(selected, ())

    def test_explicit_check_runs_without_a_path_match(self):
        selected = local_ci.select_checks(
            registry(),
            "aiLabSolution/lis-control",
            ("README.md",),
            requested=("scripts-tests",),
        )
        self.assertEqual([item.name for item in selected], ["scripts-tests"])


class PullRequestTests(unittest.TestCase):
    @mock.patch("local_ci._run")
    def test_resolves_exact_head_and_changed_paths(self, run):
        run.return_value = completed(
            stdout=json.dumps(
                {
                    "headRefOid": SHA,
                    "url": PR.url,
                    "files": [{"path": "edge/drivers"}, {"path": "README.md"}],
                }
            )
        )
        value = local_ci.resolve_pr("281", "aiLabSolution/lis-control", Path("/x"))
        self.assertEqual(value.sha, SHA)
        self.assertEqual(value.repository, "aiLabSolution/lis-control")
        self.assertEqual(value.changed_paths, ("edge/drivers", "README.md"))
        argv = run.call_args.args[0]
        self.assertIn("headRefOid,url,files", argv)
        self.assertEqual(argv[-2:], ["--repo", "aiLabSolution/lis-control"])


class CheckoutVerificationTests(unittest.TestCase):
    @mock.patch("local_ci._run")
    def test_exact_clean_head_passes(self, run):
        run.side_effect = [completed(stdout=SHA + "\n"), completed(stdout="")]
        local_ci.verify_checkout(Path("/checkout"), SHA)
        status_argv = run.call_args_list[1].args[0]
        self.assertIn("--ignore-submodules=none", status_argv)
        self.assertIn("--untracked-files=all", status_argv)

    @mock.patch("local_ci._run")
    def test_head_not_equal_to_pr_head_refuses(self, run):
        run.return_value = completed(stdout="b" * 40 + "\n")
        with self.assertRaisesRegex(local_ci.LocalCIError, "does not equal the PR head"):
            local_ci.verify_checkout(Path("/checkout"), SHA)
        self.assertEqual(run.call_count, 1)

    @mock.patch("local_ci._run")
    def test_dirty_submodule_gitlink_refuses(self, run):
        run.side_effect = [
            completed(stdout=SHA + "\n"),
            completed(stdout=" M edge/drivers\n"),
        ]
        with self.assertRaisesRegex(local_ci.LocalCIError, "submodule gitlinks"):
            local_ci.verify_checkout(Path("/checkout"), SHA)

    @mock.patch("local_ci.post_status")
    @mock.patch("local_ci.verify_checkout")
    @mock.patch("local_ci.resolve_pr", return_value=PR)
    def test_dirty_or_mismatched_refusal_posts_no_status_or_gist(
        self, _resolve, verify, post
    ):
        for refusal in ("dirty worktree", "HEAD mismatch"):
            with self.subTest(refusal=refusal), mock.patch(
                "local_ci.publish_gist"
            ) as gist:
                verify.side_effect = local_ci.LocalCIError(refusal)
                with self.assertRaisesRegex(local_ci.LocalCIError, refusal):
                    local_ci.run_engine(
                        Path("/checkout"),
                        registry(),
                        "281",
                        None,
                        Path("/tmp/lock"),
                    )
                post.assert_not_called()
                gist.assert_not_called()


class MemoryPreflightTests(unittest.TestCase):
    def test_fast_checks_do_not_read_memory(self):
        with mock.patch("local_ci.available_memory_mib") as available:
            local_ci.preflight_memory([check()])
        available.assert_not_called()

    def test_heavy_refusal_is_actionable_and_never_stops_containers(self):
        heavy = check("core-backend", check_class="heavy", memory=8192)
        with self.assertRaises(local_ci.LocalCIError) as caught:
            local_ci.preflight_memory([heavy], available_mib=4096)
        message = str(caught.exception)
        self.assertIn("8192 MiB", message)
        self.assertIn("OpenELIS dev/site/proof stacks", message)
        self.assertIn("never stops containers", message)


class PublishingTests(unittest.TestCase):
    @mock.patch("local_ci._run", return_value=completed())
    def test_status_carries_host_duration_context_and_gist_link(self, run):
        local_ci.post_status(
            Path("/checkout"),
            PR.repository,
            SHA,
            "local-ci/scripts-tests",
            "success",
            "ci-host",
            12.25,
            "passed",
            "https://gist.github.com/secret",
        )
        argv = run.call_args.args[0]
        self.assertIn(f"repos/{PR.repository}/statuses/{SHA}", argv)
        self.assertIn("context=local-ci/scripts-tests", argv)
        self.assertIn("state=success", argv)
        description = next(item for item in argv if item.startswith("description="))
        self.assertIn("host=ci-host", description)
        self.assertIn("duration=12.2s", description)
        self.assertIn("target_url=https://gist.github.com/secret", argv)

    @mock.patch("local_ci._run")
    def test_gist_is_secret_by_default(self, run):
        run.return_value = completed(stdout="https://gist.github.com/secret\n")
        url = local_ci.publish_gist(Path("/checkout"), "scripts-tests", SHA, "log")
        self.assertEqual(url, "https://gist.github.com/secret")
        argv = run.call_args.args[0]
        self.assertNotIn("--public", argv)
        self.assertEqual(run.call_args.kwargs["input_text"], "log")

    @mock.patch("local_ci._run", return_value=completed(returncode=1, stderr="boom"))
    def test_gist_failure_gracefully_returns_no_link(self, _run):
        with mock.patch("sys.stderr"):
            self.assertIsNone(
                local_ci.publish_gist(Path("/checkout"), "scripts-tests", SHA, "log")
            )


class CheckExecutionTests(unittest.TestCase):
    @mock.patch("local_ci.time.monotonic", side_effect=[10.0, 12.5])
    @mock.patch("local_ci.subprocess.run")
    @mock.patch("local_ci.publish_gist", return_value="https://gist/secret")
    @mock.patch("local_ci.post_status")
    def test_check_posts_pending_then_green_with_evidence(
        self, post, gist, run, _clock
    ):
        run.return_value = completed(returncode=0, stdout="OK\n")
        result = local_ci.run_check(Path("/checkout"), check(), PR, "ci-host")
        self.assertTrue(result.passed)
        self.assertEqual(result.duration_seconds, 2.5)
        self.assertEqual(run.call_args.kwargs["timeout"], 300)
        self.assertEqual(post.call_args_list[0].args[4], "pending")
        final = post.call_args_list[1]
        self.assertEqual(final.args[3], "local-ci/scripts-tests")
        self.assertEqual(final.args[4], "success")
        self.assertEqual(final.args[5], "ci-host")
        self.assertEqual(final.args[6], 2.5)
        self.assertEqual(final.args[8], "https://gist/secret")
        self.assertIn("OK", gist.call_args.args[3])

    @mock.patch("local_ci.time.monotonic", side_effect=[10.0, 15.0])
    @mock.patch("local_ci.subprocess.run")
    @mock.patch("local_ci.publish_gist", return_value=None)
    @mock.patch("local_ci.post_status")
    def test_timeout_posts_red_without_a_gist_link(self, post, _gist, run, _clock):
        run.side_effect = subprocess.TimeoutExpired(["python3"], timeout=3, output="partial")
        result = local_ci.run_check(
            Path("/checkout"), check(timeout=3), PR, "ci-host"
        )
        self.assertFalse(result.passed)
        final = post.call_args_list[1]
        self.assertEqual(final.args[4], "failure")
        self.assertIn("timed out", final.args[7])
        self.assertIsNone(final.args[8])


class EngineTests(unittest.TestCase):
    @mock.patch("local_ci.publish_gist", return_value=None)
    @mock.patch("local_ci.post_status")
    @mock.patch("local_ci.run_check")
    @mock.patch("local_ci.preflight_memory")
    @mock.patch("local_ci.verify_checkout")
    @mock.patch("local_ci.resolve_pr", return_value=PR)
    def test_engine_runs_selected_checks_serially_and_posts_summary(
        self, _resolve, _verify, _memory, run_check_mock, post, _gist
    ):
        first = check("scripts-tests", paths=("scripts/**",))
        second = check("docs-test", paths=("scripts/**",))
        queued_results = [
            local_ci.CheckResult(first.name, True, 1.0, "passed", None),
            local_ci.CheckResult(second.name, True, 2.0, "passed", None),
        ]
        events = []

        @contextlib.contextmanager
        def locked(_path):
            events.append("lock-enter")
            yield
            events.append("lock-exit")

        def record_run(_root, selected, _pr, _host):
            events.append(selected.name)
            return queued_results.pop(0)

        with mock.patch("local_ci.global_lock", side_effect=locked), mock.patch(
            "local_ci.run_check", side_effect=record_run
        ), mock.patch("local_ci.socket.gethostname", return_value="ci-host"), mock.patch(
            "local_ci.time.monotonic", side_effect=[1.0, 4.0]
        ):
            result = local_ci.run_engine(
                Path("/checkout"),
                registry(first, second),
                "281",
                None,
                Path("/tmp/lock"),
            )
        self.assertEqual(result, 0)
        self.assertEqual(events, ["lock-enter", "scripts-tests", "docs-test", "lock-exit"])
        summary_calls = [
            call for call in post.call_args_list if call.args[3] == "local-ci/summary"
        ]
        self.assertEqual([call.args[4] for call in summary_calls], ["pending", "success"])
        self.assertEqual(summary_calls[-1].args[5], "ci-host")
        self.assertEqual(summary_calls[-1].args[6], 3.0)


if __name__ == "__main__":
    unittest.main()
