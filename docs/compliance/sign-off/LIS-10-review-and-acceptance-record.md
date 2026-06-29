# LIS-10 — Stage-0 Compliance Scaffold · Review & Acceptance Record

| | |
|---|---|
| **Document ID** | LIS-COMP-SIGNOFF-001 |
| **Version** | 1.0 — *draft for signature* |
| **Date prepared** | 2026-06-25 |
| **Status** | ☐ Pending signatures |
| **Programme** | LabSolution LIS — Stage 0, Workstream D (Compliance/QA) |
| **Slice** | **LIS-10 / S0.8** — "Compliance scaffold: VMP outline, NPC checklist, threat model, seeded traceability matrix" |
| **Source under review** | Branch `lis-10-compliance-scaffold` · GitHub PR #3 · pinned at the umbrella commit recorded at signature (ADR-0001) |

> **What this is.** This record evidences the **human review and acceptance** of the Stage-0
> compliance scaffold, consistent with ISO 15189:2022 document-control intent and the LIS-10
> definition of done. **Signing Section 7 closes LIS-10.**
>
> **What this is NOT.** It is **not** the signed IQ/OQ/PQ validation dossier (that is Stage 5),
> **not** a regulatory filing, and **not** legal advice. The load-bearing legal characterisations
> in the artifacts remain subject to PH privacy/health-regulatory counsel confirmation (Section 4).

---

## 1. Purpose & scope of review

LIS-10 stands up the *skeleton* of the LabSolution LIS compliance story so that every later stage
validates small, auditable deltas on a known-good base rather than one unauditable leap at go-live.
This record confirms that a named, accountable human has **reviewed the four core artifacts and the
supporting decision record**, and either **accepts** them as the Stage-0 baseline or returns them
with comments.

Acceptance here means: *the scaffold is a sound, internally-consistent Stage-0 foundation* — **not**
that the system is validated or that any filing is complete.

## 2. Documents under review

| # | Document | What it is | Review outcome |
|---|---|---|---|
| 1 | `validation-master-plan-outline.md` | **VMP** — ISO 15189:2022 IQ/OQ/PQ validation plan (outline) | ☐ Accepted ☐ Accepted w/ comments ☐ Rejected |
| 2 | `npc-registration-checklist.md` | **NPC checklist** — RA 10173 / NPC Circular 2022-04 registration + data-privacy | ☐ Accepted ☐ Accepted w/ comments ☐ Rejected |
| 3 | `threat-model.md` | **Threat model** — STRIDE over the LIS reference architecture | ☐ Accepted ☐ Accepted w/ comments ☐ Rejected |
| 4 | `traceability-matrix.md` | **Traceability matrix (seed)** — the authoritative `REQ-*` registry / dossier spine | ☐ Accepted ☐ Accepted w/ comments ☐ Rejected |
| 5 | `decisions-register.md` | **Decisions register** — the 26 HITL decisions, ranked by what they block | ☐ Accepted ☐ Accepted w/ comments ☐ Rejected |
| 6 | `responsibility-and-deployment.md` | **PIC/PIP responsibility split** + deployment-model compliance | ☐ Accepted ☐ Accepted w/ comments ☐ Rejected |

**Supporting (read for context, not separately accepted):** `LIS-10-preparation-brief.md` (start here),
`m3-sync-compliance-gate.md`, `reading-list.md`, and ADRs **0004** (topology), **0005** (regulatory
ownership), **0006** (interface engine / stack / fleet / license).

## 3. Leadership decisions ratified (taken 2026-06-25)

By signing, the reviewers confirm these decisions are taken and correctly recorded:

| Decision | Outcome | Record |
|---|---|---|
| **DEC-01** Regulatory ownership | Lab = PIC (all models); LabSolution (single legal entity) = neither-M1/PIP-M3; SaMD-if-triggered. Pinote = accountable QA/regulatory owner; Uy = system owner + validation lead | ADR-0007 |
| **DEC-02** DPO | **Kirsten Pinote** designated DPO (independence charter — LIS-COMP-SIGNOFF-002) | ADR-0007 |
| **DEC-07** Signatories | Uy (system owner + validation lead); Pinote (independent QA approver); pathologist per-customer | ADR-0007 |
| **DEC-08** analyzer-bridge license | **MPL-2.0** (+ Healthcare Disclaimer); HOLD-001 lifted; folds into REQ-LIC-01 | ADR-0008 |
| **DEC-04** Interface engine | Reuse `openelis-analyzer-bridge` | ADR-0008 |
| **DEC-05** Stack | Polyglot — Java validated *production* runtime (core + bridge); Python for the edge simulator + conformance harness (LIS-9) + tooling | ADR-0008 |
| **DEC-06** v1 fleet | **Pinned 2026-06-27 (SD1 added 2026-06-29):** v1 = EDAN H60S (anchor, HL7/MLLP) + H99S + RAYTO RT-7600 + Seamaty SD1 (HL7 v2.3.1/MLLP, upload-only); v1.1 = MAGLUMI X3 (ASTM/TCP + SnibeLis DPA); deferred = ERBA EC90 (serial) + HETO AU120 (incoming); confirms pending: RT-7600 format, H99S driver, AU120 | ADR-0008 |
| **DEC-03** Topology | M1 pilot / M3 post-pilot spoke / M2 parked | ADR-0006 |

## 4. Residual `[NEEDS-HUMAN]` items acknowledged

The reviewers acknowledge that the following remain open and are **tracked in
`decisions-register.md`**; they are **follow-on actions that do not block Stage-0 acceptance**, but
several **gate the Stage-5 signed dossier**:

- **Counsel confirmation** of the load-bearing legal calls — the M1 "neither PIC nor PIP" premise
  (NPC advisory-opinion route), the FDA SaMD classification, and verbatim NPC Circular 2023-06 /
  breach-window / ISO 15189 clause numbers (DEC-12/13/15/16/17/18/19/20/21/26).
- **Named-person paperwork** — DPO designation letter + independence charter (LIS-COMP-SIGNOFF-002);
  VMP signatures (VMP §13).
- **Consistency ratification** — the editorially-complete rows DEC-14/22/23/24/25 to be ratified by
  the DEC-01 owner.
- **DEC-06 fleet** — pin the exact pilot analyzer list once available test units are confirmed.

## 5. Reviewer checklist

- ☐ The four core artifacts are internally consistent and cross-referenced to the `REQ-*` registry.
- ☐ The decisions in Section 3 are correctly recorded in the ADRs and the register.
- ☐ The residual `[NEEDS-HUMAN]` items in Section 4 are understood and accepted as follow-on.
- ☐ No item that *blocks Stage-0* is left unaddressed (vs. items that block Stage 4/5, which may remain open).
- ☐ The scaffold is accepted as the Stage-0 compliance baseline for the LabSolution LIS programme.

## 6. Acceptance statement

> *"We, the undersigned, have reviewed the documents in Section 2 and confirm that the LabSolution
> LIS Stage-0 compliance scaffold is a sound and internally-consistent foundation. We accept it as
> the Stage-0 baseline (subject to the follow-on items in Section 4), and authorise the closure of
> LIS-10. This acceptance does not constitute validation, a regulatory filing, or legal advice."*

## 7. Signatures

| Role | Name | Basis of signature | Signature | Date |
|---|---|---|---|---|
| **System / technical owner** | Marloe Uy | Authoring + technical accuracy of the scaffold | ______________ | __________ |
| **QA / regulatory owner** (accountable; DEC-01) | Artis Lindy Pinote | Regulatory/QA acceptance of the scaffold + decisions | ______________ | __________ |
| **Data Protection Officer** | Kirsten Pinote | Privacy artifacts (NPC checklist, responsibility note) reviewed | ______________ | __________ |

## 8. Reviewer comments / conditions

> _(record any "Accepted with comments" conditions, scope limits, or required follow-ups here)_

<br>

---

*Prepared 2026-06-25 as part of the LIS-10 close-out. Pending signatures. Mirrors the source-of-truth
compliance scaffold under `docs/compliance/`; the exact umbrella commit (ADR-0001 IQ baseline) is to be
recorded against the signatures above. Not legal advice — counsel confirmation per Section 4 still applies.*
