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
including inside `sh|bash|zsh|dash [flags] -c '…'` wrapper strings (two
levels deep):
  * `gh pr merge ...`, and
  * `gh api ... repos/<owner>/<repo>/pulls/<n>/merge[?…]` with an explicit
    PUT method (a method-less call to that endpoint is the read-only "is it
    merged?" probe pin-bump uses, and stays allowed).
Flag values never hide a merge: spaced (`-X PUT`), equals (`--method=PUT`,
`-X=PUT`), and pflag-glued (`-XPUT`, `-Ro/r`) forms are all parsed. Each PR
is resolved via `gh pr view --json headRefOid,statusCheckRollup` and blocked
unless every rollup entry is green (CheckRun concluded SUCCESS/NEUTRAL/
SKIPPED; StatusContext state SUCCESS). When the umbrella `local_ci.json` is
in local mode, a repository marked `gate_required` must additionally have a
successful StatusContext named `local-ci/summary` on that exact head. A
branch-inferred merge (`gh pr
merge` with no selector) after a directory change anywhere earlier in the
command — including across a wrapper boundary — is blocked outright: the
hook would resolve the PR from the pre-cd cwd and could gate the wrong PR;
use an explicit number + --repo.

An EMPTY rollup passes in hosted mode. That covers repos with no CI configured
(bridge, kit) and path-filtered umbrella PRs, but ALSO a CI repo whose
workflows never triggered on the head (the LIS-210 "core CI dead" scenario) —
the hook cannot tell these apart. The doc layer closes that residual hole: the
adversarial reviewer treats unrun EXPECTED checks as red and cannot APPROVE
over them. In local mode the required summary above closes that hole for each
gate-required repository.

Known limitations (deliberate-evasion shapes, out of scope): invocations the
tokenizer cannot see — gh hidden behind another script or alias, command
substitution, an absolute path like /usr/bin/gh, endpoints assembled from
variables, wrappers nested more than two deep. The override below is the
sanctioned exception path; anything that routes around the hook instead is
a protocol violation the PR trail will show. The override token is also
honored when it appears quoted elsewhere in the same command (e.g. inside a
commit message) — accepted: it is whitespace-bounded, always visible in the
audited command, and that accident window is narrow.

Failure policy — deliberately split
-----------------------------------
* Before the command is classified as a merge (malformed stdin, non-Bash
  tool, unparseable command): FAIL OPEN, like the other hooks — a broken
  hook must never brick a session.
* After a merge is detected but the checks cannot be verified (gh missing,
  network/auth error, cwd not a repo): FAIL CLOSED. This diverges from the
  edit-guard convention on purpose: merges are rare, high-stakes, and cheap
  to retry, and the block message says exactly what failed.
* A missing or invalid umbrella local-CI registry: FAIL OPEN for the additive
  summary requirement only. The existing non-green rollup gate still fails
  closed exactly as before.

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
from pathlib import Path

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
_LOCAL_SUMMARY_CONTEXT = "local-ci/summary"
_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "local_ci.json"
_PR_URL_RE = re.compile(
    r"^https?://[^/]+/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)

_PUNCTUATION = "();<>|&"
# `gh pr merge` flags that consume a value token (so the value is never
# mistaken for the PR selector). Unknown flags are assumed boolean; the worst
# case is a spurious block whose message shows exactly what was resolved.
_VALUE_FLAGS = {"-R", "--repo", "-t", "--subject", "-b", "--body", "-F",
                "--body-file", "--match-head-commit", "-A", "--author-email"}
_PR_SHORT_VALUE = {"-R", "-t", "-b", "-F", "-A"}
# `gh api` flags that consume a value token (so the value is never mistaken
# for the endpoint — `gh api -X PUT -f merge_method=squash repos/…/merge`
# must still be detected as a merge).
_API_VALUE_FLAGS = {"-f", "--raw-field", "-F", "--field", "-H", "--header",
                    "--input", "-q", "--jq", "-t", "--template",
                    "--hostname", "-p", "--preview", "--cache"}
_API_SHORT_VALUE = {"-f", "-F", "-H", "-q", "-t", "-p"}
_API_MERGE_RE = re.compile(r"\brepos/([\w.-]+)/([\w.-]+)/pulls/(\d+)/merge/?(?:\?\S*)?$")
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


def _glued_value(token, shorts):
    """pflag-glued short-flag value: '-XPUT' / '-X=PUT' → ('-X', 'PUT'); else None."""
    if len(token) > 2 and token[0] == "-" and token[1] != "-" and token[:2] in shorts:
        value = token[2:]
        return (token[:2], value[1:] if value.startswith("=") else value)
    return None


def _skip_value_flag(tokens, j):
    """Index after a spaced value flag; never swallows a shell separator
    (`gh pr merge -t; gh pr merge 6 …` must not hide the second merge)."""
    if j + 1 < len(tokens) and not _is_sep(tokens[j + 1]):
        return j + 2
    return j + 1


def _parse_gh_pr_merge(tokens, dir_changed):
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
                if tok in ("-R", "--repo") and j + 1 < len(tokens) and not _is_sep(tokens[j + 1]):
                    repo = tokens[j + 1]
                j = _skip_value_flag(tokens, j)
                continue
            glued = _glued_value(tok, _PR_SHORT_VALUE)
            if glued:
                if glued[0] == "-R":
                    repo = glued[1]
                j += 1
                continue
            if tok.startswith("--repo="):
                repo = tok.split("=", 1)[1]
            elif tok.startswith("-"):
                pass  # boolean flag (or --flag=value that isn't a repo)
            elif selector is None:
                selector = tok
            j += 1
        if not help_seen:
            target = {"selector": selector, "repo": repo}
            if selector is None and (
                dir_changed or any(t in _DIR_CHANGERS for t in tokens[:i])
            ):
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
            if tok in ("-X", "--method"):
                if j + 1 < len(tokens) and not _is_sep(tokens[j + 1]):
                    put = tokens[j + 1].upper() == "PUT"
                j = _skip_value_flag(tokens, j)
                continue
            method_glued = _glued_value(tok, {"-X"})
            if method_glued:
                put = method_glued[1].upper() == "PUT"
                j += 1
                continue
            if tok in _API_VALUE_FLAGS:
                j = _skip_value_flag(tokens, j)
                continue
            if _glued_value(tok, _API_SHORT_VALUE):
                j += 1
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


def _wrapper_payloads(tokens):
    """(payload, dir_changed_before) for each `sh|bash|… [flags] -c '…'`."""
    payloads = []
    for i, tok in enumerate(tokens):
        if tok.rsplit("/", 1)[-1] not in _WRAPPER_SHELLS:
            continue
        k = i + 1
        while k < len(tokens) and not _is_sep(tokens[k]):
            t = tokens[k]
            if t.startswith("--"):
                k += 1  # long flag before -c (e.g. bash --login -c '…')
                continue
            if t.startswith("-") and "c" in t:
                if k + 1 < len(tokens) and not _is_sep(tokens[k + 1]):
                    dir_changed = any(x in _DIR_CHANGERS for x in tokens[:i])
                    payloads.append((tokens[k + 1], dir_changed))
                break
            break  # first non-flag token: script-file form, not -c
    return payloads


def _parse_merge_invocations(command, depth=0, dir_changed=False):
    tokens = _tokens(command)
    targets = _parse_gh_pr_merge(tokens, dir_changed) + _parse_gh_api_merge(tokens)
    if depth < 2:
        # `bash -c '…'`: the quoted script is one token — re-tokenize it so
        # wrapped merges are still gated, carrying the outer cd context in.
        for payload, changed_before in _wrapper_payloads(tokens):
            targets += _parse_merge_invocations(
                payload, depth + 1, dir_changed or changed_before
            )
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


def _resolved_repository(data, target):
    """Resolve the PR's base repository without trusting the hook cwd."""
    match = _PR_URL_RE.match(str(data.get("url") or ""))
    if match:
        return f"{match.group(1)}/{match.group(2)}"

    # `url` is part of the gh query and is normally authoritative. This fallback
    # keeps the direct helper usable with synthetic/older gh payloads while
    # still refusing ambiguous host/owner/repo shapes.
    repo = target.get("repo")
    if isinstance(repo, str) and re.fullmatch(r"[^/\s]+/[^/\s]+", repo):
        return repo
    return None


def _requires_local_summary(repository):
    """Whether the umbrella registry enables the local summary gate.

    Registry discovery is anchored to this hook's checkout, never payload cwd.
    Missing, syntactically invalid, or structurally unusable registry data
    disables only this additive check; the existing rollup gate still runs.
    """
    if not repository:
        return False
    try:
        with _REGISTRY_PATH.open(encoding="utf-8") as handle:
            registry = json.load(handle)
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(registry, dict) or registry.get("version") != 1:
        return False
    if registry.get("mode") != "local":
        return False
    repositories = registry.get("repositories")
    if not isinstance(repositories, dict):
        return False
    wanted = repository.lower()
    for name, settings in repositories.items():
        if not isinstance(name, str) or not isinstance(settings, dict):
            return False
        gate_required = settings.get("gate_required", False)
        if type(gate_required) is not bool:
            return False
        if name.lower() == wanted:
            return gate_required
    return False


def _local_summary_problem(rollup):
    summaries = [
        item for item in (rollup or [])
        if item.get("__typename") == "StatusContext"
        and item.get("context") == _LOCAL_SUMMARY_CONTEXT
    ]
    if not summaries:
        return f"missing successful StatusContext `{_LOCAL_SUMMARY_CONTEXT}`"
    states = [(item.get("state") or "").upper() for item in summaries]
    non_green = [state.lower() or "unknown" for state in states if state != "SUCCESS"]
    if non_green:
        return f"{_LOCAL_SUMMARY_CONTEXT} is " + ", ".join(non_green)
    return None


def _local_summary_message(data, repository, problem):
    head = (data.get("headRefOid") or "?")[:12]
    number = data.get("number", "?")
    where = data.get("url") or f"PR #{number}"
    checkout_hint = "/absolute/path/to/%s-pr-%s-checkout" % (
        repository.lower().replace("/", "-"), number
    )
    command = " ".join([
        "python3",
        shlex.quote(str(_REGISTRY_PATH.parent / "scripts" / "local_ci.py")),
        shlex.quote(str(number)),
        "--repo",
        shlex.quote(repository),
        "--checkout",
        shlex.quote(checkout_hint),
    ])
    return (
        f"BLOCKED: local-CI merge gate — {where} (head {head}) is gate-required "
        f"in local mode but has {problem} on that exact head.\n"
        "Run the umbrella local-CI engine against the exact, clean PR checkout "
        "and wait for its summary status:\n  " + command + "\n"
        "Replace the checkout placeholder with that PR head's absolute worktree "
        f"path; do not point it at the umbrella checkout for a component PR. {_HATCH}"
    )


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

    rollup = data.get("statusCheckRollup")
    bad = _not_green(rollup)
    repository = _resolved_repository(data, target)
    if _requires_local_summary(repository):
        summary_problem = _local_summary_problem(rollup)
        if summary_problem:
            return _local_summary_message(data, repository, summary_problem)
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
