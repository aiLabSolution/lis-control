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

## LIS-273 addendum — outbound HIS delivery queue (2026-07-22)

This addendum is deliberately narrower than the inbound raw-message archive
decision below. It records the retention and deployment gate for the separate
outbound HIS store-and-forward queue (`his_result_queue`); it does **not** make
that queue an archive, expand this ADR's inbound scope, or change this ADR from
**Proposed**. Independent QA/regulatory sign-off is still required before this
ADR can be Accepted.

For the outbound queue, LIS-273 adopts these technical defaults:

- A PENDING ORU is retained conditionally until the HIS returns a matching
  `MSA-1=AA`; age alone must never remove bytes still required for retry.
- After AA, the deployed full-message retention window is 0 ms. The delivered
  row's full ORU is redacted while the minimum metadata/fingerprint needed for
  MSH-10 duplicate and collision handling remains. Any nonzero window requires
  attributable site DPO and QA approval.
- Owner-only queue storage (0700/0600 where POSIX permissions are available),
  SQLite `secure_delete`, and WAL truncation are defense-in-depth controls over
  the active database. They are best-effort logical storage disposal, not
  cryptographic erase; backups, snapshots, filesystem recovery, and renamed
  corrupt copies remain governed by the site's separate lifecycle.
- The queue remains patient-linked after body redaction: control IDs and
  fingerprints are pseudonymous, not anonymous. Their retention duration is a
  site decision recorded in `docs/compliance/npc/retention.md`.

**HIS outbound gate.** Before patient results may use the outbound endpoint,
the site must approve the queue retention entry, place the queue on encrypted
host/volume storage, restrict access, enable TLS, and replace default
credentials. The current MAGLUMI X3 site has no OpenELIS-to-bridge HIS outbound
caller, so this addendum records a prerequisite rather than authorizing current
traffic.

This addendum closes neither the inbound archive's all-transport scope nor its
retention, encryption, access-audit, and QA-sign-off residuals. Those continue
to block an Accepted disposition for ADR-0022.

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
