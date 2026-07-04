#!/usr/bin/env python3
"""PreToolUse guard (Bash): flag commands that would stage a submodule pin.

Submodule pointer changes (core/openelis, edge/drivers, deploy/kit, ...) must
be *intentional* pin bumps — the two-level protocol is: component PR merges
first, then the umbrella PR advances the pin. A sweeping `git add -A` /
`git add .` / `git commit -a` while a submodule pointer is dirty silently
smuggles a pin change into an unrelated commit.

This hook answers with permissionDecision "ask" (never a hard block): an
intentional pin bump is one approval away; an accidental sweep gets caught.

Fail-open on any unexpected error. Stdlib only.
"""

import json
import os
import re
import shlex
import subprocess
import sys

SEPARATORS = re.compile(r"&&|\|\||;|\|")
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
SWEEP_ADD_FLAGS = {"-A", "--all", "-u", "--update", "--no-ignore-removal"}
SWEEP_COMMIT_FLAGS = {"-a", "--all", "-am"}


def ask(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def run_git(repo_dir, *argv):
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, *argv],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def submodule_paths(repo_dir):
    top = run_git(repo_dir, "rev-parse", "--show-toplevel")
    if not top:
        return None, []
    top = top.strip()
    gitmodules = os.path.join(top, ".gitmodules")
    if not os.path.isfile(gitmodules):
        return top, []
    conf = run_git(top, "config", "-f", ".gitmodules", "--get-regexp", r"submodule\..*\.path")
    if not conf:
        return top, []
    return top, [line.split(" ", 1)[1].strip() for line in conf.strip().splitlines() if " " in line]


def dirty_submodules(top, paths):
    status = run_git(top, "status", "--porcelain", "--", *paths)
    if not status:
        return []
    dirty = []
    for line in status.splitlines():
        entry = line[3:].strip().strip('"')
        if entry in paths:
            dirty.append(entry)
    return dirty


def parse_git_invocations(command, cwd):
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


def normalize(path_arg, repo_dir, top):
    """Resolve a git pathspec argument to a top-relative path."""
    p = path_arg.strip().strip('"').strip("'")
    absolute = p if os.path.isabs(p) else os.path.join(repo_dir, p)
    try:
        rel = os.path.relpath(os.path.normpath(absolute), top)
    except ValueError:
        return None
    return rel


def main():
    payload = json.load(sys.stdin)
    command = (payload.get("tool_input") or {}).get("command") or ""
    if "git" not in command or not ("add" in command or "commit" in command):
        return
    cwd = payload.get("cwd") or os.getcwd()

    for sub, args, repo_dir in parse_git_invocations(command, cwd):
        if sub not in ("add", "commit"):
            continue
        top, subs = submodule_paths(repo_dir)
        if not top or not subs:
            continue
        flags = [a for a in args if a.startswith("-")]
        paths = [a for a in args if not a.startswith("-")]

        if sub == "add":
            # explicit stage of a submodule pointer
            for arg in paths:
                rel = normalize(arg, repo_dir, top)
                if rel in subs:
                    ask("`" + command.strip() + "` explicitly stages the submodule"
                        " pointer '" + rel + "' (a pin bump). Approve only if this"
                        " is a deliberate pin advance for an umbrella PR whose"
                        " component PR already merged (two-level protocol,"
                        " docs/agents/slice-loop.md).")
            # sweeping adds while a pointer is dirty
            sweeping = bool(set(flags) & SWEEP_ADD_FLAGS) or any(
                (normalize(a, repo_dir, top) or "?") in (".", "")
                or any(s.startswith((normalize(a, repo_dir, top) or "?") + "/") for s in subs)
                for a in paths
            )
            if sweeping:
                dirty = dirty_submodules(top, subs)
                if dirty:
                    ask("Sweeping `git add` while submodule pointer(s) are dirty: "
                        + ", ".join(dirty) + ". This would silently stage a pin"
                        " bump into this commit. Approve only if the pin advance is"
                        " intended; otherwise add specific paths, or exclude with"
                        " `git add -- . ':(exclude)" + dirty[0] + "'`.")
        elif sub == "commit" and (set(flags) & SWEEP_COMMIT_FLAGS):
            dirty = dirty_submodules(top, subs)
            if dirty:
                ask("`git commit -a` while submodule pointer(s) are dirty: "
                    + ", ".join(dirty) + ". This would commit a pin bump"
                    " implicitly. Approve only if the pin advance is intended;"
                    " otherwise stage files explicitly and commit without -a.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail open
