# ADR-0014 — Bidirectional host-query (QRD/QRF) in the simulator

- **Status:** Proposed (pending review — LIS-18)
- **Date:** 2026-06-28
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `edge/sim` (the simulator harness) — the bidirectional query path
- **Relates to:** umbrella ADR-0005 (MLLP framing + ACK modes, S1.1 / LIS-13); umbrella
  ADR-0011 (ORU parse + LOINC/UCUM normalization, S1.2 / LIS-14 — reused for the returned
  result); umbrella ADR-0013 (Stage-1 milestone E2E, S1.5 / LIS-17); ADR-0008 (interface
  engine + fleet scope — **defers the *live* bidirectional host-query deployment to pilot
  sites post-pilot under change control**); plan §1 Stage 1 (bidirectional QRD/QRF exit-gate
  bullet); LIS-74 (bench-capture access checklist); forward to Stage 4 (EMR `ServiceRequest`
  → worklist order-download, S4.2)

## Context

Stage 1's exit gate includes the bidirectional bullet: "an EDAN H60S host-query (QRD/QRF) is
**answered** and a result returns" (`LIS_IMPLEMENTATION_PLAN.md` §1). HL7 v2 carries this as a
**query** message (`QRY^R02`) with a **QRD** (query definition) + **QRF** (query filter), and a
**response** (`ORF^R04`) that acknowledges the query and returns the requested result records.

Two facts frame the scope:

1. **The *live* bidirectional host-query is deferred post-pilot** (ADR-0008, pinned 2026-06-27):
   the pilot fleet is HL7-v2/MLLP **result-ingestion first**; bidirectional host-query rolls out
   post-pilot under change control (REQ-QMS-03). So this slice is the **simulator/protocol
   substrate**, not a pilot deployment — exactly as Stage 2's bidirectional ASTM (Q-record /
   NAK-retransmit) stays **simulator-driven** until a bidirectional unit is on hand
   (ADR-0009, plan §1 Stage 2). Building the QRD/QRF correlation now de-risks the later rollout
   and yields a conformance fixture.
2. **The result-normalization pipeline already exists** (S1.2 / ADR-0011): the `ORF^R04`
   response's `OBR`/`OBX` records are the same result content an `ORU^R01` carries, so the
   returned result reuses the tolerant ORU parser + LOINC/UCUM normalizer unchanged.

## Decision

Add `edge_sim.query`, test-first, modelling the **results-query** exchange end-to-end in the
simulator:

1. **`parse_query` / `build_query`** — read/emit a `QRY^R02` host-query. The QRD carries the
   **correlation id** (QRD-4) the answer must echo and the **subject** (QRD-8, the sample/specimen
   id); QRD-9 = `RES` (a results query). The QRF repeats the subject as its where-filter.
2. **`build_query_response` / `parse_query_response`** — the host **answers** with an `ORF^R04`:
   `MSA-1 = AA` (MSA-2 echoes the query's MSH-10), the **QRD query id echoed** so the requester
   correlates the answer, and the result serialized as `OBR`/`OBX`. Reserved characters in a
   unit/code (e.g. `10^9/L`, where `^` is the component separator) are **re-escaped** on the wire
   (`10\S\9/L`) so the answer is conformant HL7 and unescapes back — the inverse of the parser's
   unescape (ADR-0013 established the escaping for the milestone fixture).
3. **`correlates(query, response)`** — the answer is accepted iff it echoes the request's query id,
   `MSA-1 = AA`, and returns the queried subject (specimen ids match). This is the bidirectional
   guarantee: a requester binds an answer to *its* request, not to a stray response.
4. **Fixture + reuse.** One new conformance fixture — the `QRY^R02` host-query
   (`edan-h60s-host-query-qry-r02`, subject `SPEC-0231`, query id `Q0231-01`). The host **answers
   it from the existing EDAN H60S result fixture** (`edan-h60s-oru-r01`, S1.5): the host has a
   result for the sample and returns it. The returned result normalizes through the S1.2 pipeline.
   The `edge-sim query <qry-fixture>` CLI is the demo path.

**Verifiable output (S1.6 exit):** `test_query.py` proves, on the captured query fixture, that the
host-query is parsed (QRD/QRF), `build_query` round-trips, the host answers (`ORF^R04`, `MSA-1=AA`,
query id echoed) and **a result returns** that normalizes to the EDAN H60S Result rows; that the
query and answer survive MLLP framing and still correlate; and that correlation **rejects** a
mismatched query id or a non-accept ACK.

## Alternatives considered

- **Order-download / worklist query (analyzer asks the host "what tests for this sample?").**
  Deferred: that is the EMR-order → worklist path (Stage 4 / S4.2, `ServiceRequest` → core order).
  Stage 1's bullet is "a **result** returns", i.e. the *results*-query (`QRY^R02` → `ORF^R04`). The
  QRD/QRF mechanics built here are the shared substrate both directions reuse.
- **Two captured fixtures (query *and* a hand-authored response).** Rejected: the response is the
  host's *output*, so building it (`build_query_response`) from the existing result fixture proves
  the host can construct a conformant answer and avoids a redundant, drift-prone hand-authored
  `ORF^R04`. The query is the captured input; the answer is generated and asserted.
- **Live bidirectional host-query now (against a real/socket peer).** Rejected: ADR-0008 defers the
  live deployment post-pilot, and the S1.0 substrate (a live edge transport) is undecided
  (ADR-0013). The simulator proves the protocol; the socket is a later transport detail.
- **Enhanced-mode / deferred-response (QRD-3 = `D`) query.** Out of scope: the EDAN host-query is an
  immediate (`I`) results query; deferred responses and enhanced query acknowledgement are added
  only if a unit documents them (mirrors ADR-0005's enhanced-ACK posture).

## Consequences

- **Positive:** Stage 1's bidirectional exit-gate bullet is met in the simulator by an automated
  test; the QRD/QRF + correlation substrate exists and is reused by later order/worklist work; the
  returned result reuses the S1.2 normalizer unchanged; a conformance query fixture + a CLI demo
  exist; no new dependencies (the harness stays dependency-free).
- **Costs / deferred (flagged for review):**
  - **Live deployment** of bidirectional host-query is post-pilot under change control (ADR-0008);
    this slice is the simulator substrate, not a pilot capability.
  - **Synthetic fixture** — a real EDAN H60S query/response capture replaces it at bench
    conformance (LIS-74).
  - **Order-download / worklist query** (the analyzer requesting a test selection) is Stage 4
    (S4.2); only the results-query direction is built here.
  - **Deferred-response and enhanced query acknowledgement** (QRD-3 = `D`, QAK) are not modelled.
