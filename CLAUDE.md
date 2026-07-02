# LIS

## Repository structure

`lis-control` is the **umbrella** repo (`aiLabSolution/lis-control`). Code components
are **git submodules** pinned at known SHAs — OpenELIS core at `core/openelis`, more
to come (`edge/drivers`, `plugins`, `deploy/kit`, `infra`). Clone with
`--recurse-submodules`. Topology and rationale: `docs/adr/0001-repository-topology-submodule-umbrella.md`.
Context index: `CONTEXT-MAP.md`.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in Plane.so, driven via the bundled `plane` CLI (the `/plane` skill). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, mapped onto Plane workflow states. See `docs/agents/triage-labels.md`.

### Working a slice (the loop)

Work each Plane slice (`LIS-NN`) as a self-paced `/loop`: find, read & claim the next slice
with `scripts/slice.py next` / `show` / `claim` (the cheap, structured front door — **not**
a raw `plane issues list` dump) → work increments in a **dedicated worktree** → push to the
slice branch → log progress on the issue (`scripts/plane_issue.py comment` for markdown) →
open a PR. Non-negotiables:

- **Worktree per slice, never the shared `main` checkout.** `../lis-control-<key>` on branch
  `<key>-<slug>` (e.g. `lis-control-lis-10` / `lis-10-compliance-scaffold`). Don't switch the
  primary checkout's branch — sessions share it.
- **Slice branch → PR → `main`. Never commit on `main` or `git push origin main`.** A reviewed
  PR is the auditable `LIS-NN` ↔ `main` link for the ISO traceability story (ADR-0001); merge
  once reviewed and CI is green.
- **Submodule changes are two-level**: PR the component repo first, then bump the pin in the
  umbrella PR.
- **Coordinate across sessions via the Plane issue** — assignee = the *taken* flag, plus a
  TTL'd claim ledger (`scripts/slice.py status` / `claim` / `heartbeat` / `release`). Check
  status and claim before editing; a live claim by another agent is a cooperative lock.
  Fetch+rebase before every commit, push right after, and never force-push a shared slice branch.

Full protocol (loop steps, multi-session coordination, two-level submodule sync, PR
conventions): `docs/agents/slice-loop.md`.

### Domain docs

Multi-context layout — `CONTEXT-MAP.md` at the root points to per-context `CONTEXT.md` files. See `docs/agents/domain.md`.
