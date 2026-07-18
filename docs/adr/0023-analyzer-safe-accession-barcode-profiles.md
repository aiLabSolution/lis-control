# ADR-0023 — Analyzer-safe accession / barcode format profiles

- **Status:** Proposed (validation-owner confirmation pending — no cross-specimen collision)
- **Date:** 2026-07-15 (owner-approved); filed 2026-07-18
- **Deciders:** Marloe Uy (System/technical owner — proposer, **decision made per owner delegation "you decide"**); Artis Lindy Pinote (validation owner — confirms no cross-specimen collision, ADR-0007)
- **Scope:** `core/openelis` (accession-format config) + `edge/drivers` (barcode correlation) + `deploy/kit` (analyzer profile).
- **Relates to:** ADR-0018 (deterministic accession minting for id-less specimens — the **distinct** concern this ADR does not reopen); ADR-0015 (edge substrate — the correlation path); ADR-0022 (production inbound raw archive — its companion H9 ADR); the Lifotronic H9 driver (upload-only, correlation-by-barcode, first consumer).
- **Provenance:** drafted 2026-07-15 as `adr-DRAFT-0022` (H9 design session, `thoughts/plans/`); renumbered 0022→0023 at filing after the pinned-source-images ADR took 0021 (collision rule: an Accepted ADR keeps its number).

## Context

Some analyzers **constrain the sample identifier** they emit. The Lifotronic H9 keeps only the
**first 15 characters** of a Sample ID and depicts it as numeric (KB §10.2). Its documented workflow
is **correlation-by-barcode** — there is no order-download — so the OpenELIS accession is **printed
as the tube barcode**, the H9 scans it locally, and the uploaded result carries that Sample SN. For
this to be safe the accession must **round-trip 1:1** as the scanned Sample SN.

This is a **different axis** from ADR-0018. ADR-0018 **mints** a 25-char deterministic accession for
**id-less** specimens; that mint is *too long* to print as an H9 barcode and is not what a
barcode-correlated analyzer needs. The gap ADR-0018 does not cover: constraining the accession
**format** so an analyzer with a length/charset limit can carry it back unchanged.

**Silent truncation is the hazard.** If an over-length accession were truncated to the analyzer's
limit, two distinct accessions could collapse to the same first-15 → the same wrong-patient /
cross-specimen failure ADR-0018 was written to prevent.

## Decision

**1. Define a per-analyzer "safe accession/barcode profile"** on the analyzer registry/deploy-kit
profile: allowed **charset**, **max length**, and **leading-zero preservation**. The **H9 profile**
= numeric, **≤15 digits**, leading zeros preserved end-to-end.

**2. Primary strategy — constrain the accession format so it *is* the barcode.** Configure the
site's OpenELIS accession format to satisfy the analyzer's safe profile, so the pre-created order's
accession is printed as the barcode and the scanned Sample SN equals it with **no indirection**.
This is the recommended default (single source of truth; simplest; leading zeros survive).

**3. Fallback — audited barcode-alias map (only if the site's mandated accession format cannot be
made safe).** A persistent, **one-to-one**, audited barcode↔accession map in OpenELIS with
**collision detection** and an audit trail. Used only where an externally-mandated accession format
is incompatible with the analyzer's safe profile.

**4. Silent truncation is prohibited.** An accession that exceeds the analyzer's safe length is a
**visible enrollment/config error** (rejected at order/barcode creation), never truncated.

**5. Interplay with ADR-0018 (unchanged).** On the normal H9 path the Sample SN is present, so
**no mint is used**. An H9 frame that arrives with **no** usable Sample SN (scan no-read + no manual
entry) legitimately falls to ADR-0018 minting → a 25-char minted accession that **quarantines
visibly** (it has no barcode to round-trip, and that path never did).

## Consequences

**Positive.** Deterministic 1:1 accession↔barcode round-trip; no cross-specimen collapse from
truncation; leading zeros preserved; the analyzer's identifier limit is honored by construction, not
by lossy trimming.

**Costs / residual (flagged).**
- The site must either **constrain its OE accession format** to the safe profile, or **maintain +
  audit an alias table** — a deployment choice, not free.
- Order/barcode creation must **reject** an over-safe-length accession (a new enrollment guard).
- Alphanumeric behavior and barcode symbology remain **bench unknowns** (KB §10.2–10.3); the profile
  stays numeric-≤15 until a bench test proves otherwise.

## Alternatives considered

- **Silent truncation to the analyzer limit.** Rejected — the exact collision/wrong-patient hazard
  ADR-0018 guards against.
- **Always use an alias map.** Rejected as the default — extra indirection and a split source of
  truth when the accession format can simply be constrained; kept as the fallback for
  format-incompatible sites.
- **Widen the H9 to accept >15 chars.** Rejected — the hardware keeps the first 15; not ours to change.
- **Amend ADR-0018.** Rejected — ADR-0018 is about minting-for-id-less; format-for-round-trip is a
  separate axis better traced as its own record.
