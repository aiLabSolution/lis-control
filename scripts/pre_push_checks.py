#!/usr/bin/env python3
"""Extended client-side pre-push checks, invoked by .githooks/pre-push.

Why this exists
---------------
The POSIX hook can pattern-match refs (the main/master block) but anything subtler
needs real git plumbing, so the hook pipes its stdin here when python3 is available.
Three checks, each guarding a failure mode this project has actually hit:

  1. Force-push guard — a non-fast-forward push to a shared refs/heads/lis-* slice
     branch rewrites history other sessions have built on. A *plain* non-FF push is
     rejected server-side anyway, so the only push this stops locally is a forced
     one. The fix is always: merge origin/main INTO the branch and push a
     fast-forward (docs/agents/slice-loop.md).
  2. Submodule pin ancestry — an umbrella pin bump must reference a commit that is
     pushed AND merged to the component's default branch; a pin at an unpushed or
     unmerged SHA breaks every fresh `--recurse-submodules` clone
     (the pin-bump skill).
  3. ADR lint — pushes touching docs/adr/ or contexts/*/docs/adr/ must pass
     scripts/adr_lint.py (exit 0 clean, exit 1 with findings on stderr).

Fail-open contract: infrastructure problems (malformed stdin, missing git, missing
submodule checkout, offline fetch, missing lint script) WARN on stderr and allow —
a broken hook must never brick an editing session. Only genuine rule violations
exit 1, with every message on stderr.

Env:
  LIS_PREPUSH_OVERRIDE=1   skip all extended checks (emergency hatch)
  LIS_PREPUSH_NO_FETCH=1   skip the component `git fetch` (offline / tests)

stdin (from git's pre-push hook, one line per ref):
  <local_ref> <local_sha> <remote_ref> <remote_sha>
"""
import argparse
import os
import re
import subprocess
import sys

ZERO_SHA = "0" * 40
GIT_TIMEOUT = 25  # seconds; a hung fetch (or credential prompt) must not stall the push

# Component -> default branch, from the authoritative table in
# the pin-bump skill (`.agents/skills/pin-bump` for Codex and
# `.claude/skills/pin-bump` for Claude; "core=main, bridge=develop, kit=main");
# the skill's ancestry checks run against the component remote named "origin".
SUBMODULE_DEFAULT_BRANCH = {
    "core/openelis": "main",
    "edge/drivers": "develop",
    "deploy/kit": "main",
}
COMPONENT_REMOTE = "origin"

# Git exports repository-local variables (notably GIT_DIR) to hooks. Forwarding
# them into `git -C <submodule>` makes Git keep using the umbrella object store,
# so a valid component merge SHA appears to be missing. Every command already
# has an explicit cwd / -C target, so let Git rediscover that repository instead.
GIT_REPOSITORY_LOCAL_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)

# Umbrella ADRs plus component-scoped ADRs mounted under contexts/<mount>/docs/adr/.
ADR_PATH_RE = re.compile(r"^(docs/adr/|contexts/.+/docs/adr/)")


# --------------------------------------------------------------------------- helpers
def _warn(msg: str) -> None:
    print(f"pre-push[warn]: {msg}", file=sys.stderr)


def _git(args, cwd):
    """Run git; CompletedProcess, or None on infra failure (no git binary, timeout)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    for name in GIT_REPOSITORY_LOCAL_ENV:
        env.pop(name, None)
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=GIT_TIMEOUT, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _parse_stdin(stream):
    """(local_ref, local_sha, remote_ref, remote_sha) tuples; malformed lines warn."""
    refs = []
    for raw in stream:
        parts = raw.split()
        if len(parts) == 4:
            refs.append(tuple(parts))
        elif raw.strip():
            _warn(f"unparseable pre-push line skipped: {raw.strip()!r}")
    return refs


def _diff_base(local_sha, remote_sha, root):
    """Old tree to diff against: the remote tip when we have it locally, else the
    fork point from origin/main (first push of a new branch), else None (skip)."""
    if remote_sha != ZERO_SHA:
        r = _git(["cat-file", "-e", f"{remote_sha}^{{commit}}"], cwd=root)
        if r is not None and r.returncode == 0:
            return remote_sha
    r = _git(["merge-base", local_sha, "origin/main"], cwd=root)
    if r is not None and r.returncode == 0:
        return r.stdout.strip()
    return None


def _gitlinks(rev, root):
    """path -> pinned SHA for the tracked submodule paths at <rev>, or None on error.
    git ls-tree pairs are compared base-vs-tip; more robust than parsing
    `git diff --submodule=short` prose."""
    r = _git(["ls-tree", rev, "--", *SUBMODULE_DEFAULT_BRANCH], cwd=root)
    if r is None or r.returncode != 0:
        return None
    pins = {}
    for line in r.stdout.splitlines():
        meta, _, path = line.partition("\t")  # "<mode> <type> <sha>\t<path>"
        fields = meta.split()
        if len(fields) == 3 and fields[0] == "160000":
            pins[path] = fields[2]
    return pins


# --------------------------------------------------------------------------- checks
def check_force_push(refs, root):
    """CHECK 1: no force-push to shared refs/heads/lis-* branches."""
    errors = []
    for _local_ref, local_sha, remote_ref, remote_sha in refs:
        if not remote_ref.startswith("refs/heads/lis-"):
            continue
        if ZERO_SHA in (local_sha, remote_sha):  # branch create or delete
            continue
        known = _git(["cat-file", "-e", f"{remote_sha}^{{commit}}"], cwd=root)
        if known is None:
            _warn("git unavailable; skipping force-push check")
            return errors
        reason = f"remote tip {remote_sha[:12]} unknown locally"
        if known.returncode == 0:
            ff = _git(["merge-base", "--is-ancestor", remote_sha, local_sha], cwd=root)
            if ff is None or ff.returncode not in (0, 1):
                _warn(f"{remote_ref}: could not determine ancestry; allowing")
                continue
            if ff.returncode == 0:
                continue
            reason = f"remote tip {remote_sha[:12]} is not an ancestor of {local_sha[:12]}"
        errors.append(
            f"{remote_ref}: non-fast-forward push to a shared slice branch ({reason}).\n"
            "  Never force-push a shared slice branch — merge origin/main INTO the\n"
            "  branch and push a fast-forward instead (docs/agents/slice-loop.md).\n"
            "  LIS_PREPUSH_OVERRIDE=1 to bypass in an emergency."
        )
    return errors


def check_pin_ancestry(refs, root):
    """CHECK 2: every changed submodule pin must exist on, and be merged to, the
    component default branch."""
    errors = []
    no_fetch = os.environ.get("LIS_PREPUSH_NO_FETCH") == "1"
    fetch_ok = {}  # submodule path -> bool, so one offline component warns once
    for _local_ref, local_sha, remote_ref, remote_sha in refs:
        if local_sha == ZERO_SHA:  # branch deletion pushes no new pins
            continue
        base = _diff_base(local_sha, remote_sha, root)
        if base is None:
            _warn(f"{remote_ref}: no diff base found; skipping pin check")
            continue
        old, new = _gitlinks(base, root), _gitlinks(local_sha, root)
        if old is None or new is None:
            _warn(f"{remote_ref}: could not read submodule pins; skipping pin check")
            continue
        for path, pin in sorted(new.items()):
            if old.get(path) == pin:
                continue
            sub = os.path.join(root, path)
            usable = _git(["-C", sub, "rev-parse", "--git-dir"], cwd=root)
            if usable is None or usable.returncode != 0:
                _warn(f"{path}: submodule not usable here (common in worktrees); "
                      f"cannot verify pin {pin[:12]} — allowing")
                continue
            branch = SUBMODULE_DEFAULT_BRANCH[path]
            if not no_fetch:
                ok = fetch_ok.get(path)
                if ok is None:
                    f = _git(["-C", sub, "fetch", COMPONENT_REMOTE, branch, "--quiet"],
                             cwd=root)
                    ok = f is not None and f.returncode == 0
                    fetch_ok[path] = ok
                if not ok:
                    _warn(f"{path}: fetch of {COMPONENT_REMOTE}/{branch} failed "
                          f"(offline?); cannot verify pin {pin[:12]} — allowing")
                    continue
            exists = _git(["-C", sub, "cat-file", "-e", f"{pin}^{{commit}}"], cwd=root)
            if exists is None:
                _warn(f"{path}: git failed; cannot verify pin {pin[:12]} — allowing")
                continue
            if exists.returncode != 0:
                errors.append(
                    f"{path}: pinned SHA {pin[:12]} does not exist on the component "
                    "remote — it likely points at an unpushed local commit "
                    "(see the pin-bump skill)."
                )
                continue
            upstream = f"{COMPONENT_REMOTE}/{branch}"
            anc = _git(["-C", sub, "merge-base", "--is-ancestor", pin, upstream],
                       cwd=root)
            if anc is None or anc.returncode not in (0, 1):
                _warn(f"{path}: {upstream} not resolvable; cannot verify pin — allowing")
                continue
            if anc.returncode == 1:
                errors.append(
                    f"{path}: pin {pin[:12]} is not merged to the component default "
                    f"branch ({upstream}) — merge the component PR first, then re-pin "
                    "to the post-merge SHA; see the pin-bump skill."
                )
    return errors


def check_adr_lint(refs, root):
    """CHECK 3: pushes touching ADR paths must pass scripts/adr_lint.py."""
    touched = False
    for _local_ref, local_sha, remote_ref, remote_sha in refs:
        if local_sha == ZERO_SHA:
            continue
        base = _diff_base(local_sha, remote_sha, root)
        if base is None:
            continue
        r = _git(["diff", "--name-only", f"{base}..{local_sha}"], cwd=root)
        if r is None or r.returncode != 0:
            _warn(f"{remote_ref}: could not diff for ADR lint; skipping")
            continue
        if any(ADR_PATH_RE.match(p) for p in r.stdout.splitlines()):
            touched = True
            break
    if not touched:
        return []
    lint = os.path.join(root, "scripts", "adr_lint.py")
    if not os.path.isfile(lint):
        _warn("scripts/adr_lint.py not found; skipping ADR lint")
        return []
    try:
        # Uncaptured on purpose: the linter's findings (its stderr) reach the user.
        r = subprocess.run([sys.executable, lint], cwd=root, stdin=subprocess.DEVNULL,
                           timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        _warn("scripts/adr_lint.py could not run; skipping ADR lint")
        return []
    if r.returncode == 1:
        return ["ADR lint failed (findings above) — fix the ADRs before pushing."]
    if r.returncode != 0:
        _warn(f"scripts/adr_lint.py exited {r.returncode}; skipping ADR lint")
    return []


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Mirrors git's pre-push hook argv; informational (kept for messages/forensics).
    ap.add_argument("--remote", default="", help="remote name ($1 from the hook)")
    ap.add_argument("--url", default="", help="remote URL ($2 from the hook)")
    ap.parse_args(argv)

    if os.environ.get("LIS_PREPUSH_OVERRIDE") == "1":
        return 0
    root = os.getcwd()  # git runs pre-push hooks at the top of the working tree
    refs = _parse_stdin(sys.stdin)
    if not refs:
        return 0
    errors = (check_force_push(refs, root)
              + check_pin_ancestry(refs, root)
              + check_adr_lint(refs, root))
    for err in errors:
        print(f"pre-push: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open: a broken hook must never brick a push
        _warn(f"internal error ({type(exc).__name__}: {exc}); allowing push")
        sys.exit(0)
