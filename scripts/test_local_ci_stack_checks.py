#!/usr/bin/env python3
"""Contract tests for the Docker-backed local compose-stack checks."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_ci_stack_checks as stacks
import local_ci_docker_shim as docker_shim


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
        self.assertTrue(rendered[-1].endswith("compose.local-ci-openelis.yml"))
        isolation = Path(rendered[-1]).read_text(encoding="utf-8")
        self.assertIn("/var/lib/openelis-global/programs", isolation)
        self.assertIn("lis-local-ci-openelis-programs", isolation)

    def test_final_overlay_redirects_configuration_bind_from_checkout(self):
        # docker-compose.yml binds ./configuration into the webapp; the source
        # directory is absent at current pins, so Docker would create it as a
        # root-owned directory inside the core checkout (caught live by the
        # ownership guard on the first local Stage-4 run).
        isolation = (REPO_ROOT / "deploy/ci/compose.local-ci-openelis.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("/var/lib/openelis-global/configuration", isolation)
        self.assertIn("lis-local-ci-openelis-configuration", isolation)
        self.assertIn("lis-local-ci-openelis-configuration", stacks.PROOF_VOLUMES)

    def test_site_bridge_isolation_overlay_replaces_dev_resources(self):
        overlay = (REPO_ROOT / "deploy/ci/compose.local-ci-bridge.yml").read_text(
            encoding="utf-8"
        )
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

    def test_docker_shim_appends_overlay_before_wrapper_subcommand(self):
        environment = {
            "LIS_LOCAL_CI_OPENELIS_ROOT": "/core",
            "LIS_LOCAL_CI_OPENELIS_OVERLAY": str(
                REPO_ROOT / "deploy/ci/compose.local-ci-openelis.yml"
            ),
        }
        original = (
            "compose",
            "--project-directory",
            "/core",
            "-f",
            "/core/docker-compose.yml",
            "up",
            "-d",
        )
        augmented = docker_shim.augment_argv(original, environment)
        self.assertEqual(
            augmented[-4:],
            (
                "-f",
                str(REPO_ROOT / "deploy/ci/compose.local-ci-openelis.yml"),
                "up",
                "-d",
            ),
        )

    def test_docker_shim_passes_non_compose_commands_unchanged(self):
        argv = ("ps", "--format", "{{.Names}}")
        self.assertEqual(docker_shim.augment_argv(argv, {}), argv)

    @mock.patch("local_ci_stack_checks.assert_site_bridge_proof_clean")
    @mock.patch("local_ci_stack_checks.assert_openelis_proof_clean")
    @mock.patch("local_ci_stack_checks.site_down")
    @mock.patch("local_ci_stack_checks.ownership_guard", side_effect=lambda _root: contextlib.nullcontext())
    @mock.patch("local_ci_stack_checks.run_logged", return_value=completed())
    @mock.patch("local_ci_stack_checks.require_docker", return_value="/bin/true")
    @mock.patch("local_ci_stack_checks.initialize_pins")
    def test_site_check_executes_canonical_wrapper_and_failure_script(
        self, _pins, _docker, run, _ownership, _down, _openelis_clean, _bridge_clean
    ):
        stacks.site_stack_smoke(self.layout)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn((str(stacks.site_wrapper(self.layout)), "config", "-q"), commands)
        self.assertIn((str(stacks.site_wrapper(self.layout)), "up"), commands)
        self.assertIn(
            (
                "bash",
                str(self.layout.kit / "scripts/prove-site-failure-modes.sh"),
            ),
            commands,
        )


class TeardownTests(unittest.TestCase):
    def test_each_stack_refuses_preexisting_proof_state_without_mutating_it(self):
        layout = stacks.Layout.from_root(REPO_ROOT)
        cases = (
            ("stage0", stacks.stage0_bootstrap),
            ("stage4", stacks.stage4_smoke),
            ("site", stacks.site_stack_smoke),
        )
        for label, check in cases:
            with self.subTest(check=label), mock.patch(
                "local_ci_stack_checks.initialize_pins"
            ), mock.patch(
                "local_ci_stack_checks.require_docker", return_value="/bin/true"
            ), mock.patch(
                "local_ci_stack_checks.ownership_guard",
                side_effect=lambda _root: contextlib.nullcontext(),
            ), mock.patch(
                "local_ci_stack_checks.assert_openelis_proof_clean",
                side_effect=stacks.StackCheckError("pre-existing proof state"),
            ), mock.patch(
                "local_ci_stack_checks.run_logged",
                return_value=completed(stdout="one\ntwo\nthree\n"),
            ) as run:
                with self.assertRaisesRegex(
                    stacks.StackCheckError, "pre-existing proof state"
                ):
                    check(layout)

            mutating = [
                call.args[0]
                for call in run.call_args_list
                if "up" in call.args[0] or "down" in call.args[0]
            ]
            self.assertEqual(
                mutating,
                [],
                f"{label} touched stale proof state instead of refusing it",
            )

    def test_site_refuses_any_preexisting_bridge_state_without_mutating_it(self):
        layout = stacks.Layout.from_root(REPO_ROOT)
        cases = (
            ("project", "project", stacks.SITE_BRIDGE_PROJECT),
            ("container", "container", stacks.SITE_BRIDGE_CONTAINER),
            ("volume", "volume", stacks.SITE_BRIDGE_VOLUME),
            ("network", "network", stacks.SITE_NETWORK),
        )
        for label, stale_kind, stale_name in cases:
            with self.subTest(state=label):
                def docker_state(argv, _cwd, **_kwargs):
                    if argv[:3] == ("docker", "ps", "-aq"):
                        if stale_kind == "project" and any(
                            stale_name in value for value in argv
                        ):
                            return completed(stdout="stale-bridge-container\n")
                        return completed()
                    if (
                        len(argv) > 3
                        and argv[0] == "docker"
                        and argv[2] == "inspect"
                    ):
                        kind, name = argv[1], argv[3]
                        if kind == stale_kind and name == stale_name:
                            return completed()
                        return completed(1, f"No such {kind}: {name}\n")
                    return completed()

                with mock.patch(
                    "local_ci_stack_checks.initialize_pins"
                ), mock.patch(
                    "local_ci_stack_checks.require_docker", return_value="/bin/true"
                ), mock.patch(
                    "local_ci_stack_checks.assert_openelis_proof_clean"
                ), mock.patch(
                    "local_ci_stack_checks.ownership_guard",
                    side_effect=lambda _root: contextlib.nullcontext(),
                ), mock.patch(
                    "local_ci_stack_checks.run_logged", side_effect=docker_state
                ) as run:
                    with self.assertRaises(stacks.StackCheckError) as caught:
                        stacks.site_stack_smoke(layout)

                self.assertIn(stale_name, str(caught.exception))
                mutating = [
                    call.args[0]
                    for call in run.call_args_list
                    if "up" in call.args[0] or "down" in call.args[0]
                ]
                self.assertEqual(mutating, [])

    @mock.patch("local_ci_stack_checks.run_logged")
    def test_object_absence_requires_confirmed_docker_not_found(self, run):
        run.side_effect = [
            completed(
                1,
                "[]\nError response from daemon: get confirmed-absent: "
                "no such volume\n",
            ),
            completed(
                1,
                "permission denied while trying to connect to the Docker daemon socket\n",
            ),
        ]

        with self.assertRaisesRegex(
            stacks.StackCheckError, "indeterminate.*permission denied"
        ):
            stacks.assert_objects_missing(
                REPO_ROOT, "volume", ("confirmed-absent", "indeterminate")
            )

        self.assertEqual(run.call_count, 2)

    def test_deadline_terminates_nested_command_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            pid_file = Path(temporary) / "child.pid"
            command = (
                sys.executable,
                "-c",
                (
                    "import pathlib, subprocess, sys; "
                    "child = subprocess.Popen(['sleep', '30']); "
                    "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); "
                    "child.wait()"
                ),
                str(pid_file),
            )
            with mock.patch.object(stacks, "TIMEOUT_CLEANUP_RESERVE_SECONDS", 0):
                with self.assertRaisesRegex(
                    stacks.StackCheckError, "beginning teardown"
                ):
                    with stacks.graceful_deadline(1):
                        stacks.run_logged(command, Path(temporary), quiet=True)

            child_pid = int(pid_file.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 2
            while self._process_is_running(child_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(
                self._process_is_running(child_pid),
                f"nested process {child_pid} survived the command deadline",
            )

    @staticmethod
    def _process_is_running(pid: int) -> bool:
        try:
            state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
        except FileNotFoundError:
            return False
        return state != "Z"

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

    @mock.patch("local_ci_stack_checks.assert_openelis_proof_clean")
    @mock.patch("local_ci_stack_checks.assert_objects_missing")
    @mock.patch("local_ci_stack_checks.assert_project_empty")
    @mock.patch("local_ci_stack_checks.run_logged", return_value=completed(1, "down failed"))
    def test_site_teardown_attempts_every_cleanup_after_wrapper_failure(
        self, run, assert_empty, assert_missing, assert_oe
    ):
        with tempfile.TemporaryDirectory() as temporary:
            layout = stacks.Layout.from_root(Path(temporary))
            environment = stacks.site_environment(layout, "secret")
            extra = Path(environment["LIS_SITE_EXTRA_PROPERTIES"])
            extra.parent.mkdir(parents=True)
            extra.write_text("secret", encoding="utf-8")
            with self.assertRaisesRegex(stacks.StackCheckError, "wrapper teardown"):
                stacks.site_down(layout, environment)
            self.assertFalse(extra.exists())
        self.assertEqual(
            run.call_args_list[0].args[0],
            (str(stacks.site_wrapper(layout)), "down", "-v"),
        )
        assert_oe.assert_called_once_with(mock.ANY, stacks.SITE_OE_PROJECT)
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
