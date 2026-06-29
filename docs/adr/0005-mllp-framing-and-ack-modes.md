# ADR-0005 — MLLP framing + HL7 v2 ACK^R01 modes

- **Status:** Accepted
- **Date:** 2026-06-25
- **Deciders:** Marloe Uy (aiLabSolution)
- **Slice:** LIS-13 / S1.1 (Stage 1 — HL7 v2 edge: first result through the pipe)
- **Relates to:** ADR-0004 (analyzer simulator harness — this fills its deferred
  MLLP slice); `LIS_IMPLEMENTATION_PLAN.md` §3 Stage 1 ("MLLP listener: frame
  `0x0B <msg> 0x1C 0x0D`; original **and** enhanced ACK modes") and §1 (verification
  pyramid, levels 1–2).

## Context

ADR-0004 stood up the simulator harness with a `Transport` abstraction and a
loopback transport, and **explicitly deferred MLLP framing to LIS-13 / S1.1**. This
slice implements that transport: HL7 v2 over MLLP is the wire for the first two
Stage 1 analyzers (RAYTO RAC-050, Mindray labXpert). Three questions shaped how:

1. **How much of HL7 does an ACK need?** The headline acceptance is an
   `ACK^R01` round-trip against a simulated analyzer — not result interpretation.
   The tolerant ORU^R01 parser + LOINC/UCUM normalization is a **separate slice**
   (S1.2 / LIS-14); over-reaching here would blur slice boundaries.
2. **Original vs enhanced acknowledgment.** The plan names both. They differ in the
   `MSA-1` code domain and in whether an ACK is sent at all (driven by `MSH-15`).
3. **How to stay testable and deterministic** without a live socket, keeping the
   harness in-memory and dependency-free (ADR-0004 §3).

## Decision

1. **MLLP codec is a standalone module** (`edge_sim/mllp.py`), stdlib-only:
   - `frame(payload)` / `deframe(block)` apply and strip the
     `SB(0x0B) … EB(0x1C) CR(0x0D)` envelope, byte-faithfully. The payload is the
     application message verbatim (HL7 segments, themselves CR-separated). MLLP
     reserves the three block characters, so a conformant payload contains neither
     `SB` nor `EB`; **`frame` enforces this**, rejecting a payload that does, which
     keeps `deframe` (strips by position) and `MllpDecoder` (scans for the first
     `EB`) symmetric. `deframe` raises `MllpError` on a malformed single frame.
   - `MllpDecoder` is the **incremental, self-resynchronising** de-framer a real
     TCP listener needs: `feed(bytes) -> list[payloads]`, buffering partial frames
     across reads. It never raises on a corrupt stream and never wedges — it
     resyncs the way production receivers (HAPI/Mirth) do: inter-frame noise is
     discarded; a fresh `SB` before the in-flight frame's `EB` (an aborted or
     retransmitted frame) drops the in-flight bytes and restarts at the new `SB`;
     an `EB` not followed by `CR` drops the corrupt frame and resumes after it; and
     an in-flight frame exceeding `max_frame_bytes` (default 16 MiB) is dropped so a
     never-terminated frame cannot grow the buffer without bound. Each resync bumps
     `resync_count`, so a corrupt stream is observable without exceptions.

2. **`MllpTransport` plugs into the ADR-0004 `Transport` interface.** It frames on
   `send`, de-frames on `receive` (via `MllpDecoder`) over an in-memory wire — so
   every fixture replays through the **real** codec and the round-trip stays
   byte-faithful. A production listener swaps the in-memory wire for a TCP socket;
   the codec and de-framer are unchanged. This keeps the test substrate honest
   without pre-empting the S1.0 transport-substrate decision (still
   `ready-for-human`).

3. **ACK construction reads only `MSH`** (`edge_sim/ack.py`). It swaps the
   sending/receiving routing, echoes the trigger event (`ACK^R01` for `ORU^R01` —
   adding the message-structure 3rd component, `ACK^R01^ACK`, for v2.3.1+ per
   `MSH-12`), defaults a blank inbound `MSH-2` back to `^~\&` (a required field),
   sets `MSA-2` to the inbound message control id, and supports:
   - **Original mode** — `MSA-1 ∈ {AA, AE, AR}` (accept/error/reject).
   - **Enhanced mode** — commit `MSA-1 ∈ {CA, CE, CR}`, with `wants_accept_ack()`
     honouring `MSH-15` (`AL` always, `NE` never, `SU` on success, `ER` on error).
   A code that does not match the requested mode is rejected (`Hl7AckError`). The
   tolerant ORU^R01 parser is **out of scope** — `ack.py` knows only `MSH`.
   - **Negative acknowledgment (`build_nak`, LIS-13 AC).** A negative ACK — `AE`
     (application error) or `AR` (application reject) — additionally carries a
     **populated HL7 `ERR` segment** (not merely `MSA-3` free text). `ack.py` builds
     the `ERR` from the inbound `MSH` separators + a caller-supplied HL7 **Table
     0357** condition (`Hl7ErrorCondition`); it does **not** decide *whether* a
     message is rejected (that needs the body, which `ack.py` does not read). The
     accept/reject **decision** is the listener's, in
     `edge_sim.milestone.acknowledge()` (see Note below).

4. **Determinism is caller-controllable.** `build_ack` takes optional `timestamp`
   (`MSH-7`) and `control_id` (`MSH-10`); both default to live values (UTC now /
   inbound control id) but are injectable for byte-exact tests. This avoids the
   `Date.now()`-style nondeterminism that would otherwise make ACK assertions
   flaky.

5. **One synthetic MLLP fixture** (`fixtures/example-mllp-oru-r01/`) exercises the
   transport and documents the MLLP wire as a first-class conformance artifact.
   Per ADR-0004 §4 it stores **payload only** (`synthetic: true`); real RAC-050 /
   labXpert captures replace it in Stage 1 bench-conformance (LIS-20/21).

## Consequences

**Positive**
- Stage 1's first wire is live and CI-gated (verification levels 1–2) without a
  socket or new dependencies; the ACK round-trip — S1.1's headline — passes.
- Slice boundaries stay clean: framing + ACK here, parsing/normalization in S1.2.
- The codec is reusable by the production driver in whatever language S1.0 picks,
  exactly like the fixtures (ADR-0004 §2).

**Negative / costs**
- The in-memory `MllpTransport` proves framing correctness but **not** socket
  concurrency, timeouts, or partial-read timing against a real instrument — that is
  bench conformance (level 3, LIS-20/21), out of scope here.
- `ack.py` parses `MSH` ad hoc rather than via a general HL7 parser; once S1.2 lands
  a tolerant parser, the `MSH` read may be consolidated onto it.

## Notes

- Block characters: `SB`/`<VT>` = `0x0B`, `EB`/`<FS>` = `0x1C`, `CR` = `0x0D`.
- The ACK payload joins segments with `CR` and adds no trailing `CR`, matching the
  payload-only fixture convention; MLLP framing supplies the wire envelope.
- **ACK-mode note (2026-06 availability re-scope, LIS-74):** enhanced-mode ACK is
  currently **unexercised by any available analyzer** — the original Stage-1 unit
  (RAC-050) and its re-scoped replacement (EDAN H60S) both use **original-mode ACK
  only** — so the implemented enhanced path stays simulator-tested but hardware-unproven
  until a unit that requests it is on hand. See
  `docs/testing/stage-1-3-machine-access-checklist.md`.
- **AE/AR + `ERR` scope (LIS-13 AC, added 2026-06-29).** The LIS-13 acceptance
  criterion "malformed envelope → AE/AR ACK with a populated `ERR` segment" applies
  **per layer**, because a *negative ACK can only exist when there is a recoverable
  `MSH`** to echo (`MSA-2`) and route (swapped `MSH-3..6`):
  - **Un-de-frameable bytes** (no complete `SB … EB CR`): there is no payload and no
    `MSH`. The `MllpDecoder` **silently resynchronises** (bumping `resync_count`),
    matching production receivers (HAPI/Mirth) — *no ACK is emitted*. Nothing changes.
  - **De-framed payload with no `MSH`**: still nothing to acknowledge (`parse_msh`
    raises `Hl7AckError`); the listener does not fabricate an ACK.
  - **`MSH`-parseable but rejected**: this is the implementable AE/AR+`ERR` case.
    `acknowledge()` returns **AR** + `ERR` for an *unsupported message type*
    (anything but `ORU^R01` on the result port; 0357 = 200) and **AE** + `ERR` for a
    supported type that **cannot be processed** (unparseable body 0357 = 102; an
    `ORU^R01` with no `OBX` results 0357 = 101).

  So the literal phrase "malformed *envelope*" is **re-scoped** to "`MSH`-parseable
  message the listener rejects." The `ERR` segment targets the **pre-v2.5 `ERR-1`**
  ("Error Code and Location"; the 4th component is the `CE` `<code>&<text>&HL70357`)
  because the whole v1 fleet is **HL7 v2.3.1–v2.4** (EDAN H60S = v2.4, Seamaty SD1 =
  v2.3.1); a v2.5+ unit would move the code to `ERR-3`/`ERR-4`, a change-control delta
  if one is ever added. This crosses the original "`ack.py` knows only `MSH`" boundary
  only in the *listener* (`milestone.acknowledge()`), which owns the reject decision;
  `ack.py` stays `MSH`-only (it just builds the `ERR` it is told to).
