#!/usr/bin/env python3
"""Tests for the Docker-only LIS local-CI core heavy checks."""

import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_ci_heavy_checks as heavy


def completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess((), returncode, stdout, "")


class DockerRecipeTests(unittest.TestCase):
    def test_core_maven_recipe_is_pinned_ipv6_cached_and_nonroot(self):
        command = heavy.maven_docker_command(
            Path("/core"),
            "dataexport",
            ("clean", "install"),
            uid=1000,
            gid=1000,
            docker_gid=967,
            include_socket=True,
            settings_file=Path("/host/settings.xml"),
        )
        self.assertEqual(command[:3], ("docker", "run", "--rm"))
        self.assertIn(heavy.MAVEN_IMAGE, command)
        self.assertIn("host", command)
        self.assertIn("1000:1000", command)
        self.assertIn("967", command)
        self.assertIn("HOME=/mvnhome", command)
        self.assertIn(
            "MAVEN_OPTS=-Xmx700m -Djava.net.preferIPv6Addresses=true", command
        )
        self.assertIn("TESTCONTAINERS_RYUK_DISABLED=true", command)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", command)
        self.assertIn(
            f"{heavy.MAVEN_CACHE_VOLUME}:/mvnhome/.m2/repository", command
        )
        self.assertIn("/host/settings.xml:/mvnhome/.m2/settings.xml:ro", command)
        self.assertIn("--settings", command)
        self.assertIn("/mvnhome/.m2/settings.xml", command)
        self.assertIn("/core:/work", command)
        self.assertIn("/work/dataexport", command)
        self.assertIn("-Dmaven.repo.local=/mvnhome/.m2/repository", command)

    def test_spotless_scope_excludes_npm_prettier_markdown(self):
        pattern = re.compile(heavy.SPOTLESS_BACKEND_FILES_REGEX)
        # The Maven image has no npm; any .md in scope re-breaks the check the
        # way core main 670644335 proved (FIXTURE_LOADER_README.md).
        self.assertIsNone(
            pattern.fullmatch("/work/src/test/resources/FIXTURE_LOADER_README.md")
        )
        self.assertIsNone(pattern.fullmatch("/work/fhir/README.md"))
        self.assertIsNotNone(
            pattern.fullmatch("/work/src/main/java/org/openelisglobal/Foo.java")
        )
        self.assertIsNotNone(
            pattern.fullmatch("/work/src/test/resources/testdata/fixture.xml")
        )
        self.assertIsNotNone(pattern.fullmatch("/work/pom.xml"))

    def test_frontend_is_a_host_network_production_image_build_without_push(self):
        command = heavy.frontend_docker_command(Path("/core"), "a" * 40)
        self.assertEqual(command[:3], ("docker", "build", "--network"))
        self.assertIn("host", command)
        self.assertIn("/core/frontend/Dockerfile", command)
        self.assertEqual(command[-1], "/core/frontend")
        self.assertNotIn("--push", command)


class FormatterTests(unittest.TestCase):
    def test_known_formatter_download_timeout_retries_once(self):
        flaky = completed(
            1,
            "Failed to load eclipse jdt formatter: java.net.SocketTimeoutException",
        )
        with mock.patch(
            "local_ci_heavy_checks.run_logged", side_effect=[flaky, completed()]
        ) as run:
            result = heavy.run_spotless_with_retry(("docker", "run"), Path("/core"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_count, 2)

    def test_non_formatter_failure_is_not_retried(self):
        with mock.patch(
            "local_ci_heavy_checks.run_logged", return_value=completed(1, "bad pom")
        ) as run:
            result = heavy.run_spotless_with_retry(("docker", "run"), Path("/core"))
        self.assertEqual(result.returncode, 1)
        run.assert_called_once()


class BaselineAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.core = Path(self.tmp.name)
        self.reports = self.core / "target/surefire-reports"
        self.reports.mkdir(parents=True)

    def write_report(self, cases):
        rows = []
        for classname, name, outcome in cases:
            child = f"<{outcome} message='boom'/>" if outcome else ""
            rows.append(
                f"<testcase classname='{classname}' name='{name}'>{child}</testcase>"
            )
        (self.reports / "TEST-suite.xml").write_text(
            "<testsuite>" + "".join(rows) + "</testsuite>", encoding="utf-8"
        )

    def test_only_the_exact_known_baseline_tests_are_allowlisted(self):
        self.assertEqual(
            heavy.BASELINE_FLAKES,
            {
                "ObservationFacadeTest.createObservation_shouldCreateNewResult",
                "OrderEntryLabelRequestServiceAggregationTest."
                "ac13_columnOrdering_systemFirstThenCustomAlphabetical",
                "OrderEntryLabelRequestServiceAggregationTest."
                "determinism_sameInputsProduceSameOutput",
                "OrderEntryLabelRequestServiceAggregationTest."
                "fr014a_seededSpecimenLabel_isSampleColumn_onNoLinkOrder",
                "AnalyzerResultsAcceptUnmatchedGateTest."
                "acceptNoSampleGroup_withConfirmation_persistsUnderUnknownPatientWithAuditNote",
                "AnalyzerResultsAcceptUnmatchedGateTest."
                "secondArrivalOnAnalyzerCreatedSample_stillRequiresConfirmation",
            },
        )
        cases = []
        for test_id in sorted(heavy.BASELINE_FLAKES):
            classname, name = test_id.rsplit(".", 1)
            cases.append(("org.openelisglobal." + classname, name, "failure"))
        self.write_report(cases)
        self.assertEqual(heavy.failed_test_ids(self.core), heavy.BASELINE_FLAKES)
        self.assertTrue(heavy.can_absorb(heavy.failed_test_ids(self.core)))

    def test_unknown_failure_cannot_be_absorbed(self):
        self.write_report([("org.openelisglobal.OtherTest", "broken", "error")])
        self.assertFalse(heavy.can_absorb(heavy.failed_test_ids(self.core)))

    def test_absorption_is_loud_and_writes_status_detail(self):
        detail = self.core / "detail.txt"
        output = io.StringIO()
        with redirect_stdout(output):
            heavy.report_absorption(heavy.BASELINE_FLAKES, detail)
        self.assertIn("BASELINE FLAKE ALLOWLIST ABSORBED", output.getvalue())
        for test_id in heavy.BASELINE_FLAKES:
            self.assertIn(test_id, output.getvalue())
        self.assertEqual(
            detail.read_text(encoding="utf-8").strip(),
            "passed; absorbed 6 baseline flakes",
        )


class MainTests(unittest.TestCase):
    def core_checkout(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        core = Path(temporary.name)
        (core / "pom.xml").write_text("<project/>", encoding="utf-8")
        (core / "dataexport").mkdir()
        (core / "dataexport/pom.xml").write_text("<project/>", encoding="utf-8")
        return core

    def test_core_backend_requires_docker_and_socket(self):
        with mock.patch("local_ci_heavy_checks.shutil.which", return_value=None):
            with self.assertRaisesRegex(heavy.HeavyCheckError, "Docker CLI"):
                heavy.require_docker(require_socket=True)

        with mock.patch(
            "local_ci_heavy_checks.shutil.which", return_value="/usr/bin/docker"
        ), mock.patch(
            "local_ci_heavy_checks.DOCKER_SOCKET",
            mock.Mock(exists=mock.Mock(return_value=False)),
        ):
            with self.assertRaisesRegex(heavy.HeavyCheckError, "Docker socket"):
                heavy.require_docker(require_socket=True)

    def test_dispatch_uses_verified_component_checkout(self):
        with mock.patch.dict(
            os.environ, {"LIS_LOCAL_CI_CHECKOUT": "/verified/core"}, clear=True
        ), mock.patch("local_ci_heavy_checks.core_frontend") as frontend, mock.patch.object(
            sys, "argv", ["local_ci_heavy_checks.py", "core-frontend"]
        ):
            heavy.main()
        frontend.assert_called_once_with(Path("/verified/core"))

    def test_broken_compile_stays_red_and_is_never_absorbed(self):
        core = self.core_checkout()
        socket = mock.Mock(stat=mock.Mock(return_value=mock.Mock(st_gid=967)))
        with mock.patch("local_ci_heavy_checks.require_docker"), mock.patch(
            "local_ci_heavy_checks.DOCKER_SOCKET", socket
        ), mock.patch("local_ci_heavy_checks.ensure_maven_cache"), mock.patch(
            "local_ci_heavy_checks._settings_file", return_value=None
        ), mock.patch(
            "local_ci_heavy_checks.run_spotless_with_retry",
            return_value=completed(),
        ), mock.patch(
            "local_ci_heavy_checks.run_logged",
            side_effect=[completed(), completed(1, "COMPILATION ERROR")],
        ) as run, mock.patch(
            "local_ci_heavy_checks.failed_test_ids", return_value=frozenset()
        ):
            with self.assertRaisesRegex(heavy.HeavyCheckError, "unabsorbed"):
                heavy.core_backend(core)
        self.assertEqual(run.call_count, 2)

    def test_known_failures_complete_packaging_and_emit_status_detail(self):
        core = self.core_checkout()
        detail = core / "status.txt"
        socket = mock.Mock(stat=mock.Mock(return_value=mock.Mock(st_gid=967)))
        with mock.patch.dict(
            os.environ, {heavy.STATUS_DETAIL_ENV: str(detail)}, clear=True
        ), mock.patch("local_ci_heavy_checks.require_docker"), mock.patch(
            "local_ci_heavy_checks.DOCKER_SOCKET", socket
        ), mock.patch("local_ci_heavy_checks.ensure_maven_cache"), mock.patch(
            "local_ci_heavy_checks._settings_file", return_value=None
        ), mock.patch(
            "local_ci_heavy_checks.run_spotless_with_retry",
            return_value=completed(),
        ), mock.patch(
            "local_ci_heavy_checks.run_logged",
            side_effect=[completed(), completed(1, "test failures"), completed()],
        ) as run, mock.patch(
            "local_ci_heavy_checks.failed_test_ids",
            return_value=heavy.BASELINE_FLAKES,
        ):
            heavy.core_backend(core)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(
            detail.read_text(encoding="utf-8").strip(),
            "passed; absorbed 6 baseline flakes",
        )


if __name__ == "__main__":
    unittest.main()
