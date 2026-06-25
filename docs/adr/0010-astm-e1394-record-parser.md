# ADR-0010 — ASTM E1394 record parser (edge)

- **Status:** Proposed (pending review — LIS-24)
- **Date:** 2026-06-26
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `edge/sim` (the umbrella-side analyzer harness; the `edge/drivers` submodule is "planned")
- **Relates to:** ADR-0004 (simulator harness + fixtures, LIS-9); ADR-0009 (ASTM E1381 codec + session, LIS-23 — the framing this parses out of); ADR-0006 (HL7 ORU parser, LIS-14 — the HL7 analog one layer up); LIS-22 (Stage 2 PRD); LIS-24 (S2.2); plan §2 ("High level (ASTM E1394): records H→P→O→R→C/Q/L"); forward to S2.4 / LIS-26 (DiaSys result → normalized Result row)

## Context

S2.2 (LIS-24) is the **record layer** of the ASTM stack: once the E1381 codec
(S2.1 / LIS-23) has de-framed and checksum-validated the wire bytes, the resulting
**E1394 record set** — a flat, ordered, pipe-delimited `H>P>O>R>L` sequence — must
parse into a typed tree the rest of the pipeline can consume, *tolerant of spec
deviation* (plan §2 exit gate: "H→P→O→R→L parsed"). Normalizing a parsed result to
a LOINC/UCUM Result row is the next slice (S2.4 / LIS-26).

Facts that shape the decision:

- The harness is **dependency-free** (ADR-0004); the HL7 side already proved a small
  hand-written record/field parser is the right shape (ADR-0006), and the fixture is
  the cross-language contract.
- ASTM E1394 differs from HL7 v2 in delimiter encoding: the **`H` record itself
  declares the delimiters** — the char after `H` is the field delimiter and the next
  field (e.g. `\^&`) defines the repeat, component and escape characters (a different
  order and meaning from HL7's `MSH-2`). So the parser must read them from the header,
  not assume HL7's.
- The records are flat but **imply a tree** (a `P`, then its `O`s, then each `O`'s
  `R`s); real instruments deviate (a missing `H`, an `R` with no preceding `O`,
  vendor `M`/`C` records interleaved), so the tree builder must be defensive.
- The de-framed payload is exactly what `AstmTransport.receive()` (S2.1) returns and
  what the `diasys-r920-astm-result` fixture stores, so S2.1 + S2.2 compose directly.

## Decision

Add one dependency-free module, `e1394.py`, test-first; reuse the existing DiaSys
fixture (no new fixture needed).

- **`Delimiters.from_header(record)`** — derives `field / repeat / component / escape`
  from the `H` record (falls back to the conventional `|\^&`).
- **`Record`** — a record's type letter + `field`-split fields, with 1-based
  `field(n)` / `component(n, c)` accessors and a `test_code(n)` helper that takes the
  **last non-empty component** of a universal-test-id field (so `^^^GLU` and a bare
  `GLU` both resolve).
- **`parse_e1394(message)`** — splits records (CR/LF tolerant), reads the delimiters
  from the first `H`, and walks the records into a typed **`AstmMessage`** tree:
  `Header`, `AstmPatient[]` → `AstmOrder[]` → `AstmResult[]`, plus the terminator code
  and the flat ordered `records` list. Defensive: a missing `H` → `header=None` with
  default delimiters; an `O`/`R` with no parent gets an **implicit** parent; unknown
  record types (`C`/`Q`/`M`) are retained in `records` but left out of the tree;
  absent fields return `""`. A convenience `AstmMessage.results` flattens every result.
- **`edge-sim parse-astm <fixture>`** CLI prints the record tree.

**Verifiable output (S2.2 exit):** `test_e1394.py` proves the DiaSys fixture parses
to the expected tree (`DiaSys/R920` header; patient `PID-0077`; order `SPEC-0077`,
test `GLU`; result `GLU 5.2 mmol/L`, flags `N`, status `F`; terminator `N`), that it
composes with the S2.1 transport (de-frame → parse), and the tolerant-deviation
negatives (bare test id, `R` before `O`, unknown record types, missing `H`, short
records, blank input).

## Alternatives considered

- **An ASTM library (`astm`, `python-astm`).** Rejected: breaks the dependency-free
  contract (ADR-0004); the parse we need is ~150 lines and must match the
  fixture-as-contract philosophy a future non-Python driver re-implements.
- **Reuse the HL7 parser (`hl7.py`, S1.2).** Rejected: it is on a different (unmerged)
  branch, and ASTM's header-declared delimiters and record-typed hierarchy differ
  enough that sharing code would couple two protocols for little gain. The two parsers
  stay siblings behind the same fixture contract.
- **Raise on spec deviation (strict parse).** Rejected: plan §2 calls for tolerance —
  real serial instruments deviate, and a driver that crashes on a stray `M` record or a
  missing `H` is useless on the bench. Only genuinely empty input raises.
- **Fold normalization (test code → LOINC, unit → UCUM) into this slice.** Rejected:
  that is S2.4 (LIS-26); S2.2 is the parse. Keeping them separate matches the HL7 split
  (ORU parse S1.2 vs normalization within it) and the E1381/E1394 layering.

## Consequences

- **Positive:** the ASTM fleet now has a typed, tolerant record model that composes
  with the S2.1 codec (de-frame → parse); it is dependency-free and fixture-driven; the
  defensive tree builder is honest about real instrument deviation; `parse-astm` makes
  the parse inspectable from the CLI.
- **Costs / deferred (flagged for review):**
  - **No normalization** — results carry the analyzer-native `test_code`/`units`;
    mapping to LOINC/UCUM onto a Result row is S2.4 (LIS-26).
  - **Single message tree** — one `H…L` session per call; multi-message streams (back-to-back
    `H…L` blocks) are a later concern if an instrument batches them.
  - **`Q` (query) records are retained but not acted on** — the bidirectional query path
    is S2.5 (LIS-27).
  - **Delimiters are read once from the first `H`** — a (non-conformant) mid-stream
    delimiter change is not handled.
  - This slice is **stacked on S2.1 (LIS-23, PR #10)** to reuse the codec context and the
    DiaSys fixture; it merges after it. Code coupling is limited to the shared fixture and
    the optional de-frame-then-parse integration test.
