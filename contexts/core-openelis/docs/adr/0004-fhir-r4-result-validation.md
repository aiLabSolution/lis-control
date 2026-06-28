# ADR-0004 (core/openelis) — FHIR R4 result validation (`$validate`) + HAPI/logging stack realignment

- **Status:** Accepted — component PR [aiLabSolution/OpenELIS-Global-2#7](https://github.com/aiLabSolution/OpenELIS-Global-2/pull/7) merged (core `5f2d4068`); recorded here with the umbrella pin bump (LIS-41).
- **Date:** 2026-06-28
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `core/openelis` component (FHIR data-exchange + build dependencies)
- **Relates to:** ADR-0001 (umbrella topology — component decisions live here); LIS-40 (Stage 4 PRD); **LIS-41 (S4.1)**; ADR-0001/0002 (result shape + LOINC/UCUM, the data this serialises); plan §3 Stage 4 exit gate ("a result returns as a valid R4 DiagnosticReport + Observation (passes `$validate`)"); follow-ups LIS-80/81/82.

## Context

S4.1 (LIS-41) requires the exit-gate proof that a **finalized result** returns as a FHIR R4
**DiagnosticReport + Observation** that pass **`$validate`** (HAPI instance validation),
asserted by an automated test. OpenELIS already builds these resources —
`FhirTransformServiceImpl.transformResultToDiagnosticReport(Analysis)` /
`transformResultToObservation(Result)` — and maps a `Finalized` analysis to FHIR
`status = final`. What was missing: an actual **instance validator** and a test gating on it.

Facts discovered (all verified against the source / dependency tree):

- **No FHIR instance validator was on the classpath.** HAPI FHIR 7.0.2 shipped the parser and
  the R4 model, but not `FhirInstanceValidator` / the base-spec `StructureDefinition` resources.
- **A dependency skew blocked the 7.0.2 validator outright.** The repo pins
  `hapi-fhir 7.0.2` (which natively pairs with `org.hl7.fhir.core 6.1.2.2`) but overrides
  `org.hl7.fhir.{r4,utilities}` to **6.9.4** (upstream dependency update #3269). The 7.0.2
  validator wrapper references `org.hl7.fhir.r5.utils.FHIRPathEngine`, which core 6.9.4
  **relocated** to `org.hl7.fhir.r5.fhirpath` → `NoClassDefFoundError`. No version combination
  reconciles a 7.0.2-line validator with a 6.9.4 core. The HAPI **schema (XSD)** validator is
  also unusable (HAPI 7.0.2 ships no R4 XSDs).
- The base R4 conformance resources (`profiles-resources.xml`, ~19 MB) live in
  `hapi-fhir-validation-resources-r4`, **not** in `org.hl7.fhir.r4`; without it the validator
  cannot recognise `Observation`.
- HAPI 8.x calls the **slf4j 2.x** API (`Logger.atDebug()`); the repo resolved `slf4j-api 1.7.25`
  via the `log4j-slf4j-impl` (slf4j-1.7) binding under log4j2 2.17.1.

## Decision

**1. Realign the FHIR/logging stack** so the genuine HAPI instance validator runs, choosing the
HAPI release that **natively pairs with core 6.9.4.x** (8.10.0 → `org.hl7.fhir.core 6.9.4.1`):

| Dependency | From | To | Scope |
|---|---|---|---|
| `hapi-fhir-{base,structures-r4,client,server}` | 7.0.2 | **8.10.0** | compile |
| `org.hl7.fhir.{r4,utilities}` | 6.9.4 | **6.9.4.1** | compile |
| `slf4j-api` | 1.7.25 | **2.0.16** | compile |
| log4j2 slf4j binding | `log4j-slf4j-impl` | **`log4j-slf4j2-impl`** | runtime |
| `log4j2` (core/api/1.2-api/jcl) | 2.17.1 | **2.24.3** | compile |
| `log4j-liquibase` | 2.17.1 | **removed** | — |
| `hapi-fhir-validation`, `-validation-resources-r4`, `-caching-caffeine` | — | **8.10.0** | **test** |

The validation jars (and their `org.hl7.fhir.r5/r4b/dstu*` transitive closure) are **test scope** —
they do not ship in the WAR. **One production source file changed:** `LogEvent` (the central
logging wrapper behind all ~500 `LogEvent.*` call sites) used the legacy `org.apache.log4j.Category`
shim, whose `trace()` was dropped after log4j2 2.17.x → switched to `org.apache.log4j.Logger`
(same logger name/level resolution; retains `trace()`).

**2. The conformance gate** — `FhirResultDiagnosticReportValidationTest` (pure JUnit; no
Spring/Testcontainers): drives the **production** transform for a finalized numeric result
(Hemoglobin 12.5 g/dL, LOINC 718-7) via mocked collaborators, asserts `status = final`, and
validates both resources with `FhirInstanceValidator` over base R4 profiles +
`InMemory`/`CommonCodeSystems` terminology. The test fails on any `ERROR`/`FATAL`; offline
terminology `WARNING`s (LOINC CodeSystem not resolvable without a server) are tolerated, which is
out of scope for structural conformance.

**Verifiable output (S4.1 exit):** the test is green; OpenELIS compiles unchanged against HAPI
8.10.0 (`LogEvent` excepted); the component's full backend CI suite (incl. the existing FHIR
facade/provider integration tests) passes — the regression check on the 7→8 bump.

## Alternatives considered

- **Structural-only validation** (HAPI strict round-trip parse + hand-rolled cardinality/coding
  assertions), staying on hapi-fhir 7.0.2. Rejected: it under-delivers the literal `$validate`
  gate (no FHIRPath invariants / profile cardinality) and is partly tautological.
- **`org.hl7.fhir` core `ValidationEngine`** loading the `hl7.fhir.r4.core` IG package. Rejected:
  needs the package fetched from the network/cache — fragile in CI and on offline/on-prem builds.
- **Revert core to 6.1.2.2** (hapi-fhir 7.0.2's native pairing). Rejected: undoes an upstream
  security/maintenance update (#3269) and diverges from upstream OpenELIS.
- **Keep hapi-fhir 7.0.2 + add only the validator.** Impossible: the 7.0.2 wrapper is
  binary-incompatible with core 6.9.4 (the `FHIRPathEngine` relocation).

## Consequences

- **Positive:** genuine FHIR R4 `$validate` is available (a real validator that rejects malformed
  resources — proven adversarially); the finalized-result transform is gated as conformant; the
  fix is one production file; newer HAPI 8.10.0 + log4j2 2.24.3 also carry post-2.17.1 security
  fixes; the full backend suite is green on the new stack.
- **Costs / deferred (flagged for review):**
  - Validation is **test scope** only — no runtime `$validate` endpoint or validate-before-report,
    and no profile (US Core) conformance yet. Deferred: **LIS-81**.
  - Coverage is the finalized **numeric** path; dictionary/text/multiselect/Viral-Load value types,
    non-final statuses, and patient-bearing resources are untested against `$validate`. Deferred:
    **LIS-80**.
  - The HAPI 7→8 + log4j2 2.17→2.24 + slf4j 1.7→2.0 bump **diverges further from upstream**
    OpenELIS (ADR-0003 standalone line); contained (one source file) but a larger future-merge delta.
  - `log4j-liquibase` removal leaves Liquibase 4.8 on its built-in JUL log service (it was already
    dead under 4.x); a JUL→log4j2 bridge is not wired. Noted in **LIS-82** (with pre-existing
    `pom.xml` build-stability defects).
