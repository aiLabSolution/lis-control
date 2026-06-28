# ADR-0009 — ASTM E1381 codec + session (edge)

- **Status:** Proposed (pending review — LIS-23)
- **Date:** 2026-06-26
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `edge/sim` (the umbrella-side analyzer harness; CONTEXT-MAP marks the `edge/drivers` submodule "planned")
- **Relates to:** ADR-0004 (analyzer simulator harness + conformance fixtures, LIS-9); ADR-0005 (MLLP framing + ACK modes, LIS-13 — the framed-transport pattern this mirrors); LIS-22 (Stage 2 PRD); LIS-23 (S2.1); plan §2 (ASTM/serial edge — "Low level (ASTM E1381): ENQ/ACK/NAK/EOT contention; framing; modulo-256 checksum"); forward to S2.2 / LIS-24 (ASTM E1394 record parser) and S2.4 / LIS-26 (DiaSys R920 channel → normalized Result)

## Context

S2.1 (LIS-23) is the **low-level ASTM link layer** for the chemistry/serial fleet:
the DiaSys R920 and the small RS-232 fleet speak **ASTM E1381** beneath the
**E1394** record content. E1381 is a stop-and-wait protocol that frames a record,
protects it with a **modulo-256 checksum**, and recovers from line errors by
**NAK + retransmit** — the exit-gate behaviour: *"captured frame validates + ACKs,
corrupted frame NAKs + retransmits"* (plan §2). E1394 record parsing (H→P→O→R→L)
is the next slice (S2.2 / LIS-24); normalizing a DiaSys result is S2.4 / LIS-26.

Facts that shape the decision:

- The harness is **dependency-free** (ADR-0004) and already models a framed
  transport — MLLP (ADR-0005) — behind a `Transport` interface, with fixtures as a
  language-neutral contract. ASTM is the second framed transport and slots into the
  same shape; `transport.py` already reserved the name for this slice.
- E1381 is more than framing: unlike MLLP (pure block framing), it is a **session**
  with establishment (`ENQ`/`ACK`), checksummed numbered frames with per-frame
  `ACK`/`NAK`, retransmission, and termination (`EOT`). The slice must model the
  session, not only the frame, to prove NAK + retransmit.
- A real session runs over RS-232; tests must not need a serial port.

## Decision

Add one dependency-free module + one fixture + the transport, test-first:

1. **`astm.py` — the E1381 codec + session.**
   - Control characters `ENQ/ACK/NAK/EOT/STX/ETX/ETB/CR/LF`; `MAX_FRAME_TEXT = 240`.
   - `checksum(covered)` — the sum of the `FN … ETX|ETB` bytes mod 256 as two
     uppercase hex digits.
   - `build_frame(fn, text, final)` → `STX FN text (ETX|ETB) C1 C2 CR LF`, frame
     numbers cycling 1-7 then 0; `parse_frame(frame)` → an `AstmFrame` that **raises**
     only on a structurally-incomplete frame and returns **`valid=False`** on a
     checksum/frame-number error (so the receiver NAKs rather than crashes).
   - `AstmReceiver` — the receiver half: `ENQ`→`ACK`, per-frame checksum +
     in-sequence frame-number check → `ACK`/`NAK`, idempotent re-`ACK` of a verbatim
     retransmit, `EOT` → done.
   - `run_session(records, corrupt=…, max_retries=6)` — drives a full sender→receiver
     session over a deterministic in-memory link and reports records transferred,
     NAKs, retransmits, and whether it aborted. A `corrupt(index, frame)` hook injects
     line noise on the wire to exercise NAK + retransmit deterministically.
2. **`AstmTransport`** (in `transport.py`) — frames a payload into E1381 frames on
   `send` and validates+reassembles them on `receive`, so a captured ASTM record
   survives the framing byte-for-byte (the replay round-trip); a checksum failure
   surfaces as a `TransportError`. Registered in the CLI so
   `edge-sim replay <fixture> --transport astm` works.
3. **Fixture `diasys-r920-astm-result`** — a synthetic DiaSys R920 E1394 record set
   (H→P→O→R→L, CR-separated) carried over E1381 framing; `protocol: astm-e1381`,
   `transport: serial-rs232`, `framing: astm` (all already in the fixture schema).

**Verifiable output (S2.1 exit):** `test_astm.py` proves a built frame validates
and is `ACK`ed, a corrupted frame is `NAK`ed, a full session transfers every record,
a transiently-corrupted frame is **NAKed then retransmitted to completion**, and a
persistently-corrupted frame **aborts after the retry limit**; `test_astm_transport.py`
proves the byte-faithful round-trip (incl. multi-frame) and the DiaSys fixture replay.

## Alternatives considered

- **An ASTM library (`astm`, `python-astm`).** Rejected: breaks the dependency-free
  contract (ADR-0004); E1381 is ~150 lines and the fixture-as-contract philosophy
  wants a transparent reference a future non-Python driver re-implements.
- **Frame-only, defer the session.** Rejected: the exit gate is specifically NAK +
  retransmit, which is session behaviour; a frame codec alone cannot demonstrate it.
- **Model the link as a real byte stream with a streaming de-framer** (like
  `MllpDecoder`). Deferred: E1381 is stop-and-wait at the PDU level (one frame, one
  `ACK`/`NAK`), so a PDU-level session over an in-memory link captures the protocol
  faithfully and keeps the slice focused; a streaming de-framer can follow if a real
  serial channel needs partial-read handling.
- **Put record (E1394) parsing in this slice.** Rejected: S2.1 is explicitly the
  E1381 *codec*; H→P→O→R→L parsing is S2.2 (LIS-24). Keeping them separate matches
  the HL7 split (MLLP framing S1.1 vs ORU parsing S1.2).

## Consequences

- **Positive:** the ASTM fleet now has a tested link layer (framing + checksum +
  ACK/NAK/retransmit) behind the same `Transport`/fixture contract as MLLP; the
  DiaSys fixture replays byte-faithfully; the session model makes error recovery a
  first-class, unit-tested behaviour, not an integration afterthought.
- **Costs / deferred (flagged for review):**
  - **No E1394 record parsing** — the framed payload is opaque bytes until S2.2
    (LIS-24); `AstmReceiver.records` are raw record strings.
  - **PDU-level session, not a byte-stream de-framer** — a real RS-232 channel that
    delivers partial reads needs a streaming frame assembler; deferred until a live
    serial transport lands.
  - **No ENQ/ENQ contention handling** — a single-initiator session is modelled;
    bidirectional contention (both ends raise `ENQ`) is a later concern (S2.5 query).
  - **Built-in retry limit (6)** and no timeouts — timeouts/inter-character timing
    belong to the live serial channel, not the codec.
  - The synthetic fixture is `synthetic: true`; a real DiaSys R920 ASTM-HOST capture
    replaces it in LIS-30 (bench conformance).
