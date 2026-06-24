# ADR-0004 — Analyzer simulator harness + conformance-fixture skeleton

- **Status:** Accepted
- **Date:** 2026-06-25
- **Deciders:** Marloe Uy (aiLabSolution)
- **Slice:** LIS-9 / S0.7 (Stage 0 — Foundations & compliance scaffold)
- **Relates to:** ADR-0001 (submodule-umbrella topology); `LIS_IMPLEMENTATION_PLAN.md`
  §1 (verification pyramid, level 2) and §0 Stage 0 deliverables.

## Context

The plan gates every later stage on **component tests against a simulated analyzer**
(replay captured messages — verification level 2) and ships, in Stage 0, an
"analyzer simulator harness + conformance-fixture repo skeleton." Two questions had
to be answered to stand it up now:

1. **Where does it live?** The natural home, the `edge/drivers` submodule, is
   *planned* but does not exist yet (CONTEXT-MAP), and the production edge transport
   substrate is an open, `ready-for-human` decision (S1.0: OIE channels vs bespoke
   drivers). Creating a new component repo now would pre-empt that decision.
2. **What is the harness vs. what is a later slice?** MLLP framing (S1.1) and the
   ASTM E1381 codec (S2.1) are their own slices; the Stage 0 skeleton must not
   duplicate or pre-empt them.

## Decision

1. **The harness lives umbrella-side under `edge/sim/`** as plain umbrella content
   (a single umbrella PR), until the `edge/drivers` submodule exists. When it does,
   `edge/sim` can move into it or alongside it; nothing here assumes a fixed home.

2. **Fixtures are the contract, not the harness.** A fixture is raw
   application-payload bytes + a JSON manifest validated against a versioned,
   language-neutral schema (`fixtures/schema/fixture.schema.json`). The Python
   harness is one consumer; a future driver (any language the S1.0 decision picks)
   consumes the same files. This keeps the Stage 0 investment substrate-agnostic.

3. **The harness is implemented in Python** (3.11+, `uv`, stdlib-only runtime,
   `pytest` for tests). Justification: a test/replay harness is independent of the
   production driver language; Python is fast to stand up and runs in CI without a
   JVM. This does **not** pre-judge S1.0 — the fixtures, not the harness, are the
   durable artifact.

4. **Scope is the transport abstraction + a loopback transport + a replay
   self-test.** Wire framing is explicitly deferred to its owning slices: MLLP →
   LIS-13 / S1.1, ASTM E1381 → LIS-23 / S2.1. They implement the `Transport`
   interface defined here. Fixtures store the **payload only**; framing is applied
   by the transport at replay time, so one capture is reusable across transports.

5. **Provenance is first-class** for the ISO 15189 evidence chain: every manifest
   carries a `source.reference` and a `synthetic` flag. Synthetic seeds are clearly
   marked; real captures (Stage 1+) set `synthetic: false` with a real reference.

## Consequences

**Positive**
- Stage 0 ships a runnable, CI-gated component-test substrate that unblocks the
  edge workstream (Stages 1–3) without waiting on the S1.0 substrate decision.
- The fixture contract is reusable by a Java or Python production driver alike.
- Slice boundaries stay clean: framing codecs remain the work of their own slices.

**Negative / costs**
- `edge/sim` is umbrella-side code, a minor exception to "components live in
  submodules" (ADR-0001), accepted as temporary until `edge/drivers` exists.
- A second language in the tree (Python alongside the Java core) — contained to
  test tooling for now; the production-driver language is still S1.0's to decide.

## Notes

- The seed fixture `_example/` is a **synthetic** HL7 v2.3 `ORU^R01`; it is not a
  real instrument capture. Real RAC-050 / labXpert captures arrive in Stage 1.
- The manifest's `expected` block is reserved for downstream parser/normalization
  assertions (normalized LOINC/UCUM Result rows) once those services exist.
