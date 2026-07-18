# ADR-0022 — Production inbound raw-message archive (edge bridge)

- **Status:** Proposed (QA/regulatory sign-off pending — PHI retention/access scope)
- **Date:** 2026-07-15 (owner-approved); filed 2026-07-18
- **Deciders:** Marloe Uy (System/technical owner — proposer); Artis Lindy Pinote (QA/regulatory owner — PHI retention/access/audit sign-off required before Accepted, ADR-0007)
- **Scope:** `edge/drivers` (Java bridge). Companion to ADR-0012 (the content-addressed archive primitive, `edge/sim`).
- **Relates to:** ADR-0012 (raw-message archive + deterministic replay — Proposed, edge/sim-only; this ADR promotes its content-addressed contract into the production bridge); ADR-0015 (edge transport substrate — the inbound pipeline this archives); ADR-0018 (accession/identity — the digest-keyed idempotency this feeds); the Lifotronic H9 driver (first analyzer that structurally requires it).
- **Provenance:** drafted 2026-07-15 as `adr-DRAFT-0021` (H9 design session, `thoughts/plans/`); renumbered 0021→0022 at filing because 0021 was taken by the Accepted pinned-source-images ADR (collision rule: an Accepted ADR keeps its number).

## Context

ADR-0012 defined a durable, **content-addressed, append-only, tamper-evident** `RawMessageArchive`
(SHA-256 key, immutable entries, `ArchiveIntegrityError` on reload mismatch) — but it is **Proposed**
and scoped to the **`edge/sim` Python harness**. The production Java bridge durably persists only
**outbound-side and transport-bookkeeping** state — rejected outbound bundles (SQLite
`rejected_bundles`), the outbound HIS delivery queue (`his_result_queue`, LIS-45 — itself
PHI-bearing), and file-transport ingest state — but **no inbound raw-message archive**: nothing
retains the exact wire bytes an accepted result came from (verified against the pinned
`edge/drivers@9292566`; KB §14.7).

The Lifotronic H9 is the first analyzer that structurally **requires** a production inbound archive:

- Its payload is **positional binary** (`0x00`–`0x03` blood-type/error codes; ETX-collision risk) —
  the authoritative record must be the **exact bytes**, captured **before** any decode/parse.
- It carries **no message-control ID and no lifecycle status**; manual `Send Lis Data` can duplicate
  a result. De-duplication and changed-resend detection depend on a **raw-frame SHA-256 digest**.
- ISO 15189 evidence: the wire bytes behind a released HbA1c result must be retained, integrity-
  verifiable, and **deterministically replayable** to reproduce the normalized result.

ADR-0012 explicitly deferred **retention/GC** ("a real deployment concern, not a harness one"),
**per-receipt provenance metadata**, and **concurrent-writer durability / remote storage**.
**Encryption and access control it never addressed at all** — a sim-scoped harness holds no PHI at
rest; a production archive does, which is precisely the scope of the pending QA/regulatory sign-off.

## Decision

Implement a production **inbound** raw-byte archive in the bridge, reusing ADR-0012's
`archive()`/`load()` content-addressed contract and adding the production concerns it deferred
(retention, provenance metadata, writer durability) or never addressed (encryption, access
control):

1. **Capture exact inbound bytes before decode/parse**, keyed by **SHA-256** (idempotent; a digest
   both names and verifies its message). Immutable — first archival's provenance wins.
2. **Atomic, durable write** (write→flush→fsync before any downstream acknowledgement) with a
   **provenance sidecar**: analyzer/source id, receive time (monotonic + wall clock), firmware,
   port settings, parser/config version, content classification (patient/QC/calibration/malformed),
   and the downstream FHIR-bundle-or-rejection correlation.
3. **Encryption at rest**, a documented **retention/deletion policy**, least-privilege access, and
   **access auditing**. Raw patient payloads must **never** appear in application logs or metric
   labels.
4. **Deterministic replay is dry-run/compare by default.** Any clinical **re-drive** must be
   **explicitly authorized** and must go through OpenELIS idempotency/correction safeguards
   (ADR-0018 fail-visible staging dedup).
5. **`ArchiveIntegrityError` on reload mismatch** — corruption/tamper is evident, never silently
   trusted (inherited from ADR-0012).
6. **Applies to all inbound transports**, H9 first. FILE already pre-parses (its "raw" is the source
   file bytes); socket transports (SERIAL/MLLP/ASTM-TCP/HTTP) archive the wire frame.

## Consequences

**Positive.** The bridge retains the exact wire bytes behind every result, content-addressed and
tamper-evident (ISO 15189); manual-resend de-dup and changed-resend detection have a stable digest;
a result is reproducible from its evidence on demand; rejection/parse errors link back to the exact
raw digest.

**Costs / residual (flagged, not silent).**
- Storage growth + encryption/key-management + a real **retention policy** are deployment decisions
  requiring QA/regulatory sign-off (why this ADR is Proposed until Pinote signs).
- Concurrent-writer durability and remote/object storage arrive with the production substrate (the
  filesystem content-store is the portable stand-in behind the same contract, per ADR-0012).
- A timestamp-less analyzer emitting byte-identical records on different runs is indistinguishable
  from a re-transmission in principle (same digest) — mitigated analyzer-side (ADR-0018 residual).

## Alternatives considered

- **Keep archiving only rejected bundles.** Rejected — loses the inbound evidence, replay, and
  digest-dedup the H9 needs; rejection capture is a different concern.
- **Append-only receipt log instead of content-addressed store.** Rejected — content addressing
  gives idempotency + a verifiable raw↔digest identity + replay keying for free (ADR-0012 §Alt).
- **Put the archive in core.** Rejected — raw *wire* capture is an edge concern (core keeps the
  normalized result + version spine; the two are bound by the digest — ADR-0012 §Alt).
- **Amend ADR-0012 in place.** Rejected — ADR-0012 is a Proposed, sim-scoped record; the production
  PHI/retention/encryption scope is a genuine expansion that warrants its own sign-off and trace.
