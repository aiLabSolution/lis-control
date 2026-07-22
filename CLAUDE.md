# LIS

## Repository structure

`lis-control` is the **umbrella** repo (`aiLabSolution/lis-control`). Code components
are **git submodules** pinned at known SHAs — OpenELIS core at `core/openelis`, more
to come (`edge/drivers`, `plugins`, `deploy/kit`, `infra`). Clone with
`--recurse-submodules`. Topology and rationale: `docs/adr/0001-repository-topology-submodule-umbrella.md`.
Context index: `CONTEXT-MAP.md`.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in Plane.so, driven via the `plane-axi` CLI (the `/plane-axi` skill, tracked in-repo). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, mapped onto Plane workflow states. See `docs/agents/triage-labels.md`.

### Working a slice (the loop)

Work each Plane slice (`LIS-NN`) as a self-paced `/loop`: find, read & claim the next slice
with `scripts/slice.py next` / `show` / `claim` (the cheap, structured front door — **not**
a raw `plane-axi wi list` dump) → work increments in a **dedicated worktree** → push to the
slice branch → log progress on the issue (`scripts/plane_issue.py comment` for markdown) →
open a PR. Non-negotiables:

- **Worktree per slice, never the shared `main` checkout.** `../lis-control-<key>` on branch
  `<key>-<slug>` (e.g. `lis-control-lis-10` / `lis-10-compliance-scaffold`). Don't switch the
  primary checkout's branch — sessions share it.
- **Slice branch → PR → `main`. Never commit on `main` or `git push origin main`.** A reviewed
  PR is the auditable `LIS-NN` ↔ `main` link for the ISO traceability story (ADR-0001); merge
  once reviewed and CI is green. Run `scripts/setup-githooks.sh` once per clone to enable the
  tracked `.githooks/pre-push` guard, which rejects direct pushes to `main` locally (a git
  hook, not a Claude PreToolUse — a blocked push just fails and you re-route to a PR).
- **Submodule changes are two-level**: PR the component repo first, verify that repo's
  expected checks are green on the exact PR head, then bump the pin in the umbrella PR.
  CI is non-transitive: targeted local tests and green umbrella workflows do not replace
  component CI. Checkout/auth/submodule failures are red gates even when tests never start,
  and a component PR must not be merged or pinned merely because GitHub allows it.
- **Coordinate across sessions via the Plane issue** — assignee = the *taken* flag, plus a
  TTL'd claim ledger (`scripts/slice.py status` / `claim` / `heartbeat` / `release`). Check
  status and claim before editing; a live claim by another agent is a cooperative lock.
  Fetch+rebase before every commit, push right after, and never force-push a shared slice branch.

Full protocol (loop steps, multi-session coordination, two-level submodule sync, PR
conventions): `docs/agents/slice-loop.md`.

### Verifying bug fixes

**A bug is not verified until an end-to-end test reproduces it and passes with the fix.
Unit tests are not enough.** Write or run a test that exercises the real flow the bug
lives in — Playwright (`npm run pw:test`) for the OpenELIS frontend, the full Docker
boot + `deploy/ci/healthcheck.sh` for bootstrap/integration issues, the `edge/sim`
harness for analyzer flows. Unit tests confirm the changed unit, not that the bug is
gone from the system; cite the e2e run (or the reproducing test) in the PR / slice
comment when closing a bug.

### Model routing

Route subagents and workflow stages by task type: **opus** for orchestration/planning,
**sonnet** for implementation and mechanical stages, **fable** only for deep analysis and
adversarial verification (session-limited — spend deliberately). The bundled agents pin
their own tiers via frontmatter (adversarial-reviewer → fable, ac-verifier /
findings-triager → opus, pin-auditor → sonnet); don't override them, and never set
`CLAUDE_CODE_SUBAGENT_MODEL` — it outranks frontmatter and flattens the split.

### Domain docs

Multi-context layout — `CONTEXT-MAP.md` at the root points to per-context `CONTEXT.md` files. See `docs/agents/domain.md`.
