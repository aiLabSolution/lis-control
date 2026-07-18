#!/usr/bin/env python3
"""Stdlib-only tests for the LIS-282 local CI fast-check implementations."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_ci_fast_checks as fast


SHA_A = "a" * 40
SHA_B = "b" * 40


def completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess([], returncode, stdout, "")


class RunCheckedTests(unittest.TestCase):
    @mock.patch("local_ci_fast_checks.subprocess.run")
    def test_argv_cwd_environment_and_output_are_preserved(self, run):
        run.return_value = completed(stdout="evidence\n")
        with mock.patch("builtins.print") as output:
            value = fast.run_checked(
                ("tool", "two words"), cwd=Path("/work"), env={"EXACT": "yes"}
            )
        self.assertEqual(value, "evidence\n")
        self.assertEqual(run.call_args.args[0], ["tool", "two words"])
        self.assertEqual(run.call_args.kwargs["cwd"], "/work")
        self.assertEqual(run.call_args.kwargs["env"], {"EXACT": "yes"})
        self.assertTrue(output.called)

    @mock.patch("local_ci_fast_checks.subprocess.run", return_value=completed(7, "bad\n"))
    def test_nonzero_command_is_a_clear_check_failure(self, _run):
        with mock.patch("builtins.print"), self.assertRaisesRegex(
            fast.FastCheckError, "exit 7.*tool"
        ):
            fast.run_checked(("tool",), cwd=Path("/work"))


class GitlinkTests(unittest.TestCase):
    def test_exact_initialized_gitlink_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "core/openelis").mkdir(parents=True)
            with mock.patch("local_ci_fast_checks.git_output", side_effect=[SHA_A, SHA_A]):
                self.assertEqual(
                    fast.assert_gitlink(root, "core/openelis"), root / "core/openelis"
                )

    def test_mismatched_gitlink_names_both_shas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "deploy/kit").mkdir(parents=True)
            with mock.patch("local_ci_fast_checks.git_output", side_effect=[SHA_A, SHA_B]):
                with self.assertRaisesRegex(fast.FastCheckError, f"{SHA_B}.*{SHA_A}"):
                    fast.assert_gitlink(root, "deploy/kit")

    def test_uninitialized_gitlink_fails_before_git(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "local_ci_fast_checks.git_output"
        ) as git:
            with self.assertRaisesRegex(fast.FastCheckError, "not initialized"):
                fast.assert_gitlink(Path(tmp), "core/openelis")
            git.assert_not_called()


class ProfileDriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.control = Path(self.tmp.name)
        self.core = self.control / "core"
        self.kit = self.control / "kit"
        self.core_profiles = self.core / "projects/analyzer-profiles/hl7"
        self.kit_profiles = self.kit / "configs/analyzer-profiles/hl7"
        self.core_profiles.mkdir(parents=True)
        self.kit_profiles.mkdir(parents=True)
        (self.control / "deploy/ci").mkdir(parents=True)
        self.allowlist = self.control / "deploy/ci/profile-drift-allowlist.txt"
        self.allowlist.write_text("", encoding="utf-8")

    def test_equal_profiles_pass_and_core_only_is_informational(self):
        (self.core_profiles / "same.json").write_text("{}", encoding="utf-8")
        (self.kit_profiles / "same.json").write_text("{}", encoding="utf-8")
        (self.core_profiles / "future.json").write_text("{}", encoding="utf-8")
        fast.check_profile_drift(self.control, self.core, self.kit)

    def test_unacknowledged_drift_and_kit_only_fail_together(self):
        (self.core_profiles / "drift.json").write_text('{"v": 1}', encoding="utf-8")
        (self.kit_profiles / "drift.json").write_text('{"v": 2}', encoding="utf-8")
        (self.kit_profiles / "kit-only.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(fast.FastCheckError) as caught:
            fast.check_profile_drift(self.control, self.core, self.kit)
        self.assertIn("profile drift", str(caught.exception))
        self.assertIn("kit-only", str(caught.exception))

    def test_allowlist_accepts_drift_with_reason(self):
        (self.core_profiles / "drift.json").write_text('{"v": 1}', encoding="utf-8")
        (self.kit_profiles / "drift.json").write_text('{"v": 2}', encoding="utf-8")
        self.allowlist.write_text("hl7/drift.json LIS-99 intentional\n", encoding="utf-8")
        fast.check_profile_drift(self.control, self.core, self.kit)

    def test_allowlist_rejects_parent_traversal(self):
        self.allowlist.write_text("../escape.json nope\n", encoding="utf-8")
        with self.assertRaisesRegex(fast.FastCheckError, "relative POSIX"):
            fast.read_allowlist(self.allowlist)


class KitLintPrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_analyzer_profile_json_validation_reports_bad_file(self):
        profiles = self.root / "profiles"
        profiles.mkdir()
        (profiles / "good.json").write_text("{}", encoding="utf-8")
        (profiles / "bad.json").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(fast.FastCheckError, "bad.json"):
            fast.validate_json_files(profiles)

    def test_plugin_checksum_passes(self):
        plugins = self.root / "plugins"
        plugins.mkdir()
        payload = b"jar"
        (plugins / "plugin.jar").write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        (plugins / "plugin.jar.sha256").write_text(
            f"{digest}  plugin.jar\n", encoding="utf-8"
        )
        fast.verify_plugin_checksums(plugins)

    def test_plugin_checksum_mismatch_names_artifact(self):
        plugins = self.root / "plugins"
        plugins.mkdir()
        (plugins / "plugin.jar").write_bytes(b"jar")
        (plugins / "plugin.jar.sha256").write_text(
            f"{'0' * 64}  plugin.jar\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(fast.FastCheckError, "plugin.jar sha256 mismatch"):
            fast.verify_plugin_checksums(plugins)

    def test_plugin_jar_without_own_sidecar_fails(self):
        plugins = self.root / "plugins"
        plugins.mkdir()
        checked_payload = b"checked"
        (plugins / "checked.jar").write_bytes(checked_payload)
        (plugins / "checked.jar.sha256").write_text(
            f"{hashlib.sha256(checked_payload).hexdigest()}  checked.jar\n",
            encoding="utf-8",
        )
        (plugins / "orphan.jar").write_bytes(b"not pinned")
        with self.assertRaisesRegex(
            fast.FastCheckError,
            "orphan[.]jar: missing required checksum sidecar orphan[.]jar[.]sha256",
        ):
            fast.verify_plugin_checksums(plugins)

    def test_plugin_sidecar_targeting_different_jar_fails(self):
        plugins = self.root / "plugins"
        plugins.mkdir()
        checked_payload = b"checked"
        checked_digest = hashlib.sha256(checked_payload).hexdigest()
        (plugins / "checked.jar").write_bytes(checked_payload)
        (plugins / "orphan.jar").write_bytes(b"not pinned")
        for sidecar in ("checked.jar.sha256", "orphan.jar.sha256"):
            (plugins / sidecar).write_text(
                f"{checked_digest}  checked.jar\n", encoding="utf-8"
            )
        with self.assertRaisesRegex(
            fast.FastCheckError,
            "orphan[.]jar[.]sha256: must contain a sha256 entry for its own "
            "artifact orphan[.]jar",
        ):
            fast.verify_plugin_checksums(plugins)

    def test_kit_lint_runs_shellcheck_syntax_json_and_checksum(self):
        for directory in ("scripts", "tests"):
            (self.root / directory).mkdir()
            (self.root / directory / f"{directory}.sh").write_text(
                "#!/bin/sh\n", encoding="utf-8"
            )
        with mock.patch("local_ci_fast_checks.shellcheck") as shellcheck, mock.patch(
            "local_ci_fast_checks.bash_syntax"
        ) as syntax, mock.patch("local_ci_fast_checks.validate_json_files") as jsons, mock.patch(
            "local_ci_fast_checks.verify_plugin_checksums"
        ) as checksums:
            fast.kit_lint(self.root)
        shellcheck.assert_called_once()
        syntax.assert_called_once()
        jsons.assert_called_once_with(self.root / "configs/analyzer-profiles")
        checksums.assert_called_once_with(self.root / "configs/plugins")


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.languages = self.root / "frontend/src/languages"
        self.languages.mkdir(parents=True)

    def test_duplicate_key_in_nested_object_fails_with_file_and_key(self):
        (self.languages / "fr.json").write_text(
            '{"outer": {"same": 1, "same": 2}}', encoding="utf-8"
        )
        with self.assertRaises(fast.FastCheckError) as caught:
            fast.check_language_json(self.languages)
        self.assertIn("fr.json", str(caught.exception))
        self.assertIn("same", str(caught.exception))

    @mock.patch("local_ci_fast_checks.git_output")
    def test_non_english_change_relative_to_exact_base_fails(self, git):
        (self.languages / "en.json").write_text("{}", encoding="utf-8")
        git.side_effect = [SHA_B, "frontend/src/languages/fr.json\n"]
        with self.assertRaisesRegex(fast.FastCheckError, "fr.json"):
            fast.core_i18n(self.root, SHA_A, SHA_B, "feature")
        diff_call = git.call_args_list[1]
        self.assertIn(f"{SHA_A}...{SHA_B}", diff_call.args)

    @mock.patch("local_ci_fast_checks.git_output", return_value=SHA_B)
    def test_transifex_branch_skips_diff_but_still_checks_json(self, git):
        (self.languages / "en.json").write_text("{}", encoding="utf-8")
        fast.core_i18n(self.root, SHA_A, SHA_B, "chore/update-transifex")
        git.assert_called_once_with(self.root, "rev-parse", "HEAD")

    @mock.patch("local_ci_fast_checks.git_output", return_value=SHA_A)
    def test_wrong_checkout_head_fails_before_diff(self, git):
        (self.languages / "en.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(fast.FastCheckError, "expected exact PR head"):
            fast.core_i18n(self.root, SHA_A, SHA_B, "feature")
        git.assert_called_once()


class ComposeRenderTests(unittest.TestCase):
    def test_three_models_use_versioned_compose_and_docker_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp)
            core = control / "core/openelis"
            kit = control / "deploy/kit"
            bridge = control / "edge/drivers"
            for path in (core, kit / "scripts", bridge):
                path.mkdir(parents=True)
            (bridge / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
            calls = []

            def record(argv, *, cwd, env=None):
                calls.append((tuple(argv), cwd, dict(env or {})))
                return ""

            with mock.patch("local_ci_fast_checks.run_checked", side_effect=record):
                fast.render_compose_models(control, core, kit, bridge)
        self.assertEqual(len(calls), 3)
        self.assertTrue(
            all(
                call[0][:4] == ("mise", "x", fast.COMPOSE_TOOL, "--")
                for call in calls
            )
        )
        self.assertNotIn("LIS_DEPLOY_USE_LOCAL_PROOF", calls[0][2])
        self.assertEqual(calls[1][2]["LIS_DEPLOY_USE_LOCAL_PROOF"], "true")
        self.assertTrue(calls[2][0][-3].endswith("compose-site.sh"))
        self.assertTrue(all(call[2]["PATH"] for call in calls))


class DeployKitConfigTests(unittest.TestCase):
    @mock.patch("local_ci_fast_checks.render_compose_models")
    @mock.patch("local_ci_fast_checks.run_wrapper_harnesses")
    @mock.patch("local_ci_fast_checks.shellcheck")
    @mock.patch("local_ci_fast_checks.shell_scripts", return_value=(Path("x.sh"),))
    @mock.patch("local_ci_fast_checks.check_profile_drift")
    @mock.patch("local_ci_fast_checks.assert_gitlink")
    def test_asserts_all_three_gitlinks_before_comparison_and_render(
        self, gitlink, drift, _scripts, _shellcheck, _harnesses, render
    ):
        control = Path("/control")
        core = control / "core/openelis"
        kit = control / "deploy/kit"
        bridge = control / "edge/drivers"
        gitlink.side_effect = [core, kit, bridge]
        fast.deploy_kit_config(control)
        self.assertEqual(
            [call.args[1] for call in gitlink.call_args_list],
            ["core/openelis", "deploy/kit", "edge/drivers"],
        )
        drift.assert_called_once_with(control, core, kit)
        render.assert_called_once_with(control, core, kit, bridge)


class BridgeTests(unittest.TestCase):
    @mock.patch("local_ci_fast_checks.shutil.which", return_value="/usr/bin/docker")
    @mock.patch("local_ci_fast_checks.Path.home")
    @mock.patch("local_ci_fast_checks.run_checked")
    def test_bridge_uses_core_verify_docker_recipe_library_first(
        self, run, home, _docker
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / ".m2"
            cache.mkdir()
            checkout = root / "bridge"
            checkout.mkdir()
            home.return_value = root
            fast.bridge_tests(checkout)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ("docker", "run", "--rm"))
        self.assertIn("--network", argv)
        self.assertIn("host", argv)
        self.assertIn(f"{checkout}:/work", argv)
        self.assertIn(f"{cache}:/mvnhome/.m2", argv)
        self.assertIn(fast.MAVEN_IMAGE, argv)
        script = argv[-1]
        self.assertLess(script.index("astm-http-lib/pom.xml"), script.index("mvn -B", 10))
        self.assertIn("-DskipTests && mvn", script)
        self.assertIn("-DargLine=", script)

    @mock.patch("local_ci_fast_checks.shutil.which", return_value=None)
    @mock.patch("local_ci_fast_checks.Path.home")
    @mock.patch("local_ci_fast_checks.run_checked")
    def test_bridge_falls_back_to_pinned_mise_tools_without_docker(
        self, run, home, _docker
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".m2").mkdir()
            checkout = root / "bridge"
            checkout.mkdir()
            home.return_value = root
            fast.bridge_tests(checkout)
        self.assertEqual(run.call_count, 2)
        library = run.call_args_list[0].args[0]
        application = run.call_args_list[1].args[0]
        self.assertEqual(library[:4], ("mise", "x", fast.JAVA_TOOL, fast.MAVEN_TOOL))
        self.assertIn("astm-http-lib/pom.xml", library)
        self.assertIn("clean", library)
        self.assertIn("-DskipTests", library)
        self.assertIn("test", application)
        self.assertIn("-DargLine=-Xmx1300m -Djava.net.preferIPv6Addresses=true", application)


class MainTests(unittest.TestCase):
    @mock.patch("local_ci_fast_checks.run_checked")
    def test_edge_sim_uses_frozen_python_312_uv_command(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(fast.main(["edge-sim", "--checkout", tmp]), 0)
        self.assertEqual(
            run.call_args.args[0],
            ("uv", "run", "--frozen", "--python", "3.12", "pytest", "-q"),
        )
        self.assertEqual(run.call_args.kwargs["cwd"], Path(tmp) / "edge/sim")

    @mock.patch("local_ci_fast_checks.core_i18n")
    def test_runner_metadata_supplies_standalone_core_arguments(self, core_i18n):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "LIS_LOCAL_CI_CHECKOUT": tmp,
                "LIS_LOCAL_CI_BASE_SHA": SHA_A,
                "LIS_LOCAL_CI_HEAD_SHA": SHA_B,
                "LIS_LOCAL_CI_HEAD_BRANCH": "feature",
            },
            clear=False,
        ):
            self.assertEqual(fast.main(["core-i18n"]), 0)
        core_i18n.assert_called_once_with(Path(tmp), SHA_A, SHA_B, "feature")

    @mock.patch("local_ci_fast_checks.deploy_kit_config")
    def test_umbrella_config_uses_verified_checkout_not_runner_root(self, config):
        self.assertEqual(
            fast.main(
                [
                    "deploy-kit-config",
                    "--checkout",
                    "/exact-umbrella",
                    "--control-root",
                    "/runner",
                ]
            ),
            0,
        )
        config.assert_called_once_with(Path("/exact-umbrella"))

    @mock.patch("local_ci_fast_checks.kit_lint")
    @mock.patch("local_ci_fast_checks.assert_gitlink")
    def test_umbrella_kit_pin_runs_lint_in_exact_gitlink(self, gitlink, lint):
        kit = Path("/control/deploy/kit")
        gitlink.return_value = kit
        with mock.patch.dict(
            os.environ,
            {"LIS_LOCAL_CI_REPOSITORY": "aiLabSolution/lis-control"},
            clear=False,
        ):
            self.assertEqual(
                fast.main(
                    [
                        "kit-lint",
                        "--checkout",
                        "/control",
                        "--control-root",
                        "/runner",
                    ]
                ),
                0,
            )
        gitlink.assert_called_once_with(Path("/control"), "deploy/kit")
        lint.assert_called_once_with(kit)

    @mock.patch("local_ci_fast_checks.bridge_tests")
    @mock.patch("local_ci_fast_checks.assert_gitlink")
    def test_umbrella_bridge_pin_runs_tests_in_exact_gitlink(self, gitlink, tests):
        bridge = Path("/control/edge/drivers")
        gitlink.return_value = bridge
        with mock.patch.dict(
            os.environ,
            {"LIS_LOCAL_CI_REPOSITORY": "aiLabSolution/lis-control"},
            clear=False,
        ):
            self.assertEqual(
                fast.main(
                    [
                        "bridge-tests",
                        "--checkout",
                        "/control",
                        "--control-root",
                        "/runner",
                    ]
                ),
                0,
            )
        gitlink.assert_called_once_with(Path("/control"), "edge/drivers")
        tests.assert_called_once_with(bridge)


if __name__ == "__main__":
    unittest.main()
