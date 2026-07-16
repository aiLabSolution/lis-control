"""Regression tests for authoritative pinned-source deployment provenance."""

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class DeployProvenanceTest(unittest.TestCase):
    def test_core_bootstrap_builds_pinned_core_and_dataexport(self):
        workflow = (
            REPO_ROOT / ".github/workflows/core-bootstrap-health.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("-f core/openelis/build.docker-compose.yml", workflow)
        self.assertNotIn("deploy/ci/compose.bootstrap.yml", workflow)
        self.assertIn("HEAD:dataexport", workflow)
        self.assertIn("path: core/openelis/dataexport", workflow)
        self.assertIn("ref: ${{ steps.nested.outputs.dataexport }}", workflow)
        self.assertIn("--build", workflow)

    def test_live_instructions_and_workflows_do_not_use_legacy_overlay(self):
        live_paths = [REPO_ROOT / "AGENTS.md", REPO_ROOT / "CLAUDE.md"]
        live_paths.extend(
            path
            for root in (
                REPO_ROOT / ".github/workflows",
                REPO_ROOT / "docs/runbooks",
            )
            for path in root.rglob("*")
            if path.is_file()
        )
        live_paths.extend(
            path
            for path in (REPO_ROOT / "deploy/ci").rglob("*")
            if path.is_file() and path.suffix in {".py", ".sh"}
        )

        offenders = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in live_paths
            if "compose.bootstrap.yml" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders, "legacy overlay referenced by live files")

    def test_legacy_overlay_is_labeled_for_teardown_compatibility_only(self):
        overlay = (REPO_ROOT / "deploy/ci/compose.bootstrap.yml").read_text(
            encoding="utf-8"
        )
        header = "\n".join(overlay.splitlines()[:12])

        self.assertIn("LEGACY TEARDOWN COMPATIBILITY ONLY", header)
        self.assertIn("NEVER USE FOR up/config", header)


if __name__ == "__main__":
    unittest.main()
