# ADR-0005 (core/openelis) — FHIR R4 Specimen + Device resolve and link from the DiagnosticReport

- **Status:** Accepted — component PR [aiLabSolution/OpenELIS-Global-2#8](https://github.com/aiLabSolution/OpenELIS-Global-2/pull/8) merged (core `a81dc516`); recorded here with the umbrella pin bump (LIS-43).
- **Date:** 2026-06-28
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `core/openelis` component (FHIR data-exchange transforms)
- **Relates to:** ADR-0001 (umbrella topology — component decisions live here); **ADR-0004 (S4.1 — the `$validate` gate + HAPI 8.10.0 stack this builds on)**; LIS-40 (Stage 4 PRD); **LIS-43 (S4.3)**; plan §3 Stage 4 exit gate ("a result returns as a valid R4 DiagnosticReport + Observation (passes `$validate`)"); broaden-coverage follow-up LIS-80.

## Context

S4.3 (LIS-43) extends the S4.1 conformance gate (ADR-0004) from the **DiagnosticReport + Observation**
to the two resources a report **references** for provenance: the **Specimen** (what was measured) and
the **Device** (the analyzer that produced the result). The exit-gate proof: from a finalized result's
`DiagnosticReport`, the referenced Specimen and Device must (a) build as FHIR R4 resources that pass
**`$validate`** (HAPI instance validation), and (b) **resolve and link** from the report.

OpenELIS already builds all four resources and wires the links during bundle assembly
(`transformPersistObjectsUnderSamples`). Facts verified against the source:

- **`DiagnosticReport.specimen`** is set directly by `transformResultToDiagnosticReport(Analysis)` to
  `Specimen/{sampleItem.fhirUuid}`; `transformToSpecimen(SampleItem)` sets the Specimen's id to the same
  UUID → the reference **resolves**.
- **`DiagnosticReport.result`** is set to `Observation/{result.fhirUuid}`; `transformResultToObservation`
  sets the Observation id to the same UUID → resolves.
- **`Observation.device`** is set to `Device/{analyzer.fhirUuid}` during bundle assembly (in the private
  `setDeviceReferenceAndInclude`), and `transformAnalyzerToDevice(Analyzer)` sets the Device id to the
  same UUID → resolves. There is no `DiagnosticReport.device` element in R4, so the Device links from the
  report **transitively** via `DiagnosticReport.result → Observation.device`.

What was missing: an automated gate proving these resources are `$validate`-clean **and** that the
reference graph resolves. Two transform seams were also not reachable for a pure-unit test — the Device
transform was `private`, and the Observation→Device linking was inlined inside the bundle-only
`setDeviceReferenceAndInclude`.

## Decision

**1. The conformance + linkage gate** — `FhirDiagnosticReportSpecimenDeviceLinkageValidationTest` (pure
JUnit; no Spring/Testcontainers, mirroring the S4.1 gate). For a finalized numeric result it drives the
**production** transforms to build the DiagnosticReport, Specimen, Observation, and Device, then asserts:

- Specimen and Device are **`$validate`-clean** (`FhirInstanceValidator` over base R4 profiles +
  `InMemory`/`CommonCodeSystems` terminology; fails on `ERROR`/`FATAL`, tolerates offline terminology
  `WARNING`s — same policy as ADR-0004).
- `DiagnosticReport.specimen` resolves to the built Specimen's id (direct link).
- `DiagnosticReport.result` resolves to the built Observation's id, whose `Observation.device` resolves
  to the built Device's id (transitive link), and `Observation.specimen` agrees with the report.

A **negative-control** run (a deliberately wrong id in the link seam) was used to confirm the gate is
non-vacuous — it fails on the device-resolution assertion.

**2. Two minimal, behavior-preserving production seams** so the linkage is unit-testable:

- Extract `linkObservationToDevice(Observation, Analyzer)` from `setDeviceReferenceAndInclude` (the
  `Observation.device` wiring is byte-for-byte identical; the bundle path calls the extracted method in
  the same position and still includes the Device resource).
- Relax `transformAnalyzerToDevice(Analyzer)` from `private` to **package-visible** so the gate can build
  and validate the Device for a result's analyzer.

No public interface (`FhirTransformService`) method was added; the seams are package-private, reached only
by the same-package test. No runtime behavior changes.

**Verifiable output (S4.3 exit):** the test is green; the change is two source-file seams + one new test;
the component's full backend CI suite passes (the regression check that the extraction didn't alter bundle
assembly).

## Alternatives considered

- **Drive the full bundle (`transformPersistObjectsUnderSamples`) and assert on the emitted `Bundle`.**
  Rejected for this gate: that path is `@Async`, DB/Testcontainers-bound, and stitches dozens of
  collaborators — heavy and slow for a structural conformance proof. The transform-level test asserts the
  same reference semantics (id-part equality on the production `createReferenceFor` output) without a DB.
- **Expose the Device transform on the `FhirTransformService` interface (public).** Deferred: no caller
  outside the bundle path needs it yet; package-visibility is the minimal surface to make the gate
  expressible. Promote to the interface when a non-test caller appears.
- **Add `Observation.device` inside `transformResultToObservation` itself** (so a standalone Observation
  carries its Device). Rejected here: it would add an `analyzerService.get(analyzerId)` DB lookup to a hot
  per-result path that the bundle deliberately serves from an analyzer cache — a perf regression for no
  gate value. The bundle path remains the single place that resolves+caches the analyzer.

## Consequences

- **Positive:** the Specimen + Device a report depends on are gated as `$validate`-clean and proven to
  resolve/link from the DiagnosticReport (direct for Specimen, transitive via the result Observation for
  Device); the linking logic is now an extracted, named, unit-tested seam; no runtime behavior change and
  no new production dependencies (builds on the ADR-0004 stack).
- **Costs / deferred (flagged for review):**
  - Coverage is the finalized **numeric** path with a single analyzer; non-final statuses, other value
    types, patient-bearing resources, and multi-analyzer/no-analyzer results are untested against
    `$validate`. Folds into the broaden-coverage follow-up **LIS-80**.
  - The linkage proof is **id-part equality** on detached resources (not a Bundle/server resolution); this
    matches FHIR R4 relative-reference semantics and is the appropriate scope for a unit gate. An
    end-to-end Bundle-resolution assertion would ride on the runtime-`$validate` work (LIS-81).
