# ADR-0013 — Stage-1 milestone E2E + edge↔core ingest-contract correspondence

- **Status:** Proposed (pending review — LIS-17)
- **Date:** 2026-06-28
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `edge/sim` (the simulator harness) + the edge↔core seam
- **Relates to:** umbrella ADR-0005 (MLLP framing + ACK modes, S1.1 / LIS-13); umbrella
  ADR-0011 (ORU parse + LOINC/UCUM normalization, S1.2 / LIS-14); umbrella ADR-0012
  (raw-message archive + deterministic replay, S1.4 / LIS-16); core ADR-0003 (Result
  ingest contract, S1.3 / LIS-15 — the persistence seam this milestone targets); core
  ADR-0001 (append-only Result store, S0.5 / LIS-7); ADR-0001 (umbrella topology);
  plan §1 Stage 1 (🎯 milestone — *first result through the pipe*); LIS-18 / S1.6
  (bidirectional QRD/QRF, the remaining Stage-1 edge slice)

## Context

Stage 1's exit gate is the 🎯 **milestone — first result**: a captured **EDAN H60S**
`ORU^R01` replayed over MLLP produces a normalized **Result** (analyzer-native
code/unit preserved beside LOINC/UCUM; final) *and* the listener returns a correct
`ACK^R01` with `MSA-1 = AA`, asserted by an automated E2E test
(`LIS_IMPLEMENTATION_PLAN.md` §1). The vehicle was re-scoped (2026-06) from
RAYTO RAC-050 / Mindray labXpert to the **EDAN H60S** (HL7 v2.4 / MLLP / port 7999;
the analyzer is the TCP client, our edge listens) — the protocol contract is unchanged
(see the [access checklist](../testing/stage-1-3-machine-access-checklist.md) / LIS-74).

By the time this slice starts, every *part* of that pipeline has been built and proven
in isolation by an earlier slice:

- **MLLP frame/de-frame + `ACK^R01` (AA/AE/AR)** — S1.1 / LIS-13 (ADR-0005).
- **Tolerant `ORU^R01` parse → LOINC/UCUM `NormalizedObservation`** — S1.2 / LIS-14
  (ADR-0011), raw analyzer code/unit preserved beside the normalized form.
- **Raw-message archive + deterministic replay → normalized Result** — S1.4 / LIS-16
  (ADR-0012).
- **Core Result-ingest contract** — S1.3 / LIS-15 (core ADR-0003):
  `ResultIngestService.ingest(NormalizedObservation) → result id` persists a normalized
  observation into the append-only store, proven by a Testcontainers integration test.

What is missing is the **milestone** itself: the single automated assertion that these
parts *compose* end-to-end on a real EDAN H60S message, plus the **wiring** from the
edge's normalized output to the core ingest seam. Two facts shape how far that wiring
reaches in this slice:

1. **The edge and core are different processes in different languages.** Core ADR-0003
   deliberately makes the seam a **language-neutral value object** (`NormalizedObservation`:
   `value` + analyzer-native `rawCode`/`rawUnit` beside normalized `loinc`/`ucumValue` +
   `status`), *not* a shared class — "the edge holds its own `NormalizedObservation` analog
   and maps to this contract over whatever transport S1.0 picks."
2. **The S1.0 substrate (the edge→core transport) is still undecided** (core ADR-0003
   alternatives; plan §1 open decisions). A live cross-process bridge would presuppose that
   decision, and core-side persistence of the DTO is **already proven** by LIS-15.

## Decision

Land the milestone as an **edge-side automated E2E plus the contract artifact**, in a
single umbrella PR (pure `edge/sim` + docs), test-first:

1. **EDAN H60S fixture** (`fixtures/edan-h60s-oru-r01/`) — a synthetic HL7 v2.4 `ORU^R01`
   CBC result with EDAN-native `99EDAN` codes (WBC/RBC/HGB/HCT/MCV/PLT) and EDAN-default
   units (HGB in `g/L`, RBC in `10^12/L`). The `10^9/L` / `10^12/L` unit carets are
   HL7-escaped on the wire (`10\S\9/L`) since `^` is the component separator; the tolerant
   parser unescapes them before normalization. The terminology seed (ADR-0011) gains the
   EDAN units, exercising a second vendor's terminology beyond the RAYTO seed.

2. **`edge_sim.milestone.run_milestone`** — the milestone path: an inbound `ORU^R01` is
   framed onto an MLLP wire and de-framed (the listener receiving it), acknowledged
   (`ACK^R01`, MSA-1 = `AA`, framed back on the wire), and parsed + normalized. The
   `MilestoneOutcome` carries the normalized observations (raw beside LOINC/UCUM), the ACK,
   and each observation's **finality** (OBX-11 → a lifecycle label). The automated test
   `test_milestone.py` is the milestone exit-gate assertion.

3. **`edge_sim.ingest.to_ingest_dto`** — the edge half of the wiring: serialize the edge
   `NormalizedObservation` to the **core ADR-0003 ingest contract DTO**, field-for-field
   (`value`, `rawCode`, `rawUnit`, `loinc`, `ucumValue`, `status`). This makes the edge↔core
   correspondence an auditable, tested artifact (ISO 15189 evidence) rather than an ad-hoc
   dict at a call site. The `edge-sim milestone <fixture>` CLI command prints the Result,
   the ACK, and the DTO — the human-runnable demo path.

4. **Status-terminology reconciliation.** The plan's "status = final" is the HL7
   **result-lifecycle finality** (OBX-11 `F`), surfaced at the edge by `run_milestone`. The
   core contract's `status` field (core ADR-0003) is the **normalization** status
   (`NORMALIZED`/`PARTIAL`/`UNMAPPED`). Both coexist: the milestone asserts the captured
   result is final *and* fully normalized; the contract DTO carries the normalization status.

**Verifiable output (S1.5 exit):** `test_milestone.py` proves, on the EDAN H60S fixture,
that the `ORU^R01` survives MLLP framing, is accepted (`ACK^R01` / MSA-1 = `AA`, framed back
on the wire), and normalizes to six final Result rows with analyzer-native code/unit
preserved beside populated LOINC/UCUM; `test_ingest.py` proves the edge emits the core
ADR-0003 DTO field-for-field; the `edge-sim milestone` CLI is the demo path.

## Alternatives considered

- **Full cross-process E2E now (live or Testcontainers core).** Rejected for this slice: it
  presupposes the **undecided S1.0 substrate** (the edge→core transport, core ADR-0003) and
  re-proves what LIS-15 already proves (core persistence of the DTO via Testcontainers). The
  cross-process leg lands once the substrate is chosen; this slice fixes the **contract** the
  two sides speak so that wiring is a transport detail, not a re-design.
- **Edge E2E only, no contract DTO.** Rejected: it would assert the edge pipeline but miss the
  milestone's "wiring → ingest" half. Emitting the core ADR-0003 DTO is the minimum that makes
  the edge↔core seam real and testable without a live core.
- **Add a result-lifecycle (`final`/`preliminary`) field to the core ingest contract now.**
  Rejected: a contract change beyond S1.3's scope; finality is not needed to *persist* a
  result, and core `result.status` already carries the normalization status (core ADR-0003,
  S0.5). Lifecycle propagation into the contract is deferred (flagged below).
- **Synthesize EDAN units without escaping (e.g. `10*9/L` on the wire).** Rejected: it would
  dodge the real HL7 caret-vs-component-separator problem and make `raw_unit == ucum_value`
  (a trivial normalization). The escaped `10\S\9/L` is HL7-conformant and exercises the
  unescape path.

## Consequences

- **Positive:** Stage 1's milestone is met by a single automated E2E on the re-scoped EDAN
  H60S vehicle; the edge↔core ingest correspondence (core ADR-0003) is a tested, auditable
  artifact; a second vendor's terminology is normalized; a CLI demo path exists; no new
  dependencies (the harness stays dependency-free).
- **Costs / deferred (flagged for review):**
  - **Live cross-process leg** — handing the DTO to a running/Testcontainers core over a wire
    waits on the **S1.0 substrate decision** (core ADR-0003). Until then the seam is proven by
    correspondence (edge emits the DTO ↔ LIS-15 proves core persists it), not a live socket.
  - **Staging demo** — the plan's "demo on staging from a real or captured instrument message"
    is the manual exit-gate bullet, separate from this automated test; it follows a core
    bring-up (memory: `local-openelis-bringup`).
  - **Result-lifecycle status** is surfaced at the edge (OBX-11) but **not** propagated into the
    core ingest contract; carrying finality to the store is later work.
  - **Synthetic fixture** — a real EDAN H60S capture replaces it at bench conformance
    (LIS-74); the second-vendor proof (HETO AU120) and the bidirectional QRD/QRF path
    (**LIS-18 / S1.6**) are the remaining Stage-1 edge slices.
