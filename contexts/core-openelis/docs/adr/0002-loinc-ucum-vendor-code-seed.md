# ADR-0002 (core/openelis) — LOINC/UCUM reference seed + vendor-code normalization mapping

- **Status:** Proposed (pending review — LIS-8)
- **Date:** 2026-06-26
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `core/openelis` component (clinical core data model / reference data)
- **Relates to:** ADR-0001 (umbrella topology — component-scoped decisions live here); ADR-0001 (core — result shape, the columns this seed targets); LIS-2 (Stage 0 PRD); LIS-8 (S0.6); plan §0 ("Seed LOINC/UCUM reference tables") + §1 ("Normalization service: vendor code → LOINC, unit → UCUM") + research §5.1; forward-looking to Stage 1 (LIS-14/S1.2 — normalize an ORU^R01 to a LOINC/UCUM intermediate)

## Context

S0.6 (LIS-8) is the **normalization seed**: the LOINC/UCUM reference data must load, and
**≥1 sample vendor code must map to a LOINC code + UCUM unit, proven end-to-end onto a
`clinlims.result` row** (plan §0 exit gate; §5.1). It is the data-layer foundation the
Stage-1 normalization service ("vendor code → LOINC, unit → UCUM", plan §1) consumes — the
result columns it writes were laid down by S0.5 (core ADR-0001).

Facts discovered in the core that shape the decision (verified against the source):

- **The five normalized columns already exist** on `clinlims.result` — `raw_code`,
  `raw_unit`, `loinc`, `ucum_value`, `status` (S0.5, changeset `047`). S0.6 supplies the
  *reference data + mapping* that populate them at ingest; the schema is done.
- **LOINC** lives in several coarse, test-scoped places (`TEST.LOINC`, `PANEL.loinc`,
  `DICTIONARY.loinc_code`); the canonical multi-source terminology table is
  `clinlims.test_terminology_mapping` (`043`) — but it is **keyed per `test_id` with an FK
  to `clinlims.test`**, and per-test LOINC backfill is already owned by OGC-939
  (`loinc-mapping-backfill`). It maps an OpenELIS *test* to a code, not an **analyzer-native
  observation code** to one.
- **UCUM** lives in `clinlims.unit_of_measure.ucum_code` (`042`, `VARCHAR(40)`).
- **There is no table** joining an analyzer-native (vendor) observation code directly to
  `(LOINC, UCUM)`. The nearest, `clinlims.unit_mapping`, resolves a vendor unit string to an
  internal `openelis_unit` — not to a UCUM code, and not for the observation code.
- The integration-test harness brings the schema up by **applying the full Liquibase
  changelog** (`base-changelog.xml` → `3.5.x.x/base.xml`), so reference data shipped as a
  changeset (no `context`) is present in the test DB with no test-side fixture.

So normalization needs a lookup the core does not have: **analyzer-native code → (LOINC,
UCUM)**. S0.6 supplies it, seeded with one real mapping, and proves it reaches a result row.

## Decision

Ship S0.6 as a single Liquibase changelog, `3.5.x.x/048-loinc-ucum-seed.xml` (wired after
`047` in `base.xml`), plus one integration test. **No Java entity/DAO/service** (see below).

**1. A new additive reference table `clinlims.vendor_code_mapping`** — the analyzer-native
code → normalized `(LOINC, UCUM)` lookup:

| Column | Type | Meaning |
|---|---|---|
| `id` | `VARCHAR(36)` PK | surrogate (uuid), matching `test_terminology_mapping` (`043`) |
| `source` | `VARCHAR(20)` | analyzer/vendor family the code belongs to (e.g. `ANALYZER`) |
| `vendor_code` | `VARCHAR(80)` | analyzer-native observation code as reported (= `result.raw_code` width) |
| `loinc` | `VARCHAR(80)` | normalized LOINC (= `test_terminology_mapping.code` / `result.loinc` width) |
| `ucum_code` | `VARCHAR(40)` | normalized UCUM unit (= `unit_of_measure.ucum_code` / `result.ucum_value` width) |
| `description` | `VARCHAR(255)` | human analyte label for review/audit |
| `is_active` | `VARCHAR(2)` (`Y`) | lifecycle flag, matching the `043`/`042` convention |
| `lastupdated` | `TIMESTAMP` (`now()`) | |

Unique on `(source, vendor_code)`. Column widths mirror the canonical terminology/UoM
columns and the `047` result columns, so a mapping is directly comparable to what it
populates.

**2. One seeded mapping** — `ANALYZER`/`GLU` → LOINC `2345-7` (*Glucose [Mass/volume] in
Serum or Plasma*), UCUM `mg/dL`. The row carries **both** the LOINC code and the UCUM unit,
so it is the self-contained LOINC/UCUM reference the slice needs — no second table.

Both changesets are idempotent (`preConditions onFail="MARK_RAN"`) and ship to every
environment (no `context`), each with an explicit `<rollback>`.

**Verifiable output (S0.6 exit):** `VendorCodeNormalizationIntegrationTest` proves, via raw
JDBC against the migrated schema, that (a) the seed loaded — `ANALYZER`/`GLU` resolves to
LOINC `2345-7` + UCUM `mg/dL` on `vendor_code_mapping`; and (b) resolving the vendor code and
writing `(loinc, ucum)` onto a `clinlims.result` persists a row where the analyzer-native
`raw_code`/`raw_unit` coexist with the normalized `loinc`/`ucum_value`/`status` — the
normalization tracer-bullet end-to-end. The assertion targets only the new
`vendor_code_mapping`; see the unit-of-measure alternative below.

## Alternatives considered

- **Seed `test_terminology_mapping` (043) instead of a new table.** Rejected: it is keyed
  per `test_id` with an FK to `clinlims.test`, so seeding requires a matching glucose *test*
  row (absent in a bare migrated schema → a no-op seed and a non-deterministic test). It
  also models a *test → code* axis; normalization keys on the **analyzer-native observation
  code**, a distinct axis. Per-test LOINC backfill stays OGC-939's job.
- **Add the JPA entity/DAO/normalization service now.** Deferred to **Stage 1** (LIS-14):
  S0.6's exit gate is the *seed loads + maps onto a result row*, provable at the data layer.
  Resolving-on-ingest (entity + service wiring) is the HL7-edge slice's work; pulling it
  forward would widen S0.6 past its tracer bullet.
- **Seed via `db/dbInit` / a dictionary load rather than a Liquibase changeset.** Rejected:
  the integration-test harness applies the Liquibase changelog, not `dbInit`, so only a
  changeset is guaranteed present in both test and production schemas.
- **An FK from `vendor_code_mapping.ucum_code`/`loinc` to `unit_of_measure`/terminology.**
  Rejected for S0.6: the canonical rows are not guaranteed present in every environment, and
  a soft (by-value) link keeps the seed self-contained and the migration order-independent —
  consistent with how `047` treats `loinc` as a snapshot, not a second authority.
- **Also seed the canonical `clinlims.unit_of_measure` UCUM column** (an `mg/dL` row with
  `ucum_code = 'mg/dL'`). Tried, then dropped: the OpenELIS integration-test harness
  **resets/reloads the canonical reference tables** (`unit_of_measure` included) between
  tests, so a row a new changeset seeds there is **not observable** to an integration test
  (it failed in the full suite though it passed in isolation) — whereas the new
  `vendor_code_mapping`, which the harness does not reset, is. Since the mapping row already
  carries the UCUM unit, seeding `unit_of_measure` added an untestable artifact for no gain;
  tying the UCUM unit into `unit_of_measure.ucum_code` is deferred to later
  normalization-service work that can handle the harness reset properly.

## Consequences

- **Positive:** the analyzer-code → `(LOINC, UCUM)` lookup is first-class and queryable, the
  exact shape Stage-1 normalization consumes; the change is small, additive, idempotent, and
  reversible; the seed lives in one self-contained table (no dependency on harness-reset
  reference tables); the end-to-end proof onto a `result` row is a real data-layer test, not
  a mock.
- **Costs / deferred (flagged for review):**
  - **No entity/DAO/service** — `vendor_code_mapping` is reachable only via SQL until the
    Stage-1 normalization service maps it (LIS-14). The seed test reads it via JDBC.
  - **One mapping, one analyzer family** (`ANALYZER`/`GLU`). A real per-analyzer terminology
    set (RAC-050, labXpert, DiaSys, …) is seeded per-driver in Stages 1–3; `source` is sized
    now to carry the analyzer family then.
  - **`loinc`/`ucum_code` are free text**, not FK-validated against a LOINC/UCUM authority
    or against `unit_of_measure.ucum_code`; tighten when those references are wired in (and
    when the harness-reset constraint above is handled).
  - The `vendor_code_mapping` seed rollback deletes the seeded row by `(source, vendor_code)`
    — a best-effort data rollback (acceptable for a reference seed, unlike the schema
    `dropTable` rollback of the table changeset).

## 2026-07-05 update — Test.loinc after Test Catalog terminology

The DIGI-UW Test Catalog v2 sync introduced `clinlims.test_terminology_mapping` as the editor-owned
terminology model for tests. `TEST.LOINC` remains the legacy resolver column used by existing core
paths (`getTestsByLoincCode`, analyzer bridge sync, order dispatch), but it is now mirrored from the
active `LOINC` / `SAME_AS` terminology mapping when the editor saves. Direct SQL writes to
`TEST.LOINC` can therefore diverge from the terminology table.

Fork-side changeset `051-backfill-test-loinc-terminology.xml` re-runs the LOINC backfill after the
SD1 seed changesets so seeded tests have matching terminology rows. Until a later slice removes the
legacy dependency, treat `TEST.LOINC` as a compatibility mirror, not an independent source of truth.
