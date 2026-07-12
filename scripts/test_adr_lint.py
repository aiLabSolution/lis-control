#!/usr/bin/env python3
"""Tests for adr_lint: per-namespace collision detection, deliberate non-findings.

Fixtures are temp-dir repos, not the live tree — the live tree's numbering gaps
and cross-namespace reuse are exactly the things the linter must NOT flag, so
they are asserted here as explicit negative cases.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import adr_lint


def run_main(root):
    """Invoke the CLI entry point with findings output captured, return exit code."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return adr_lint.main(["--repo-root", str(root)])

ADR_BODY = "# ADR-%s — %s\n\n- **Status:** %s\n- **Date:** 2026-07-12\n\n## Context\n\nBody.\n"


class AdrLintTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write_adr(self, namespace, filename, status="Accepted", body=None):
        ns = self.root / namespace
        ns.mkdir(parents=True, exist_ok=True)
        number = filename[:4]
        text = body if body is not None else ADR_BODY % (number, filename, status)
        (ns / filename).write_text(text, encoding="utf-8")

    def test_clean_tree_no_findings_exit_0(self):
        self.write_adr("docs/adr", "0001-first-decision.md", status="Accepted")
        self.write_adr("docs/adr", "0002-second-decision.md", status="Proposed")
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(run_main(self.root), 0)

    def test_duplicate_number_in_one_namespace_is_error(self):
        self.write_adr("docs/adr", "0003-topology.md")
        self.write_adr("docs/adr", "0003-concurrent-merge-twin.md")
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicate ADR number 0003", errors[0])
        self.assertIn("0003-topology.md", errors[0])
        self.assertIn("0003-concurrent-merge-twin.md", errors[0])
        self.assertTrue(errors[0].startswith("ERROR docs/adr"))
        self.assertEqual(warnings, [])
        self.assertEqual(run_main(self.root), 1)

    def test_same_number_across_namespaces_is_ok(self):
        # The namespace is deliberately overloaded: umbrella ADR-0003 and a
        # context's ADR-0003 are two legitimate documents.
        self.write_adr("docs/adr", "0003-umbrella-decision.md")
        self.write_adr("contexts/core-openelis/docs/adr", "0003-core-decision.md")
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_numbering_gap_is_not_flagged(self):
        # Gaps are the natural residue of collision resolution (renumbering is forbidden).
        self.write_adr("docs/adr", "0001-first.md")
        self.write_adr("docs/adr", "0005-after-a-gap.md")
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_bad_filename_is_warning(self):
        self.write_adr("docs/adr", "0001-good.md")
        self.write_adr("docs/adr", "adr-2-no-number-prefix.md")
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("WARN docs/adr/adr-2-no-number-prefix.md"))
        self.assertIn("NNNN-<kebab-slug>.md", warnings[0])

    def test_missing_status_is_warning(self):
        self.write_adr("docs/adr", "0001-no-status.md", body="# ADR-0001 — no status\n\n## Context\n\nBody.\n")
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("no recognizable Status", warnings[0])

    def test_unknown_status_value_is_warning(self):
        self.write_adr("docs/adr", "0001-rejected.md", status="Rejected")
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("'Rejected'", warnings[0])

    def test_real_status_spellings_accepted(self):
        # The shapes actually present in this repo: annotated, bolded, heading form.
        self.write_adr("docs/adr", "0001-annotated.md", status="Accepted (signed off 2026-06-30, M. Uy)")
        self.write_adr("docs/adr", "0002-bolded.md", status="**Accepted** (ratified 2026-06-29; was *Proposed*)")
        self.write_adr("docs/adr", "0003-pending.md", status="Proposed (pending review — LIS-4)")
        self.write_adr(
            "docs/adr",
            "0004-heading-form.md",
            body="# ADR-0004 — heading form\n\n## Status\n\nSuperseded\n\n## Context\n\nBody.\n",
        )
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_adr_dirs_is_clean(self):
        # Fail open: a root with no docs/adr at all is not a lint finding.
        errors, warnings = adr_lint.lint_repo(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(run_main(self.root), 0)

    def test_duplicate_in_context_namespace_is_error(self):
        self.write_adr("contexts/edge-drivers/docs/adr", "0002-transport.md")
        self.write_adr("contexts/edge-drivers/docs/adr", "0002-transport-rewrite.md")
        errors, _ = adr_lint.lint_repo(self.root)
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("ERROR contexts/edge-drivers/docs/adr"))


if __name__ == "__main__":
    unittest.main()
