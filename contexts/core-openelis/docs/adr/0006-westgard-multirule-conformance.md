# ADR-0006 (core/openelis) — Westgard multirule engine emits named in/out-of-control verdicts (conformance gate)

- **Status:** Accepted — component PR [aiLabSolution/OpenELIS-Global-2#9](https://github.com/aiLabSolution/OpenELIS-Global-2/pull/9) merged (core `566e9f84`); recorded here with the umbrella pin bump (LIS-52).
- **Date:** 2026-06-28
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `core/openelis` component (QC — Westgard rule evaluation)
- **Relates to:** ADR-0001 (umbrella topology — component decisions live here); **ADR-0004 / ADR-0005 (the S4.1 / S4.3 conformance-gate precedent this follows)**; LIS-51 (Stage 5 PRD); **LIS-52 (S5.1)**; plan §3 Stage 5 exit gate ("a Westgard violation (e.g., 1₃ₛ / 2₂ₛ) **blocks autorelease**"); downstream slices that build on the engine — **LIS-55 (S5.4, autoverification gating)**, **LIS-53 (S5.2, Levey-Jennings)**, **LIS-54 (S5.3, delta check)**.

## Context

S5.1 (LIS-52) requires the QC engine to turn **control-point vectors into named in/out-of-control
verdicts**. The pinned core already ships that engine (upstream PR #3390):

- `WestgardRuleEvaluationServiceImpl` orchestrates eight rule evaluators over a current `QCResult`, its
  chronological history (oldest-first), and the control-lot `QCStatistics` (mean / SD).
- Each `WestgardRuleEvaluator` is a **pure POJO** returning a `RuleEvaluationResult` (`ruleCode`,
  `violated`, `severity` = `WARNING` | `REJECTION`). The rule set: `1₂ₛ`, `1₃ₛ`, `2₂ₛ`, `R₄ₛ`, `3₁ₛ`,
  `4₁ₛ`, `7ₜ`, `10ₓ`. The z-score is read from the result or computed as `(value − mean) / SD`.
- The object overload `evaluateAllRules(current, history, testId, instrumentId)` runs every **enabled**
  rule (config from `WestgardRuleConfigService`) against the supplied statistics and returns the list of
  per-rule verdicts; `hasRejectionViolation(...)` is the rejection ⇒ out-of-control predicate.

What was missing was an automated proof that the **assembled** engine maps a vector to the
correctly-named verdicts:

- `WestgardRuleEvaluationServiceTest` **mocks** the evaluators — it proves orchestration (dispatch,
  filtering, error handling), not the rule semantics.
- Only **four of eight** evaluators have an isolated unit test (`1₃ₛ`, `2₂ₛ`, `R₄ₛ`, `4₁ₛ`); **`1₂ₛ`,
  `3₁ₛ`, `7ₜ`, `10ₓ` have none**.

So nothing wired the **real** evaluators into the engine and asserted a vector → named verdict, including
the *multirule* essence S5.1 is about (one extreme point simultaneously trips `1₂ₛ` **and** `1₃ₛ`).

## Decision

**1. The conformance gate** — `WestgardMultiruleEngineConformanceTest` (pure JUnit + Mockito; no
Spring/Testcontainers, mirroring the S4.1 / S4.3 gates). It injects the **real** evaluator set into
`WestgardRuleEvaluationServiceImpl`, stubs only the two persistence collaborators the object overload
reads (rule-config lookup → all eight rules enabled; statistics DAO → mean = 100, SD = 10), and drives the
engine with canonical Westgard vectors, asserting per scenario the **exact set** of violated rule codes
(equality, not containment — so a missed rule *and* a spurious extra verdict both fail), each verdict's
`WARNING` / `REJECTION` severity, and the run-level verdict (out-of-control ⇔ any `REJECTION`):

| Vector (mean 100, SD 10) | Named verdicts | Run |
|---|---|---|
| 12-pt straddling history (**negative control**) | `{}` | in-control |
| single point z = +3.5 | `{1₂ₛ, 1₃ₛ}` | out-of-control |
| z = +2.4 after z = +2.3 | `{1₂ₛ, 2₂ₛ}` | out-of-control |
| z = +1.4 vs z = −2.6 (range 4 SD) | `{R₄ₛ}` | out-of-control |
| four points > +1 SD | `{3₁ₛ, 4₁ₛ}` | out-of-control |
| seven rising points < 1 SD | `{7ₜ}` | in-control (warning only) |
| ten points above mean < 1 SD | `{10ₓ}` | out-of-control |

A completeness test asserts the union of verdicts across the vectors covers **all eight** published rules,
and the negative control asserts every rule actually *evaluated* (not skipped for want of history).

**2. No production seams.** Unlike S4.3 (ADR-0005, which needed two transform seams), the evaluators were
already pure and package-visible and the service already exposes the object overload, so the gate is
expressible with **zero production-code changes** — it is test-only, the lowest-risk shape of this gate.

**Verifiable output (S5.1):** the test is green (8 tests, ~2 s); the component's full backend CI passes.
**Non-vacuity** was confirmed by perturbing the `1₃ₛ` threshold (`3.0 → 30.0`): the gate goes red on
exactly the two `1₃ₛ`-dependent assertions, then green on revert.

## Alternatives considered

- **Assert at the individual-evaluator level** (call each evaluator directly, no service). Rejected as the
  primary gate: it cannot express the multirule behavior (one vector → a *set* of simultaneous named
  verdicts via the orchestrator) that S5.1 names, and four rules already have isolated tests. The
  service-level gate exercises the real wiring (config gating, evaluator dispatch, verdict aggregation)
  that no test covered, and still runs every rule's production logic.
- **Integration test through the live FHIR QC pipeline / DB-backed config + statistics.** Rejected for
  this gate: Testcontainers-bound and slow, and it would exercise ingestion/persistence, not rule
  semantics. The unit gate stubs the two DAOs and asserts the same vector → verdict contract
  deterministically and fast. Runtime/pipeline coverage is a separate concern.
- **Just add the four missing isolated evaluator unit tests.** Subsumed — the engine gate exercises all
  eight rules' production logic — but framed as a single **named S5.1 conformance artifact** over the
  assembled engine (the canonical-vector matrix is the IQ/OQ-citable proof), not four more isolated tests.

## Consequences

- **Positive:** S5.1 has an executable, traceable proof that the pinned core maps QC vectors to the
  correctly-named in/out-of-control verdicts — covering all eight rules (including the four with no prior
  unit test) and the multirule simultaneity — with **zero production change**, no new dependencies, and no
  Spring/Testcontainers cost.
- **Costs / deferred (flagged for review):**
  - The gate **stubs** the control-lot statistics (mean/SD) and the enabled-rule config; it does not
    exercise the live `QCStatisticsService` calculators (rolling / manufacturer-fixed) or the DB-backed
    `WestgardRuleConfigService`. Those have their own tests; this gate deliberately isolates **rule
    semantics** from statistics derivation and configuration.
  - **Autoverification gating** — "a Westgard violation blocks autorelease" (plan §3 Stage 5) — is tracked
    by **LIS-55 (S5.4)**. This slice proves the *verdicts* and asserts the rejection ⇒ out-of-control
    predicate; wiring that predicate into the release path is LIS-55.
  - Vectors use a single test/instrument/lot with synthetic mean/SD. Real-instrument QC characterization
    rides on Stage-5 validation (IQ/OQ execution) and the Levey-Jennings read path (**LIS-53 / S5.2**).
