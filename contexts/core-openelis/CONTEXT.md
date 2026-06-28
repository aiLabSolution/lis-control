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
- **ADR-0002 — LOINC/UCUM reference seed + vendor-code normalization mapping** (S0.6 / LIS-8):
  `docs/adr/0002-loinc-ucum-vendor-code-seed.md`.
- **ADR-0003 — Result ingest contract (edge → append-only Result store)** (S1.3 / LIS-15):
  `docs/adr/0003-result-ingest-contract.md`.
- **ADR-0004 — FHIR R4 result validation (`$validate`) + HAPI/logging stack realignment**
  (S4.1 / LIS-41): `docs/adr/0004-fhir-r4-result-validation.md`. Bumps hapi-fhir 7.0.2→8.10.0
  (+ slf4j 2.x / log4j2 2.24.3) so the FHIR instance validator runs; a finalized result is gated
  as a `$validate`-clean R4 DiagnosticReport + Observation.

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

Normalization reference (post-S0.6 — see component ADR-0002):

- **Vendor-code mapping** — the analyzer-native code → normalized `(LOINC, UCUM)` lookup,
  `clinlims.vendor_code_mapping`, keyed by `(source, vendor_code)` (e.g. `ANALYZER`/`GLU`
  → LOINC `2345-7`, UCUM `mg/dL`). The reference the Stage-1 normalization service
  ("vendor code → LOINC, unit → UCUM") consumes to populate a result's `loinc`/`ucum_value`
  from its `raw_code`/`raw_unit`. Seeded by changeset 048; reached via SQL until the
  Stage-1 entity/service lands (LIS-14). Distinct from `test_terminology_mapping` (043),
  which keys a LOINC code per OpenELIS `test` (FK to `test`), not per analyzer code.
- **UCUM master** — `clinlims.unit_of_measure.ucum_code` (changeset 042) is the canonical
  UCUM home. The S0.6 seed keeps the UCUM unit only on `vendor_code_mapping` (a
  self-contained reference), **not** on `unit_of_measure`: the integration-test harness
  resets/reloads `unit_of_measure` between tests, so a seeded row there is unobservable to
  an integration test. Wiring the mapping's UCUM into `unit_of_measure.ucum_code` is later
  normalization-service work (ADR-0002).

Result ingest (post-S1.3 — see component ADR-0003):

- **Ingest contract** — the edge→core seam (`org.openelisglobal.result.ingest`): a
  transport-neutral `NormalizedObservation` (the analyzer-native `rawCode`/`rawUnit` beside
  the normalized `loinc`/`ucumValue` + `status`, mirroring the edge normalizer's intermediate
  row) and `ResultIngestService.ingest(...)`, which persists one observation as a new
  `result` row through `ResultService` so the append-only `result_version` spine records the
  write. The edge normalizes (ADR-0006); core persists raw beside normalized. Insert-only —
  order-linkage (S4.2), a configurable ingest service-account (today the system user `1`),
  and re-ingest idempotency are deferred.
