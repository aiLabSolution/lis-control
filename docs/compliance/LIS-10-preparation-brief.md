# LIS-10 — Preparation Brief (plain language)

> Prepared 2026-06-23 for **LIS-10 / [S0.8] "Compliance scaffold"**; **revised 2026-06-24**
> for the deployment-topology decision. This is the human-facing wrapper for the compliance
> artifacts in this folder. It explains — in plain language — **what LIS-10 actually asks for,
> what has already been drafted, what still needs a human decision, and how to close the
> issue.** Nothing here needs to be read in order; jump to
> [§4 Decisions](#4-what-needs-you-the-decisions) if you only have five minutes.

> **⮕ TOPOLOGY DECISION (2026-06-24).** One of the four 🔴 blockers below — **DEC-03 (deployment
> topology)** — is now **decided** (recorded in [ADR-0006](../adr/0006-deployment-topology.md)):
> the **pilot runs fully on-site at each lab, with no sync (M1)**; a **central sync at our own
> on-prem server (M3)** is a **separate, later "spoke" built after the pilot**, behind a
> **compliance extra-work gate** ([`m3-sync-compliance-gate.md`](m3-sync-compliance-gate.md));
> **public cloud (M2) is not the path.** In plain terms: **the pilot no longer waits on any of
> the sync/central-server privacy paperwork** — for the pilot, each customer lab is the
> data-controller and registers its own system, and LabSolution (holding no patient data) carries
> almost no privacy duty. Two newer artifacts now sit alongside the original four:
> [`responsibility-and-deployment.md`](responsibility-and-deployment.md) (who's the regulated
> party, per model) and the M3 gate above.

---

## 1. What LIS-10 is, in one paragraph

LIS-10 is the **paperwork-and-safety foundation** for the LabSolution LIS. It sits in
**Stage 0 (Foundations)** — the stage that has to be solid *before* any analyzer is wired
up — and it belongs to the **Compliance/QA** workstream (labelled `D — Compliance/QA`).
Because the LIS will store patient data (names + lab results = "PHI"), Philippine law and
medical-lab quality standards apply from day one. LIS-10's job is to put the **skeleton of
that compliance story in place now**, so that every later stage can prove it is correct as
a *small change on a known-good base* rather than as one giant unauditable leap at the end.

The issue was filed as a **stub** — a title and nothing else. It is marked **high
priority**, **`ready-for-human`**, and **`HITL`** (human-in-the-loop) because finishing it
needs decisions only you and leadership can make. This preparation does **all the drafting
that doesn't need you**, and parks every real decision in a register you can work through
later.

## 2. The dense title, decoded

The title is *"Compliance scaffold: VMP outline, NPC checklist, threat model, seeded
traceability matrix."* That is four documents:

| Jargon in the title | What it actually means | File (drafted) |
|---|---|---|
| **VMP outline** | **Validation Master Plan** — the plan for *proving the software works correctly, provably*, to medical-lab quality standards (ISO 15189, the "IQ/OQ/PQ" testing ritual). This is the **outline**, not the full signed dossier (that is a Stage-5 deliverable). | [`validation-master-plan-outline.md`](validation-master-plan-outline.md) |
| **NPC checklist** | A practical to-do list for registering with the **National Privacy Commission** under the **Data Privacy Act (RA 10173)** — because you hold patient data. Covers appointing a privacy officer, breach procedures, retention, vendor agreements, and the actual online filing. | [`npc-registration-checklist.md`](npc-registration-checklist.md) |
| **Threat model** | A structured *"how could this be attacked or leak patient data, and what stops it"* analysis (STRIDE method), with every defense mapped to a requirement and a test. | [`threat-model.md`](threat-model.md) |
| **Seeded traceability matrix** | The master table: **every requirement → the test that proves it → the evidence**. "Seeded" = started now, grown until pilot. It becomes the **backbone of the validation dossier** and is the single authoritative list of requirement IDs (`REQ-*`) the other three docs refer to. | [`traceability-matrix.md`](traceability-matrix.md) |

Plus two registers and this brief, also produced as part of the prep:

| File | What it is |
|---|---|
| [`decisions-register.md`](decisions-register.md) | **26 decisions** — deduplicated across all artifacts, each with why it matters, the options, a recommendation, the owner, and what it blocks. **DEC-03 (topology) is now decided (ADR-0006); 25 remain parked.** Ranked 🔴 blocks-LIS-10 → 🟠 blocks-a-later-stage → 🟡 tidy-up-before-signing. |
| [`reading-list.md`](reading-list.md) | The **primary sources to read before deciding** (laws, the ISO standard, the NPC circular, the licence questions), grouped must-read vs reference, each mapped to the decision it informs. |
| `LIS-10-preparation-brief.md` | This document. |

## 3. What's already done (so you don't have to)

Everything that can be drafted from the research report and the plan **has been drafted**:

- A complete **VMP outline** with the validation strategy (validate the *known base* — the
  pinned OpenELIS fork — plus LabSolution's *deltas*, never a black box), the IQ/OQ/PQ
  lifecycle, how the six-level test pyramid feeds qualification, change control, and a
  stage-by-stage validation schedule.
- A full **NPC registration checklist** (sections A–J) — applicability, DPO, the NPCRS
  filing mechanics, RoPA/PIA, lawful basis + data-subject rights, security evidence, breach
  management, vendor agreements, retention, and a "re-confirm before filing" currency check.
- A **STRIDE threat model** over the whole architecture — assets, trust boundaries, actors,
  a threat-by-threat table with mitigations mapped to requirement IDs and test levels, the
  residual risks, and the minimum scope for the Stage-5 penetration test.
- A **seeded traceability matrix** — 30+ requirements (`REQ-*`) each mapped to a regulation,
  workstream, test level, the Stage-0 sibling issue that delivers it, and an evidence
  artifact; plus a Stage-0 exit-gate coverage table.

**How it was produced and checked.** The four artifacts were drafted in parallel, then run
through three adversarial review passes — **regulatory accuracy** (does any citation, date,
or threshold go beyond what the verified research established?), **cross-document
consistency** (do the requirement IDs and test levels line up across all four?), and
**completeness / human-in-the-loop separation** (is anything that needs a human invented
instead of flagged?) — and then reconciled. They are deliberately grounded only in your
already-fact-checked research, so they do **not** invent statute or clause numbers; wherever
a specific clause is needed but wasn't independently verified, the text says *"(confirm
exact clause)"* rather than guessing.

## 4. What needs you (the decisions)

The full list is in [`decisions-register.md`](decisions-register.md). The **🔴 ones that
actually block LIS-10 from being closed** are:

| # | Decision | Why it blocks | Maps to |
|---|---|---|---|
| **DEC-01** | **Who owns regulatory** — name the accountable owner for NPC registration + the ISO 15189 validation dossier (and how per-customer lab licensing is split). | This is *the* gate. Until there's a named owner, **no document can be signed**, no "Owner" cell can be filled, and the DPO can't report to anyone. | Research §13 **#5** |
| **DEC-02** | **Appoint a Data Protection Officer (DPO).** | A named person is legally required and the NPC filing needs their contact. Reports into DEC-01. | RA 10173 |
| ~~**DEC-03**~~ ✅ **DECIDED** | **Deployment topology** — ~~cloud-central vs on-prem~~. **Resolved ([ADR-0006](../adr/0006-deployment-topology.md)): M1 fully-onsite pilot → M3 own on-prem central-sync as a post-pilot spoke; M2 public cloud not selected.** | *No longer blocks LIS-10.* It also **decoupled the sync/PIP privacy paperwork from the pilot** (now the M3 extra-work gate). | Research §13 **#3** |
| **DEC-04** | **Build vs buy the instrument interface engine.** | Decides which codebase becomes a "validated object" and reopens the licence question (the `openelis-analyzer-bridge` has **no declared licence** — tracked as HOLD-001). | Research §13 **#6** |

There are also four **🟡 internal-consistency decisions** (DEC-22 → DEC-26) that the review
surfaced — small disagreements between the drafts (e.g. which test level "channel isolation"
is verified at). These don't block drafting; they just need ratifying before the matrix is
treated as the signed dossier's spine. I've already fixed the one purely-mechanical one
(file paths — see [§6](#6-housekeeping-already-handled)); the rest are genuine judgment
calls left for you.

> **Bottom line:** **DEC-03 (topology) is now decided** — the remaining hard blocker is
> **DEC-01 (regulatory ownership)**. Take that one plus DEC-02 (DPO) and DEC-04 (interface
> engine), and almost everything else unlocks.

## 5. How to actually close LIS-10

LIS-10's own exit gate (from the plan) is modest: *"Compliance artifacts (VMP outline + NPC
checklist) exist in-repo and are **reviewed**; traceability matrix is maintained."* So:

1. **Read the four artifacts** (≈30 min each, or skim — this brief is the map).
2. **Take the 🔴 decisions** in the register (DEC-01–DEC-08), at least to the "named owner"
   level. Record your choices in the register itself.
3. **Mark the four artifacts reviewed** (a comment on the Plane issue, or a sign-off line).
   That satisfies the Stage-0 gate — the scaffold *exists and is reviewed*.
4. The heavy execution — actually **filing with the NPC, signing the IQ/OQ/PQ dossier,
   running the pen-test, the breach tabletop** — is **Stage 5**, not now. LIS-10 only has to
   stand the scaffold up and get it reviewed.

Everything `[NEEDS-HUMAN]` in the artifacts is deferred work that is *correctly* deferred —
it needs a legal-entity fact, an appointment, a signature, or a filing that no agent can
produce. None of it blocks reviewing and accepting the scaffold.

## 6. Housekeeping already handled

- Created the `docs/compliance/` home and wrote all six artifacts + this brief there.
- Fixed broken internal cross-references and **standardised the file layout** (this
  pre-answers DEC-25 with a sensible default — ratify or override): the four core artifacts
  live flat in `docs/compliance/`; the future NPC *filing-pack* artifacts (RoPA, PIA, breach
  runbook, retention, lawful-basis) will live under `docs/compliance/npc/`.
- Posted a plain-language summary back onto the Plane issue (its description was empty) and
  added a comment linking these artifacts, so LIS-10 is no longer a stub.

---

*Source material: `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` (§5 data model, §10 regulatory
plan, §13 open decisions), `LIS_IMPLEMENTATION_PLAN.md` (§1 verification pyramid, Stage 0/5
exit gates), `docs/adr/0001-...`, and the `diagrams/06-regulatory-controls-map` /
`08-verification-pyramid` views.*
