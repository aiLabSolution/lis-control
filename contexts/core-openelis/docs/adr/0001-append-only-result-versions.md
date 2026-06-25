# ADR-0001 (core/openelis) — Result table shape + append-only result versions

- **Status:** Proposed (pending review — LIS-7)
- **Date:** 2026-06-25
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `core/openelis` component (clinical core data model)
- **Relates to:** ADR-0001 (umbrella topology — component-scoped decisions live here); LIS-2 (Stage 0 PRD); LIS-7 (S0.5); LIS-6 / ADR-less S0.4 (append-only audit history, the pattern this mirrors); plan §0 + research §5.1; forward-looking to Stage 4 (LIS-45/48 — append-only result versions + explicit reconciliation)

## Context

S0.5 (LIS-7) requires the result table to carry **raw + normalized observation data
side by side** and to establish **append-only result versions** — the data-model
foundation every later stage validates deltas against. Two needs:

1. **Raw vs normalized.** Ingest normalizes a vendor/analyzer observation to LOINC/UCUM
   (plan §0, research §5.1). Both the *raw* analyzer code/unit and the *normalized*
   LOINC/UCUM form must persist on the result so a finalized value is traceable back to
   exactly what the instrument reported.
2. **Append-only versions.** Stage 4's site↔central sync (LIS-45/48) reconciles
   concurrent edits with **append-only result versions, never last-writer-wins**. S0.5
   lays that spine now so it is a known base, not a Stage-4 retrofit.

Facts discovered in the core that shape the decision (all verified against the source):

- `clinlims.result` is a legacy `numeric(10)` table. `value varchar(200)` holds the
  result; `result_type varchar(1)` is a **value-type discriminator** ("Dictionary, titer,
  number, date"), *not* a lifecycle status — so a normalization `status` column does not
  collide. None of `raw_code/raw_unit/loinc/ucum_value/status` exist on `result` today.
- The live result row is **mutated in place** on every edit
  (`BaseObjectServiceImpl.update()` → Hibernate `UPDATE clinlims.result`). A whole-table
  immutability trigger like the S0.4 history guard therefore *cannot* sit on `result`
  itself — it would break every normal result save.
- The S0.4 audit spine, `clinlims.history`, is **append-only at the DB layer** (a
  `BEFORE UPDATE OR DELETE` trigger, changeset `046`) and references the entities it
  audits via a **soft `reference_id`/`reference_table`** (plain `numeric`, **no foreign
  key**) — deliberately, so the audit trail survives entity deletion and the
  `TRUNCATE … CASCADE` resets used by the integration-test harness and the
  training-installation `DatabaseClean` endpoints.
- LOINC already lives in three coarse places (`TEST.LOINC`, `PANEL.loinc`,
  `DICTIONARY.loinc_code`); UCUM lives in `unit_of_measure.ucum_code` (changeset `042`);
  the canonical multi-source terminology table is `test_terminology_mapping` (`043`).

## Decision

Ship S0.5 as a single Liquibase changelog, `3.5.x.x/047-result-shape.xml` (wired after
`046` in `base.xml`), plus the matching `Result` entity mapping and one integration test.

**1. Five additive, nullable columns on `clinlims.result`** — raw beside normalized:

| Column | Type | Meaning |
|---|---|---|
| `raw_code` | `VARCHAR(80)` | analyzer-native test/result code as reported |
| `raw_unit` | `VARCHAR(40)` | unit string exactly as the analyzer reported it |
| `loinc` | `VARCHAR(80)` | normalized LOINC for the observation (a **snapshot**, not a new authority) |
| `ucum_value` | `VARCHAR(40)` | normalized UCUM unit |
| `status` | `VARCHAR(20)` | normalization/lifecycle status (e.g. RAW / NORMALIZED / RECONCILED) |

Widths align to the canonical columns so raw and normalized are comparable:
`raw_code`/`loinc` ← `test_terminology_mapping.code` (80); `raw_unit`/`ucum_value` ←
`unit_of_measure.ucum_code` (40). All nullable + `dynamic-update="true"` on the entity,
so existing result inserts/updates are untouched. `loinc` is documented as a captured
snapshot of `TEST.LOINC` (authority unchanged) to avoid a second source of truth.

**2. An append-only `clinlims.result_version` sidecar**, auto-populated and DB-enforced:

- Columns: `id` (PK from `result_version_seq`), `result_id` (**soft reference**, NOT NULL,
  indexed via the unique constraint — **no FK**, mirroring `history`), `version_number`,
  a snapshot of `value` + the five normalization columns, and `changed_at`. Unique on
  `(result_id, version_number)`.
- **Auto-versioning:** an `AFTER INSERT OR UPDATE` trigger on `result` appends the next
  version whenever a value/normalization column actually changes (an `IS DISTINCT FROM`
  guard means incidental edits — `sort_order`, `is_reportable` — spawn no version). No
  write path — app, analyzer import, manual SQL — can escape versioning.
- **Immutability:** a `BEFORE UPDATE OR DELETE` trigger on `result_version` rejects any
  rewrite/removal of an existing version (`RAISE EXCEPTION … 'append-only'`), cloned from
  the proven `046` guard. Last-writer-wins is therefore structurally impossible on the
  version spine. As in `046`, **no `TRUNCATE` guard** — fixture/training resets keep working.

The append-only guard is on the **sidecar only**, never on `result` (which must stay
mutable). `result_id` is a soft reference, not an FK, for the same reason `history` uses
one: the version trail is an audit artifact that should outlive its result and survive
the suites that hard-delete results (`DELETE FROM result WHERE analysis_id IN …`) — an FK
would either block that delete (RESTRICT) or cascade a row-level delete that the
append-only guard rejects (CASCADE).

**Verifiable output (S0.5 exit):** `ResultVersionAppendOnlyIntegrationTest` proves, via
raw JDBC against the migrated schema, that (a) one result row carries all five
normalization columns beside `value`, (b) an update **appends** a new version leaving the
prior version byte-for-byte unchanged, and (c) a direct `UPDATE`/`DELETE` on a version row
is rejected at the DB layer with an `append-only` message.

## Alternatives considered

- **Immutability trigger on `result` itself** (force corrections to be new rows). Rejected:
  the result row is mutated in place on every edit, so a guard there breaks every save.
- **Reuse the generic `history` audit spine** (no new table). Rejected for the *version
  store*: `history` keeps opaque serialized before/after diffs, not typed,
  reconstructable raw+normalized versions — a weak base for Stage-4 reconciliation.
  (`history` remains the authoritative **who/when** audit; `result_version` is the typed
  value spine.)
- **An in-row "previous value" column on `result`** (à la `eqa_result.previous_*`).
  Rejected: keeps only one prior value — last-writer-wins on everything older, the exact
  anti-pattern Stage-4 must avoid.
- **`result_version.result_id` as a hard FK to `result`.** Rejected: an FK (RESTRICT or
  CASCADE) breaks the suites that hard-delete results once those results have versions;
  the soft reference (matching `history`) avoids this with no loss for an audit artifact.

## Consequences

- **Positive:** raw↔normalized is first-class and queryable; the append-only version spine
  is DB-enforced (un-bypassable, consistent with S0.4) and ready for Stage-4 reconciliation;
  zero change to hot result-save Java; consistent with the established `history` pattern.
- **Costs / deferred (flagged for review):**
  - The version table has no `changed_by`; the per-change **actor** currently lives in the
    append-only `history` audit. A user-aware version-write path (populating `changed_by`
    from session context) is deferred to **Stage 4**.
  - `result.status` is free-text `VARCHAR(20)` with documented values for minimality;
    tighten to a CHECK/lookup before Stage-4 reconciliation depends on it.
  - `version_number` is assigned by an in-trigger `MAX()+1`; fine for single-writer paths,
    the unique constraint catches a true race. Concurrency-harden in Stage 4 if needed.
  - After a result is hard-deleted/truncated, its version rows are retained as orphaned
    soft references (intended for an append-only trail; consistent with `history`).
  - `ucum_value` is not yet sourced from `unit_of_measure.ucum_code` via the entity layer
    (that property is unmapped); for S0.5 it is written by the normalizer/analyzer.
