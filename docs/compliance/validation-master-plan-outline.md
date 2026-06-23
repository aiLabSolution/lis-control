# Validation Master Plan (VMP) — Outline

> **Stage-0 SCAFFOLD / OUTLINE.** This document is a Stage-0 Validation Master Plan *outline*, drafted by an agent for issue **LIS-10 / S0.8** ("Compliance scaffold"). It is **pending human review** and is not an executed validation dossier — the signed IQ/OQ/PQ dossier is a Stage-5 deliverable (REQ-VAL-01). Drafted **2026-06-23**. It establishes the validation skeleton so that every later stage validates *deltas on a known base*. Do not treat any item marked `[NEEDS-HUMAN]` as approved.

## Status legend

| Marker | Meaning |
|---|---|
| `[DRAFTED]` | Agent-drafted; ready for human review. |
| `[NEEDS-HUMAN]` | Requires a human decision, input, appointment, signature, or filing before it can be completed. |

Companion Stage-0 artifacts (LIS-10): the **NPC checklist** (privacy/RA 10173 controls), the **threat model** (security controls), and the **seeded traceability matrix** (`docs/compliance/traceability-matrix.*`), which is the authoritative registry of `REQ-*` IDs referenced throughout this VMP. Supporting diagrams already in-repo: `diagrams/06-regulatory-controls-map.png` and `diagrams/08-verification-pyramid.png`.

---

## 1. Purpose & scope `[DRAFTED]`

### 1.1 Purpose
This VMP defines **how the LabSolution LIS will be validated** as a regulated medical-laboratory computerized system. It states the validation strategy, lifecycle, deliverables, responsibilities, and acceptance approach so that, by Stage 5, LabSolution can produce a **written validation dossier with executed and signed IQ/OQ/PQ** (REQ-VAL-01) that withstands ISO 15189:2022 assessment and DOH/HFSRB licensing review.

### 1.2 Scope
**In scope** — the complete LabSolution LIS as a system that *creates, stores, normalizes, transmits, and releases* patient health information (PHI):

- the **forked OpenELIS Global 2 clinical core** (`core/openelis`, mounted per ADR-0001) — orders/requisitions, specimens, results, QC, reporting, RBAC, audit, data model;
- the **LabSolution-owned driver / interface engine** (`edge/drivers`, planned) speaking MLLP/HL7 and ASTM over serial/TCP at the analyzer edge;
- **ingest normalization** to LOINC/UCUM (LIS-8 / S0.6);
- the **FHIR R4** interoperability surface (Stage 4) to downstream EMR/HIS;
- **offline-first deployment** with store-and-forward and site↔central sync (Stage 4);
- the **analyzer simulator harness and conformance fixtures** (LIS-9 / S0.7) used as validation instruments.

**Out of scope (this document)** — privacy/data-protection controls (covered by the **NPC checklist** under RA 10173, cross-referenced where they are *validated controls*: REQ-PRIV-\*); the executed dossier itself; and per-customer lab-specific operational SOPs, which each licensed laboratory must author against its own RA 4688 license.

Because the LIS holds patient identifiers and results, the data it processes is **RA 10173 "sensitive personal information"**; this elevates the rigor of validation (record integrity, audit, access control) but the privacy *filing* obligations are tracked in the NPC checklist, not here. One privacy control is also a **validated engineering deliverable, not documentation-only**: **REQ-PRIV-04** (data-subject rights — access, correction, erasure, objection) carries an **L4 E2E verification** in the traceability matrix (a data-subject request resolves to access/correction expressed as an append-only Result `corrected` version per LIS-7). It is therefore tested through this VMP's qualification frame (OQ→PQ), with the matrix level (L4) authoritative; its policy/filing aspects remain in the NPC checklist.

---

## 2. Regulatory & standards basis `[DRAFTED]`

| Authority | Edition / instrument | Bearing on validation |
|---|---|---|
| **ISO 15189:2022** | LIVE edition. (The :2012 transition closed end-2025; **:2012 is retired**.) | Primary driver. Requires LIS validation (IQ/OQ/PQ), record control, equipment/result traceability, an immutable audit trail, and change control. Specific sub-clauses to be cited in the executed dossier *(confirm exact clause)*. |
| **RA 4688** (Clinical Laboratory Law) | — | The LIS must support **licensed-lab workflows** and **pathologist/physician result release**; validation must demonstrate the result-release workflow (Stage 5). |
| **DOH AO 2021-0037** (supersedes AO 2007-0027) | Current rules on regulation/licensing of clinical labs. | Governs the operating context the validated LIS must fit. **CURRENCY CAVEAT:** a draft amendment is in **HFSRB public consultation (not yet signed)** — `[NEEDS-HUMAN]` to track and re-confirm before go-live; validation acceptance criteria may shift if it is signed. |
| **RA 5527** (Medical Technology Act) | — | Defines medtech personnel scope ⇒ **named-user RBAC** mapped to medtech/pathologist roles (REQ-RBAC-01) is a validated control. |
| **RA 10173** (Data Privacy Act) + **NPC** | NPC Circular 2022-04 / NPCRS | Handled in the **NPC checklist**. Referenced here only where privacy controls are *validated* (e.g., access logging, retention/disposal, audit integrity, and data-subject rights as an L4 E2E test): REQ-PRIV-02/03/04. |
| **PNPAQC / EQAS** | — | External quality assessment ⇒ the QC engine (Westgard/Levey-Jennings, delta checks, autoverification gating — REQ-QMS-04) and proficiency-testing result handling are validated objects (Stage 5). |
| **OpenELIS (MPL-2.0) + analyzer-bridge license** | MPL-2.0 (file-level copyleft); analyzer-bridge license **"TBD"** | Two distinct, separately-tracked obligations: **REQ-LIC-01** = MPL-2.0 file-level obligations honored across the fork (LIS-3 inventory); **REQ-LIC-02** = the **openelis-analyzer-bridge** license confirmed before any reuse (**HOLD-001**, `[NEEDS-HUMAN]`). Which codebase ultimately *is* the validated interface engine depends on Open Decision #6 (build vs buy). |

This VMP does **not** invent clause numbers, thresholds, or dates beyond the above; any needed specific clause is flagged `(confirm exact clause)` and any missing fact is surfaced as a deferred decision.

---

## 3. Validation strategy — known base + deltas `[DRAFTED]`

### 3.1 The key idea: validate a known base, not a black box
The LabSolution LIS is **not** validated as an opaque whole. It is decomposed into:

1. a **KNOWN BASE** — the **pinned OpenELIS Global 2 fork** at a specific upstream tag/SHA (established by LIS-3 / S0.1), and
2. **LabSolution DELTAS** — the driver/interface engine, LOINC/UCUM normalization, FHIR R4 surface, offline sync, and any core modifications.

Validation effort concentrates on the **deltas** and on the **seams** between base and deltas (ingest normalization, channel isolation, result versioning). The known base carries forward its inherited behavior, re-confirmed by regression rather than re-validated from zero on every change. This is what makes the validation tractable and what every later stage relies on: **each stage validates the delta it introduces on top of an already-known base.**

### 3.2 Reproducibility = the pinned-submodule snapshot (REQ-VAL-02)
Per **ADR-0001**, one `lis-control` umbrella commit pins every component (the OpenELIS core and, later, `edge/drivers`, `plugins`, `deploy/kit`, `infra`) at exact SHAs. Therefore **one umbrella commit = one reproducible, pinned snapshot of the entire system**. That snapshot *is* the IQ/OQ/PQ spine: the IQ "what was installed" is answerable precisely (component SHAs), and any validated state can be reconstructed from a clean recursive checkout. Reproducible CI bootstrap to a 200 health check (LIS-4 / S0.2) is the executable evidence for REQ-VAL-02.

### 3.3 Risk-based approach `[DRAFTED]`
Validation depth scales with patient-safety and data-integrity risk. Indicative risk tiers (to be ratified by the QA/regulatory owner):

- **High** — anything that can corrupt, lose, or misattribute a result: ingest normalization (LIS-8), result store + versioning (LIS-7), append-only audit (LIS-6), RBAC + result release (LIS-5, RA 4688), offline sync reconciliation (Stage 4, **no last-writer-wins**), QC/autoverification gating (Stage 5, REQ-QMS-04).
- **Medium** — channel isolation (a bad driver must not corrupt the core, REQ-SEC-03), FHIR R4 export fidelity, encryption in transit/at rest (REQ-SEC-01/02).
- **Lower** — UI cosmetics, non-PHI reporting layout.

Formal risk classification (FMEA or equivalent) is `[NEEDS-HUMAN]` — it requires the appointed QA/regulatory owner (see §5 and Decision #5).

---

## 4. System description & GxP / risk classification `[DRAFTED]`

### 4.1 Reference architecture (validated dataflow)
```
Analyzer (physical) → [edge driver: MLLP/HL7, ASTM serial/TCP]
        → Interface engine (channel-isolated, SEPARATE from core)
        → Ingest normalization (raw_value/raw_unit/raw_code → LOINC + UCUM)
        → OpenELIS core (Patient → Order → Specimen → Result; RBAC + append-only audit cross-cutting)
        → FHIR R4 surface → downstream EMR/HIS
        ⇅ Offline sync (store-and-forward; append-only result versions + explicit reconciliation)
```
See `diagrams/01-reference-architecture.png` and the controls overlay `diagrams/06-regulatory-controls-map.png`.

### 4.2 Validated data objects (PHI-bearing)
`Patient → Order/Requisition → Specimen/Sample → Result` (entity-relationship view: `diagrams/07-er-data-model.png`, the same ER basis used by the NPC checklist §D and the traceability matrix). **Result** is the highest-risk object: it stores `raw_value`, `raw_unit`, `raw_code`, `loinc`, `ucum_value`, `status` (preliminary/final/corrected), `verified_by`, `instrument_id`, `flags`, with **append-only versions** (LIS-7). `Instrument → InterfaceChannel`, `QCResult → Westgard/Levey-Jennings`, `User → Role`, and **every mutation writes an append-only `AuditEvent`** (LIS-6).

### 4.3 Classification approach `[DRAFTED]`
The LIS is a **configurable, customized application** in CSV terms: a configurable open-source base (OpenELIS) plus **bespoke development** (drivers, normalization, sync). It is therefore treated at the higher-rigor end — bespoke components get full lifecycle qualification; configured-only behavior of the base gets configuration verification plus regression. The formal category label and its mapping to validation depth is `[NEEDS-HUMAN]` (QA/regulatory owner to ratify). Note: the bespoke-vs-configured boundary for the **interface engine** is not yet fixed — it depends on Open Decision #6 (build bespoke drivers vs adopt an Open Integration Engine), which changes which codebase is a validated object (see §13).

---

## 5. Roles & responsibilities `[DRAFTED]` / `[NEEDS-HUMAN]`

| Role | Responsibility in validation | Status |
|---|---|---|
| **System owner** | Owns the LIS as a product; accountable that a validated system is deployed. | `[NEEDS-HUMAN]` — name to be assigned. |
| **Validation lead** | Authors/executes URS→FRS→DQ→IQ→OQ→PQ; maintains the traceability matrix as the spine. | `[NEEDS-HUMAN]` — assign. |
| **QA / regulatory owner** | Owns ISO 15189 conformance, risk classification, deviation disposition, change-control approval, and the link to DOH/HFSRB licensing and NPC registration. | `[NEEDS-HUMAN]` — **this is the blocking gap.** |
| **Pathologist approver** | Approves the result-release workflow (RA 4688) and signs PQ for clinical use. | `[NEEDS-HUMAN]` — named pathologist required. |
| **Lab director / medtech reviewers (per site)** | Per RA 4688 / RA 5527, validate workflows under the site's own license. | `[NEEDS-HUMAN]` — per customer. |

> **OPEN DECISION #5 (Regulatory ownership) — `[NEEDS-HUMAN]`, BLOCKING.** Who owns NPC registration, the ISO 15189 validation dossier, and per-customer lab-licensing alignment is undecided. **LIS-10 cannot be fully executed until this is resolved**, because almost every signature line in this VMP and the NPC checklist needs a named, accountable owner. This VMP can be *drafted* without it; it cannot be *approved* without it.

---

## 6. Validation lifecycle & deliverables `[DRAFTED]`

| Phase | Produces | Acceptance criteria (outline) |
|---|---|---|
| **URS** — User Requirement Spec | The `REQ-*` registry (seeded in the traceability matrix) restated as user-facing requirements: PHI handling, RBAC, audit, normalization, result release, offline resilience, security. | Every `REQ-*` traceable to a stated user need; reviewed. |
| **FRS** — Functional Requirement Spec | How OpenELIS-base + LabSolution deltas satisfy each URS item (functional behavior, interfaces, data model). | Each URS item maps to ≥1 functional requirement. |
| **DQ** — Design Qualification | Confirmation that the reference architecture (§4.1), channel isolation (REQ-SEC-03), append-only result versioning (REQ-DATA-01), and no-LWW reconciliation (REQ-RES-02) are designed to meet the FRS. | Design review signed; ADRs referenced. |
| **IQ** — Installation Qualification | Evidence the system is installed as specified: **the pinned umbrella SHA + component SHAs** (REQ-VAL-02), environment, TLS/at-rest config, seeded LOINC/UCUM tables (LIS-8). | Recursive checkout reproduces the snapshot; CI green to a 200 health check (LIS-4). |
| **OQ** — Operational Qualification | Evidence each function operates per FRS: RBAC denials (403, LIS-5), audit append-only + DB-layer mutation failure (LIS-6), driver vs simulated analyzer (LIS-9), end-to-end vendor-code → Result normalization (LIS-8), data-subject-rights request → access/correction via append-only `corrected` Result version (REQ-PRIV-04, L4). | All in-scope `REQ-*` functional tests pass with recorded evidence. |
| **PQ** — Performance Qualification | Evidence the system performs in the real workflow: pathologist result release (RA 4688), **QC engine + autoverification gating (Westgard multirules, Levey-Jennings, delta checks — REQ-QMS-04)**, resilience under WAN outage / edge restart / sync conflict with **zero data loss** (REQ-RES-01). | Acceptance per documented PQ protocol; pathologist sign-off `[NEEDS-HUMAN]`. |

Each phase's protocol, executed record, and sign-off are themselves controlled records (§11). In Stage 0 only the **templates/outlines** of these deliverables are produced; execution is staged (§12).

---

## 7. Mapping the six-level verification pyramid onto IQ/OQ/PQ `[DRAFTED]`

The six-level test pyramid (`diagrams/08-verification-pyramid.png`, plan §1) is the *engineering* test strategy; IQ/OQ/PQ is the *regulatory* qualification frame. They are not parallel tracks — the pyramid **feeds** qualification:

| Pyramid level | What it verifies | Feeds |
|---|---|---|
| **L1 Unit** | Parsers / codecs / mapping logic (HL7/ASTM decode, LOINC/UCUM mapping). | **OQ** |
| **L2 Component** | Driver vs **simulated analyzer** (LIS-9 harness). | **OQ** |
| **L3 Bench conformance** | A *physical* unit speaks as documented; **signed per-unit report** (REQ-CONF-01). | **OQ → PQ** |
| **L4 Integration E2E** | Instrument message → normalized Result → **FHIR R4** resource; **data-subject request → access/correction (REQ-PRIV-04)**. | **OQ → PQ** |
| **L5 Resilience / chaos** | WAN outage, edge restart, sync conflict; **no data loss** (REQ-RES-01/02). | **PQ** |
| **L6 Validation / regulatory** | requirement → test → evidence; the **ISO 15189 IQ/OQ/PQ dossier, signed**. | **= the dossier (REQ-VAL-01)** |

So: **L1–L2 and L4 form the bulk of OQ; L3 and L4 also feed PQ; L5 is PQ; L6 *is* the dossier** that this VMP plans toward. IQ stands slightly apart — it is satisfied primarily by the pinned-snapshot reproducibility (REQ-VAL-02) plus configuration/install evidence.

---

## 8. Traceability matrix as the spine `[DRAFTED]`

The **traceability matrix** (companion LIS-10 artifact, `docs/compliance/traceability-matrix.*`) is the authoritative `REQ-*` registry and the spine of the entire validation effort. It maps, for each requirement: **requirement → design (DQ) → test (pyramid level / OQ-PQ protocol) → evidence (CI run, signed report, dossier section)**.

- It is **maintained from Stage 0** (seeded now with the Stage-0 sibling issues as evidence rows) and grows through Stage 5, where it becomes the index of the signed dossier.
- Stage-0 evidence rows link to the verifiable outputs of: LIS-3 (**MPL-2.0 file-level inventory → REQ-LIC-01**; analyzer-bridge license confirmation is tracked separately as **HOLD-001 → REQ-LIC-02**, `[NEEDS-HUMAN]`), LIS-4 (reproducible bootstrap → REQ-VAL-02), LIS-5 (RBAC 403 → REQ-RBAC-01), LIS-6 (append-only audit → REQ-AUD-01), LIS-7 (raw+normalized result store → REQ-DATA-01), LIS-8 (LOINC/UCUM end-to-end → REQ-DATA-02/REQ-QMS-02), LIS-9 (simulator harness → L2/L3 instrument).
- Any new requirement uses the **same prefixes** (`REQ-PRIV/RBAC/AUD/SEC/VAL/QMS/DATA/RES/CONF/LIC-*`) and is registered in the matrix, not invented ad hoc in prose.

This VMP defers the authoritative requirement list to the matrix to avoid drift between artifacts.

---

## 9. Change control & revalidation `[DRAFTED]`

Because the LIS is "known base + deltas," change control is the mechanism that keeps the *known base* known (REQ-QMS-03).

- **Upstream OpenELIS merges** — pulling `upstream/develop` into the fork changes the base. Each merge: re-pin the submodule SHA in `lis-control` (new validated snapshot), run the full regression suite (L1–L4), and assess impact on high-risk seams (normalization, audit, result versioning). Only a passing snapshot is promoted.
- **Per-analyzer channels** — adding/altering a driver channel is a *delta* requiring its own L2 component tests and an L3 **signed bench-conformance report** before the analyzer is marked "supported" (REQ-CONF-01). Channel isolation (REQ-SEC-03) bounds blast radius so one driver change does not force whole-system revalidation. **The shape of this delta depends on Open Decision #6 (build bespoke vs adopt an integration engine):** a bought engine changes the L1/L2 surface and reopens the license question (REQ-LIC-01/02, HOLD-001) — see §13.
- **Configuration changes** — RBAC role maps, LOINC/UCUM table seeds, reference ranges, QC rules (REQ-QMS-04): versioned, reviewed, and regression-tested; high-risk configs (mappings, QC gating) get targeted OQ re-execution.
- **Revalidation triggers** — to be enumerated by the QA/regulatory owner; at minimum: base version change, new analyzer channel, data-model change to PHI objects, sync/reconciliation logic change, security control change, or a signed DOH AO 2021-0037 amendment. Trigger thresholds are `[NEEDS-HUMAN]`.

---

## 10. Deviation / nonconformance management `[DRAFTED]`

Any failed acceptance criterion, unexpected behavior, or as-found discrepancy during qualification is logged as a **deviation** with: description, risk impact (patient safety / data integrity), affected `REQ-*` and pyramid level, root cause, corrective action, and disposition (accept / fix-and-retest / scope-out with justification). Deviations are linked from the traceability matrix evidence cell so the dossier shows not just passes but how failures were resolved. Disposition authority sits with the **QA/regulatory owner** — `[NEEDS-HUMAN]`. The deviation log is a controlled record (§11).

---

## 11. Document & record control `[DRAFTED]`

Per ISO 15189:2022 record control (REQ-QMS-01) and change control (REQ-QMS-03):

- **Versioning** — all validation artifacts (this VMP, protocols, executed records, the matrix) are version-controlled. System-wide compliance artifacts live in the umbrella under `docs/compliance/`; their *state* is bound to the pinned umbrella commit, so "which document version validated which system version" is answerable by commit.
- **Signatures** — protocols and executed qualifications require author + reviewer + approver sign-off. Electronic-signature mechanism and whether wet-ink is required for DOH/HFSRB submission is `[NEEDS-HUMAN]` *(confirm exact clause)*.
- **Retention & secure disposal** — validation records and the PHI they may reference follow the **data retention schedule + secure disposal** policy (REQ-PRIV-03; cross-ref NPC checklist), aligned to ISO 15189 record-control retention periods. Concrete retention durations are `[NEEDS-HUMAN]` (legal/regulatory input) *(confirm exact clause)*.
- **Access** — validation records that contain PHI are themselves subject to RBAC (REQ-RBAC-01) and access logging (REQ-AUD-02).
- **Data-subject rights against records** — REQ-PRIV-04 (data-subject access, correction, erasure, objection) is not documentation-only: it is verified end-to-end (L4) by demonstrating that a data-subject correction request resolves to an append-only `corrected` Result version (LIS-7), preserving the audit trail. Policy/filing aspects remain in the NPC checklist; the matrix level (L4) is authoritative.

---

## 12. Stage-gated validation schedule `[DRAFTED]`

Each stage closes on its **verifiable output (exit gate)** and contributes evidence rows to the traceability matrix. Validation is incremental: the snapshot validated at the end of stage *N* is the known base for stage *N+1*.

| Stage | Validation contribution | Closes on (exit gate) |
|---|---|---|
| **Stage 0 — Foundations & compliance scaffold** | This VMP outline + NPC checklist + threat model + seeded matrix (LIS-10); fork/MPL-2.0 inventory = REQ-LIC-01, analyzer-bridge license HOLD = REQ-LIC-02 (LIS-3 / HOLD-001); reproducible bootstrap = IQ seed (LIS-4); RBAC/audit/result/normalization controls proven (LIS-5/6/7/8); simulator harness (LIS-9). | Compliance artifacts exist in-repo and are **reviewed**; matrix maintained. |
| **Stage 1–3 — Drivers & conformance** | L1/L2 unit+component per channel; **L3 signed bench-conformance** before "supported" (REQ-CONF-01). | Per-analyzer conformance reports signed. |
| **Stage 4 — API & offline** | L4 E2E (instrument → normalized Result → **FHIR R4**); store-and-forward + **no-LWW reconciliation** designed for L5 (REQ-RES-01/02). | FHIR + offline sync demonstrable. |
| **Stage 5 — Validation + pilot** | **Execute IQ/OQ/PQ** and produce the **signed dossier** (REQ-VAL-01); **QC engine — Westgard multirules, Levey-Jennings, delta checks, autoverification gating (REQ-QMS-04)**; **file NPC registration** (REQ-PRIV-01); pen-test + remediation (REQ-SEC-04); TLS + at-rest verified (REQ-SEC-01/02); breach-runbook tabletop (REQ-PRIV-02); **pathologist result-release** workflow (RA 4688); go/no-go. | Signed IQ/OQ/PQ dossier + NPC registration filed; pilot go-live decision. |

> The **draft DOH AO 2021-0037 amendment** must be re-confirmed before the Stage-5 go/no-go (`[NEEDS-HUMAN]`); if signed, acceptance criteria are re-baselined.

---

## 13. Approvals & signatories `[NEEDS-HUMAN]`

This VMP is **not approved** until the following are named and have signed. No signatures can be applied by the drafting agent.

| Approval | Name | Signature | Date |
|---|---|---|---|
| System owner | `[NEEDS-HUMAN]` | — | — |
| Validation lead | `[NEEDS-HUMAN]` | — | — |
| QA / regulatory owner (Decision #5) | `[NEEDS-HUMAN]` | — | — |
| Pathologist approver (RA 4688) | `[NEEDS-HUMAN]` | — | — |

---

## Deferred decisions (HITL)

- **Regulatory ownership (Open Decision #5)** — who owns NPC registration, the ISO 15189 validation dossier, and per-customer lab-licensing alignment. **Blocks LIS-10 execution** and every signature line here.
- **Build vs buy the interface engine (Open Decision #6)** — bespoke LabSolution drivers vs adopting an Open Integration Engine. This **determines which interface-engine codebase is a validated object**, drives the L1/L2 unit/component test surface (§7, §9), sets the per-analyzer conformance scope (REQ-CONF-01), and directly drives the license question (REQ-LIC-01 MPL-2.0 obligations / REQ-LIC-02 analyzer-bridge confirmation, HOLD-001). **The validated boundary of the system cannot be finalized until this is fixed.**
- **Stack language (Open Decision #2)** — Java end-to-end vs polyglot edge. Changes the L1/L2 unit/component test surface for the drivers (tooling, codecs, conformance harness language) and therefore part of the OQ test plan.
- **Deployment topology (Open Decision #3)** — central-cloud + thin sites vs full on-prem per site + central sync. Materially changes IQ scope (what is installed where), the resilience/PQ test matrix, and the validated boundary.
- **DOH AO 2021-0037 draft amendment** — track HFSRB consultation; re-confirm before Stage-5 go/no-go; re-baseline acceptance criteria if signed.
- **CSV classification + formal risk method (FMEA or equivalent)** and **revalidation trigger thresholds** — require the appointed QA/regulatory owner.
- **Retention durations + electronic-signature mechanism** for validation records (legal/regulatory input; confirm exact ISO 15189 clause and DOH submission format).
- **Named signatories** (system owner, validation lead, QA/regulatory owner, pathologist approver).

## Reading

- ISO 15189:2022 — *Medical laboratories — Requirements for quality and competence* (LIVE edition; :2012 retired end-2025). Validation, record control, traceability, audit, change control.
- RA 4688 (Clinical Laboratory Law) — licensed-lab workflows and pathologist/physician result release.
- DOH AO 2021-0037 (supersedes AO 2007-0027) — current clinical-lab regulation/licensing; **check HFSRB for the draft amendment status**.
- RA 5527 (Medical Technology Act) — medtech personnel scope → RBAC role mapping.
- RA 10173 (Data Privacy Act) + NPC Circular 2022-04 / NPCRS — for the REQ-PRIV-04 data-subject-rights mechanism that this VMP treats as an L4-tested control (cross-ref NPC checklist).
- `LIS_IMPLEMENTATION_PLAN.md` (§1 pyramid, §5 topology, Stage 0–5 exit gates) and `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` (§5 data model, §10 binding design obligations, §13 open leadership decisions incl. #2/#3/#5/#6).
- `docs/adr/0001-repository-topology-submodule-umbrella.md` — pinned-submodule snapshot = reproducibility/IQ spine (REQ-VAL-02).
- Companion LIS-10 artifacts: NPC checklist (RA 10173 / NPC Circular 2022-04), threat model, and the seeded traceability matrix (authoritative REQ-* registry, incl. the REQ-LIC-01/02 split and the L4 level for REQ-PRIV-04).
- `diagrams/06-regulatory-controls-map.png`, `diagrams/07-er-data-model.png` (validated PHI data objects), and `diagrams/08-verification-pyramid.png`.
