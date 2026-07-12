---
name: work-slice
description: Work a Plane slice (LIS-NN) end to end — pick, claim, worktree, increments, PR, review gates, teardown, release. Use when asked to 'work the next slice', 'pick up LIS-NN', 'grab a slice', or via /work-slice. A recipe card over docs/agents/slice-loop.md, which stays the authority.
model: opus
---

# work-slice — one slice, end to end

`docs/agents/slice-loop.md` is the authority (rationale, multi-session coordination,
sub-item partitioning) — this card is the executable path through it and never overrides
it. Commands run from the umbrella checkout root.

## Model routing

The invoking turn runs on **opus** (frontmatter; later turns resume the session model) —
the orchestration tier. When delegating:
implementation increments and workflow stages go to **sonnet** (`model: sonnet`; effort
low/medium for mechanical work); reserve **fable** for wire-protocol analysis and adversarial
verification (session-limited). The bundled agents pin their own tiers via frontmatter —
don't override them.

## 0. Preflight

```bash
[ -n "${PLANE_API_KEY:+set}" ] || echo "PLANE_API_KEY missing"   # ask the user — never grep for the key
[ "$(git config core.hooksPath)" = ".githooks" ] || scripts/setup-githooks.sh
```

The key's presence flip-flops between sessions, so check FIRST. The hook guard rejects
direct pushes to `main` locally (a blocked push just fails — re-route to a PR).

## 1. Pick

```bash
python3 scripts/slice.py next          # ready-for-agent ∧ unassigned, stage-ordered (~800 tokens)
python3 scripts/slice.py show LIS-NN   # read the ticket (--comments N, --json)
```

Never a raw `plane issues list` dump — the API ignores server-side filters and costs
~28k tokens (`docs/agents/issue-tracker.md`).

## 2. Claim

```bash
python3 scripts/slice.py status LIS-NN
python3 scripts/slice.py claim LIS-NN --task "<sub-task / files>" --start
```

`--start` transitions to In Progress in the same call; claim TTL defaults to 90 min.
Recovery paths (both exit non-zero):

- **CONTENDED** — another agent's live claim is a cooperative lock. Pick a different
  slice; `--force` ONLY to deliberately share it (then partition by sub-item).
- **LOST RACE** — the claim is ledger-first, first-writer-wins: the tool already
  withdrew your claim. Re-check `status`, pick another slice.

## 3. Worktree

```bash
git fetch origin
git worktree add ../lis-control-lis-NN -b lis-NN-<slug> origin/main
```

NEVER work in the shared `main` checkout; never commit on `main`.

## 4. Work increments

TDD (`/tdd`), small commits whose subjects reference `LIS-NN`. Before every commit
`git fetch origin && git rebase origin/<slice-branch>`, push immediately after — exactly
as slice-loop.md states. NEVER force-push the shared slice branch; if it falls behind
main, merge origin/main INTO the branch (fast-forward push). On long runs extend the
claim before the 90-min TTL lapses:

```bash
python3 scripts/slice.py heartbeat LIS-NN   # task text carries over
```

## 5. Log progress on the issue

```bash
printf '%s' "$BODY" | python3 scripts/plane_issue.py comment LIS-NN --body-file -
```

Markdown renders properly; `--dry-run` to preview. Comments are the progress log and
claim ledger — never the issue body.

## 6. PR

Title `LIS-NN: <summary>`; body links the Plane issue and lists each AC and how it is
met — this body is the ISO-traceability artifact (ADR-0001). Keep
`.claude/plane-context.json` churn OUT of the diff. Submodule slices are two-level
(component PR → umbrella pin bump) — defer to the **pin-bump** skill for the chain;
edge ingestion slices land in BOTH `edge/drivers` and the `edge/sim` mirror.

## 7. Gate

Run the **adversarial-reviewer** agent on the PR — it is the merge gate (umbrella CI is
path-filtered, components have no CI). Run **ac-verifier** before moving the issue to
Done.

## 8. Merge + teardown (one-liners — detail in pin-bump)

- `gh pr merge` from a linked worktree errors on its LOCAL post-step while the server
  merge succeeded — verify via REST `.merged`, then clean up by hand.
- Root-owned `target/` from Docker builds blocks worktree removal:
  `docker run --rm -v <worktree>:/w alpine rm -rf /w/target`.
- Then `git worktree remove ../lis-control-lis-NN`, `git worktree prune`, delete the
  branch.

## 9. Release

```bash
python3 scripts/slice.py release LIS-NN
```

Drops your claim and unassigns — unless another agent still holds a live claim, in
which case the assignee (the *taken* flag) stays until the last claim releases. Use
`--keep-assignee` to stay assigned across a handoff.
