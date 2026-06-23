# NPC Registration & Data-Privacy Compliance Checklist — LabSolution LIS

> **Stage-0 SCAFFOLD / OUTLINE prepared for LIS-10 (S0.8).** Drafted by an agent on **2026-06-23**, pending human review. This is the data-privacy spine for RA 10173 (Data Privacy Act of 2012) compliance and the National Privacy Commission (NPC) registration filing that must complete **before go-live**. Items below are seeded against the canonical requirement-ID registry maintained in the traceability matrix. Many items depend on legal-entity facts, appointments, signatures, and the actual NPCRS filing — these are honestly marked **[NEEDS-HUMAN]** and several are blocked on open leadership decision **#5 (regulatory ownership)** and **#3 (deployment topology / data residency)**.

## Status legend

| Marker | Meaning |
| --- | --- |
| `[DRAFTED]` | Agent-drafted, ready for human review. The artifact/control exists or is specified in-repo. |
| `[NEEDS-HUMAN]` | Requires a human decision, input, appointment, signature, or filing before it can be completed. A subagent cannot legitimately produce this. |

**Cross-references:** Threat model (`docs/compliance/threat-model.md`), Validation Master Plan outline (`docs/compliance/validation-master-plan-outline.md`), Traceability matrix (`docs/compliance/traceability-matrix.md`), regulatory controls map (`diagrams/06-regulatory-controls-map.png`). Filing-pack artifacts live under `docs/compliance/npc/` (`ropa.md`, `pia.md`, `breach-runbook.md`, `retention.md`). Governing instruments are cited by name per the grounding facts; clause numbers are flagged "(confirm exact clause)" where not independently held.

---

## A. Applicability & threshold assessment

> **Conclusion: NPC registration is MANDATORY for the LabSolution LIS.** A clinical-laboratory LIS stores patient identifiers plus diagnostic results — this is **sensitive personal information** under RA 10173. Any production LIS clears the NPC Circular 2022-04 registration thresholds.

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| A1 | Classify LIS data as **sensitive personal information** under RA 10173 — health/medical records (Patient identifiers + Result.raw_value/loinc/status) are explicitly sensitive PII. | `[DRAFTED]` | Regulatory owner (per decision #5) | This checklist §A; data-flow inventory in §D | REQ-PRIV-05 |
| A2 | Threshold test — **sensitive PII of ≥1,000 individuals** OR **≥250 employees** OR **high-risk processing**. A real lab fleet processes far more than 1,000 patients; processing health data at scale is high-risk by nature. Any one trigger suffices. (NPC Circular 2022-04.) | `[DRAFTED]` | Regulatory owner | Threshold determination memo (to be signed) | REQ-PRIV-01 |
| A3 | Record that NPC Circular **17-01 is OBSOLETE**; registration is governed by **NPC Circular 2022-04**, filed via the online **NPCRS**. Do not follow 17-01 process or forms. | `[DRAFTED]` | Regulatory owner | This checklist §C, §J | REQ-PRIV-01 |
| A4 | Confirm registrant legal entity and PIC/PIP status — is LabSolution a **Personal Information Controller (PIC)**, a **Personal Information Processor (PIP)** for customer labs, or both (depends on deployment topology, decision #3). Each customer lab is itself a PIC under RA 4688. | `[NEEDS-HUMAN]` | Legal entity / counsel | Legal-entity determination | REQ-PRIV-01, REQ-PRIV-05 |
| A5 | Document scope boundary — what LabSolution registers vs. what each licensed lab (RA 4688 DOH-registered clinical lab) registers separately. SaaS-central vs. full on-prem materially changes who controls which copy of PHI and the cross-border / data-residency posture for the offline-sync topology. | `[NEEDS-HUMAN]` | Regulatory owner + counsel | Scope-of-registration note (blocked on decision #3) | REQ-PRIV-01, REQ-PRIV-08 |

---

## B. Governance & accountability

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| B1 | **Appoint a Data Protection Officer (DPO)** — RA 10173 requires a designated DPO; the NPCRS filing requires the DPO's name and contact. This is a named-person appointment, not a draftable artifact. | `[NEEDS-HUMAN]` | Executive / decision #5 owner | DPO appointment letter; DPO contact for NPCRS | REQ-PRIV-06 |
| B2 | Define DPO mandate, independence, and reporting line (confirm exact clause in RA 10173 and its implementing issuances). | `[NEEDS-HUMAN]` | Executive | DPO charter | REQ-PRIV-06 |
| B3 | Optionally appoint **Compliance Officer(s) for Privacy (COP)** per processing site if deployment is multi-site on-prem (decision #3). | `[NEEDS-HUMAN]` | Regulatory owner | COP designation(s) | REQ-PRIV-06 |
| B4 | Stand up a data-privacy accountability structure — who signs the PIA, who owns breach response, who interfaces with NPC. Cross-reference open decision **#5 (regulatory ownership)** which currently blocks ownership assignment for the whole of LIS-10. | `[NEEDS-HUMAN]` | Executive / decision #5 owner | RACI for privacy program | REQ-PRIV-06 |
| B5 | Adopt a written data-privacy management program / privacy manual referencing the LIS controls (RBAC, audit, encryption). Scaffold can be drafted; sign-off is human. | `[DRAFTED]` | Regulatory owner | Privacy manual outline (to be drafted under VMP) | REQ-PRIV-06, REQ-QMS-01 |

---

## C. NPCRS registration mechanics

> The NPCRS process and its phase/field structure must be confirmed at filing time (see §J2); the breakdown below is an **assumption** pending that confirmation. NPC Circular 2022-04 governs registration, filed via the online NPCRS — that much is grounded; the specific Phase 1 / Phase 2 split and field allocation described here is a working assumption, not an authoritative fact.

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| C1 | Create the **NPCRS account** for the registrant legal entity. | `[NEEDS-HUMAN]` | DPO / regulatory owner | NPCRS account credentials (held by DPO) | REQ-PRIV-01 |
| C2 | Register the organization and the appointed DPO (legal name, address, DOH-license context, DPO contact) in the NPCRS step that handles organization/DPO details. Requires confirmed legal-entity facts (§A4) and a real DPO (§B1). *(Whether this is a discrete "Phase 1" is an assumption — see preamble and §J2.)* | `[NEEDS-HUMAN]` | DPO | NPCRS organization/DPO acknowledgement | REQ-PRIV-01, REQ-PRIV-06 |
| C3 | Register the **data processing systems**: the LabSolution LIS (OpenELIS fork), the driver/interface engine (MLLP/ASTM edge), the offline sync store-and-forward layer, and the FHIR R4 / EMR interface. Each is a processing system handling PHI. *(Whether this is a discrete "Phase 2" is an assumption — see preamble and §J2.)* | `[NEEDS-HUMAN]` | DPO + engineering | NPCRS processing-system entries (informed by §D inventory) | REQ-PRIV-01, REQ-PRIV-07 |
| C4 | Assemble the supporting filing pack the NPCRS requires — security measures summary (§F), data-flow/processing description (§D), breach procedure (§G), data-sharing/outsourcing list (§H). Agent can draft the pack; submission is human. | `[DRAFTED]` (pack) / `[NEEDS-HUMAN]` (submission) | DPO | Filing pack folder under `docs/compliance/npc/` | REQ-PRIV-01, REQ-PRIV-07 |
| C5 | **Execute the actual NPCRS filing** and obtain the Certificate of Registration / registration reference. Pay any fees. This is the irreducibly human, legally accountable act. | `[NEEDS-HUMAN]` | DPO / legal entity | NPC Certificate of Registration (go-live gate evidence) | REQ-PRIV-01 |
| C6 | Calendar the **renewal / update** obligation (confirm whether and at what cadence NPCRS registrations expire at filing). | `[NEEDS-HUMAN]` | DPO | Renewal reminder in QMS calendar | REQ-PRIV-01, REQ-QMS-03 |

---

## D. Records of Processing Activities (RoPA) + Privacy Impact Assessment (PIA)

> The LIS data flow is **Patient → Order/Requisition → Specimen/Sample → Result**, with cross-cutting **AuditEvent** and **User→Role (RBAC)**. PHI is created/derived at every node and moves across: instrument edge (Instrument → InterfaceChannel, MLLP/ASTM), normalization at ingest (LOINC/UCUM), offline sync (store-and-forward), and outbound FHIR R4 to EMR/HIS. Each crossing is a PIA-relevant flow. See ER model `diagrams/07-er-data-model.png` and controls map `diagrams/06-regulatory-controls-map.png`.

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| D1 | Draft the **RoPA** enumerating each processing activity: registration/order capture, specimen tracking, instrument result ingest, normalization, verification/release, EMR transmit, QC/PT reporting, sync. | `[DRAFTED]` | DPO + engineering | RoPA table under `docs/compliance/npc/ropa.md` | REQ-PRIV-07 |
| D2 | Map data categories per entity — Patient (direct identifiers, sensitive health), Result (raw_value/raw_unit/raw_code/loinc/ucum_value/status/verified_by/flags), QCResult, Instrument/InterfaceChannel config. | `[DRAFTED]` | Engineering | Data-element catalog (derived from research §5.1) | REQ-PRIV-07, REQ-DATA-01 |
| D3 | Draft the **PIA** for LIS data flows — identify privacy risks (unauthorized access, mis-routed result, sync conflict exposing wrong patient, edge-device theft) and map mitigations to §F controls. | `[DRAFTED]` (draft) / `[NEEDS-HUMAN]` (sign-off) | DPO + regulatory owner | PIA document under `docs/compliance/npc/pia.md` | REQ-PRIV-07, REQ-SEC-03 |
| D4 | Document **data residency / cross-border** posture per flow — central-cloud vs. full on-prem changes whether PHI leaves the lab site or the country. **Blocked on deployment-topology decision #3.** | `[NEEDS-HUMAN]` | Architecture + DPO | Data-residency annex to PIA | REQ-PRIV-08, REQ-PRIV-07, REQ-RES-01 |
| D5 | PIA sign-off by DPO/regulatory owner — analysis is draftable; the accountable sign-off is human. | `[NEEDS-HUMAN]` | DPO | Signed PIA cover sheet | REQ-PRIV-07 |

---

## E. Lawful basis & data-subject rights

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| E1 | Document the **lawful basis** for processing sensitive health PII (e.g. medical-treatment / lab-service provision under RA 10173 sensitive-info processing grounds; consent where applicable). Confirm exact RA 10173 grounds clause with counsel. | `[NEEDS-HUMAN]` | Counsel + DPO | Lawful-basis register | REQ-PRIV-05 |
| E2 | Provide a **privacy notice** to patients/data subjects (collection purpose, retention, rights, DPO contact) — surfaced at the lab/registration point. Template draftable; lab-specific facts are human. | `[DRAFTED]` (template) | DPO | Privacy notice template | REQ-PRIV-05, REQ-PRIV-04 |
| E3 | Implement **data-subject rights mechanisms** — access, correction, erasure, objection. Map each to a LIS capability: access/correction via patient-record query + append-only Result correction (status `corrected`, not overwrite); erasure constrained by ISO 15189 record-control retention (§I). | `[DRAFTED]` | Engineering + DPO | DSR procedure; ties to LIS-5 (RBAC), LIS-7 (append-only versions) | REQ-PRIV-04, REQ-DATA-01 |
| E4 | Resolve the **erasure vs. medical-record-retention tension** — RA 10173 erasure rights are bounded by ISO 15189 / RA 4688 record-retention duties; "erasure" may be restriction/de-identification, not deletion. Confirm exact clause in RA 10173 and its implementing issuances. Needs documented policy decision. | `[NEEDS-HUMAN]` | DPO + counsel | DSR-vs-retention policy (cross-ref §I) | REQ-PRIV-04, REQ-PRIV-03 |
| E5 | Define DSR request intake, identity-verification, and SLA (confirm RA 10173 response-time clause). | `[NEEDS-HUMAN]` | DPO | DSR intake runbook | REQ-PRIV-04 |
| E6 | Define **lawful basis / consent mechanics for minors and incapacitated data subjects** — a clinical lab routinely processes pediatric and incapacitated-patient results; RA 10173's consent and lawful-basis grounds for sensitive PII differ where the data subject is a minor or lacks capacity (guardian / parental authority, substitute consent). Needs counsel to confirm the applicable RA 10173 grounds and how guardian authority is captured at registration and reflected in the privacy notice (§E2). | `[NEEDS-HUMAN]` | Counsel + DPO | Minors/incapacity lawful-basis memo (annex to lawful-basis register) | REQ-PRIV-05 |

---

## F. Security measures evidence

> Cross-references the **threat model** (`docs/compliance/threat-model.md`) and **VMP outline** (`docs/compliance/validation-master-plan-outline.md`). These controls are the technical "organizational, physical, and technical security measures" the NPCRS filing attests to. Most are being built and verified across the Stage-0 sibling issues; this checklist points NPC at the evidence rather than re-implementing it.

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| F1 | **Encryption in transit** — TLS on MLLP/ASTM edge channels and on offline sync. | `[DRAFTED]` (spec) / verified Stage 5 | Engineering | TLS config + Stage-5 verification evidence | REQ-SEC-01 |
| F2 | **Encryption at rest** — DB and edge-device storage encrypted; verified before go-live. | `[DRAFTED]` (spec) / verified Stage 5 | Engineering | At-rest encryption attestation (Stage 5) | REQ-SEC-02 |
| F3 | **Named-user RBAC** — authorized action passes; unauthorized denied **403** with recorded denial; roles mapped to medtech/pathologist scope (RA 5527). | `[DRAFTED]` | Engineering | LIS-5 / S0.3 test evidence | REQ-RBAC-01 |
| F4 | **Append-only audit trail** — who/what/when/before/after on every mutation; direct DB mutation fails at the DB layer. | `[DRAFTED]` | Engineering | LIS-6 / S0.4 test evidence | REQ-AUD-01 |
| F5 | **Access / authentication logging** — login/auth events recorded for monitoring and breach forensics. | `[DRAFTED]` | Engineering | Auth-log spec; ties to LIS-6 | REQ-AUD-02 |
| F6 | **Channel isolation** — a bad/compromised driver cannot corrupt the core; interface engine is architecturally separate (research §5.2). Limits blast radius of an edge breach. | `[DRAFTED]` | Architecture | Threat model §channel-isolation; controls map diagram | REQ-SEC-03 |
| F7 | **Penetration test + remediation before go-live** — the NPCRS attestation should reflect a pen-tested system. | `[NEEDS-HUMAN]` | Security + external tester | Pen-test report + remediation log (Stage 5) | REQ-SEC-04 |

---

## G. Breach management

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| G1 | Draft the **personal-data-breach notification procedure** — assess, contain, notify NPC and affected data subjects within the NPC-prescribed window (RA 10173 / NPC breach rules). The runbook structure is draftable; the **exact notification window and clause must be confirmed against the current NPC breach issuance** (see §J4) before the procedure is finalized. | `[DRAFTED]` (runbook structure) / `[NEEDS-HUMAN]` (notification window + clause) | DPO + security | Breach runbook under `docs/compliance/npc/breach-runbook.md` | REQ-PRIV-02 |
| G2 | Define **breach severity / notifiability criteria** — when sensitive PII exposure triggers mandatory notification. | `[DRAFTED]` | DPO | Breach decision tree | REQ-PRIV-02 |
| G3 | Wire breach detection to audit/access logs (§F4/F5) and channel-isolation alerting (§F6) so a breach is detectable. | `[DRAFTED]` | Engineering | Detection-source mapping | REQ-PRIV-02, REQ-AUD-02 |
| G4 | Maintain a **breach register / Data Breach Response Team** roster — named members. | `[NEEDS-HUMAN]` | DPO | DBRT roster + breach register | REQ-PRIV-02, REQ-PRIV-06 |
| G5 | **Tabletop exercise** the runbook in **Stage 5** to validate it works. | `[NEEDS-HUMAN]` | DPO + security | Stage-5 tabletop after-action report | REQ-PRIV-02 |

---

## H. Data sharing & outsourcing agreements

> Every party that touches PHI on LabSolution's behalf needs a **data-processing agreement (DPA)** or **data-sharing agreement (DSA)** under RA 10173. These are contracts requiring legal review and signatures — all **[NEEDS-HUMAN]**. The set of parties depends on deployment topology (decision #3). The sub-processor / DPA / DSA obligation across this section is anchored to **REQ-PRIV-09** in the traceability matrix so the contractual register is traceable in the spine.

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| H1 | **Cloud host** (if central-cloud topology, decision #3) — DPA covering PHI hosting, residency, sub-processors, breach cooperation. Residency posture routes to §D4. | `[NEEDS-HUMAN]` | Counsel + DPO | Signed cloud-host DPA | REQ-PRIV-09, REQ-PRIV-08 |
| H2 | **SnibeLis / SnibeLinker** instrument middleware — confirm whether PHI flows through vendor middleware; if so, DPA/DSA. (Also named in threat model §3 TB-1 / supply-chain context.) | `[NEEDS-HUMAN]` | Counsel + DPO | Signed vendor DPA | REQ-PRIV-09, REQ-PRIV-07 |
| H3 | **Mindray DMS** data-management software — same determination and agreement. (Also named in threat model §3 supply-chain context.) | `[NEEDS-HUMAN]` | Counsel + DPO | Signed vendor DPA | REQ-PRIV-09, REQ-PRIV-07 |
| H4 | **EMR / HIS** receiving FHIR R4 results — data-sharing agreement covering the outbound result feed (controller-to-controller vs. processor). | `[NEEDS-HUMAN]` | Counsel + DPO | Signed EMR/HIS DSA | REQ-PRIV-09, REQ-PRIV-07 |
| H5 | **PhilHealth** (claims/reporting) — data-sharing agreement / lawful-basis confirmation for any PHI disclosed for reimbursement. | `[NEEDS-HUMAN]` | Counsel + DPO | Signed PhilHealth DSA / basis memo | REQ-PRIV-09, REQ-PRIV-05 |
| H6 | Maintain a **sub-processor / outsourcing register** enumerating all of H1–H5 for the NPCRS filing and PIA. | `[DRAFTED]` (register shell) | DPO | Outsourcing register under `docs/compliance/npc/` | REQ-PRIV-09, REQ-PRIV-07 |

---

## I. Retention & secure disposal

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| I1 | Draft a **data-retention schedule** per data class — clinical results / medical records vs. audit logs vs. QC/PT records. Retention is bounded by **ISO 15189:2022 record control** and RA 4688 (confirm exact retention period with counsel; medical-record retention periods are jurisdiction-specific). | `[DRAFTED]` (schedule shell) / `[NEEDS-HUMAN]` (periods) | DPO + QA | Retention schedule under `docs/compliance/npc/retention.md` | REQ-PRIV-03, REQ-QMS-01 |
| I2 | Define **secure disposal** method (cryptographic erasure / destruction) honoring the append-only constraint — disposal applies at end-of-retention, not as in-life mutation (Result versions are append-only, LIS-7). | `[DRAFTED]` | Engineering + DPO | Secure-disposal procedure | REQ-PRIV-03, REQ-DATA-01 |
| I3 | Reconcile retention with **data-subject erasure** (§E4) — a single documented policy resolving RA 10173 erasure vs. ISO 15189 record-control duties. | `[NEEDS-HUMAN]` | DPO + counsel | Retention-vs-erasure policy | REQ-PRIV-03, REQ-PRIV-04 |
| I4 | Cover **edge-device** disposal (offline-first deployment) — decommissioned site devices holding cached PHI must be securely wiped. | `[DRAFTED]` | Engineering | Edge decommission checklist | REQ-PRIV-03, REQ-SEC-02 |

---

## J. Currency & re-confirmation before filing

> Compliance instruments drift. Re-confirm the following at filing time; do not file against stale process.

| Item | What / why | Status | Owner | Evidence/Artifact | Req ID |
| --- | --- | --- | --- | --- | --- |
| J1 | Confirm **NPC Circular 2022-04** is still the governing registration circular and that **NPCRS** is the live filing portal (Circular 17-01 remains obsolete). Re-check immediately before C5. | `[NEEDS-HUMAN]` | DPO | Currency note dated at filing | REQ-PRIV-01 |
| J2 | Re-verify the **NPCRS process and current field set**, including whether the assumed Phase 1 / Phase 2 structure (§C) holds — phases and required fields can change between drafting and filing. | `[NEEDS-HUMAN]` | DPO | NPCRS process snapshot | REQ-PRIV-01 |
| J3 | Track the **DOH AO 2021-0037 draft amendment** in HFSRB public consultation — its interplay with lab licensing (RA 4688) and the LIS workflow must be re-confirmed before go-live; not yet signed as of 2026-06-23. | `[NEEDS-HUMAN]` | Regulatory owner | DOH AO tracking note | REQ-PRIV-01, REQ-QMS-03 |
| J4 | Confirm current **NPC breach-notification window and clause** (§G1) and current **DSR response SLA** (§E5) against the live NPC issuances. | `[NEEDS-HUMAN]` | DPO | Currency note | REQ-PRIV-02, REQ-PRIV-04 |
| J5 | Confirm **ISO 15189:2022** is the live edition for the retention/record-control cross-reference (:2012 retired end-2025). | `[DRAFTED]` | QA | VMP outline edition note | REQ-PRIV-03, REQ-QMS-01 |

---

## Summary: what blocks completion

- The **actual NPCRS filing (C5)**, the **DPO appointment (B1)**, **PIA sign-off (D5)**, **lawful-basis register (E1)**, **minors/incapacity lawful basis (E6)**, the **breach-notification window confirmation (G1/J4)**, all **data-sharing/processing agreements (§H)**, and **retention periods (I1)** are irreducibly `[NEEDS-HUMAN]` — they need legal-entity facts, appointed persons, counsel review, signatures, or a regulator submission.
- The whole NPC workstream is **gated on open leadership decision #5 (regulatory ownership)** — until ownership of NPC registration and the validation dossier is assigned, the Owner column cannot be populated with a real accountable person.
- The **data-residency and PIC/PIP scope** questions (A4, A5, D4, §H1) are **gated on decision #3 (deployment topology)** — central-cloud vs. full on-prem changes which entity controls which PHI copy (REQ-PRIV-08) and which agreements are needed (REQ-PRIV-09).

## Deferred decisions (HITL)

- **#5 — Regulatory ownership:** who owns NPC registration (DPO + accountable executive)? Blocks every Owner assignment in this checklist.
- **#3 — Deployment topology / data residency:** central-cloud + thin sites vs. full on-prem per site + central sync. Determines PIC/PIP classification, cross-border posture (REQ-PRIV-08), and the set of DPAs/DSAs (REQ-PRIV-09).
- **DPO appointment** (B1): a named person must be designated before NPCRS organization/DPO registration.
- **Erasure vs. medical-record retention** (E4/I3): policy decision reconciling RA 10173 data-subject erasure with ISO 15189 / RA 4688 retention duties.
- **Minors / incapacitated lawful basis** (E6): counsel decision on RA 10173 grounds and guardian/parental authority for pediatric and incapacitated-patient PHI.
- **Vendor PHI exposure** (H2/H3): does PHI actually transit SnibeLis/SnibeLinker/Mindray DMS, or only de-identified instrument data? Determines whether DPAs (REQ-PRIV-09) are required.

## Reading

- **RA 10173** (Data Privacy Act of 2012) and its implementing issuances — lawful bases for sensitive personal information (including minors / incapacitated data subjects), DPO duties, data-subject rights, breach notification.
- **NPC Circular 2022-04** — registration of data processing systems and the NPCRS online filing process (supersedes the obsolete Circular 17-01); confirm the current phase/field structure at filing.
- **NPC breach-notification issuance** — confirm the current notification window and notifiability criteria (§G1, §J4); the grounding facts establish that a breach-notification regime applies but do not fix the window.
- **RA 4688** (Clinical Laboratory Law) + **DOH AO 2021-0037** (and the pending HFSRB draft amendment) — clinical-lab licensing context that frames each customer lab as its own PIC.
- **ISO 15189:2022** — record control and equipment/result traceability that bound the retention schedule (§I).
- In-repo: `docs/compliance/threat-model.md`, `docs/compliance/validation-master-plan-outline.md`, `docs/compliance/traceability-matrix.md`, `docs/compliance/npc/` (ropa.md, pia.md, breach-runbook.md, retention.md), `diagrams/06-regulatory-controls-map.png`, `diagrams/07-er-data-model.png`.
