# Working a slice: the loop

A **slice** is one Plane work item (key `LIS-NN`) — a tracer-bullet vertical slice from
`/to-issues`, or any issue moved to `ready-for-agent`. This doc is the step-by-step for
working a slice as a self-paced loop and for keeping multiple sessions on the **same**
slice out of each other's way. The load-bearing rules also live in `CLAUDE.md` (always in
context); this is the detail.

## Decisions — "worktree? PR? or merge to main directly?"

| Question | Decision |
|---|---|
| Where does the work happen? | A **dedicated git worktree per slice**: `../lis-control-<key>` on branch `<key>-<slug>` (matches the existing `lis-control-lis-10` / `lis-10-compliance-scaffold`). **Never switch the primary `main` checkout's branch** — sessions share it. |
| How does it reach `main`? | **Slice branch → Pull Request → `main`. Always.** Never commit on `main`, never `git push origin main`. Merge the PR once reviewed and CI is green. |
| Why PRs, not a direct merge? | It's the established practice (every change so far is a PR) and it serves the ISO 15189 / IQ‑OQ‑PQ traceability story (ADR‑0001): a reviewed PR is the auditable link from a `main` commit back to its `LIS-NN`. |
| Submodule changes (`core/openelis`, …)? | **Two-level**: PR the component repo first (its own CI runs), then bump the pin in the umbrella slice branch + umbrella PR. See below. |
| How do sessions coordinate? | The **Plane issue is the shared ledger** (state + comments). The slice branch is the shared artifact: fetch+rebase before every commit, push right after, never force-push. |

## The loop

Run with `/loop` self-paced (no interval) so each iteration re-reads the issue before
acting. Resolve `PROJECT_ID` from `.claude/plane-context.json` and run the `plane` CLI per
`docs/agents/issue-tracker.md`. One iteration:

1. **Select** — the slice is the current `.claude/plane-context.json` issue, or pick one from
   `python3 scripts/slice.py next` (ready-for-agent ∧ unassigned, grouped by stage and
   priority-sorted — prefer the **earliest open stage**, that's the startable work). Don't use
   raw `plane issues list --state <…>`: the API ignores that filter and returns everything
   (`docs/agents/issue-tracker.md`).
2. **Set up the workspace** (first iteration) — ensure the slice worktree + branch exist;
   create them from an up-to-date `main` if not:
   ```bash
   git -C /home/marloeu/projects/lis-control fetch origin
   git -C /home/marloeu/projects/lis-control worktree add ../lis-control-lis-NN -b lis-NN-<slug> origin/main
   ```
   Reuse the worktree if it already exists. Point that worktree's
   `.claude/plane-context.json` at the slice issue.
3. **Sync + claim** — read the ticket with `python3 scripts/slice.py show LIS-NN`, then
   `python3 scripts/slice.py status LIS-NN` for current ownership (assignee + any live
   claims with their TTL) without reading the whole activity feed. To take work,
   `python3 scripts/slice.py claim LIS-NN --task "<sub-task / files>" --start` — this
   assigns the issue (the coarse *taken* flag, which then hides it from other agents'
   `slice.py next`), posts a machine-readable TTL'd claim record, **and** (with `--start`)
   transitions the issue to In Progress in the same command. The claim is race-safe:
   the ledger record is written first and re-read, and if another agent's live claim
   landed earlier the command withdraws and exits non-zero. If another agent already
   holds a live claim, `claim` refuses (cooperative lock) — take a different sub-task, or
   `--force` to share the slice and partition by sub-item. For full history,
   `plane comments list --all` still works.
4. **Work one increment** toward the acceptance criteria. For code, follow `/tdd`
   (red→green→refactor) and the relevant `CONTEXT.md` glossary (`docs/agents/domain.md`).
   Keep the increment small enough to commit cleanly.
5. **Integrate** — from the slice worktree:
   `git -C <worktree> fetch origin && git -C <worktree> rebase origin/<branch>`, then commit
   (subject references `LIS-NN`), then **push immediately** so other sessions see it.
6. **Log** — post a progress comment on the issue (what landed, what's next). Markdown
   renders properly via
   `printf '%s' "$NOTE" | python3 scripts/plane_issue.py comment LIS-NN --body-file -`.
7. **Done?** — if the acceptance criteria are met, open/refresh the PR (see PR conventions)
   and move the issue to your review/done state, then stop or select the next slice.
   Otherwise, loop.

Stop the loop when: the PR is open and the slice is in review/done; you're blocked (set the
issue to `needs-info`, comment why, stop); or you hit a budget/time bound.

## Coordinating multiple sessions on one slice

Sessions may run **in the same worktree** (memory: "multiple sessions share this checkout")
or in separate worktrees on the same branch. The Plane issue is the coordination point:

- **Claim, then work.** `scripts/slice.py status LIS-NN` to see live claims; `scripts/slice.py
  claim LIS-NN --task "<sub-task / files>"` to take one. Claims are a machine-readable ledger
  (assignee = coarse *taken* flag; a `LIS-CLAIM v1 agent=… task=… until=…` comment = the
  fine, per-agent record) — not free-text prose to eyeball. A live claim by another agent is a
  cooperative lock: `claim` refuses without `--force`. Claims carry a **TTL**, so an expired
  claim is automatically reclaimable.
- **Partition by sub-item.** Split a slice into Plane sub-items
  (`plane issues create -p PROJECT_ID --name "…" --parent <key>`); each session owns disjoint
  sub-items → disjoint files. This is the unit of parallelism.
- **Same worktree = one working tree and index.** Only one session runs mutating git ops
  (commit / rebase) at a time, and never edit the same file concurrently. Announce long
  edits or builds in a comment first.
- **Branch hygiene.** `fetch && rebase origin/<branch>` before every commit; push right
  after. **Never force-push** a shared slice branch. A rebase conflict means two sessions
  touched the same lines — resolve and re-partition.
- **Heartbeat.** Long loops run `scripts/slice.py heartbeat LIS-NN` to extend the claim's TTL
  (the task text carries over), so a second agent reads active-vs-stalled from the structured
  record instead of guessing from prose. On done / blocked / handoff,
  `scripts/slice.py release LIS-NN` drops the claim and unassigns — unless another agent still
  holds a live claim on the shared slice, in which case the *taken* flag stays until the last
  live claim releases.

## Submodule slices (two-level sync)

A slice that touches a submodule (e.g. `core/openelis`) lands in **two** PRs, because the
umbrella only pins a component SHA (ADR‑0001):

1. **Component PR.** Inside the submodule, branch and commit
   (`git -C core/openelis switch -c lis-NN-<slug>`), push to the component repo
   (`aiLabSolution/OpenELIS-Global-2`), and open a PR there. Let the component's own CI run
   (OpenELIS has backend / frontend / e2e workflows).
2. **Umbrella pin bump.** Once the component change is on its target branch, bump the pin in
   the slice worktree (`git -C <worktree> add core/openelis`), commit
   (`bump core/openelis to <sha> for LIS-NN`), push, and open the umbrella PR. Umbrella-side
   docs (`contexts/<mount>/…`, ADRs, plan) go in this same umbrella PR — one umbrella commit
   is a reproducible pinned snapshot.

A slice that touches only umbrella assets (docs, ADRs, plan, agent config) is a single
umbrella PR.

## PR conventions

- Open with `gh pr create` from the slice worktree; title `LIS-NN: <summary>`; body links
  the Plane issue and lists the acceptance criteria met.
- Keep `.claude/plane-context.json` churn out of the substantive diff — it's per-checkout
  bookkeeping, not slice content.
- Merge once reviewed and CI is green. After merge, `git worktree remove` the slice worktree,
  delete the branch, and move the issue to done.
