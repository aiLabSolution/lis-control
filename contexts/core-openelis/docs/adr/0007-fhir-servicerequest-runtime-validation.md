# ADR-0007 (core/openelis) — Runtime FHIR R4 `$validate` gate for inbound ServiceRequest orders

- **Status:** Accepted — component PR [aiLabSolution/OpenELIS-Global-2#31](https://github.com/aiLabSolution/OpenELIS-Global-2/pull/31) merged (core `585a0d29c`, adversarial review APPROVE); recorded here with the umbrella pin bump (LIS-42).
- **Date:** 2026-07-12
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `core/openelis` component (FHIR data-exchange + build dependencies)
- **Relates to:** ADR-0004 (test-scope `$validate` harness — partially superseded here), ADR-0005
  (Specimen/Device linkage), LIS-40 (Stage 4 PRD — AC: "FHIR R4 result and order flows pass
  validation for DiagnosticReport/Observation and ServiceRequest"), **LIS-42 (S4.2)**; plan §3's
  Stage-4 exit gate attaches `$validate` literally to results and has orders post as
  ServiceRequest — this ADR extends instance validation to that inbound order leg.

## Context

S4.2 (LIS-42) requires that a FHIR R4 **ServiceRequest** POSTed to the API is **validated**, mapped
into a core order, and appears on the LIS worklist — and that a ServiceRequest which **fails
`$validate` is rejected with no order created** (AC2).

Facts at the pre-slice pin (`344be3cf`):

- `POST /fhir/ServiceRequest` already exists: core serves an **embedded HAPI `RestfulServer`** at
  `/fhir/*` (`FhirRestfulServer`, registered in `AnnotationWebAppInitializer`), and
  `ServiceRequestProvider.createServiceRequest` maps the resource via `FhirTransformService` and
  persists **Sample + SampleItem + Analysis** through `SamplePatientEntryService.persistData`,
  returning the created resource with a server-assigned id. There is no `ElectronicOrder` staging
  row on this local path (that belongs to the separate remote-poll referral flow).
- **No runtime instance validation existed.** ADR-0004 brought the genuine HAPI
  `FhirInstanceValidator` stack into the build but deliberately left
  `hapi-fhir-validation`, `hapi-fhir-validation-resources-r4`, and `hapi-fhir-caching-caffeine`
  at **test scope** (the LIS-41 pom comment: "no runtime `$validate` operation is exposed
  yet"). The provider performed only hand-rolled `require*` presence checks.
- The "worklist" in OpenELIS is the **Workplan** feature (`/rest/WorkPlanByTest` and siblings);
  a persisted order's analyses (status `NotStarted`) are what the workplan queries return.

## Decision

1. **Promote the three validation artifacts to runtime (compile) scope.** This supersedes
   ADR-0004's packaging note for exactly these artifacts; the rest of ADR-0004 stands.
2. **One singleton `FhirValidator` Spring bean** (in the FHIR config alongside the existing
   `FhirContext` bean), constructed with the same chain the ADR-0004 conformance tests proved:
   `FhirInstanceValidator` over `ValidationSupportChain(DefaultProfileValidationSupport,
   InMemoryTerminologyServerValidationSupport, CommonCodeSystemsTerminologyService)`. Validator
   construction is expensive — it is never built per-request.
3. **Fail-closed gate in `ServiceRequestProvider.createServiceRequest`:** the inbound resource is
   validated **before** any patient resolution, mapping, or persistence. Any `ERROR`/`FATAL`
   validation message rejects the request with HTTP **422** (`UnprocessableEntityException`)
   carrying the `OperationOutcome`; no order artifacts are created. `WARNING`/`INFORMATION`
   messages are tolerated (offline terminology warnings — LOINC CodeSystem not resolvable without
   a terminology server — are expected and out of scope for structural conformance, matching
   ADR-0004's test policy).

**Verifiable output (S4.2 exit):** component tests through the facade harness assert (AC1) a valid
R4 fixture returns 201 with a server-assigned id and the order appears via the workplan query
seam; (AC2) a parseable-but-invalid ServiceRequest is rejected 422 with an OperationOutcome and
zero new sample/analysis rows.

## Alternatives considered

- **Keep manual `require*` checks only.** Rejected: under-delivers the literal `$validate` AC;
  cardinality/enum/FHIRPath invariants stay unenforced (same reasoning that rejected
  structural-only validation in ADR-0004).
- **Server-wide HAPI `RequestValidatingInterceptor`** on `FhirRestfulServer`. Rejected for this
  slice: it would gate *every* inbound resource type at once (Patient, Observation, Task, …) —
  existing integrations (analyzer bridge, remote-poll referral flow) have never run against an
  instance validator, so the blast radius is untested. The inline gate is surgical and matches
  the provider's existing style. Widening to an interceptor is a candidate follow-up.
- **Validate after mapping (on the transformed artifacts).** Rejected: AC2 requires *no order
  created* on invalid input; validating first is the only fail-closed ordering.

## Consequences

- The WAR now ships the validation jars and their `org.hl7.fhir.r5/r4b/dstu*` transitive closure:
  31 added runtime artifacts totalling ≈80 MB (pure additions, no version swaps; the base R4
  conformance-resources jar alone is 5.6 MB packed — the ~19 MB figure in ADR-0004 is its
  unpacked `profiles-resources.xml`). Accepted as the cost of a runtime gate; the deploy kit is
  unaffected functionally. Known wart (adversarial review P2 → **LIS-208**): the promotion
  re-introduces `org.ogce:xpp3` — which bundles `javax.xml.namespace.QName`, the exact class the
  existing `hapi-fhir-structures-r4` exclusion targets — mitigated on Tomcat by parent-first
  delegation for JavaSE classes; the new jars also need recording in the third-party license
  inventory (same issue).
- The first validation on a fresh JVM pays profile-loading latency (seconds); subsequent requests
  are fast. Acceptable for order creation.
- Only the `@Create` ServiceRequest path is gated. Follow-ups filed: `@Update` validation
  (**LIS-207**); remote-import-path validation, 201 `Location` assertion, and validator
  cold-start warm-up (**LIS-209**); the `/fhir/*` auth-ordering gap — an unauthenticated POST
  currently falls through to the form-login chain and 302s to `/LoginPage`, with no
  `SecurityConfig` test covering `/fhir/*` (**LIS-212**). Component CI could not run the full
  suite on this change (checkout cannot clone the private plugins fork — **LIS-210**, urgent);
  the executed evidence is the 10-test facade class plus the LIS-41/43 conformance guards.
