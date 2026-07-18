# ADR-0012 — Raw-message archive + deterministic replay round-trip (edge)

- **Status:** Proposed (pending review — LIS-16 / S1.4)
- **Date:** 2026-06-28
- **Deciders:** Marloe Uy (aiLabSolution)
- **Scope:** `edge/sim` (the umbrella-side analyzer harness; CONTEXT-MAP marks the `edge/drivers` submodule "planned")
- **Relates to:** ADR-0004 (analyzer simulator harness + conformance fixtures, LIS-9 — the `replay()` byte-round-trip primitive this extends); ADR-0005 (MLLP framing, LIS-13); ADR-0011 (tolerant ORU^R01 parse + LOINC/UCUM normalization, LIS-14 — the pipeline this re-derives a Result through); core ADR-0001 (result raw+normalized shape + append-only `result_version`, LIS-7 / S0.5 — the persistence analog); core ADR-0003 (result ingest contract, LIS-15 / S1.3 — the persistence seam); LIS-11 (Stage 1 PRD); plan §1 ("Normalization service … persist raw + normalized"; verification pyramid L2); forward to LIS-17 / S1.5 (milestone E2E — replay → ingest → Result + ACK on staging)
- **Promoted to production by:** ADR-0022 (production inbound raw-message archive) — carries this archive's content-addressed `archive()`/`load()` contract into the `edge/drivers` Java bridge, takes up the deployment concerns this ADR deferred (retention/GC, per-receipt provenance metadata, concurrent-writer durability), and adds the PHI-at-rest concerns a sim-scoped harness never had (encryption, access control, access audit)

## Context

S1.4 (LIS-16) is the **archive + deterministic-replay** step of Stage 1's "first
result through the pipe". The harness can already frame/de-frame a message
(S1.1), parse + normalize an `ORU^R01` to an in-memory normalized row (S1.2,
ADR-0011), and persist that row to the core append-only Result store (S1.3, core
ADR-0003). What is missing is the edge-side **evidence and reproducibility** layer:
keeping the *raw inbound bytes* that produced a Result, and proving a Result can be
re-derived from them deterministically. This is what makes the milestone E2E (S1.5)
a *replay* — and what the ISO 15189 evidence chain (plan §1) needs: the wire bytes
behind a result are retained, tamper-evident, and reproducible.

Facts that shape the decision (verified against the code/fixtures):

- The existing `replay.py` (ADR-0004) does a **byte-only** round-trip — `sent` vs
  `received` through a `Transport` — and its own docstring flags the extension:
  "once a parser/normalization service exists, `Fixture.expected` carries the
  asserted normalized Result for end-to-end checks." Those services now exist
  (S1.2), but nothing consumes `expected` yet.
- The fixture manifest schema already reserves the **`expected`** object for "the
  normalized LOINC/UCUM Result row"; `rayto-rac050-oru-r01` populates it with the
  four asserted observations — an assertion target with no checker.
- The parse + normalize pipeline (`oru.py` + `normalize.py`) is **pure** (no clock,
  no I/O, default `TerminologyMap` seed), so the same bytes always yield the same
  normalized rows — determinism is available, just not asserted or fingerprinted.
- Core S0.5 keeps `result.raw_*` **beside** `result.loinc`/`ucum_value` and an
  append-only, immutable `result_version` spine. The edge has no equivalent record
  of the *raw message* a result came from; fixtures are checked-in test data, not a
  runtime capture store.
- The harness is **dependency-free** by the ADR-0004 principle (fixtures are a
  language-neutral contract; the harness stays a thin, portable reference), so the
  archive must use only the stdlib (`hashlib`, `json`, filesystem).

## Decision

Add one module and extend the replay engine, all under `edge/sim`, test-first, with
no new dependency:

1. **`archive.py` — `RawMessageArchive`.** A durable, **content-addressed**,
   append-only store of raw inbound messages kept *exactly as received* (application
   payload, pre-parse). The archive key is the **SHA-256** of the bytes, so archival
   is idempotent (identical message → same entry) and a digest both names and
   verifies its message. Entries are **immutable** (first archival's provenance
   wins) — the edge analog of the core append-only spine. `load()` re-hashes the
   stored bytes and raises **`ArchiveIntegrityError`** on a mismatch, so corruption
   or tamper is evident rather than silently trusted. Filesystem-backed
   (`<digest>.msg` + a `<digest>.json` provenance sidecar, sharded by prefix, atomic
   writes); a production archive swaps the directory for object storage, contract
   unchanged. `archive_fixture()` carries a conformance fixture's manifest
   provenance into the archive.

2. **Deterministic replay round-trip — extend `replay.py`.** Keep `replay()` (byte
   round-trip) and add the pipeline level:
   - **`replay_normalized(bytes, transport)` → `NormalizedReplay`** — wire
     round-trip, then parse + normalize the *received* `ORU^R01` to a normalized
     Result, fingerprinted by a reproducible **`result_digest`** (canonical SHA-256
     over the rows). The pure pipeline makes the same source bytes always re-derive
     the same `result_digest` — the operational definition of "deterministic".
   - **`replay_from_archive(archive, digest, transport)`** — reload the
     integrity-checked source bytes and re-derive the Result: *reproduce a Result
     from its evidence*. A tampered blob surfaces as `ArchiveIntegrityError`.
   - **`deterministic_round_trip(fixture, transport, archive=…)`** — the full
     vertical: capture → archive → reload → wire round-trip → parse → normalize.
   - **`check_against_expected(replay, expected)`** — assert the normalized Result
     equals the manifest's asserted `expected` rows (message_type / patient /
     specimen / observations), closing the loop the `expected` block was placed for.

3. **CLI — `edge-sim archive` + `edge-sim roundtrip`.** `archive` stores a fixture's
   message and prints its digest; `roundtrip` runs the full deterministic round-trip
   and prints the src/result digests, the normalized rows, and an `expected`
   OK/MISMATCH verdict (exit 1 on a wire or expected mismatch). The CLI's default
   scratch archive is `.edge-archive/` (gitignored; idempotent under content
   addressing).

**Verifiable output (S1.4 exit):** the new `pytest` suites prove — (a) the archive
round-trips raw bytes, is idempotent + immutable, and rejects a corrupted blob;
(b) `replay_normalized` is **deterministic** (identical `result_digest` across runs)
and content-bound (a changed byte changes the digest); (c) a fixture archived then
replayed *from the archive* re-derives a normalized Result that matches its
`expected` rows, over both loopback and real MLLP framing; and (d) archive integrity
failure propagates through replay. Full `edge/sim` suite green; CI runs it on every
change under `edge/sim/`.

## Alternatives considered

- **A receipt log (one append per receipt) instead of a content-addressed store.**
  Rejected for S1.4: content addressing gives idempotency, a verifiable raw↔digest
  identity, and deterministic replay keying for free; a duplicate-receipt count /
  ordered log is additive later if an analyzer's re-sends must be distinguished.
- **A database / WAL for the archive.** Rejected: violates the dependency-free
  harness principle and over-builds for a reference simulator. The filesystem
  content-store is a faithful, portable stand-in; production storage swaps in behind
  the same `archive()`/`load()` contract.
- **Parse the *sent* bytes rather than the *received* bytes.** Rejected: normalizing
  what actually came back off the wire makes the round-trip prove the transport
  *and* the pipeline on the same bytes; `round_trip_ok` separately attests the bytes
  were unchanged.
- **Put the archive in core (next to the Result store).** Rejected: the raw *wire*
  capture is an edge concern (the core ingest contract, ADR-0003, accepts an
  already-normalized row and cannot assume the edge's transport). Core keeps the
  normalized result + its version spine; the edge keeps the raw message evidence.
  The two are bound by the digest.

## Consequences

- **Positive:** the edge retains the raw bytes behind every Result, content-addressed
  and tamper-evident (ISO 15189 evidence chain); a Result is reproducible from its
  source message and fingerprinted by a stable `result_digest`; the fixture
  `expected` block is finally a checked assertion; the milestone E2E (S1.5) now has
  its *replay* half — archive a captured message and re-drive it to a normalized
  Result on demand.
- **Costs / deferred (flagged for review):**
  - **No retention / GC policy** — the archive grows unbounded; pruning, retention
    windows, and an archive-size budget are deferred (a real deployment concern, not
    a harness one).
  - **No receipt metadata beyond the first archival** — re-sends of an identical
    message collapse to one entry; per-receipt timestamps/counters are deferred (see
    alternatives).
  - **`result_digest` covers the normalized rows only** — not patient/specimen
    identifiers; if later slices need a whole-Result fingerprint, widen the canonical
    form (versioned via the sidecar `v`).
  - **Single-process, local filesystem** — no concurrent-writer locking or remote
    store; both arrive with the production driver substrate (S1.0, undecided) behind
    the same contract.
  - **ORU-only pipeline** — `replay_normalized` assumes an `ORU^R01`; ASTM/other
    record replay-to-normalized is its own slice (the `archive` half is protocol-
    agnostic and already reusable).
