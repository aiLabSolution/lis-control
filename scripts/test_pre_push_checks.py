#!/usr/bin/env python3
"""Tests for scripts/pre_push_checks.py and the .githooks/pre-push wrapper.

Everything is subprocess-driven against throwaway git repos built with plumbing
(commit-tree / update-index --cacheinfo), so no test moves a branch or touches the
network: LIS_PREPUSH_NO_FETCH=1 is always set and the component "remote" state is
simulated by writing refs/remotes/origin/* directly. A nested plain git repo stands
in for the core/openelis submodule — same shape the checks see in a real checkout.
scripts/adr_lint.py is deliberately NOT exercised (another module owns it); only the
warn-allow path for its absence is covered here.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
CHECKS = os.path.join(SCRIPTS_DIR, "pre_push_checks.py")
HOOK = os.path.join(REPO_ROOT, ".githooks", "pre-push")

ZERO = "0" * 40
BOGUS = "deadbeef" * 5  # well-formed 40-hex, guaranteed-nonexistent object

BASE_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
    GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid",
    GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
    LIS_PREPUSH_NO_FETCH="1",
)
BASE_ENV.pop("LIS_PREPUSH_OVERRIDE", None)


def git(cwd, *args, git_input=None):
    r = subprocess.run(["git", *args], cwd=cwd, input=git_input, text=True,
                       capture_output=True, env=BASE_ENV, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {r.stderr}")
    return r.stdout.strip()


def commit_file(cwd, relpath, content, message):
    path = os.path.join(cwd, relpath)
    os.makedirs(os.path.dirname(path) or cwd, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    git(cwd, "add", relpath)
    git(cwd, "commit", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


class ChecksScriptTest(unittest.TestCase):
    """Drive scripts/pre_push_checks.py directly with synthetic pre-push stdin."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="prepush-checks-")
        cls.umbrella = os.path.join(cls._tmp.name, "umbrella")
        os.makedirs(cls.umbrella)
        git(cls.umbrella, "init", "-q", "-b", "main")
        cls.c1 = commit_file(cls.umbrella, "README.md", "umbrella\n", "c1")

        # Nested plain repo standing in for the core/openelis submodule; its
        # "remote default branch" is a hand-written remote-tracking ref (no network).
        cls.sub = os.path.join(cls.umbrella, "core", "openelis")
        os.makedirs(cls.sub)
        git(cls.sub, "init", "-q", "-b", "main")
        cls.s1 = commit_file(cls.sub, "a.txt", "one\n", "s1")
        cls.s2 = commit_file(cls.sub, "a.txt", "two\n", "s2")
        s1_tree = git(cls.sub, "rev-parse", f"{cls.s1}^{{tree}}")
        cls.s3 = git(cls.sub, "commit-tree", s1_tree, "-p", cls.s1, "-m", "s3-divergent")
        git(cls.sub, "update-ref", "refs/remotes/origin/main", cls.s2)

        # Umbrella main tip carries the s1 gitlink; c1 predates it.
        git(cls.umbrella, "update-index", "--add",
            "--cacheinfo", f"160000,{cls.s1},core/openelis")
        git(cls.umbrella, "commit", "-q", "-m", "c2: pin core/openelis@s1")
        cls.c2 = git(cls.umbrella, "rev-parse", "HEAD")
        git(cls.umbrella, "update-ref", "refs/remotes/origin/main", cls.c2)

        # Divergent-from-main commit (parent c1) for non-fast-forward scenarios.
        c1_tree = git(cls.umbrella, "rev-parse", f"{cls.c1}^{{tree}}")
        cls.d1 = git(cls.umbrella, "commit-tree", c1_tree, "-p", cls.c1, "-m", "d1")

        cls.pin_ok = cls._pin_commit("core/openelis", cls.s2)
        cls.pin_unmerged = cls._pin_commit("core/openelis", cls.s3)
        cls.pin_missing = cls._pin_commit("core/openelis", BOGUS)
        cls.pin_uninit_sub = cls._pin_commit("edge/drivers", cls.s2)

        blob = git(cls.umbrella, "hash-object", "-w", "--stdin",
                   git_input="# ADR 0099\n")
        cls.adr_commit = cls._index_edit_commit(
            "--cacheinfo", f"100644,{blob},docs/adr/0099-test.md")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def _index_edit_commit(cls, *update_index_args):
        """Commit c2's tree plus one index edit, via plumbing — no branch moves,
        so the shared fixture stays valid for every test."""
        git(cls.umbrella, "update-index", "--add", *update_index_args)
        tree = git(cls.umbrella, "write-tree")
        commit = git(cls.umbrella, "commit-tree", tree, "-p", cls.c2, "-m", "scenario")
        git(cls.umbrella, "read-tree", cls.c2)
        return commit

    @classmethod
    def _pin_commit(cls, path, sha):
        return cls._index_edit_commit("--cacheinfo", f"160000,{sha},{path}")

    def run_checks(self, lines, env_extra=None):
        env = dict(BASE_ENV)
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, CHECKS, "--remote", "origin", "--url", "file:///x"],
            cwd=self.umbrella, input=lines, text=True, capture_output=True,
            env=env, timeout=120)

    def line(self, remote_ref, local_sha, remote_sha):
        return f"refs/heads/x {local_sha} {remote_ref} {remote_sha}\n"

    # ---- CHECK 1: force-push guard ------------------------------------------
    def test_fast_forward_lis_push_allowed(self):
        r = self.run_checks(self.line("refs/heads/lis-5", self.c2, self.c1))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_non_fast_forward_lis_push_blocked(self):
        r = self.run_checks(self.line("refs/heads/lis-5", self.d1, self.c2))
        self.assertEqual(r.returncode, 1)
        self.assertIn("non-fast-forward push to a shared slice branch", r.stderr)
        self.assertIn("never force-push", r.stderr.lower())

    def test_unknown_remote_sha_on_lis_branch_blocked(self):
        r = self.run_checks(self.line("refs/heads/lis-5", self.c2, BOGUS))
        self.assertEqual(r.returncode, 1)
        self.assertIn("non-fast-forward push to a shared slice branch", r.stderr)

    def test_non_lis_branch_non_ff_not_blocked_by_check1(self):
        r = self.run_checks(self.line("refs/heads/feature-x", self.d1, self.c2))
        self.assertEqual(r.returncode, 0, r.stderr)

    # ---- CHECK 2: submodule pin ancestry -------------------------------------
    def test_pin_to_ancestor_of_default_allowed(self):
        r = self.run_checks(self.line("refs/heads/lis-6", self.pin_ok, self.c2))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_pin_not_merged_to_default_blocked(self):
        r = self.run_checks(self.line("refs/heads/lis-6", self.pin_unmerged, self.c2))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not merged to the component default branch", r.stderr)

    def test_pin_object_missing_blocked(self):
        r = self.run_checks(self.line("refs/heads/lis-6", self.pin_missing, self.c2))
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not exist on the component remote", r.stderr)

    def test_uninitialized_submodule_warns_and_allows(self):
        r = self.run_checks(self.line("refs/heads/lis-6", self.pin_uninit_sub, self.c2))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("edge/drivers", r.stderr)
        self.assertIn("allowing", r.stderr)

    def test_pin_checked_on_new_branch_via_origin_main_fork_point(self):
        # remote_sha all-zero (branch creation): base falls back to merge-base
        # with origin/main, so a bad pin still can't ride in on a fresh branch.
        r = self.run_checks(self.line("refs/heads/lis-7", self.pin_unmerged, ZERO))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not merged to the component default branch", r.stderr)

    def test_hook_git_dir_does_not_poison_submodule_checks(self):
        # Git exports the umbrella repository's local GIT_* variables to hooks.
        # They must not leak into `git -C core/openelis`, or that command reads
        # the umbrella object database and falsely reports a valid pin missing.
        r = self.run_checks(
            self.line("refs/heads/lis-7", self.pin_ok, ZERO),
            env_extra={"GIT_DIR": os.path.join(self.umbrella, ".git")},
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    # ---- CHECK 3 absence + generic behavior ----------------------------------
    def test_adr_touch_without_linter_warns_and_allows(self):
        r = self.run_checks(self.line("refs/heads/lis-8", self.adr_commit, self.c2))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("adr_lint.py not found", r.stderr)

    def test_override_env_allows_everything(self):
        lines = (self.line("refs/heads/lis-5", self.d1, self.c2)
                 + self.line("refs/heads/lis-6", self.pin_missing, self.c2))
        r = self.run_checks(lines, env_extra={"LIS_PREPUSH_OVERRIDE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def test_branch_deletion_lines_ignored(self):
        r = self.run_checks(f"(delete) {ZERO} refs/heads/lis-5 {self.c2}\n")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_malformed_stdin_fails_open(self):
        r = self.run_checks("this is not a pre-push line\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("unparseable", r.stderr)


class HookEndToEndTest(unittest.TestCase):
    """Run real `git push` through the edited .githooks/pre-push."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="prepush-hook-")
        self.addCleanup(self._tmp.cleanup)
        self.remote = os.path.join(self._tmp.name, "remote.git")
        git(self._tmp.name, "init", "-q", "--bare", self.remote)

        self.repo = os.path.join(self._tmp.name, "umbrella")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        commit_file(self.repo, "README.md", "umbrella\n", "c1")
        git(self.repo, "remote", "add", "origin", self.remote)
        # Seed the remote (and refs/remotes/origin/main) BEFORE enabling the hook.
        git(self.repo, "push", "-q", "origin", "main")

        hooks_dir = os.path.join(self.repo, ".githooks")
        os.makedirs(hooks_dir)
        hook = os.path.join(hooks_dir, "pre-push")
        shutil.copy(HOOK, hook)
        os.chmod(hook, os.stat(hook).st_mode | stat.S_IXUSR | stat.S_IXGRP)
        scripts_dir = os.path.join(self.repo, "scripts")
        os.makedirs(scripts_dir)
        shutil.copy(CHECKS, scripts_dir)
        git(self.repo, "config", "core.hooksPath", ".githooks")

    def push(self, *refspec):
        return subprocess.run(["git", "push", "origin", *refspec], cwd=self.repo,
                              text=True, capture_output=True, env=BASE_ENV,
                              timeout=120)

    def test_main_push_still_blocked_with_original_message(self):
        seeded = git(self.remote, "rev-parse", "refs/heads/main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "c2")
        r = self.push("main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pre-push: blocked direct push to refs/heads/main.", r.stderr)
        self.assertIn("Protocol: slice branch -> PR -> main "
                      "(docs/agents/slice-loop.md).", r.stderr)
        self.assertIn("Push your slice branch and open a PR instead.", r.stderr)
        # Nothing landed on the remote: its main still sits at the seeded commit.
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/main"), seeded)

    def test_clean_feature_push_allowed(self):
        git(self.repo, "branch", "lis-77", "main")
        r = self.push("lis-77")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/lis-77"),
                         git(self.repo, "rev-parse", "lis-77"))


if __name__ == "__main__":
    unittest.main()
