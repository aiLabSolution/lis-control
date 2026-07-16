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
Bash commands that merge a GitHub PR — EVERY such invocation in the command,
including inside `sh|bash|zsh|dash -c '…'` wrapper strings (two levels deep):
  * `gh pr merge ...`, and
  * `gh api ... repos/<owner>/<repo>/pulls/<n>/merge` with an explicit PUT
    method (a method-less call to that endpoint is the read-only "is it
    merged?" probe pin-bump uses, and stays allowed).
It resolves each PR via `gh pr view --json headRefOid,statusCheckRollup` and
blocks unless every rollup entry is green (CheckRun concluded
SUCCESS/NEUTRAL/SKIPPED; StatusContext state SUCCESS). A branch-inferred
merge (`gh pr merge` with no selector) after a directory change in the same
command is blocked outright: the hook would resolve the PR from the pre-cd
cwd and could gate the wrong PR — use an explicit number + --repo.

An EMPTY rollup passes. That covers repos with no CI configured (bridge,
kit) and path-filtered umbrella PRs, but ALSO a CI repo whose workflows
never triggered on the head (the LIS-210 "core CI dead" scenario) — the
hook cannot tell these apart. The doc layer closes that residual hole: the
adversarial reviewer treats unrun EXPECTED checks as red and cannot APPROVE
over them.

Known limitations (deliberate-evasion shapes, out of scope): invocations the
tokenizer cannot see — gh hidden behind another script or alias, command
substitution, an absolute path like /usr/bin/gh, endpoints assembled from
variables. The override below is the sanctioned exception path; anything
that routes around the hook instead is a protocol violation the PR trail
will show.

Failure policy — deliberately split
-----------------------------------
* Before the command is classified as a merge (malformed stdin, non-Bash
  tool, unparseable command): FAIL OPEN, like the other hooks — a broken
  hook must never brick a session.
* After a merge is detected but the checks cannot be verified (gh missing,
  network/auth error, cwd not a repo): FAIL CLOSED. This diverges from the
  edit-guard convention on purpose: merges are rare, high-stakes, and cheap
  to retry, and the block message says exactly what failed.

Escape hatch for a deliberate, reviewed exception: prefix the command itself
with LIS_MERGE_GATE_OVERRIDE=1 (honored as a token in the command string —
the hook process env works too but is not normally reachable mid-session).

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
    "Deliberate, reviewed exception only: prefix the command itself with "
    f"{_OVERRIDE}=1 (this is audited via the PR trail, not a convenience flag)."
)
_OVERRIDE_TOKEN_RE = re.compile(r"(?:^|\s)" + _OVERRIDE + r"=1(?:\s|$)")
_GH_TIMEOUT = 45  # seconds; one networked gh call per merge target

# CheckRun conclusions that count as green. Anything else — FAILURE, ERROR,
# CANCELLED, TIMED_OUT, ACTION_REQUIRED, STALE, or an unfinished run — blocks.
_PASS_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}

_PUNCTUATION = "();<>|&"
# `gh pr merge` flags that consume a value token (so the value is never
# mistaken for the PR selector). Unknown flags are assumed boolean; the worst
# case is a spurious block whose message shows exactly what was resolved.
_VALUE_FLAGS = {"-R", "--repo", "-t", "--subject", "-b", "--body", "-F",
                "--body-file", "--match-head-commit", "-A", "--author-email"}
# `gh api` flags that consume a value token (so the value is never mistaken
# for the endpoint — `gh api -X PUT -f merge_method=squash repos/…/merge`
# must still be detected as a merge).
_API_VALUE_FLAGS = {"-f", "--raw-field", "-F", "--field", "-H", "--header",
                    "--input", "-q", "--jq", "-t", "--template",
                    "--hostname", "-p", "--preview", "--cache"}
_API_MERGE_RE = re.compile(r"\brepos/([\w.-]+)/([\w.-]+)/pulls/(\d+)/merge/?$")
_WRAPPER_SHELLS = {"bash", "sh", "zsh", "dash"}
_DIR_CHANGERS = {"cd", "pushd"}


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


def _value_after(tokens, start, names):
    for j in range(start, len(tokens)):
        if _is_sep(tokens[j]):
            return None
        if tokens[j] in names and j + 1 < len(tokens):
            return tokens[j + 1]
    return None


def _parse_gh_pr_merge(tokens):
    """Every `gh pr merge` invocation → [{'selector','repo',…}, …]."""
    targets = []
    i = 0
    while i + 2 < len(tokens):
        if not (tokens[i] == "gh" and tokens[i + 1] == "pr" and tokens[i + 2] == "merge"):
            i += 1
            continue
        selector, repo, help_seen = None, None, False
        j = i + 3
        while j < len(tokens) and not _is_sep(tokens[j]):
            tok = tokens[j]
            if tok in ("-h", "--help"):
                help_seen = True  # merges nothing
            if tok in _VALUE_FLAGS:
                j += 2
                continue
            if tok.startswith("--repo=") or tok.startswith("-R="):
                repo = tok.split("=", 1)[1]
            elif tok.startswith("-"):
                pass  # boolean flag (or --flag=value that isn't a repo)
            elif selector is None:
                selector = tok
            j += 1
        if repo is None:
            repo = _value_after(tokens, i + 3, ("-R", "--repo"))
        if not help_seen:
            target = {"selector": selector, "repo": repo}
            if selector is None and any(t in _DIR_CHANGERS for t in tokens[:i]):
                # branch-inferred merge after cd: the hook would resolve the
                # PR from the pre-cd cwd and could gate the WRONG PR.
                target["ambiguous_cwd"] = True
            targets.append(target)
        i = j
    return targets


def _parse_gh_api_merge(tokens):
    """Every REST merge (PUT on pulls/<n>/merge) → [{'selector','repo'}, …]."""
    targets = []
    i = 0
    while i + 1 < len(tokens):
        if not (tokens[i] == "gh" and tokens[i + 1] == "api"):
            i += 1
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
            if tok in _API_VALUE_FLAGS:
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
                targets.append({"selector": number, "repo": f"{owner}/{repo}"})
        i = j
    return targets


def _parse_merge_invocations(command, depth=0):
    tokens = _tokens(command)
    targets = _parse_gh_pr_merge(tokens) + _parse_gh_api_merge(tokens)
    if depth < 2:
        # `bash -c '…'` (also -lc/-ec clusters): the quoted script is one
        # token — re-tokenize it so wrapped merges are still gated.
        for i, tok in enumerate(tokens):
            base = tok.rsplit("/", 1)[-1]
            if base in _WRAPPER_SHELLS and i + 2 < len(tokens):
                flag = tokens[i + 1]
                if flag.startswith("-") and not flag.startswith("--") and "c" in flag:
                    targets += _parse_merge_invocations(tokens[i + 2], depth + 1)
    return targets


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
    if target.get("ambiguous_cwd"):
        return _infra_message(
            "the command changes directory before a branch-inferred `gh pr merge`, "
            "so the hook cannot tell which PR would be merged. Use an explicit PR "
            "number plus --repo owner/repo."
        )
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
        return None  # all green, or an empty rollup (see docstring caveat)
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
        if _OVERRIDE_TOKEN_RE.search(command):
            return None  # sanctioned override, visible in the command itself
        targets = _parse_merge_invocations(command)
    except Exception:
        return None  # cannot even classify the command — fail open
    if not targets:
        return None
    try:
        for target in targets:
            message = _gate(target, payload.get("cwd"))
            if message:
                return message
        return None
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
