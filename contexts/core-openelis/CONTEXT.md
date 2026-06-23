# Context — OpenELIS core

> Layered context for the `core/openelis` submodule. Hosted in the umbrella alongside the
> pin. The core is now a **standalone line on `main`** (ADR-0003); upstream tracking removed.

## What this is

The clinical core of the LIS: orders, results, QC, reporting, RBAC, audit, and the
clinical data model. We adopt it by **forking OpenELIS Global 2** rather than
building these solved problems from scratch (research report, executive summary;
plan §0 Stage 0).

## Repo & versioning

- **Mount:** `core/openelis/` (git submodule, pinned in `lis-control`).
- **origin:** `https://github.com/aiLabSolution/OpenELIS-Global-2.git` — standalone; default & tracked branch `main` (ADR-0003).
- **No `upstream` remote.** Upstream tracking was removed; the repo is a standalone export
  (not a GitHub fork). Pulling a future DIGI-UW fix is a deliberate ad-hoc cherry-pick.
- **Bump the pin:** develop on `core/openelis` `main`, push, then
  `git -C ../.. add core/openelis && git commit -m "core: bump openelis to <sha>"` to record the new pin.
- **Local build env:** JDK 21 + Maven (Testcontainers-backed tests); see `docs/runbooks/core-build-env.md`.

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
