# ADR-0018 — Analyzer specimen identity: per-specimen bundle groups, deterministic accession minting, Patient emission

- **Status:** Accepted (LIS-121/LIS-122/LIS-123 — the accession→identity P0 cluster from the LIS-120 review)
- **Date:** 2026-07-04
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `edge/drivers` (result parsers, FHIR northbound bundle) + `core/openelis` (staging dedup); amends the bundle-structure note of ADR-0015 §Decision 5
- **Relates to:** ADR-0015 (edge transport substrate — FHIR northbound is the production wire this enriches); core ADR-0003 (result ingest contract — Observation is the serialization of the semantic contract); ADR-0011/0013 (edge parse/normalize + ingest-contract correspondence); LIS-97 (patient-identity completeness follow-up this unblocks); LIS-148 (review leads worklist)

## Context

OpenELIS identifies analyzer results by `accessionNumber` **alone** — no patient
dimension — at both the staging-dedup layer (`AnalyzerResultsServiceImpl.insertAnalyzerResults`,
keyed `(analyzerId, accessionNumber, testName)`) and the accept layer
(`AnalyzerResultsController.groupAnalyzerResults` → `AnalyzerResultsAcceptServiceImpl` →
`getSampleByAccessionNumber` → `list.get(0)`). This upstream-inherited design is safe only
under the invariant *accession == unique per-specimen number*. The bridge broke that
invariant three ways (all verified at core `09702567` / edge `b89b426`):

1. **Multi-order collapse (LIS-122):** both result parsers kept a single accession variable
   and one flat result list per transmission, so a multi-OBR ORU or multi-O ASTM session
   attributed every result to whichever specimen was parsed *last*.
2. **MRN as accession (LIS-121):** with no OBR order number, `HL7ResultParser` fell back to
   the patient MRN (PID-3.1 → PID-2.1) — so two runs of the same patient share an
   accession, and the second run's unchanged values were *silently dropped* by staging
   dedup, or staged as a bogus "correction" of the earlier run.
3. **Shared sentinels (LIS-123):** all remaining id-less messages collapsed onto the
   constants `HL7-UNKNOWN`/`ASTM-UNKNOWN`, so *distinct patients* shared one accession; at
   accept, later walk-up results attach to the first patient's Unknown sample →
   wrong-patient commit.

The bundle carried **no Patient resource** (`FhirBundleBuilder`), so core had no identity
to disambiguate on even in principle.

Three candidate strategies were weighed against the ADRs:

- **Core-side identity keying** (patient+specimen key in staging/accept): rejected as
  primary — `analyzer_results` has **no patient column at all**, so this needs schema +
  import + accept + UI changes across upstream-inherited code: the highest blast radius
  and a semantic fork of core's identity model (ADR-0001 mirror concern).
- **Quarantine placeholder accessions at accept**: rejected — LIS-121's silent drop
  happens at staging *insert*, before any accept-time quarantine could see it, and
  quarantining MRN-tagged walk-up results would break the SD1 flow.
- **Bridge-side identity restoration**: chosen, layered with a core-side fail-visible
  dedup fix (below). Key enabling fact: core's FHIR import already resolves each
  Observation's accession through its **own** Specimen reference
  (`AnalyzerFhirImportController`), so a multi-Specimen bundle routes per-specimen with no
  core change; the `Observation.subject.identifier` fallback fires only when the Specimen
  reference is absent and only reads an *inline* identifier.

## Decision

**1. The bridge restores the accession-uniqueness invariant at the source**
(`openelis-analyzer-bridge#16`):

- `ParsedResults` carries one **`SpecimenGroup` per OBR group / ASTM O-record** (accession,
  results, result type, patient identity). The bundle emits one Specimen + one
  DiagnosticReport per group; each Observation references its own group's Specimen.
  Blank-sample typing, QC-rule evaluation, and OBR-14/20 lot/level are per-group
  (previously last-OBR-wins).
- **No fabricated shared accessions.** An id-less group gets a minted deterministic
  accession `<MRN | protocol tag>-<10-hex SHA-256>` hashed over analyzer identity +
  message timestamp/control id + the group's raw records + group index, capped at 25
  chars (the `accession_number` column width, liquibase `3.5.x.x/031`). Determinism means
  a re-transmission re-derives the *same* accession (idempotent re-import), while distinct
  runs/patients never collide. The MRN prefix keeps the walk-up queue readable.
- **Patient identity rides the bundle as identity, never as accession**: a FHIR `Patient`
  resource (deduped per bundle) referenced from `Specimen.subject` /
  `Observation.subject`, reference-only — an inline identifier would be misread by core's
  subject-identifier accession fallback.

**2. Core staging dedup becomes fail-visible** (core PR, `AnalyzerResultsServiceImpl`):
skip **only a true re-import** (existing row with equal `completeDate` AND equal value);
anything else on an existing key stages as a read-only, duplicate-back-linked correction
the tech can see. The old date-OR-value skip silently lost real results (a re-run with an
unchanged value; a corrected value re-sent under the same completion timestamp) — and the
key carries no patient dimension, so the lost row could belong to another patient.

**3. The northbound contract note of ADR-0015 §Decision 5 is amended**: the production
bundle is Device + **Patient\*** + per-specimen (Specimen + DiagnosticReport +
Observation[]) — additive, FHIR-native, and unchanged for single-specimen messages with
wire accessions. Core ADR-0003's semantic contract is untouched (Observation fields are
unchanged).

## Consequences

- **Positive:** multi-order sessions route per-specimen with zero core routing changes;
  distinct patients/runs can no longer collapse onto a shared accession; nothing is
  silently dropped at staging; the wire MRN survives as structured identity (unblocks
  LIS-97's staging/accept surfacing); re-import idempotency is preserved by minting
  determinism + the (date AND value) skip.
- **Costs / residual risks (flagged, not silent):**
  - A timestamp-less analyzer emitting byte-identical records on different runs is
    indistinguishable from a re-transmission *in principle*; such runs mint the same
    accession and the second is treated as a re-import. Mitigation is analyzer-side
    configuration (timestamps/sequence ids).
  - Operator-caused accession reuse across patients (same real specimen id typed for two
    patients) remains possible until staging carries a patient dimension — deferred to
    the LIS-97 follow-up, now unblocked by the Patient resource.
  - Core ignores the Patient resource today (staged rows still carry no identity); the
    accept queue shows minted accessions (MRN-prefixed) instead of bare MRNs — a
    deliberate trade: readable, unique, and honest about specimen ≠ patient.
  - **Closed 2026-07-16 by LIS-157:** `edge/sim` now exposes one `SpecimenGroup`
    per HL7 OBR / ASTM O record, applies blank/QC/calibration typing per group, and
    mirrors the bridge's deterministic 25-character accession minting. The legacy
    `OruReport` scalar view remains first-group compatible while observations stay
    flattened in wire order.
