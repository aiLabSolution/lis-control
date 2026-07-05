#!/usr/bin/env python3
"""PreToolUse guard (Bash): enforce the repo's branch protocol.

Blocks (exit 2, message on stderr):
  - `git commit` while the effective repo's HEAD is on a protected branch
    (main / master / develop). Work belongs in a slice worktree on a slice
    branch — see docs/agents/slice-loop.md.
  - `git push` targeting a protected branch (explicit refspec such as
    `origin main` / `HEAD:main`, or a bare `git push` while on one).
  - Any force-push (`-f`, `--force`, `--force-with-lease`, ...) — shared
    slice branches are never force-pushed.

Everything else passes. Best-effort static analysis of the command string;
any unexpected error fails OPEN (exit 0) so the hook can never wedge
unrelated commands. Stdlib only, matching scripts/ conventions.
"""

import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master", "develop"}
SEPARATORS = re.compile(r"&&|\|\||;|\|")
# git global options that consume the following token
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# push options that consume the following token (so their value isn't read as a refspec)
PUSH_OPTS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def deny(message):
    sys.stderr.write(
        "BLOCKED by .claude/hooks/git-guard.py: "
        + message
        + "\nProtocol: never commit on or push to main/master/develop; work in a"
        " slice worktree (`git worktree add ../lis-control-<key> -b <key>-<slug>`)"
        " and land changes via a PR (docs/agents/slice-loop.md). If this block is"
        " a false positive, ask the user to run the command themselves with the"
        " `!` prefix.\n"
    )
    sys.exit(2)


def current_branch(path):
    """Branch name at `path`, or None (detached HEAD / not a repo / error)."""
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    branch = out.stdout.strip()
    return None if branch in ("", "HEAD") else branch


def parse_git_invocations(command, cwd):
    """Yield (subcommand, args, repo_dir) for each git call, tracking `cd`."""
    cur_dir = cwd
    for segment in SEPARATORS.split(command):
        try:
            toks = shlex.split(segment)
        except ValueError:
            toks = segment.split()
        if not toks:
            continue
        if toks[0] == "cd" and len(toks) > 1:
            target = toks[1]
            cur_dir = target if os.path.isabs(target) else os.path.join(cur_dir, target)
            continue
        if "git" not in toks:
            continue
        i = toks.index("git") + 1
        repo_dir, sub, args = cur_dir, None, []
        while i < len(toks):
            t = toks[i]
            if sub is None and t.startswith("-"):
                if t in GIT_OPTS_WITH_VALUE and i + 1 < len(toks):
                    if t == "-C":
                        c = toks[i + 1]
                        repo_dir = c if os.path.isabs(c) else os.path.join(cur_dir, c)
                    i += 2
                    continue
                i += 1
                continue
            if sub is None:
                sub = t
            else:
                args.append(t)
            i += 1
        if sub:
            yield sub, args, repo_dir


def check_push(args, repo_dir):
    positionals, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("-"):
            if a in ("-f", "--force", "--force-with-lease", "--force-if-includes") or a.startswith(
                "--force-with-lease="
            ):
                deny("force-push detected (`" + a + "`). Never force-push a shared"
                     " slice branch; merge origin/main INTO the branch instead"
                     " (fast-forward push).")
            if a in ("-n", "--dry-run"):
                return  # dry runs are harmless
            if a in PUSH_OPTS_WITH_VALUE and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        positionals.append(a)
        i += 1

    refspecs = positionals[1:]  # positionals[0] is the remote
    if not refspecs:
        branch = current_branch(repo_dir)
        if branch in PROTECTED:
            deny("`git push` with no refspec while '" + repo_dir + "' is on"
                 " protected branch '" + str(branch) + "'.")
        return
    for spec in refspecs:
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        dst = dst.lstrip("+")
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        if dst == "HEAD":
            dst = current_branch(repo_dir) or ""
        if dst in PROTECTED:
            deny("`git push` targets protected branch '" + dst + "' (refspec `"
                 + spec + "`).")


def main():
    payload = json.load(sys.stdin)
    command = (payload.get("tool_input") or {}).get("command") or ""
    if "git" not in command:
        return
    cwd = payload.get("cwd") or os.getcwd()

    for sub, args, repo_dir in parse_git_invocations(command, cwd):
        if sub == "commit":
            branch = current_branch(repo_dir)
            if branch in PROTECTED:
                deny("`git commit` in '" + repo_dir + "' which is on protected"
                     " branch '" + branch + "'. This checkout is shared across"
                     " sessions.")
        elif sub == "push":
            check_push(args, repo_dir)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail open: guard must never break unrelated commands
