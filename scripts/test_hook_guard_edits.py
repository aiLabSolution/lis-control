#!/usr/bin/env python3
"""Tests for scripts/hook_guard_edits.py.

Drives the guard as a real subprocess with JSON on stdin — that exercises the
actual hook contract (stdin parsing, exit codes, stderr feedback), not just the
internals. The umbrella repo is faked as a temp dir whose core/openelis
"submodule" is a plain nested git repo (from the guard's point of view — a git
dir at core/openelis answering `ls-tree HEAD` — that is indistinguishable from
an initialized submodule). Git identity/config come from env so bare CI
runners work.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "hook_guard_edits.py"
LIQUIBASE_REL = Path("core/openelis/src/main/resources/liquibase/3.5.x.x")
FORMATTER_REL = Path("core/openelis/tools/OpenELIS_java_formatter.xml")

# Include shapes mirror the real files: attribute order varies, self-closing
# with and without a space before "/>".
INCLUDE_001 = '  <include relativeToChangelogFile="true" file="001-x.xml"/>\n'
INCLUDE_002 = '  <include file="liquibase/3.5.x.x/002-y.xml" />\n'
BASE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<databaseChangeLog\n"
    '  xmlns="http://www.liquibase.org/xml/ns/dbchangelog"\n'
    '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
    '  xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog'
    ' http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-3.8.xsd">\n'
    "\n"
    "  <!-- first changeset -->\n" + INCLUDE_001 + INCLUDE_002 + "\n"
    "</databaseChangeLog>\n"
)
CHANGESET_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog">\n'
    '  <changeSet id="1" author="test">\n'
    "    <sql>SELECT 1;</sql>\n"
    "  </changeSet>\n"
    "</databaseChangeLog>\n"
)
FORMATTER_XML = '<profiles version="13"><profile name="OpenELIS"/></profiles>\n'

GIT_ENV = {
    "GIT_AUTHOR_NAME": "hook-test",
    "GIT_AUTHOR_EMAIL": "hook-test@example.invalid",
    "GIT_COMMITTER_NAME": "hook-test",
    "GIT_COMMITTER_EMAIL": "hook-test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, **GIT_ENV},
    )


def _build_umbrella(root, init_git):
    liqui = root / LIQUIBASE_REL
    liqui.mkdir(parents=True)
    (liqui / "base.xml").write_text(BASE_XML)
    (liqui / "001-x.xml").write_text(CHANGESET_XML)
    formatter = root / FORMATTER_REL
    formatter.parent.mkdir(parents=True)
    formatter.write_text(FORMATTER_XML)
    if init_git:
        sub = root / "core" / "openelis"
        _git(sub, "init", "-q")
        _git(sub, "add", "-A")
        _git(sub, "commit", "-q", "-m", "seed")


def _edit(path, old, new, **extra):
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new, **extra},
    }


def _write(path, content):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


class HookGuardEditsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="hook-guard-test-")
        tmp = Path(cls._tmp.name)
        cls.root = tmp / "umbrella"
        _build_umbrella(cls.root, init_git=True)
        cls.uninit_root = tmp / "umbrella-uninit"
        _build_umbrella(cls.uninit_root, init_git=False)
        cls.outside = tmp / "elsewhere"
        cls.outside.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_guard(self, payload, root=None, extra_env=None):
        env = {**os.environ, **GIT_ENV}
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "LIS_EDIT_GUARD_OVERRIDE"):
            env.pop(key, None)
        env["LIS_HOOK_REPO_ROOT"] = str(root or self.root)
        env["GIT_CEILING_DIRECTORIES"] = self._tmp.name  # never discover a repo above the fixture
        if extra_env:
            env.update(extra_env)
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            [sys.executable, str(GUARD)],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def assert_blocked(self, proc, *fragments):
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("LIS_EDIT_GUARD_OVERRIDE=1", proc.stderr)
        for fragment in fragments:
            self.assertIn(fragment, proc.stderr)

    def assert_allowed(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)

    # --- rule 1: liquibase append-only -------------------------------------

    def test_new_liquibase_file_allowed(self):
        new_file = self.root / LIQUIBASE_REL / "055-foo.xml"
        self.assert_allowed(self.run_guard(_write(new_file, CHANGESET_XML)))
        # An agent that just created 055-foo.xml (on disk, not yet committed)
        # must still be able to fix a typo in it.
        new_file.write_text(CHANGESET_XML)
        try:
            self.assert_allowed(self.run_guard(_edit(new_file, "SELECT 1", "SELECT 2")))
        finally:
            new_file.unlink()

    def test_edit_committed_changeset_blocked(self):
        proc = self.run_guard(_edit(self.root / LIQUIBASE_REL / "001-x.xml", "SELECT 1", "SELECT 2"))
        self.assert_blocked(proc, "already-committed", "NEW numbered changeset")

    def test_relative_path_normalized_against_repo_root(self):
        rel_path = LIQUIBASE_REL / "001-x.xml"  # not absolute: must resolve against repo root
        self.assert_blocked(self.run_guard(_edit(rel_path, "SELECT 1", "SELECT 2")))

    def test_write_committed_changeset_blocked(self):
        proc = self.run_guard(_write(self.root / LIQUIBASE_REL / "001-x.xml", "<xml/>"))
        self.assert_blocked(proc, "already-committed")

    def test_multiedit_committed_changeset_blocked(self):
        payload = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": str(self.root / LIQUIBASE_REL / "001-x.xml"),
                "edits": [{"old_string": "SELECT 1", "new_string": "SELECT 2"}],
            },
        }
        self.assert_blocked(self.run_guard(payload))

    def test_append_include_to_base_allowed(self):
        proc = self.run_guard(
            _edit(
                self.root / LIQUIBASE_REL / "base.xml",
                "</databaseChangeLog>",
                '  <include relativeToChangelogFile="true" file="003-z.xml"/>\n</databaseChangeLog>',
            )
        )
        self.assert_allowed(proc)

    def test_remove_include_from_base_blocked(self):
        proc = self.run_guard(_edit(self.root / LIQUIBASE_REL / "base.xml", INCLUDE_001, ""))
        self.assert_blocked(proc, "append-only", "never-renumber")

    def test_multiedit_remove_include_blocked(self):
        payload = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": str(self.root / LIQUIBASE_REL / "base.xml"),
                "edits": [{"old_string": INCLUDE_002, "new_string": ""}],
            },
        }
        self.assert_blocked(self.run_guard(payload), "append-only")

    def test_reorder_includes_blocked(self):
        swapped = BASE_XML.replace(INCLUDE_001 + INCLUDE_002, INCLUDE_002 + INCLUDE_001)
        proc = self.run_guard(_write(self.root / LIQUIBASE_REL / "base.xml", swapped))
        self.assert_blocked(proc, "append-only")

    def test_rewrite_existing_include_attributes_blocked(self):
        # Adding an attribute to an existing entry changes which file the chain
        # resolves to — mutation, not append (adversarial-review finding, PR #121).
        proc = self.run_guard(
            _edit(
                self.root / LIQUIBASE_REL / "base.xml",
                INCLUDE_002,
                '  <include relativeToChangelogFile="true" file="liquibase/3.5.x.x/002-y.xml" />\n',
            )
        )
        self.assert_blocked(proc, "append-only")

    def test_base_edit_with_missing_old_string_allowed(self):
        # The Edit itself would fail; the guard must not block what cannot happen.
        proc = self.run_guard(_edit(self.root / LIQUIBASE_REL / "base.xml", "NOT PRESENT", "x"))
        self.assert_allowed(proc)

    # --- rule 2: formatter xml ----------------------------------------------

    def test_formatter_xml_blocked(self):
        proc = self.run_guard(_edit(self.root / FORMATTER_REL, "OpenELIS", "Other"))
        self.assert_blocked(proc, "formatting source")

    # --- override + fail-open behavior ---------------------------------------

    def test_override_env_allows(self):
        proc = self.run_guard(
            _edit(self.root / LIQUIBASE_REL / "001-x.xml", "SELECT 1", "SELECT 2"),
            extra_env={"LIS_EDIT_GUARD_OVERRIDE": "1"},
        )
        self.assert_allowed(proc)

    def test_non_liquibase_path_allowed(self):
        self.assert_allowed(self.run_guard(_write(self.root / "README.md", "hello")))

    def test_file_outside_repo_allowed(self):
        self.assert_allowed(self.run_guard(_write(self.outside / "notes.xml", "<xml/>")))

    def test_garbage_stdin_fails_open(self):
        self.assert_allowed(self.run_guard("this is { not json"))

    def test_unknown_tool_fails_open(self):
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": str(self.root / LIQUIBASE_REL / "001-x.xml")},
        }
        self.assert_allowed(self.run_guard(payload))

    def test_uninitialized_submodule_fails_open(self):
        proc = self.run_guard(
            _edit(self.uninit_root / LIQUIBASE_REL / "001-x.xml", "SELECT 1", "SELECT 2"),
            root=self.uninit_root,
        )
        self.assert_allowed(proc)


if __name__ == "__main__":
    unittest.main()
