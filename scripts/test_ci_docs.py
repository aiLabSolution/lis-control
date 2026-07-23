import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiDocumentationContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_ci_map_is_linked_from_repository_indexes(self):
        self.assertIn("docs/agents/ci-map.md", self.read("CONTEXT-MAP.md"))
        self.assertIn("docs/agents/ci-map.md", self.read("README.md"))

    def test_expected_check_wording_covers_both_registry_modes(self):
        for relative in (
            "docs/agents/slice-loop.md",
            ".agents/skills/work-slice/SKILL.md",
            ".codex/agents/adversarial-reviewer.toml",
        ):
            with self.subTest(relative=relative):
                text = self.read(relative)
                self.assertIn("hosted mode", text)
                self.assertIn("local mode", text)
                self.assertIn("local-ci/summary", text)
                self.assertIn("exact", text)

    def test_runbook_preserves_order_and_schedule_hygiene(self):
        text = self.read("docs/runbooks/flip-back-private-ci.md")
        headings = [
            "## 1. Flip the registry",
            "## 2. Disable hosted Actions",
            "## 3. Make the temporary public repositories private",
            "## 4. Refresh check-poisoned PR heads",
            "## 5. Prove one end-to-end local-evidence merge",
        ]
        offsets = [text.index(heading) for heading in headings]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("tx-pull.yml", text)
        self.assertIn("e2e-cache-cleanup.yml", text)
        self.assertIn("self-hosted runner", text)
        self.assertIn("PHI", text)
        self.assertIn("public-repository-phi-review.md", text)
        self.assertIn("actions/permissions", text)
        self.assertIn("LIS_LOCAL_CI_TIMEOUT_SECONDS=301", text)
        self.assertIn("--expected-core-sha", text)
        self.assertIn("time-bounded compensating-control approval", text)
        self.assertIn("date to restore server-side protection", text)

    def test_heavy_evidence_is_isolated_and_durable(self):
        text = self.read("docs/runbooks/flip-back-private-ci.md")
        self.assertIn("five separately provisioned disposable workers", text)
        self.assertIn('--check "$HEAVY_CHECK"', text)
        self.assertIn("snapshot_runtime historical-red.before", text)
        self.assertIn("snapshot_runtime historical-green.before", text)
        self.assertIn("snapshot_runtime timeout.before", text)
        self.assertIn("snapshot_runtime interruption.before", text)
        self.assertIn("approved/private/evidence-store", text)
        self.assertIn("lis-local-ci-maven-repository-v1", text)
        self.assertIn("allowed_new_volume", text)
        self.assertIn("sixth disposable evidence worker", text)
        self.assertIn("lis-local-ci-scenarios", text)
        self.assertIn("lis-local-ci-foreign-sentinel", text)
        self.assertIn("sentinel-content.sha256", text)

    def test_actions_inventory_is_replayable_without_dynamic_workflows(self):
        text = self.read("docs/runbooks/flip-back-private-ci.md")
        self.assertIn(".workflows.replay", text)
        self.assertIn(".github\\/workflows\\/", text)
        self.assertIn("workflow_id workflow_path state", text)
        self.assertIn("actions/workflows/$workflow_id/enable", text)
        self.assertIn("dynamic/**", text)

    def test_refreshed_component_prs_use_trusted_umbrella_runner(self):
        text = self.read("docs/runbooks/flip-back-private-ci.md")
        self.assertIn("RUNNER_CONTROL", text)
        self.assertIn('"$RUNNER_CONTROL/scripts/local_ci.py" <PR>', text)
        for repository in (
            "aiLabSolution/lis-control",
            "aiLabSolution/OpenELIS-Global-2",
            "aiLabSolution/openelis-analyzer-bridge",
            "aiLabSolution/lis-deploy-kit",
        ):
            with self.subTest(repository=repository):
                self.assertIn(f"--repo {repository}", text)

    def test_ci_map_does_not_misrepresent_missing_docker_timings(self):
        text = self.read("docs/agents/ci-map.md")
        for check in (
            "core-backend",
            "core-frontend",
            "stage0-bootstrap",
            "stage4-smoke",
            "site-stack-smoke",
        ):
            with self.subTest(check=check):
                row = next(line for line in text.splitlines() if f"`{check}`" in line and "LIS-28" in line)
                self.assertIn("not measured", row)
        self.assertIn("PR #164", text)
        self.assertIn("PR #168", text)

    def test_ci_map_names_every_pinned_hosted_workflow(self):
        text = self.read("docs/agents/ci-map.md")
        workflows = (
            "core-bootstrap-health.yml",
            "deploy-kit-config.yml",
            "deploy-kit-smoke.yml",
            "edge-sim.yml",
            "scripts-tests.yml",
            "site-stack-smoke.yml",
            "backend.yml",
            "build-installer.yml",
            "deploy-testing.yml",
            "e2e-authoritative-reusable.yml",
            "e2e-cache-cleanup.yml",
            "e2e-cypress-deprecated.yml",
            "e2e-playwright-reusable.yml",
            "e2e-playwright.yml",
            "e2e-tests.yml",
            "frontend.yml",
            "i18n-check.yml",
            "label-merge-conflict.yml",
            "publish-dev-backend-images.yml",
            "publish-dev-frontend-images.yml",
            "publish-images.yml",
            "spec-pages.yml",
            "speckit-validate.yml",
            "tx-pull.yml",
            "tx-push.yml",
            "docker-build-dev.yml",
            "docker-build-master.yml",
            "test.yml",
        )
        for workflow in workflows:
            with self.subTest(workflow=workflow):
                self.assertIn(workflow, text)

    def test_core_hosted_terminal_contexts_are_explicit(self):
        text = self.read("docs/agents/ci-map.md")
        self.assertIn("01 Checkpoint - Backend", text)
        self.assertIn("02 Checkpoint - Frontend", text)
        self.assertIn("skipped terminal checkpoint", text)

    def test_phi_review_covers_reachable_component_history_and_signoff(self):
        text = self.read("docs/runbooks/public-repository-phi-review.md")
        self.assertIn("rev-list --objects --all", text)
        self.assertIn("OpenELIS-Global-2", text)
        self.assertIn("openelis-analyzer-bridge", text)
        self.assertIn("lis-deploy-kit", text)
        self.assertIn("privacy owner", text)
        self.assertIn("sign a manifest", text)
        self.assertIn("approved private", text)
        self.assertIn("*.blob-shas", text)
        self.assertIn("every unique object", text)
        self.assertIn("regardless of", text)
        self.assertIn("unsupported formats", text)
        self.assertIn("git clone --mirror", text)
        self.assertIn("--is-shallow-repository", text)
        self.assertIn("+refs/heads/*:refs/remotes/origin/*", text)


if __name__ == "__main__":
    unittest.main()
