# ADR-0003 (core/openelis) — Result ingest contract (edge → append-only Result store)

- **Status:** Proposed (pending review — LIS-15)
- **Date:** 2026-06-28
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `core/openelis` component (clinical core — result persistence seam)
- **Relates to:** ADR-0001 (umbrella topology — component-scoped decisions live here); core ADR-0001 (result shape + append-only `result_version`, S0.5 / LIS-7 — the store this writes to); core ADR-0002 (LOINC/UCUM vendor-code seed, S0.6 / LIS-8); umbrella ADR-0006 (edge ORU parse + LOINC/UCUM normalization, S1.2 / LIS-14 — produces the in-memory normalized row this persists); LIS-11 (Stage 1 PRD); plan §1 ("Normalization service … persist raw + normalized"); forward to LIS-17 / S1.5 (milestone E2E wiring edge replay → ingest → Result + ACK)

## Context

S1.3 (LIS-15) is the **persistence** step of Stage 1's "first result through the pipe".
The edge normalizer (S1.2 / LIS-14, ADR-0006) parses an `ORU^R01` to an in-memory
LOINC/UCUM intermediate row but deliberately stops short of persistence — ADR-0006
defers "writes it to the core append-only Result store" to **here**. S0.5 (core
ADR-0001) already laid the store down: `clinlims.result` with raw + normalized columns
and the auto-versioning, immutable `clinlims.result_version` spine. What is missing is
the **seam** the edge targets to land a normalized observation in that store.

Facts that shape the decision (verified against the core source):

- **`clinlims.result` already carries** `value` + `raw_code` / `raw_unit` / `loinc` /
  `ucum_value` / `status` (S0.5, changeset `047`); the `result_append_version` trigger
  appends a `result_version` snapshot on every value/normalization write, and that spine
  is immutable (append-only guard). So persistence needs **no schema change** — it reuses
  the store.
- **`ResultService extends BaseObjectService<Result, String>`** exposes
  `insert(Result) → id`, and `Result`'s `analysis` / `analyte` / `testResult` are
  **nullable** many-to-ones (hbm), so a normalized observation persists as a `result` row
  without an order/analysis graph (order-linkage is later — S4.2).
- **`AuditableBaseObjectServiceImpl.insert` records a `clinlims.history` audit row**
  keyed by `baseObject.getSysUserId()` (S0.4 spine), so an ingest must attribute an actor.
- core ADR-0002 deferred the analyzer-code → `(LOINC, UCUM)` entity/service, and ADR-0006
  placed normalization **at the edge**. So core's job here is **persistence of an
  already-normalized row**, not re-normalization.

## Decision

Add a small ingest contract under `org.openelisglobal.result.ingest`, test-first, with
**no schema change**:

1. **`NormalizedObservation`** — an immutable, transport-neutral value object: `value`
   plus the analyzer-native `rawCode` / `rawUnit` **beside** the normalized `loinc` /
   `ucumValue` and a normalization `status`. Mirrors the edge normalizer's intermediate
   row (ADR-0006), so the contract is the language-neutral correspondence between a Python
   edge `NormalizedObservation` and core. The edge — a separate process — targets this
   stable shape, not the heavyweight `Result` entity (an anti-corruption seam).
2. **`ResultIngestService.ingest(NormalizedObservation) → result id`** — maps the
   observation onto a `Result` and persists it through `ResultService.insert`, so the
   `AFTER INSERT` trigger appends `result_version` #1: the observation lands in the
   append-only, no-last-writer-wins store. Insert-only (one observation → one new `result`
   row); correcting/re-versioning an existing result, and order-linkage, are later slices.
3. **`ResultIngestServiceImpl`** attributes the write to the **system user** (`"1"`): the
   edge is a service, not a named OpenELIS user. A configurable ingest service-account is
   deferred (mirrors S0.5's deferred user-aware version-write path).

**Verifiable output (S1.3 exit):** `ResultIngestContractIntegrationTest` (Testcontainers,
full migrated schema) proves **via the contract** (not raw SQL) that — (a) `ingest` of a
fully-normalized observation persists a `clinlims.result` row carrying `raw_code` /
`raw_unit` beside `loinc` / `ucum_value` / `status` + `value`; (b) the contract write
auto-appended `result_version` #1 and that version is **immutable** (the append-only guard
rejects a direct mutation) — the observation is in the append-only store; and (c) a
partially-normalized observation (unmapped code, no LOINC, status `PARTIAL`) still persists
(tolerant ingest, mirroring the edge's status vocabulary).

## Alternatives considered

- **Persist via raw JDBC / a DAO-only path.** Rejected: the slice's point is the *contract*
  the edge calls; routing through `ResultService` proves the append-only spine fires on the
  **real application write path** (a stronger guarantee than S0.5's raw-JDBC proof) and
  reuses the S0.4 auditing for free.
- **Re-normalize in core (consume `vendor_code_mapping` live at ingest).** Rejected:
  normalization is the edge's job (ADR-0006), and the edge cannot assume a live core DB at
  parse time (S1.0 substrate undecided). The contract accepts an already-normalized row;
  sourcing core's mapping is later normalization-service work (ADR-0002 / 0006).
- **Require an Analysis / order on ingest.** Rejected for S1.3: order-matching (EMR
  `ServiceRequest` → worklist) is Stage 4 (S4.2). The store persists the normalized
  observation now; linkage is additive later (flagged below).
- **Put the ingest type in the `edge/sim` repo.** Rejected: the persistence seam is
  core-side by definition; the edge holds its own `NormalizedObservation` analog and maps to
  this contract over whatever transport S1.0 picks.

## Consequences

- **Positive:** the edge has a stable, typed core seam to land normalized results in the
  append-only store; no schema change (reuses S0.5 / S0.6); append-only versioning is proven
  on the real service write path; tolerant of partial normalization; the milestone E2E (S1.5)
  now has its persistence half.
- **Costs / deferred (flagged for review):**
  - **Insert-only, no order-linkage** — one observation → one new `result` row with null
    `analysis` / `analyte` / `testResult`; matching to an OpenELIS order/analysis is Stage 4
    (S4.2). Until then, ingested results are unlinked rows.
  - **System-user attribution** (`"1"`) — a configurable ingest service-account is deferred
    (as S0.5 deferred the user-aware version-write `changed_by`).
  - **`status` is free text** carried from the edge (`NORMALIZED` / `PARTIAL` / `UNMAPPED`)
    onto `result.status` (which S0.5 also documents as `RAW` / `NORMALIZED` / `RECONCILED`);
    a documented enum/lookup is deferred (S0.5 already flagged tightening `result.status`).
  - **No re-ingest idempotency / dedupe** — re-ingesting the same observation inserts another
    `result` row; idempotency keys are later work once the edge carries stable
    message/observation ids.
