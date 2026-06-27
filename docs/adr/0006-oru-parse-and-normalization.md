# ADR-0006 — Tolerant ORU^R01 parse + LOINC/UCUM normalization (edge)

- **Status:** Proposed (pending review — LIS-14)
- **Date:** 2026-06-26
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `edge/sim` (the umbrella-side analyzer harness; CONTEXT-MAP marks the `edge/drivers` submodule "planned")
- **Relates to:** ADR-0004 (analyzer simulator harness + conformance fixtures, LIS-9); ADR-0005 (MLLP framing + ACK modes, LIS-13); core ADR-0001 (result raw+normalized shape, LIS-7); LIS-8 / S0.6 (core `vendor_code_mapping` seed — the mapping this mirrors); LIS-11 (Stage 1 PRD); plan §1 (HL7 v2 edge — "HL7 v2.3 parser (tolerant)"; "Normalization service: vendor code → LOINC, unit → UCUM"); forward to LIS-15 / S1.3 (persist to the append-only Result store) and LIS-17 / S1.5 (first-result milestone E2E)

## Context

S1.2 (LIS-14) is the **parse + normalize** step of Stage 1's "first result through
the pipe": a captured RAYTO RAC-050 `ORU^R01` must be parsed and **normalized to a
LOINC/UCUM intermediate row**. S1.1 (LIS-13) delivered MLLP framing + the `ACK^R01`,
but the MLLP transport reads only enough of `MSH` to acknowledge — nothing parses
the result content yet. This slice adds that, stopping at the in-memory normalized
row; persistence to the core append-only Result store is S1.3 (LIS-15).

Facts that shape the decision (verified against the code/fixtures):

- The harness is **dependency-free** (`pyproject.toml` `dependencies = []`), by the
  ADR-0004 principle that fixtures are a language-neutral contract and the harness
  stays a thin, portable reference. So an HL7 PyPI parser is out.
- `ack.py` already splits an `MSH` segment for acknowledgment, but is deliberately
  MSH-only and ACK-scoped; it is not a general parser.
- The fixture manifest schema reserves an **`expected`** object
  (`additionalProperties: true`) explicitly "for the normalized LOINC/UCUM Result
  row, wired up once those services land in Stage 1" — the home for S1.2 assertions.
- The existing `example-mllp-oru-r01` fixture carries **already-LOINC** codes in
  `OBX-3` (it was seeded for S1.1 MLLP framing, which ignores content), so it cannot
  exercise vendor-code→LOINC normalization.
- Core S0.6 (LIS-8) seeds `clinlims.vendor_code_mapping` (analyzer code → LOINC +
  UCUM). The edge normalizer needs the same shape of mapping, but the edge is a
  separate Python process and (per S1.0, undecided substrate) cannot assume a live
  core DB at parse time.

## Decision

Add three small, dependency-free modules and one fixture, all under `edge/sim`,
test-first:

1. **`hl7.py` — a tolerant HL7 v2 parser.** Splits a message into `Segment`s and
   their fields/components/repetitions, honouring `MSH-1`/`MSH-2` delimiters and
   decoding the standard escapes (`\F\ \S\ \T\ \R\ \E\ \Xhh\`). Tolerant per plan
   §1: `\r`/`\n`/`\r\n` terminators, missing trailing fields, short/empty segments
   parse without raising. HL7 field numbering is preserved (`MSH-1` is the field
   separator; other segments index naturally) so callers use manual/spec numbers
   directly. General-purpose — labXpert (S1.6) and future HL7 reuse it.
2. **`oru.py` — `ORU^R01` extraction.** Walks the parsed message to a typed,
   transport-neutral `OruReport` (analyzer, patient/specimen ids) with one
   `RawObservation` per `OBX`, carrying the analyzer-native code/unit **as
   reported**. Only a message with no `MSH` is rejected; a non-`ORU` message parses
   to a report with whatever `OBX` it has (tolerant ingest).
3. **`normalize.py` — LOINC/UCUM normalization.** A `TerminologyMap`
   (vendor code → LOINC, vendor unit → UCUM) drives a `Normalizer` that emits a
   `NormalizedObservation` — the **intermediate row**: the raw analyzer code/unit
   **beside** the normalized `loinc`/`ucum_value` and a `status`
   (`NORMALIZED`/`PARTIAL`/`UNMAPPED`). The same raw-beside-normalized shape the
   core `result` table persists (core ADR-0001), and the same mapping shape as the
   S0.6 `vendor_code_mapping` seed.
4. **Fixture `rayto-rac050-oru-r01`** — a synthetic RAC-050 `ORU^R01` with
   analyzer-native (`99RAC`) codes (`HGB/HCT/WBC/PLT`) and raw vendor units, whose
   manifest `expected` block declares the normalized rows. The acceptance test
   asserts parse+normalize equals `expected`, so the fixture is the contract.
5. **`edge-sim normalize <fixture>`** CLI subcommand printing the intermediate rows.

**Verifiable output (S1.2 exit):** `VendorCodeNormalizationIntegrationTest`-analog
in pytest — `test_oru_normalize.py` — proves the RAC-050 `ORU^R01` parses to four
observations and each normalizes to its expected LOINC/UCUM intermediate row
(`HGB`→`718-7`/`g/dL`, `WBC`→`6690-2`/`10*3/uL`, …), with tolerant-parse negatives
(unmapped code, missing unit, non-ORU, missing MSH, stray blank segment).

## Alternatives considered

- **Use an HL7 library (`python-hl7`, `hl7apy`).** Rejected: breaks the
  dependency-free contract (ADR-0004); the tolerant subset we need is ~150 lines and
  must match the fixture-as-contract philosophy a future non-Python driver re-implements.
- **Extend `ack.py` into the full parser.** Rejected: `ack.py` is intentionally
  MSH-only and ACK-scoped; a general parser is a distinct concern. (A later slice may
  re-base `ack.py`'s MSH read on `hl7.py`; out of scope here to keep S1.2 additive.)
- **Reuse `example-mllp-oru-r01` instead of a new fixture.** Rejected: its `OBX-3`
  already carries LOINC, so normalization would be identity and prove nothing. A new
  fixture with local codes (and a genuine unit transform, `K/uL`→`10*3/uL`) is the
  honest input. The S1.1 fixture stays the MLLP-framing fixture, untouched.
- **Query the core `vendor_code_mapping` (LIS-8) live for the mapping.** Rejected for
  S1.2: the edge cannot assume a live core DB at parse time (S1.0 substrate undecided),
  and S1.2's gate is the parse+normalize, not wiring to core. The built-in
  `TerminologyMap.default()` seed is the edge analog; sourcing it from core / a shared
  terminology export is later normalization-service work.
- **Encode `10^9/L` literally in the fixture unit.** Rejected: `^` is the HL7 component
  separator, so an unescaped `10^9/L` in `OBX-6` is two components — a spec deviation a
  tolerant parser must not silently "fix". The fixture uses `K/uL` (no delimiter
  collision) to demonstrate a real vendor→UCUM transform; escape-handling is covered
  separately in `test_hl7.py`.

## Consequences

- **Positive:** Stage 1 now parses + normalizes a real-shaped `ORU^R01` to the
  LOINC/UCUM intermediate the milestone (S1.5) and the Result store (S1.3) consume;
  the parser is general (reused by labXpert S1.6 and beyond); the fixture `expected`
  block makes normalization a language-neutral contract; tolerant by construction.
- **Costs / deferred (flagged for review):**
  - **No persistence** — the intermediate row is in-memory; S1.3 (LIS-15) writes it
    to the core append-only Result store.
  - **Built-in terminology seed** — `TerminologyMap.default()` ships a small RAC-050
    CBC mapping. A richer per-analyzer set, and sourcing it from the core
    `vendor_code_mapping` (LIS-8) or a shared terminology export rather than a Python
    dict, is later normalization-service work.
  - **Unit normalization is a lookup table**, not a UCUM grammar; sufficient for the
    discrete analyzer unit vocabularies, revisit if free-form units appear.
  - **`ack.py` still has its own MSH read** — a future consolidation onto `hl7.py` is
    possible but deliberately out of this slice.
  - The synthetic fixture is `synthetic: true`; a real RAC-050 capture replaces it in
    LIS-20 (bench conformance).
