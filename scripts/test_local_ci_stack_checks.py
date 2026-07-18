#!/usr/bin/env python3
"""Contract tests for the Docker-backed local compose-stack checks."""

import os
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_ci_stack_checks as stacks


REPO_ROOT = Path(__file__).resolve().parents[1]


def completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess((), returncode, stdout, "")


class ComposeRecipeTests(unittest.TestCase):
    def setUp(self):
        self.layout = stacks.Layout.from_root(REPO_ROOT)

    def test_stage0_uses_pinned_source_and_never_the_retired_digest_overlay(self):
        rendered = [path.as_posix() for path in stacks.openelis_files(self.layout)]
        self.assertIn("core/openelis/build.docker-compose.yml", rendered[1])
        self.assertIn("core/openelis/.github/ci/ci.memory-limits.yml", rendered[2])
        self.assertNotIn("compose.bootstrap.yml", "\n".join(rendered))

    def test_site_bridge_isolation_overlay_is_last(self):
        files = stacks.bridge_files(self.layout)
        self.assertEqual(files[-1], REPO_ROOT / "deploy/ci/compose.local-ci-bridge.yml")
        overlay = files[-1].read_text(encoding="utf-8")
        self.assertIn("container_name: lis-local-ci-site-bridge", overlay)
        self.assertIn('"28442:8443"', overlay)
        self.assertIn('"22021:12021"', overlay)
        self.assertIn("name: lis-local-ci-site-bridge-data", overlay)

    def test_compose_command_is_exact_argv_with_explicit_project(self):
        command = stacks.compose_command(
            "proof",
            Path("/core"),
            (Path("/core/base.yml"), Path("/tmp/last.yml")),
            ("up", "-d", "--build"),
        )
        self.assertEqual(command[:6], (
            "docker", "compose", "--project-directory", "/core", "--project-name", "proof"
        ))
        self.assertEqual(command[-3:], ("up", "-d", "--build"))
        self.assertNotIn("sh", command)

    def test_site_environment_names_proof_resources_away_from_dev_defaults(self):
        environment = stacks.site_environment(self.layout, "secret")
        self.assertEqual(environment["LIS_SITE_NETWORK"], "lis-local-ci-site")
        self.assertEqual(environment["LIS_SITE_X3_BIND"], "22021")
        self.assertEqual(environment["LIS_SITE_BRIDGE_PROJECT"], "lis-local-ci-site-bridge")
        self.assertNotEqual(environment["LIS_SITE_NETWORK"], "lis-site")
        self.assertNotEqual(environment["LIS_SITE_X3_BIND"], "12021")

    def test_image_sanity_rejects_retired_floating_images(self):
        with self.assertRaisesRegex(stacks.StackCheckError, "floating"):
            stacks.image_list_sanity("one\ntwo\nthree:develop\n")


class TeardownTests(unittest.TestCase):
    def test_cleanup_trap_runs_lifo_on_red_check(self):
        events = []
        with self.assertRaisesRegex(RuntimeError, "deliberate"):
            with stacks.TeardownTrap() as trap:
                trap.add("first", lambda: events.append("first"))
                trap.add("second", lambda: events.append("second"))
                raise RuntimeError("deliberate red")
        self.assertEqual(events, ["second", "first"])

    def test_ownership_guard_detects_only_new_root_owned_paths(self):
        with mock.patch(
            "local_ci_stack_checks.root_owned_entries",
            side_effect=[frozenset({"old"}), frozenset({"old", "target/new"})],
        ):
            with self.assertRaisesRegex(stacks.StackCheckError, "target/new"):
                with stacks.ownership_guard(Path("/core")):
                    pass

    @mock.patch("local_ci_stack_checks.assert_objects_missing")
    @mock.patch("local_ci_stack_checks.assert_project_empty")
    @mock.patch("local_ci_stack_checks.run_logged", return_value=completed())
    def test_site_teardown_targets_only_proof_projects_and_names(
        self, run, assert_empty, assert_missing
    ):
        with tempfile.TemporaryDirectory() as temporary:
            layout = stacks.Layout.from_root(Path(temporary))
            environment = stacks.site_environment(layout, "secret")
            extra = stacks.render_site_properties(environment)
            with mock.patch("local_ci_stack_checks.wrapper_openelis_down"):
                stacks.site_down(layout, environment)
            self.assertFalse(extra.exists())
        bridge_command = run.call_args_list[0].args[0]
        self.assertIn(stacks.SITE_BRIDGE_PROJECT, bridge_command)
        self.assertIn("down", bridge_command)
        self.assertIn("-v", bridge_command)
        assert_empty.assert_called_with(mock.ANY, stacks.SITE_BRIDGE_PROJECT)
        flattened = " ".join(str(call) for call in assert_missing.call_args_list)
        self.assertIn(stacks.SITE_BRIDGE_CONTAINER, flattened)
        self.assertIn(stacks.SITE_BRIDGE_VOLUME, flattened)


class PinAndAcidTestTests(unittest.TestCase):
    def test_historical_red_and_green_shas_are_exact_and_distinct(self):
        self.assertRegex(stacks.HISTORICAL_STAGE4_RED_SHA, r"^[0-9a-f]{40}$")
        self.assertRegex(stacks.HISTORICAL_STAGE4_GREEN_SHA, r"^[0-9a-f]{40}$")
        self.assertNotEqual(
            stacks.HISTORICAL_STAGE4_RED_SHA, stacks.HISTORICAL_STAGE4_GREEN_SHA
        )

    def test_core_override_requires_exact_sha_and_is_stage4_only(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            parser_error = stacks.main(
                ["stage4-smoke", "--root", "/umbrella", "--core-checkout", "/core"]
            )
        self.assertEqual(parser_error, 2)
        with redirect_stderr(errors):
            other_check = stacks.main(
                [
                    "stage0-bootstrap",
                    "--root",
                    "/umbrella",
                    "--core-checkout",
                    "/core",
                    "--expected-core-sha",
                    "a" * 40,
                ]
            )
        self.assertEqual(other_check, 2)

    @mock.patch.dict(os.environ, {"LIS_LOCAL_CI_CHECKOUT": "/verified"}, clear=True)
    @mock.patch("local_ci_stack_checks.stage0_bootstrap")
    def test_registry_dispatch_uses_verified_umbrella_checkout(self, stage0):
        self.assertEqual(stacks.main(["stage0-bootstrap"]), 0)
        self.assertEqual(stage0.call_args.args[0].root, Path("/verified"))


if __name__ == "__main__":
    unittest.main()
