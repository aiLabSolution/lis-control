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

## Component decisions

- **ADR-0001 — Result table shape + append-only result versions** (S0.5 / LIS-7):
  `docs/adr/0001-append-only-result-versions.md`.

## Glossary

Result data model (post-S0.5 — see component ADR-0001):

- **Raw observation** — what the analyzer reported, persisted on `clinlims.result` as
  `raw_code` (vendor/analyzer test code) + `raw_unit` (unit string as reported).
- **Normalized observation** — the LOINC/UCUM form, persisted beside the raw on the same
  `result` row as `loinc` (a snapshot of `TEST.LOINC`, not a new authority) + `ucum_value`,
  with `status` (`RAW` / `NORMALIZED` / `RECONCILED`) tracking normalization state. Distinct
  from `result_type` (the legacy value-type discriminator: Dictionary / titer / number / date).
- **Result version** — an append-only snapshot of a result's `value` + the five
  normalization columns, one row per change in `clinlims.result_version` (`version_number`
  per `result_id`). Written automatically by an `AFTER INSERT OR UPDATE` trigger on
  `result`; made immutable by a `BEFORE UPDATE OR DELETE` trigger (rejects mutation with an
  `append-only` error). `result_id` is a **soft reference** (no FK), mirroring the
  append-only `clinlims.history` audit spine. This is the no-last-writer-wins foundation
  Stage-4 site↔central reconciliation builds on.
- **Append-only spine** — the project's tamper-evident DB-layer pattern: a `BEFORE
  UPDATE OR DELETE` trigger that `RAISE`s, used by `clinlims.history` (S0.4 / changeset 046)
  and `clinlims.result_version` (S0.5 / changeset 047). `UPDATE`/`DELETE` rejected;
  `INSERT` and `TRUNCATE` (fixture/training resets) unaffected.
