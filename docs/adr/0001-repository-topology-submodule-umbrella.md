# ADR-0001 — Repository topology: submodule umbrella with upstream-tracking forks

- **Status:** Accepted
- **Date:** 2026-06-22
- **Deciders:** Marloe Uy (aiLabSolution)
- **Supersedes / Superseded by:** §4–§5 (upstream-tracking remote + clean-mirror branch) **superseded by ADR-0003** for the `core/openelis` component. The submodule-umbrella topology (§1–§3) still stands.

## Context

The LIS programme spans (a) planning/architecture/agent assets that are
LabSolution's own and (b) several large code components that are **forks or
mirrors of upstream open-source projects** — first the OpenELIS Global 2 clinical
core, later the instrument driver/interface layer, analyzer plugins, deploy kit,
and IaC (see `LIS_IMPLEMENTATION_PLAN.md` §5). The plan requires that we be able
to **track upstream releases** and **contribute generic plugins back upstream**
(plan §0, §6), and it leans heavily on **reproducibility/traceability** for the
ISO 15189 / IQ-OQ-PQ validation story ("a clean checkout reproduces the system").

`lis-control` itself is a thin control plane: research, the phased plan, diagrams,
and agent/issue-tracker configuration. It is not application code.

The question: how should `lis-control` relate to the code components?

## Decision

1. **`lis-control` is the umbrella repo** (`aiLabSolution/lis-control`, **private**).
   It holds LabSolution-authored planning/architecture/agent assets and **pins each
   code component as a git submodule**. One revision of `lis-control` therefore
   reproduces the whole system at known component SHAs — the spine of the
   traceability story.

2. **Each code component is its own standalone repo under the `aiLabSolution` org**
   and is mounted as a submodule. OpenELIS is mounted at `core/openelis`
   (→ `aiLabSolution/OpenELIS-Global-2`, branch `develop`). Future components:
   `edge/drivers/`, `plugins/`, `deploy/kit/`, `infra/`.

3. **Components are NOT vendored into `lis-control`'s history** (no `git subtree`,
   no monorepo for the core). Vendoring would block pulling upstream releases and
   PRing fixes upstream.

4. **Each fork carries an `upstream` remote** pointing at the canonical project,
   so releases can be merged in and generic work contributed back. For OpenELIS:
   - `origin`   → `https://github.com/aiLabSolution/OpenELIS-Global-2.git` (our mirror)
   - `upstream` → `https://github.com/DIGI-UW/OpenELIS-Global-2.git` (canonical)

5. **Fork tracked branches stay a clean mirror of upstream.** LabSolution-authored
   documentation and overlays (including per-component `CONTEXT.md`) live in the
   **umbrella** under `contexts/<mount>/`, *not* committed into the fork's tracked
   branch. This keeps `git merge upstream/<branch>` conflict-free and keeps all
   LabSolution-authored docs versioned together with the pin. (See "Layered
   context" in `CONTEXT-MAP.md`.) This is reversible: if in-tree `CONTEXT.md`
   files become preferable, move them into each submodule and reference them from
   the map instead.

## Consequences

**Positive**
- A single `lis-control` commit = a reproducible, pinned snapshot of every
  component — directly serves IQ/OQ/PQ traceability.
- Upstream sync and upstream contribution stay first-class (clean fork branches).
- Each component versions, branches (per-analyzer channel), and ships independently
  without redeploying the core (plan §5).

**Negative / costs**
- Submodule UX friction: detached HEAD inside submodules; updating a component is
  two steps (commit/push in the submodule, then bump the pin in `lis-control`).
- Clone requires `--recurse-submodules` (documented in `README.md`).
- OpenELIS itself contains **nested submodules** (`plugins`, `hapi-fhir-jpaserver-starter`,
  `dataexport`, `tools/*`, `Consolidated-Server`, `projects/catalyst`) still pointing
  at DIGI-UW (and one via SSH). Building the core requires initialising those; per
  plan §5 they should eventually be mirrored under `aiLabSolution` too. **Open item.**

## Alternatives considered

- **Monorepo** (everything in one repo): simplest dev UX, but forfeits upstream
  tracking/contribution for the OpenELIS core — rejected.
- **`git subtree`** (vendor upstream into history): one clone gets everything, but
  heavier and muddies upstream sync/PR flow — rejected for the core.
- **Ignored nested clones + manifest** (`repos.yaml` / `vcstool` / `git-repo`):
  lower daily friction, but loses the automatic single-revision pin unless the
  manifest records SHAs — rejected in favour of submodules given the
  reproducibility requirement.
- **Sibling repos + thin meta repo** (components beside `lis-control`, not nested):
  avoids a heavy nested tree, but components aren't physically under the umbrella —
  rejected per the chosen nested layout.
