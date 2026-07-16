#!/usr/bin/env python3
"""Claude Code PreToolUse merge gate — no PR merge on a non-green head.

Why this exists
---------------
Green CI on the exact PR head is a hard merge gate in this project (CLAUDE.md
non-negotiables; work-slice skill §7), but until this hook it was doc-level
only: `Bash(gh pr merge*)` is prefix-allowlisted, so a session that skipped
the protocol could still merge a red or unchecked PR. The LIS-133 / core PR
#40 incident proved the failure mode is real — a component PR can be red
while the umbrella pin PR shows green. This hook makes the gate mechanical.

What it gates
-------------
Bash commands that merge a GitHub PR:
  * `gh pr merge ...` (any position in a compound command), and
  * `gh api ... repos/<owner>/<repo>/pulls/<n>/merge` with an explicit PUT
    method (a method-less call to that endpoint is the read-only "is it
    merged?" probe pin-bump uses, and stays allowed).
It resolves the PR via `gh pr view --json headRefOid,statusCheckRollup` and
blocks unless every rollup entry is green (CheckRun concluded
SUCCESS/NEUTRAL/SKIPPED; StatusContext state SUCCESS). An EMPTY rollup passes:
repos with no CI configured (bridge, kit) and path-filtered umbrella PRs get
zero checks by design — there the adversarial review is the whole gate.

Failure policy — deliberately split
-----------------------------------
* Before the command is classified as a merge (malformed stdin, non-Bash
  tool, unparseable command): FAIL OPEN, like the other hooks — a broken
  hook must never brick a session.
* After a merge is detected but the checks cannot be verified (gh missing,
  network/auth error, cwd not a repo): FAIL CLOSED. This diverges from the
  edit-guard convention on purpose: merges are rare, high-stakes, and cheap
  to retry, and the block message says exactly what failed. Escape hatch for
  a deliberate, reviewed exception: LIS_MERGE_GATE_OVERRIDE=1.

Wired in .claude/settings.json as a PreToolUse hook on Bash. Contract: hook
payload JSON on stdin; exit 0 allows, exit 2 blocks (stderr goes back to the
model). Stdlib only.
"""
import json
import os
import re
import shlex
import subprocess
import sys

_OVERRIDE = "LIS_MERGE_GATE_OVERRIDE"
_HATCH = (
    "Deliberate, reviewed exception only: re-run with "
    f"{_OVERRIDE}=1 (this is audited by the PR trail, not a convenience flag)."
)
_GH_TIMEOUT = 45  # seconds; one networked gh call

# CheckRun conclusions that count as green. Anything else — FAILURE, ERROR,
# CANCELLED, TIMED_OUT, ACTION_REQUIRED, STALE, or an unfinished run — blocks.
_PASS_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}

_PUNCTUATION = "();<>|&"
# `gh pr merge` flags that consume a value token (so the value is never
# mistaken for the PR selector). Unknown flags are assumed boolean; the worst
# case is a spurious block whose message shows exactly what was resolved.
_VALUE_FLAGS = {"-R", "--repo", "-t", "--subject", "-b", "--body", "-F",
                "--body-file", "--match-head-commit"}
_API_MERGE_RE = re.compile(r"\brepos/([\w.-]+)/([\w.-]+)/pulls/(\d+)/merge/?$")


def _tokens(command):
    # punctuation_chars so `gh pr merge 5;` yields ['…', '5', ';'] — plain
    # shlex.split would glue the separator onto the selector token.
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return command.split()


def _is_sep(token):
    return bool(token) and all(c in _PUNCTUATION for c in token)


def _parse_gh_pr_merge(tokens):
    """{'selector':…,'repo':…} for the first `gh pr merge`, else None."""
    for i in range(len(tokens) - 2):
        if tokens[i] == "gh" and tokens[i + 1] == "pr" and tokens[i + 2] == "merge":
            selector, repo = None, None
            j = i + 3
            while j < len(tokens) and not _is_sep(tokens[j]):
                tok = tokens[j]
                if tok in ("-h", "--help"):
                    return None  # help invocation merges nothing
                if tok in _VALUE_FLAGS:
                    j += 2
                    continue
                if tok.startswith("--repo="):
                    repo = tok.split("=", 1)[1]
                elif tok.startswith("-"):
                    pass  # boolean flag (or --flag=value that isn't --repo)
                elif selector is None:
                    selector = tok
                j += 1
            if tok_repo := _value_after(tokens, i + 3, ("-R", "--repo")):
                repo = tok_repo
            return {"selector": selector, "repo": repo}
    return None


def _value_after(tokens, start, names):
    for j in range(start, len(tokens)):
        if _is_sep(tokens[j]):
            return None
        if tokens[j] in names and j + 1 < len(tokens):
            return tokens[j + 1]
    return None


def _parse_gh_api_merge(tokens):
    """REST merge (PUT on pulls/<n>/merge) → {'selector','repo'}, else None."""
    for i in range(len(tokens) - 1):
        if tokens[i] != "gh" or tokens[i + 1] != "api":
            continue
        put = False
        endpoint = None
        j = i + 2
        while j < len(tokens) and not _is_sep(tokens[j]):
            tok = tokens[j]
            if tok in ("-X", "--method") and j + 1 < len(tokens):
                put = tokens[j + 1].upper() == "PUT"
                j += 2
                continue
            if tok.startswith("--method="):
                put = tok.split("=", 1)[1].upper() == "PUT"
            elif not tok.startswith("-") and endpoint is None:
                endpoint = tok
            j += 1
        if endpoint and put:
            match = _API_MERGE_RE.search(endpoint)
            if match:
                owner, repo, number = match.groups()
                return {"selector": number, "repo": f"{owner}/{repo}"}
    return None


def _parse_merge_invocation(command):
    tokens = _tokens(command)
    return _parse_gh_pr_merge(tokens) or _parse_gh_api_merge(tokens)


def _not_green(rollup):
    """Human-readable lines for every rollup entry that is not green."""
    bad = []
    for item in rollup or []:
        name = item.get("name") or item.get("context") or "<unnamed check>"
        if item.get("__typename") == "StatusContext" or (
            "state" in item and "status" not in item
        ):
            state = (item.get("state") or "").upper()
            if state != "SUCCESS":
                bad.append(f"{name}: {state.lower() or 'unknown state'}")
            continue
        status = (item.get("status") or "").upper()
        conclusion = (item.get("conclusion") or "").upper()
        if status and status != "COMPLETED":
            bad.append(f"{name}: {status.lower()} (not finished)")
        elif conclusion not in _PASS_CONCLUSIONS:
            bad.append(f"{name}: {conclusion.lower() or 'no conclusion'}")
    return bad


def _infra_message(detail):
    return (
        "BLOCKED: green-CI merge gate could not verify this PR's checks, and it "
        f"fails CLOSED on a merge it cannot verify.\nProblem: {detail}\n"
        "Green CI on the exact PR head is a hard merge gate (CLAUDE.md; work-slice "
        "§7). Remedy: make sure `gh` is installed/authenticated and the PR is "
        "unambiguous (explicit PR number + --repo owner/repo), then re-run. "
        f"{_HATCH}"
    )


def _gate(target, cwd):
    args = ["gh", "pr", "view"]
    if target["selector"]:
        args.append(target["selector"])
    if target["repo"]:
        args += ["--repo", target["repo"]]
    args += ["--json", "number,url,headRefOid,statusCheckRollup"]
    if cwd and not os.path.isdir(cwd):
        cwd = None
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=_GH_TIMEOUT, cwd=cwd or None
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _infra_message(f"could not run gh: {exc}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return _infra_message(
            "`%s` failed: %s" % (" ".join(args), tail[-1] if tail else "no output")
        )
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return _infra_message("gh returned unparseable JSON")

    bad = _not_green(data.get("statusCheckRollup"))
    if not bad:
        return None  # all green, or a genuine no-CI/path-filtered PR (empty rollup)
    head = (data.get("headRefOid") or "?")[:12]
    where = data.get("url") or f"PR #{data.get('number', '?')}"
    return (
        f"BLOCKED: green-CI merge gate — {where} (head {head}) has non-green "
        "checks:\n  - " + "\n  - ".join(bad) + "\n"
        "Every expected check must conclude success on the exact PR head before "
        "approval or merge (CLAUDE.md non-negotiables; work-slice §7). Local runs "
        "supplement CI, never replace it; still-running checks must finish.\n"
        "Remedy: fix and re-run CI, or wait for pending checks, then retry the "
        f"merge. A repo with no CI configured passes this gate automatically. {_HATCH}"
    )


def check(payload):
    """None = allow; str = block message (stderr, exit 2)."""
    if os.environ.get(_OVERRIDE) == "1":
        return None
    try:
        if payload.get("tool_name") != "Bash":
            return None
        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str) or "gh" not in command:
            return None
        target = _parse_merge_invocation(command)
    except Exception:
        return None  # cannot even classify the command — fail open
    if target is None:
        return None
    try:
        return _gate(target, payload.get("cwd"))
    except Exception as exc:  # a detected merge must never slip through on a bug
        return _infra_message(f"unexpected hook error: {exc!r}")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # fail open: a broken hook must never brick a session
    message = check(payload)
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
