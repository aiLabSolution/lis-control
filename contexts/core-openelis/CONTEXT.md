# Context — OpenELIS core

> Layered context for the `core/openelis` submodule. Hosted in the umbrella so the
> fork's tracked branch stays a clean mirror of upstream (ADR-0001 §5).

## What this is

The clinical core of the LIS: orders, results, QC, reporting, RBAC, audit, and the
clinical data model. We adopt it by **forking OpenELIS Global 2** rather than
building these solved problems from scratch (research report, executive summary;
plan §0 Stage 0).

## Repo & versioning

- **Mount:** `core/openelis/` (git submodule, pinned in `lis-control`).
- **origin:** `https://github.com/aiLabSolution/OpenELIS-Global-2.git` — our mirror; tracked branch `develop`.
- **upstream:** `https://github.com/DIGI-UW/OpenELIS-Global-2.git` — canonical OpenELIS Global 2.
- **Sync:** `cd core/openelis && git fetch upstream && git merge upstream/develop`, then
  `git -C ../.. add core/openelis && git commit -m "core: bump openelis to <sha>"` to record the new pin.

## Open items

- **Nested submodules.** Upstream OpenELIS declares its own submodules
  (`plugins`, `hapi-fhir-jpaserver-starter`, `dataexport`, `tools/Liquibase-Outdated`,
  `tools/Password-Migrator`, `tools/openelis-analyzer-bridge`, `tools/analyzer-mock-server`,
  `Consolidated-Server` (SSH), `projects/catalyst`). They still point at DIGI-UW and
  are **not yet initialised**. A buildable core needs them; per plan §5 they should be
  mirrored under `aiLabSolution`. Decide pin/mirror strategy before Stage 0 build.
- **License hygiene.** MPL-2.0 file-level copyleft applies; confirm the
  `openelis-analyzer-bridge` license before reuse (plan §0).

## Glossary

_(lazy — populated by `/grill-with-docs` as terms are resolved)_
