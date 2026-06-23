# Compliance scaffold (`docs/compliance/`)

System-wide compliance & quality artifacts for the LabSolution LIS programme. This folder is
the **Stage-0 deliverable of [LIS-10 / S0.8 "Compliance scaffold"]** — the Compliance/QA
(workstream D) foundation that lets every later stage validate *deltas on a known base*
rather than one unauditable leap at go-live. It lives in the umbrella repo because compliance
is system-wide (ADR-0001), not specific to any one submodule.

**Start here:** [`LIS-10-preparation-brief.md`](LIS-10-preparation-brief.md) — plain-language
explanation of what LIS-10 is, what's drafted, and what needs a human decision.

## Contents

| File | What it is | Status |
|---|---|---|
| [`LIS-10-preparation-brief.md`](LIS-10-preparation-brief.md) | Plain-language brief + how to close LIS-10 | Drafted |
| [`validation-master-plan-outline.md`](validation-master-plan-outline.md) | **VMP** — ISO 15189:2022 / IQ-OQ-PQ validation plan (outline) | Drafted, pending review |
| [`npc-registration-checklist.md`](npc-registration-checklist.md) | **NPC checklist** — RA 10173 / NPC Circular 2022-04 registration & data-privacy checklist | Drafted, pending review |
| [`threat-model.md`](threat-model.md) | **Threat model** — STRIDE over the LIS reference architecture | Drafted, pending review |
| [`traceability-matrix.md`](traceability-matrix.md) | **Traceability matrix (seed)** — requirement → verification → evidence; the authoritative `REQ-*` registry | Drafted, pending review |
| [`decisions-register.md`](decisions-register.md) | **26 deferred decisions** (HITL), ranked by what they block | Open — for the human |
| [`reading-list.md`](reading-list.md) | Primary sources to read before deciding | Reference |

The four core artifacts (VMP, NPC, threat model, matrix) are the literal deliverables named
in the LIS-10 title; the brief, registers, and this index are the preparation wrapper.

## How these relate

- The **traceability matrix is the spine** — it owns the canonical `REQ-*` IDs. The VMP, NPC
  checklist, and threat model all reference those IDs; they don't restate requirements.
- The **VMP** is the *plan to validate*; the **matrix** is *what gets validated*; the
  **threat model** supplies the *security requirements* the matrix tracks; the **NPC
  checklist** supplies the *privacy requirements*.
- Every document separates `[DRAFTED]` (agent-drafted, ready to review) from `[NEEDS-HUMAN]`
  (needs a decision, appointment, signature, or filing). The consolidated `[NEEDS-HUMAN]`
  items are deduplicated in [`decisions-register.md`](decisions-register.md).

## File-layout convention (DEC-25 default)

To keep the matrix's evidence cells pointing at real paths, this layout is the chosen
default (pending ratification — see DEC-25 in the register):

- **Core artifacts** — flat in `docs/compliance/` (the table above).
- **NPC filing pack** (created later, mostly Stage 5) — under `docs/compliance/npc/`:
  `ropa.md`, `pia.md`, `breach-runbook.md`, `retention.md`, `lawful-basis.md`.

## Published to Plane

These docs are mirrored to **Plane project pages** (LIS project) for in-tracker reading —
titled `LIS-10 · N · …`. **This repo is the source of truth.** When a doc here changes,
update the matching Plane page; the file↔page-ID mapping and sync procedure (and the Plane
API's create/read-only limitation for pages) are in
[`../agents/compliance-pages.md`](../agents/compliance-pages.md). `README.md` is not mirrored.

## Provenance

Drafted 2026-06-23 from `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` (§5, §10, §13) and
`LIS_IMPLEMENTATION_PLAN.md` (§1, Stage 0/5 gates), via a parallel draft → 3-lens adversarial
review (regulatory accuracy · cross-document consistency · completeness/HITL) → reconcile
workflow. Grounded only in the fact-checked research, so regulatory citations are not
invented; unverified specifics are marked *"(confirm exact clause)"*. **Pending human
review** — not approved, not filed, not signed.
