# ADR-0003 — OpenELIS core: standalone `main`, upstream tracking removed

- **Status:** Accepted
- **Date:** 2026-06-23
- **Deciders:** Marloe Uy (aiLabSolution)
- **Supersedes:** ADR-0001 §4 and §5 **for the `core/openelis` component** (the rest of ADR-0001 — the submodule-umbrella topology — still stands).

## Context

ADR-0001 set up `aiLabSolution/OpenELIS-Global-2` as an upstream-tracking fork: `develop`
was kept a **clean mirror** of `DIGI-UW/OpenELIS-Global-2`, an `upstream` remote was carried
for syncing/contributing, and LabSolution-authored material was kept out of the fork's
tracked branch (overlays lived in the umbrella under `contexts/<mount>/`).

That model blocks Stage 0's core work: LIS-5/6/7/8 require **LabSolution code and schema
deltas committed into the core itself** (403-denial recording, DB-layer audit-immutability
triggers, the Result-table shape, the LOINC/UCUM seed + alias tables) plus tests that run in
the core's own build gate. A clean-mirror branch cannot hold those.

## Decision

1. **`main` is the LabSolution line of development** for the OpenELIS core, created from the
   pinned upstream snapshot (`develop@5318e61`, 2026-06-22) and set as the repo's **default
   branch**. LabSolution deltas + tests are committed to `main` (and PR branches off it).

2. **Upstream tracking is removed.** The `upstream` remote (→ `DIGI-UW`) is dropped; we no
   longer keep a clean mirror branch or take routine `git merge upstream/<branch>`. The repo
   is a standalone export (it is already not a GitHub fork: `fork=false`, `parent=null`).

3. **The umbrella pins `core/openelis` on `main`** (`.gitmodules` `branch = main`). The pinned
   SHA is unchanged by this ADR (`main` was branched at the existing pin), so existing umbrella
   commits remain reproducible.

4. **Pulling future upstream fixes becomes a deliberate, manual cherry-pick/merge** from
   `DIGI-UW` when wanted (re-add a remote ad hoc), rather than a standing sync obligation.

5. **`develop` is left in place** (now stale, no longer a mirror); it may be deleted later.

## Consequences

**Positive**
- LIS-5/6/7/8 (and later core deltas) have a home — committed to `main` and gated by the
  core's own CI (`backend.yml` runs on PRs).
- Simpler mental model: one line (`main`), one owner (LabSolution).

**Negative / costs**
- **No automatic upstream fixes.** Security/bug fixes from DIGI-UW must be pulled deliberately;
  without a clean mirror, those merges may conflict with our deltas. Mitigation: keep deltas
  small/localised and cherry-pick upstream fixes as needed.
- The "contribute generic plugins upstream" goal (plan §6, ADR-0001) now needs an explicit
  per-contribution flow rather than a standing clean branch. Revisit when we have generic work
  to upstream.

## Notes

- ADR-0001's nested-submodule open item still applies; the prebuilt-image bootstrap (ADR-0002)
  avoids it. The license-blocked `tools/openelis-analyzer-bridge` (HOLD-001) remains blocked
  for reuse regardless of branch.
