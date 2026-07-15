import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "deploy" / "ci" / "smoke-diagnostic-report.sh"
HEALTHCHECK_SCRIPT = ROOT / "deploy" / "ci" / "healthcheck.sh"
REPORT_UUID = "5a6a7750-7cb7-4d6d-9fe0-50ecb8530001"
OBSERVATION_UUID = "5a6a7750-7cb7-4d6d-9fe0-50ecb8530002"


class DiagnosticReportSmokeTest(unittest.TestCase):
    def test_valid_diagnostic_report_read_passes(self):
        result = self._run_with_payload(
            f'{{"resourceType":"DiagnosticReport","id":"{REPORT_UUID}",'
            f'"status":"final","result":[{{"reference":"Observation/{OBSERVATION_UUID}"}}]}}'
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            f"FHIR_SMOKE_OK resourceType=DiagnosticReport id={REPORT_UUID} status=final",
            result.stdout,
        )

    def test_operation_outcome_payload_fails(self):
        result = self._run_with_payload(
            '{"resourceType":"OperationOutcome","issue":[{"severity":"error"}]}'
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("expected DiagnosticReport", result.stderr)

    def test_wrong_observation_reference_fails(self):
        result = self._run_with_payload(
            f'{{"resourceType":"DiagnosticReport","id":"{REPORT_UUID}",'
            '"status":"final","result":[{"reference":"Observation/example"}]}'
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            f"expected DiagnosticReport.result to reference Observation/{OBSERVATION_UUID}",
            result.stderr,
        )

    def _run_with_payload(self, payload: str) -> subprocess.CompletedProcess[str]:
        return self._run_with_curl_script(
            "#!/usr/bin/env bash\n" f"printf '%s\\n' '{payload}'\n"
        )

    def _run_with_curl_script(
        self, curl_script: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_bin = Path(temp_dir)
            self._write_executable(fake_bin / "docker", "#!/usr/bin/env bash\ncat >/dev/null\n")
            self._write_executable(fake_bin / "curl", curl_script)

            return subprocess.run(
                ["bash", str(SMOKE_SCRIPT)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "BASE_URL": "https://example.test/api/OpenELIS-Global",
                    "REPORT_UUID": REPORT_UUID,
                    **(extra_env or {}),
                },
                capture_output=True,
                text=True,
            )

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


class DeployHealthcheckTest(unittest.TestCase):
    def test_explicit_health_url_is_checked_without_rewriting(self):
        health_url = "https://example.test/api/OpenELIS-Global/health"
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_bin = Path(temp_dir) / "bin"
            fake_bin.mkdir()
            url_file = Path(temp_dir) / "curl-url"
            DiagnosticReportSmokeTest._write_executable(
                fake_bin / "docker",
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  *Health*) printf '%s\\n' healthy ;;\n"
                "  *inspect*) printf '%s\\n' running ;;\n"
                "  *logs*) printf '%s\\n' 'Server startup in 123 ms' ;;\n"
                "esac\n",
            )
            DiagnosticReportSmokeTest._write_executable(
                fake_bin / "curl",
                "#!/usr/bin/env bash\n"
                "for arg in \"$@\"; do last=$arg; done\n"
                "printf '%s' \"$last\" > \"$CURL_URL_FILE\"\n"
                "printf '%s' 200\n",
            )

            result = subprocess.run(
                ["bash", str(HEALTHCHECK_SCRIPT)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "CURL_URL_FILE": str(url_file),
                    "HEALTH_URL": health_url,
                    "TIMEOUT": "1",
                },
                capture_output=True,
                text=True,
            )

            checked_url = url_file.read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(health_url, checked_url)
        self.assertIn("HEALTHY", result.stdout)


if __name__ == "__main__":
    unittest.main()
