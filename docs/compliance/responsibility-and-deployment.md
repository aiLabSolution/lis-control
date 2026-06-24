# Responsibility Allocation & Deployment-Model Compliance (LabSolution LIS)

> **Stage-0 SCAFFOLD / RESEARCH NOTE** prepared for **LIS-10**, drafted by an agent on **2026-06-24**.
> **Status: `[NEEDS-HUMAN]` — PENDING human review AND confirmation by PH privacy/health-regulatory counsel.**
> This is an internal compliance scaffold to structure the traceability matrix and the deployment-topology
> decision. **It is NOT formal legal advice.** Every "owner" allocation and every "you are / are not required to"
> conclusion below must be confirmed with qualified Philippine privacy and health-regulatory counsel — and several
> turn on facts (the actual M1/M2/M3 data flow, LabSolution's PH headcount, the FDA SaMD classification) that
> engineering and counsel must verify before any conclusion is relied on. Items flagged `(confirm with counsel)`
> are unsettled or jurisdiction-specific.

---

## 1. Purpose & the core question

LabSolution is a **software vendor**: it builds and supplies a Laboratory Information System (LIS) — a fork of
**OpenELIS Global 2** (MPL-2.0) plus a LabSolution-owned **instrument driver / analyzer-bridge** edge layer
(HL7 v2 / ASTM / serial / file ingest, normalization to **LOINC/UCUM**, **FHIR R4** API, **store-and-forward**
site↔central sync) — to **DOH-licensed clinical laboratories and hospitals in the Philippines**. LabSolution is
**not** itself a clinical-laboratory operator: it does not analyze specimens, does not employ the medtechs /
pathologists, and (by default) does not collect or use the patient data.

The core question this note answers, requirement by requirement and across three deployment models:

> **For each compliance obligation, who is the legally responsible party — LabSolution (the software provider) or
> the customer laboratory/hospital (the operator) — and how does that change across the deployment topology?**

The recurring distinction is between:

- **a duty the law puts directly on LabSolution** (e.g. its own product QMS; FDA manufacturer registration if the
  software is a medical device; its own security and registration duties *when* it actually holds PHI as a
  processor); versus
- **a duty that belongs to the lab/hospital, which LabSolution merely ENABLES** through product features (RBAC,
  audit logging, encryption, retention/disposal controls, breach-detection hooks) and inherits a slice of by
  contract.

The single load-bearing legal fact that drives almost everything is the **RA 10173 PIC-vs-PIP characterization**
(§2), which itself shifts across the three deployment models (§4).

---

## 2. The two legal persons + the RA 10173 PIC vs PIP framework

### 2.1 The definitions (cited)

**Personal Information Controller (PIC)** — under the IRR of RA 10173, Sec. 3(m) (statute Sec. 3(h)), a PIC
"controls the processing of personal data, **or instructs another to process** personal data on its behalf." The
term **excludes** a person "who performs such functions **as instructed by another**" (and a natural person
processing for personal/household affairs). The IRR adds a bright-line control test: there is control if the body
**"decides on what information is collected, or the purpose or extent of its processing."**
([IRR — Official Gazette PDF](https://www.officialgazette.gov.ph/images/uploads/20160825-IRR-RA-10173-data-privacy.pdf);
[RA 10173 — LawPhil](https://lawphil.net/statutes/repacts/ra2012/ra_10173_2012.html))

**Personal Information Processor (PIP)** — IRR Sec. 3(n): "any natural or juridical person or any other body **to
whom a personal information controller may outsource or instruct** the processing of personal data pertaining to a
data subject." (The parent statute Sec. 3(i) is slightly narrower — "qualified to act as such… to whom a PIC may
outsource the processing"; the difference is not load-bearing here, but whether "qualified to act as such" imposes
any threshold on processing **sensitive/health** data is an open question — *(confirm with counsel)*.)
([IRR](https://www.officialgazette.gov.ph/images/uploads/20160825-IRR-RA-10173-data-privacy.pdf))

**"Processing"** is defined extremely broadly — IRR Sec. 3(o): "any operation or set of operations … such as
collection, recording, organization, **storage**, updating, **consultation, use**, consolidation, blocking,
**erasure or destruction**," automated or manual. **Hosting, storing, syncing, or even *consulting/viewing* PHI is
itself processing.** This is the hook that turns a hosting/sync vendor into a PIP.

### 2.2 The key result

- **The DOH-licensed lab/hospital is the PIC in all three models** — it decides what patient data is collected and
  the purpose/extent of processing (patient identifiers + lab results = **sensitive personal information**).
  LabSolution never sets the clinical purpose, so **LabSolution is never the PIC.** *(high confidence.)*
  - Edge case to watch: if LabSolution ever processed aggregated PHI for **its own purposes** (product analytics,
    QA benchmarking, ML/model training on patient data), it could become an independent/co-controller **for that
    activity** — outside the stated fact pattern, but it must stay outside it. *(confirm with counsel; lock down
    contractually.)*
- **LabSolution is at most a PIP**, and **possibly NEITHER PIC nor PIP in M1.** Whether it is a PIP or neither
  turns entirely on whether it actually *processes* PHI (stores/hosts/syncs/views) on the lab's instruction.

### 2.3 How accountability and liability split (the crux)

- **The PIC's accountability is primary and non-delegable.** RA 10173 Sec. 21 / IRR Sec. 50: the PIC "is
  responsible for personal information under its control or custody, **including information that have been
  transferred to a third party** for processing … whether domestically or internationally," and must "use
  contractual or other reasonable means to provide a **comparable level of protection** while the information are
  being processed by a third party." **So even in M2/M3 the lab remains accountable to the NPC and to data
  subjects for the PHI LabSolution holds.**
  ([RA 10173 Sec. 21 — LawPhil](https://lawphil.net/statutes/repacts/ra2012/ra_10173_2012.html))
- **The PIP is independently liable too.** IRR Sec. 45: a PIP "shall comply with the requirements of the Act,
  these Rules … **in addition to** obligations provided in a contract." IRR Sec. 51: **any** natural/juridical
  person "involved in the processing of personal data" who violates the Act is **directly liable**. NPC Circular
  2022-01 (Guidelines on Administrative Fines) applies to **"PICs OR PIPs"** and computes the fine on the
  **offending entity's own** annual gross income — so LabSolution-as-PIP can be fined on its own income for its own
  security failure, independently of the lab. *(high confidence, M2/M3.)*
- **The outsourcing/subcontracting contract (the "DPA") is mandatory and prescriptive in M2/M3.** IRR Rule X
  (Secs. 43–45) requires a contract binding the PIP to: process only on the PIC's **documented instructions**;
  impose **confidentiality**; implement **security measures**; engage a further processor only with the PIC's
  **prior authorization** (flow-down of equivalent protections); **assist** the PIC with data-subject rights and
  breach duties; **delete/return** data at end of service; submit to **audits**; and **flag** any instruction it
  believes unlawful. The contract must state subject-matter, duration, nature/purpose, data types, categories of
  data subjects, the PIC's rights, and the **geographic location** of processing.
  ([Rule X analysis — pnl-law](https://pnl-law.com/blog/outsourcing-and-subcontracting-agreements-rule-x-data-privacy-act/))
  - **Note on terminology:** RA 10173 / its IRR do **not** use the GDPR terms "sub-processor" or "joint
    controller." The operative PH mechanism for M2's cloud provider (and any PHI-touching analyzer middleware) is
    the **Rule X flow-down** — "no further processor without the PIC's prior instruction, with equivalent
    protections." We use "sub-processor" below only as a familiar shorthand for that flow-down target.
- **The right instrument is the PIC→PIP DPA, not a Data Sharing Agreement.** A DSA (NPC Circular 2020-03) is a
  **PIC→PIC** instrument and, per **NPC Advisory 2025-01 (26 Jun 2025)**, is now explicitly **optional /
  best-practice** and not NPC-approved. A DSA is the **wrong** instrument for the LabSolution↔lab relationship; it
  would only ever concern the lab when *it* shares PHI with another independent controller (DOH, PhilHealth, a
  referring hospital).
  ([eLegal](https://elegal.ph/npc-clarifies-data-sharing-agreement-requirements-under-npc-circular-no-2020-03/))

---

## 3. Responsibility allocation — requirement-by-requirement

**Owner legend:** **Customer lab (PIC)** = the lab/hospital's legal duty. **LabSolution (vendor)** = LabSolution's
own direct legal duty. **Shared** = both carry a direct statutory duty (typically only in M2/M3 where LabSolution
becomes a PIP). Where a privacy duty is the lab's and LabSolution only supplies the controls, the owner is the lab
and the "LabSolution's actual job" column says **ENABLE**.

Unless a row says otherwise, the allocation is **for the default M1 fact pattern** (LabSolution holds no PHI); the
M2/M3 shifts are called out in the row and detailed in §4–§5.

| Requirement (REQ-\* id) | Owner | LabSolution's actual job |
|---|---|---|
| **RA 4688 — Clinical Laboratory license (LTO)** | Customer lab (PIC/operator) | None. RA 4688 binds whoever "operates and maintains a clinical laboratory"; it has **no software/vendor provisions**. A pure software vendor that does not analyze specimens needs no RA 4688 license. *(high; all models)* ([RA 4688 — LawPhil](https://lawphil.net/statutes/repacts/ra1966/ra_4688_1966.html)) |
| **DOH AO 2021-0037 — clinical-lab regulation / result release** | Customer lab | None directly. AO 2021-0037 is scoped to the "applicant"/operator; its IT-adjacent rules (record retention, PNPKI digital signatures, results signed by the RMT and Pathologist who is "accountable for the reliability of the results") are the **lab's** duties. LabSolution **ENABLEs** them: PNPKI-compatible e-signature support, RMT/pathologist result-release workflow, signed-report generation. *(A draft amendment is in HFSRB consultation, **unsigned as of 2026-06-24** — monitor; if signed it may add LIS/electronic-records obligations.)* *(high; all)* ([HFSRB advisory](https://hfsrb.doh.gov.ph/advisory-on-the-draft-amendment-ao-on-2021-0037/)) |
| **RA 5527 — Medical Technology personnel licensing** | Customer lab | None. Personnel-licensing duty of the lab. LabSolution **ENABLEs** via **named-user RBAC** (REQ-RBAC-01) so result entry/verification/release is tied to a licensed, identified medtech/pathologist (links to result-release authorization). *(high; all; RA 5527 treated per grounding facts, not independently re-verified)* |
| **ISO 15189:2022 accreditation — laboratory QMS & competence** | Customer lab | None directly (the lab is accredited, not the vendor). LabSolution **ENABLEs** via the deliverables in REQ-VAL/REQ-QMS/REQ-SEC rows below. *(medium-high; all)* |
| **ISO 15189:2022 Cl. 7.6 — LIS validation in the lab's environment (site IQ/OQ/PQ)** | Customer lab | **ENABLE.** Cl. 7.6 requires the lab to validate the LIS **before use**, control access/changes, keep audit trails, protect data, and maintain downtime/recovery plans — and states the lab **"remains responsible"** even when the system is **externally hosted** (bites in M2/M3). LabSolution **performs its own product verification** (factory IQ/OQ-style) and **supplies** the evidence the lab needs for **on-site** IQ/OQ/PQ. The lab runs PQ in its environment; LabSolution does not. *(medium-high; all; clause numbering per accreditation-body summaries — confirm against the purchased standard)* ([SADCAS F134(a)](https://www.sadcas.org/sites/default/files/2025-10/SADCAS%20F%20134%28a%29%20-%20Management%20%20Requirements%20for%20Medical%20laboratories%20ISO%2015189-2022%20%5BIssue%203%5D.pdf)) |
| **ISO 15189:2022 Cl. 6.8 — externally-provided products & services (supplier mgmt)** | Customer lab | **ENABLE.** Supplier-qualification of LabSolution is the lab's duty (document requirements, evaluate, approve, monitor). LabSolution supplies **supplier documentation** so the lab can qualify it. *(medium-high; all)* ([ANAB/ANSI](https://blog.ansi.org/anab/changes-in-the-new-iso-15189-2022/)) |
| **PNPAQC / EQAS — external quality assessment** | Customer lab | **ENABLE.** EQA/PT participation (NRL- or DOH-approved EQAP) is a **hard condition of LTO renewal** — the lab's duty, invariant across M1/M2/M3. LabSolution's enabling role: the LIS must capture, **segregate**, and report EQA/PT sample results and support result traceability (ties to REQ-DATA-01/02, REQ-QMS-02). *(high; all)* |
| **REQ-PRIV-01 — NPC/NPCRS registration of the data-processing system** | Customer lab (PIC) for the LIS; **LabSolution (vendor) for its OWN service DPS in M2/M3** | The lab registers the operational LIS as a DPS it operates (it almost always crosses ≥1,000-SPI / health-risk triggers). **M1:** LabSolution does **not** register the lab's LIS (it neither operates it nor — on the no-access facts — processes PHI). **M2/M3:** NPC Circular 2022-04 Sec. 5(B) — "**A PIP who uses its own system as a service to process personal data must register**" — so LabSolution must register its **own** sync/aggregation DPS. Separately, LabSolution owes an NPC **registration or sworn declaration (Annex 1)** for its **own corporate** systems if it has ≥250 staff (model-independent). *(high M2/M3; medium M1)* ([NPC Circular 2022-04](https://privacy.gov.ph/wp-content/uploads/2023/05/Circular-2022-04-1.pdf)) |
| **REQ-PRIV-02 — breach notification (NPC + data subjects, 72 h)** | Customer lab (PIC) | **ENABLE + (M2/M3) detect-and-escalate + own apparatus.** The **72-hour** notification to NPC/data subjects is **always the lab's** (IRR Sec. 38(a); duty stays with the PIC even when outsourced — NPC Circular 16-03). LabSolution **ENABLEs** detection (audit/access logging, alerting). **In M2/M3** LabSolution additionally has **direct** duties: notify the PIC per the DPA, and — as a PIP — maintain its **own** Security Incident Management Policy, a **Data Breach Response Team**, incident documentation, and file the **annual security-incident report** to the NPC. *(high; all)* ([NPC Circular 16-03](https://privacy.gov.ph/wp-content/uploads/2022/01/sgd-npc-circular-16-03-personal-data-breach-management.pdf)) |
| **REQ-PRIV-03 — retention / disposal** | Customer lab (PIC) | **ENABLE.** Governing instrument is **DOH AO 2022-0007** (*Philippine Standards on the Retention Period of Documents, Records, Slides and Specimens in Clinical Laboratories*, Annex A schedules; aligned to the National Archives RDS) — **not** AO 2021-0037 — and it expressly allows electronic records if accessible/retrievable by authorized users. RA 10173 retention-limitation overlays it. LabSolution **ENABLEs**: configurable retention periods, legal hold, controlled disposal/purge, exportable records. *(high; all)* ([DOH AO 2022-0007](https://www.dataguidance.com/sites/default/files/doh_administrative_order_2022-0007_philippine_standards_on_the_retention_period_of_documents_records_slides_and_specimens_in_clinical_laboratories-compressed.pdf)) |
| **REQ-PRIV-04 — data-subject rights** | Customer lab (PIC) | **ENABLE + (M2/M3) assist.** Honoring access/correction/erasure/portability/object/blocking is the PIC's duty. LabSolution **ENABLEs** via product features (record retrieval, correction with audit trail, export, erasure/purge). In M2/M3 the DPA obliges LabSolution to **assist** the lab in responding (Rule X). *(high; all)* |
| **REQ-PRIV-05 — lawful basis (Secs. 12/13)** | Customer lab (PIC) | None / ENABLE-only. Establishing the lawful basis for clinical processing is purely the PIC's. LabSolution merely processes on instruction (M2/M3) and must not process beyond it. *(high; all)* |
| **REQ-PRIV-06 — Data Protection Officer (DPO)** | Customer lab (PIC); **LabSolution for its own processing** | The lab designates a DPO for the LIS processing. LabSolution must designate a DPO/compliance officer for **its own** processing in **all** models (its corporate data), and **specifically for the LIS-PHI processing it performs as a PIP in M2/M3** (IRR Sec. 26). *(high; all)* |
| **REQ-PRIV-07 — RoPA / PIA** | Customer lab (PIC); **LabSolution for its own processing in M2/M3** | The lab maintains the RoPA and conducts the PIA for the LIS. LabSolution **ENABLEs** (system/data-flow documentation, security-control descriptions). **In M2/M3** LabSolution must maintain its **own** RoPA and PIA for the sync/aggregation processing it performs. *(high M2/M3; medium M1)* |
| **REQ-PRIV-08 — cross-border / data residency** | Customer lab (PIC) | None in M1/M3; **ENABLE + flow-down in M2.** PH has **no general data-localization mandate** for private health data; cross-border transfer is permitted under **Sec. 21 accountability** (not an adequacy whitelist or prior-approval regime). The PIC carries the transfer's lawfulness. **M2-offshore** is the only model that triggers a genuine cross-border transfer; LabSolution-as-PIP must flow Sec. 21 protections down to the offshore cloud provider (NPC Model Contractual Clauses, Advisory 2024-01, are **voluntary**). **M3 (in-PH) and M1 raise no cross-border issue.** *(high; all)* ([NPC Advisory 2024-01](https://privacy.gov.ph/wp-content/uploads/2024/06/Published-NPC-Advisory-No.-2024-01-Contractual-Clauses-for-Cross-Border-Transfers_30May24.pdf)) |
| **REQ-PRIV-09 — sub-processor / flow-down DPAs** | Customer lab (PIC) imposes the head DPA; **LabSolution executes downstream flow-down in M2/M3** | The lab must impose the Rule X PIC→PIP DPA on LabSolution (the lab's drafting duty). **LabSolution signs/complies and must execute back-to-back flow-down agreements** with any further PHI-touching processor: in **M2** the public-cloud IaaS provider (and any managed-service/monitoring vendor); in **M2/M3** any PHI-touching **analyzer middleware** (e.g. SnibeLis / Mindray DMS). **M3** has the shortest chain (typically the single head DPA, no cloud sub-processor). *(high M2/M3)* |
| **REQ-RBAC-01 — named-user RBAC** | Customer lab (PIC) operates it; **LabSolution provides it** | **ENABLE (M1) / direct duty over its environment (M2/M3).** LabSolution must ship robust named-user RBAC (role separation for entry/verify/release; ties RA 5527 / pathologist accountability to identified users). In M2/M3 LabSolution also owes IRR Sec. 25 access-control over the PHI it holds. *(high; all)* |
| **REQ-AUD-01/02 — audit trail + access logging** | Customer lab operates; **LabSolution provides** | **ENABLE (M1) / direct (M2/M3).** Append-only audit (who/what/when/before-after) + access logging; supports ISO 15189 Cl. 7.6 audit-trail-of-changes/access and NPC Circular 2023-06 technical logging (retain security logs longer than general logs). In M2/M3, logging the PHI it holds is LabSolution's own Sec. 25 duty. *(high; all)* |
| **REQ-SEC-01 — TLS in transit** | Customer lab operates; **LabSolution provides** | **ENABLE (M1) / direct (M2/M3).** TLS for LIS↔analyzer-edge, LIS↔FHIR API, and the store-and-forward **sync channel**. NPC Circular 2023-06 wants secure authentication (MFA/encrypted links) for online access to SPI. *(high; all)* |
| **REQ-SEC-02 — encryption at rest** | Customer lab operates; **LabSolution provides + (M2/M3) directly applies** | **ENABLE (M1) / direct (M2/M3).** At-rest encryption of the PHI store. **In M2/M3 LabSolution holds the PHI** and so carries the **direct** at-rest duty over the cloud/central store. (Note: NPC Circular 2023-06 clearly mandates encryption of **portable/removable media** and MFA for online SPI access; whether it universally mandates at-rest encryption of all stored data, and any named algorithm, is **not confirmed verbatim** — *confirm against the signed circular*.) *(medium; all)* |
| **REQ-SEC-03 — channel isolation** | Customer lab operates; **LabSolution provides + (M2/M3) directly** | **ENABLE (M1) / direct (M2/M3).** Network/tenant isolation of the sync boundary and per-site segregation in the central node; this is exactly where the **sync-boundary threat (TB-5)** bites. *(medium; all)* |
| **REQ-SEC-04 — penetration testing** | Shared (per environment) | Each party pen-tests **what it operates**: the lab its on-prem deployment; **LabSolution its own cloud/central infrastructure in M2/M3**. LabSolution should offer/coordinate testing of the shipped product. *(medium; all)* |
| **REQ-SEC-05 — secrets / key management** | Customer lab operates; **LabSolution provides + holds keys in M2/M3** | **ENABLE (M1) / direct + custody (M2/M3).** Key/secret management for at-rest encryption and sync credentials. **In M3 especially, LabSolution holds the keys to aggregated multi-lab PHI on its own premises** — a direct, non-delegable custody duty. *(medium; all)* |
| **REQ-VAL-01 — IQ/OQ/PQ dossier** | Shared (split) | **LabSolution direct (product side).** LabSolution authors and supplies the **IQ/OQ-style product validation dossier** + intended-use/specs; the **lab** performs **on-site IQ/OQ/PQ** (Cl. 7.6) and owns the accreditation-facing PQ. *(medium-high; all)* |
| **REQ-VAL-02 — reproducible build** | LabSolution (vendor) | **Direct.** Reproducible, containerized, version-controlled build of the OpenELIS fork + edge layer; a build the lab can pin and the dossier can reference. *(high; all)* |
| **REQ-QMS-01 — record control** | Customer lab operates; **LabSolution provides** | **ENABLE.** Record-control features (versioning, controlled correction, audit) feeding the lab's ISO 15189 record control and the AO 2022-0007 retention regime. *(medium-high; all)* |
| **REQ-QMS-02 — traceability** | Customer lab operates; **LabSolution provides** | **ENABLE.** End-to-end traceability (order→specimen→raw analyzer code/unit→**LOINC/UCUM** normalized result→verified→released report; EQA samples segregated). *(medium-high; all)* |
| **REQ-QMS-03 — change control** | LabSolution (vendor) for the product; lab for its instance | **Direct (product).** Documented, authorized change control + release notes for every LIS change; Cl. 7.6 requires the **lab** to authorize changes **before** deployment, so LabSolution must furnish release notes/change records to enable that. *(high; all)* |
| **REQ-DATA-01/02 — result store + normalization** | LabSolution (vendor) | **Direct (product).** Store raw_code/raw_unit alongside normalized LOINC/UCUM + status; correct, lossless normalization. *(high; all)* |
| **REQ-CONF-01/02 — bench / component conformance** | LabSolution (vendor) | **Direct (product).** Conformance fixtures + bench tests for analyzer drivers, HL7/ASTM parsing, FHIR R4 resources. *(high; all)* |
| **REQ-LIC-01 — MPL-2.0 compliance** | LabSolution (vendor) | **Direct.** File-level copyleft: preserve license headers, publish modified MPL-covered files, NOTICE hygiene across the fork and contributed plugins. *(high; all)* |
| **REQ-LIC-02 — analyzer-bridge license (HOLD-001)** | LabSolution (vendor) | **Direct + BLOCKER.** The `openelis-analyzer-bridge` has **no declared license** (HOLD-001). Resolve before embedding/distributing. **Overlap flag:** this is the very module most likely to host the autoverification/CDS logic that could make the product **SaMD** (see below) — an undeclared license on the FDA-manufacturer-triggering component is a combined IP + device-reg risk. *(high; all)* |
| **PH FDA SaMD / MDSW manufacturer registration** *(not in REQ registry — flag for addition)* | **LabSolution (legal manufacturer)** | **Direct, topology-invariant.** If the LIS's **autoverification / QC-gating / clinical-decision-support** functions qualify the product as Medical Device Software, the **legal manufacturer** (LabSolution — software placed on the PH market under its own name) owes a **License to Operate** + **CMDN/CMDR** registration — **separate** from the lab's RA 4688/ISO duties and **the same in M1/M2/M3** (classification follows function, not deployment). The plain results-store/display core is most likely out of scope; the autoverification layer is the risk. The dedicated MDSW circular is **DRAFT/unsigned as of 2026-06-24**, but "software" is already inside the device definition under RA 9711 / AO 2018-0002. There is an unresolved **IVD carve-out** (software-as-IVD / software-in-IVD) that may route an autoverification LIS to the CIVDR/CIVDN pathway or a gap. *(medium; all — needs an FDA pre-submission classification; confirm with counsel)* ([FDA draft MDSW circular](https://www.fda.gov.ph/wp-content/uploads/2025/05/Draft-FDA-Circular-FDA-Medical-Device-Software.pdf)) |

---

## 4. Deployment models

> **Common to all models:** the lab/hospital is the **PIC**; RA 4688 / DOH AO 2021-0037 / AO 2022-0007 / RA 5527 /
> ISO 15189 accreditation + EQAS are the **lab's** duties (LabSolution ENABLEs); LabSolution's own product duties
> (REQ-VAL-02, REQ-QMS-03, REQ-DATA, REQ-CONF, REQ-LIC) and the **PH FDA SaMD manufacturer obligation if
> triggered** do **not** vary with topology.

### 4.1 M1 — FULLY ONSITE

The LIS runs entirely on-premises at each lab/hospital; no sync; LabSolution ships software and, **by default,
never accesses or stores PHI**.

- **LabSolution's data-protection role:** **NEITHER PIC nor PIP** — a **software supplier** outside the RA 10173
  processor taxonomy, governed by the lab's ISO 15189 supplier-management duty and the supply contract, not by RA
  10173 as a processor. *(medium confidence — **wholly fact-dependent**; see the load-bearing caveat below.)*
- **Where PHI lives:** entirely on the lab's premises, on infrastructure the lab controls. PHI never leaves the
  lab.
- **Cross-border / residency (REQ-PRIV-08):** **inert.** No transfer occurs.
- **Sub-processors / DPAs/DSAs (REQ-PRIV-09):** **None for ongoing processing.** **But** a **narrow, scoped
  support DPA** (Rule X) is prudent for any remote-support / break-glass access that *could* touch live PHI — that
  access is "consultation/use" = processing, and would make LabSolution a PIP **for that scope and duration**. No
  DSA (wrong instrument).
- **NPC / NPCRS registration (REQ-PRIV-01):** the **lab registers the LIS as PIC**. **LabSolution does not register
  the lab's LIS.** LabSolution still owes its **own** corporate-systems registration or **sworn declaration**
  (Annex 1) regardless of model (e.g. ≥250-employee trigger).
- **Breach chain (REQ-PRIV-02):** the lab detects, decides, and notifies NPC/data subjects within 72 h.
  LabSolution has **no direct breach duty over the lab's data** — its role is to **ENABLE** detection (audit/access
  logs, alerts). (If a support session touches PHI, detect-and-escalate for that incident attaches.)
- **Security incl. physical custody (REQ-SEC-02/05):** the **lab** carries the IRR Sec. 25 / NPC Circular 2023-06
  organizational/physical/technical duties; LabSolution's duty is to **provide the controls as product features**
  (RBAC, TLS, at-rest encryption, key mgmt, audit). LabSolution has **no physical custody** of PHI.
- **Threat-surface delta (forward-ref threat model):** **no sync boundary (TB-5 does not exist in M1)**; at-rest
  PHI (**TB-7**) lives only inside the lab's perimeter. Smallest attack surface.
- **ISO 15189 validation split:** LabSolution supplies the product validation dossier, reproducible build, change
  control/release notes, and supplier documentation; the **lab** performs on-site IQ/OQ/PQ and qualifies
  LabSolution as a supplier (Cl. 6.8). The lab is fully responsible at assessment (Cl. 7.6).
- **NET compliance burden on LabSolution:** **lowest.** Product QMS + license hygiene + SaMD-if-triggered + its own
  corporate NPC filing + a prudent support DPA. **No PHI-custody, registration, breach, or cross-border duty over
  the lab's data.**

> **`[NEEDS-HUMAN]` — load-bearing factual premise.** The "neither PIC nor PIP" conclusion holds **only if
> LabSolution genuinely never accesses, stores, or receives PHI** — including via remote-support sessions that
> view live data, **telemetry, crash dumps, error logs, automatic backups, or update channels that pull data
> back**, and including the case where **support/engineering staff sit offshore** (offshore remote access to PH PHI
> is itself a Sec. 6 / Sec. 21 cross-border processing event regardless of where the data is stored). No PH
> statute, IRR provision, or NPC advisory squarely characterizes a software vendor's support/maintenance access —
> the "support flips M1 to PIP" position is a reasoned extrapolation from the broad Sec. 3(o) definition, not
> settled law. **Confirm the actual M1 data-flow with engineering, and the characterization with counsel (an NPC
> advisory-opinion request is the authoritative route). Lock any residual access down with a scoped support DPA +
> break-glass controls.**

### 4.2 M2 — ONSITE + PUBLIC-CLOUD SYNC / SERVICE

The LIS runs on-prem at each site but syncs/replicates PHI to (or uses) a **public-cloud service** (AWS/GCP/Azure)
operated by or for LabSolution; the cloud provider is a third party; the cloud region may be **offshore**.

- **LabSolution's data-protection role:** **PIP** — it stores/processes PHI as a service for the labs (storing/
  syncing = processing under Sec. 3(o)). *(high confidence.)*
- **Where PHI lives:** on the lab's premises **and** replicated to LabSolution's cloud service — physically on the
  **public-cloud provider's** infrastructure, possibly **offshore**.
- **Cross-border / residency (REQ-PRIV-08):** **the genuine cross-border model.** If the region is offshore, this
  is an international transfer; PH imposes **no localization ban** but the **PIC (lab)** must account for it and
  ensure comparable protection under Sec. 21, and RA 10173 reaches the offshore processor extraterritorially
  (Sec. 6). The **NPC MCCs (Advisory 2024-01) are voluntary**, not a mandate. *(Sub-case: a public-cloud region
  **physically in PH** is a domestic outsourcing — like M3 for transfer purposes — while still adding a cloud
  sub-processor. Confirm the deployed region **per customer**.)*
- **Sub-processors / DPAs (REQ-PRIV-09):** **head DPA** (lab→LabSolution, Rule X) **plus** back-to-back flow-down
  to the **public-cloud IaaS provider** and to any **PHI-touching analyzer middleware** (SnibeLis / Mindray DMS) or
  managed-service/monitoring vendor. No DSA.
- **NPC / NPCRS registration (REQ-PRIV-01):** the **lab registers the LIS as PIC**; **LabSolution must register its
  own sync-service DPS** ("PIP using its own system as a service") and disclose the offshore cloud
  provider/region. The **aggregate SPI count** across all labs flowing through LabSolution's service likely
  crosses the ≥1,000-SPI threshold independently — *verify the numbers.*
- **Breach chain (REQ-PRIV-02):** **lab → NPC/data subjects (72 h)** stays the lab's; **LabSolution (PIP) → notify
  the lab** per the DPA, and runs its **own** Security Incident Management Policy + Breach Response Team + annual
  NPC report. A cloud-provider breach flows up the chain.
- **Security incl. custody (REQ-SEC-02/05):** **direct IRR Sec. 25 / NPC Circular 2023-06 duties on LabSolution**
  for the cloud environment (technical + organizational; physical largely delegated to the cloud provider under
  back-to-back terms). LabSolution holds the at-rest encryption keys for the synced PHI.
- **Threat-surface delta:** introduces the **store-and-forward sync boundary (TB-5)** and an **offsite, possibly
  offshore, at-rest PHI store (TB-7)** outside any single lab's perimeter, plus a third-party cloud trust boundary.
  Largest attack surface.
- **ISO 15189 validation split:** same deliverables as M1, **plus** the lab "remains responsible" for the
  externally-hosted system (Cl. 7.6) and must qualify LabSolution's cloud service under Cl. 6.8 — so LabSolution
  must furnish hosting/security attestations.
- **NET compliance burden on LabSolution:** **highest.** PIP status + own DPS registration + own breach apparatus
  + direct cloud security duties + a multi-party sub-processor flow-down chain + cross-border accountability
  support. (For **public-hospital/government customers**, an offshore M2 may be foreclosed if the **DICT
  government data-residency draft** is finalized — see §7.)

### 4.3 M3 — ONSITE + CENTRALIZED SYNC AT LABSOLUTION'S OWN ON-PREM DATACENTER (in PH)

The LIS runs on-prem at each site but syncs/aggregates PHI to a **central node LabSolution operates on its own
premises/infrastructure, located in the Philippines** (not public cloud).

- **LabSolution's data-protection role:** **PIP with physical custody** — it aggregates PHI on its own PH
  infrastructure as a service. *(high confidence.)*
- **Where PHI lives:** on the lab's premises **and** on LabSolution's **own** datacenter, **in the Philippines**.
- **Cross-border / residency (REQ-PRIV-08):** **purely domestic outsourcing — no cross-border transfer, no offshore
  sub-processor, no residency exposure.** Lowest-risk model on this axis. *(Watch: if the central node replicates
  backups/DR to an offshore region, M3 silently acquires an M2-style cross-border transfer — confirm the backup/DR
  topology.)*
- **Sub-processors / DPAs (REQ-PRIV-09):** **shortest chain** — typically the single head DPA (lab→LabSolution),
  no public-cloud sub-processor. Any PHI-touching analyzer middleware still needs flow-down.
- **NPC / NPCRS registration (REQ-PRIV-01):** identical **trigger** to M2 — the **lab registers as PIC**;
  **LabSolution must register its own aggregation DPS** ("PIP using its own system as a service"). The only delta
  vs M2 is disclosure content (no offshore sub-processor to name). Aggregate-SPI threshold likely crossed by the
  central node — *verify.*
- **Breach chain (REQ-PRIV-02):** same as M2 — lab notifies NPC/subjects; LabSolution notifies the lab and runs its
  own apparatus. Aggregating many labs' SPI **raises the breach-impact profile**.
- **Security incl. PHYSICAL custody (REQ-SEC-02/05):** **this is where NPC Circular 2023-06's PHYSICAL measures
  bite hardest on LabSolution** — its own datacenter **physical/environmental access controls, physical-media
  handling/logging, secure off-site storage, BCP/backup-restore with recovery-time objectives** — a **direct,
  non-delegable** statutory duty on LabSolution as PIP (it cannot delegate physical custody to a cloud provider as
  in M2). Full technical controls + key custody for the aggregated store sit with LabSolution. *(specific
  physical-measure wording and any at-rest-encryption mandate: confirm against the signed 2023-06 text.)*
- **Threat-surface delta:** the **sync boundary (TB-5)** exists (as in M2) but terminates **in-country on
  LabSolution-controlled infra**; the aggregated **at-rest PHI store (TB-7)** is the densest single target (many
  labs' SPI in one place) — but no third-party cloud / offshore boundary.
- **ISO 15189 validation split:** same as M2 (externally-hosted "remains responsible"; supplier qualification of
  LabSolution's hosting), without a cloud-provider layer to attest.
- **NET compliance burden on LabSolution:** **high — trades M2's cloud/cross-border risk for direct
  physical-custody + key-management duty over aggregated PHI in-country.** Heavier physical-security/BCP burden
  than M1; fewer cross-border/sub-processor concerns than M2.

---

## 5. Comparison matrix

| Compliance dimension | M1 — Fully onsite | M2 — Onsite + public-cloud sync | M3 — Onsite + LabSolution's own in-PH datacenter |
|---|---|---|---|
| **LabSolution RA 10173 role** | **Neither** PIC nor PIP *(fact-dependent — confirm)* | **PIP** | **PIP (physical custody)** |
| **PHI leaves the lab?** | No | Yes → public cloud (possibly offshore) | Yes → LabSolution's in-PH datacenter |
| **Cross-border risk (REQ-PRIV-08)** | None | **High** if offshore region (Sec. 21 accountability; Sec. 6 reach) | None (domestic) — unless offshore DR/backup |
| **Sub-processor flow-down DPAs (REQ-PRIV-09)** | None (only a scoped support DPA, prudent) | Head DPA + cloud IaaS + middleware (longest chain) | Head DPA only (+ middleware if PHI-touching) — shortest chain |
| **LabSolution NPC/NPCRS registration (REQ-PRIV-01)** | No (own corporate filing/sworn declaration only) | **Yes** — own sync-service DPS (discloses offshore provider) | **Yes** — own aggregation DPS (no offshore disclosure) |
| **Breach duty (REQ-PRIV-02)** | ENABLE only (lab notifies NPC) | PIP→PIC notice + own SIM policy/response team/annual report (lab still notifies NPC) | Same as M2 |
| **Physical-security custody of PHI** | None (lab) | Largely delegated to cloud provider (back-to-back) | **Direct on LabSolution — heaviest** (own datacenter) |
| **At-rest encryption scope (REQ-SEC-02)** | Provide as product feature (lab applies) | Direct over cloud store *(verify 2023-06 mandate)* | Direct over aggregated in-PH store *(verify mandate)* |
| **Key-management custody (REQ-SEC-05)** | Lab holds keys; LabSolution provides tooling | LabSolution holds keys (cloud store) | **LabSolution holds keys to aggregated multi-lab PHI** |
| **NET vendor compliance burden** | **Lowest** | **Highest** | **High** (physical-custody-weighted) |

---

## 6. How LabSolution's direct obligations escalate M1 → M3

LabSolution's **direct** statutory exposure scales with how much PHI it actually touches. **M1 minimizes it**:
LabSolution is a software supplier — its only direct duties are its product QMS / license hygiene / a SaMD
manufacturer registration if the autoverification layer qualifies / its own corporate NPC filing, with **no
PHI-custody, registration, breach, security, or cross-border duty over the lab's data** (subject to the load-bearing
"zero PHI access" premise holding). Crossing into **M2 maximizes it**: LabSolution becomes a **PIP** with its own
DPS registration, its own breach apparatus, direct cloud-environment security duties, the **longest sub-processor
flow-down chain**, *and* offshore cross-border accountability support. **M3** is **not** simply "M2 minus the
cloud": it **trades M2's cloud/cross-border risk for a direct, non-delegable physical-custody + key-management duty**
over aggregated multi-lab PHI held on LabSolution's own PH premises — eliminating the offshore/sub-processor axis but
making LabSolution the densest single PHI target and the bearer of the heaviest NPC Circular 2023-06 **physical**
obligations. **Takeaway:** on vendor compliance burden, **M1 < M3 < M2** — M1 minimizes, M2 maximizes; M3 swaps
cloud/cross-border exposure for physical-custody duty. The PH FDA SaMD manufacturer obligation, if triggered, is the
**one** direct LabSolution duty that does **not** move with the topology.

---

## 7. Decisions this informs & open items

**Decisions (forward-referenced; these ADR/decision records are to be created):**

- **DEC-01 — Regulatory ownership.** Codify that the customer lab/hospital is the **PIC** in all models and bears
  primary, non-delegable accountability; LabSolution is **neither (M1) / PIP (M2,M3)**; and the SaMD manufacturer
  duty (if triggered) sits on LabSolution regardless of model. Drives the head-DPA template and the customer
  contract's privacy allocation.
- **DEC-03 — Topology.** The M1/M2/M3 choice **is** a compliance decision, not just an architecture one: it sets
  LabSolution's PIP status, registration, breach, cross-border, and physical-custody duties. Recommend a
  **per-customer decision gate** (esp. public-vs-private customer; offshore-vs-in-PH region) rather than one global
  topology.
- **DEC-17 — Vendor PHI boundary.** Pin down, with engineering, **exactly** what touches PHI in M1 (remote
  support, telemetry, crash dumps, logs, backups, update channel, offshore staff access). This single fact
  determines whether M1 is truly "neither" or a latent PIP — and whether a scoped support DPA + break-glass
  controls are mandatory.
- **NPC checklist A4/A5** (the NPCRS registration / DPO-designation checklist items in the Stage-0 NPC
  registration checklist): A4 = lab's PIC DPS registration of the LIS (all models); A5 = LabSolution's own
  PIP-service DPS registration (**triggered in M2/M3**, not M1) + its corporate filing/sworn declaration (all
  models). Map both onto the NPCRS filing workflow.

**Open items for PH counsel** — see the structured `counselItems` list accompanying this document; the most
load-bearing are: confirming the M1 "neither PIC nor PIP" characterization against an actual data-flow audit;
confirming whether the autoverification/CDS layer makes the product FDA-regulated SaMD (and which pathway given the
IVD carve-out); confirming the exact NPC Circular 2023-06 physical/at-rest-encryption requirements against the
signed text; and confirming the per-customer cross-border posture for offshore M2 and for public/government
hospital customers under the (still-draft) DICT residency rule.

---

## 8. Sources & reading

### Primary / authoritative (PH law, NPC, DOH, FDA)

- **RA 10173 (Data Privacy Act of 2012)** — [LawPhil](https://lawphil.net/statutes/repacts/ra2012/ra_10173_2012.html) · [NPC](https://privacy.gov.ph/data-privacy-act/) · [Official Gazette](https://www.officialgazette.gov.ph/2012/08/15/republic-act-no-10173/) (Secs. 3, 6, 20(f), 21)
- **IRR of RA 10173** — [Official Gazette PDF](https://www.officialgazette.gov.ph/images/uploads/20160825-IRR-RA-10173-data-privacy.pdf) · [NPC (as amended)](https://privacy.gov.ph/wp-content/uploads/2023/06/IRR_RA-10173-as-amended.pdf) (Secs. 3, 25–26, 38–45, 47, 50–51 / Rule X)
- **NPC Circular 2022-04** — Registration of Personal Data Processing Systems & DPO designation (NPCRS) — [PDF](https://privacy.gov.ph/wp-content/uploads/2023/05/Circular-2022-04-1.pdf) · [Annex 1 sworn declaration](https://privacy.gov.ph/wp-content/uploads/2023/05/Circular-2022-04-Annex-1-1.pdf) · [NPC exemption page](https://privacy.gov.ph/pips-and-pics/exemption/)
- **NPC Circular 16-03** — Personal Data Breach Management — [PDF](https://privacy.gov.ph/wp-content/uploads/2022/01/sgd-npc-circular-16-03-personal-data-breach-management.pdf)
- **NPC Circular 2023-06** — Security of Personal Data (Govt & Private Sector; repeals 16-01) — [NPC announcement](https://privacy.gov.ph/npc-issues-circulars-to-strengthen-personal-data-protection-in-ph/) · [FAQ PDF](https://privacy.gov.ph/wp-content/uploads/2024/12/v12-19-2024_FAQ-NPC-Circular-2023-06_NNJ_JDN.pdf)
- **NPC Advisory 2024-01** — Model Contractual Clauses for Cross-Border Transfers (voluntary) — [PDF](https://privacy.gov.ph/wp-content/uploads/2024/06/Published-NPC-Advisory-No.-2024-01-Contractual-Clauses-for-Cross-Border-Transfers_30May24.pdf)
- **NPC Circular 2020-03 + NPC Advisory 2025-01** — Data Sharing Agreements (PIC↔PIC; DSA now optional) — [Circular 2020-03](https://privacy.gov.ph/wp-content/uploads/2021/01/Circular-Data-Sharing-Agreement-amending-16-02-21-Dec-2020-clean-copy-FINAL-LYA-and-JDN-signed-minor-edit.pdf) · [Advisory 2025-01](https://privacy.gov.ph/wp-content/uploads/2025/07/SGD-2025-01-DSA-Clarification.pdf)
- **RA 4688 (Clinical Laboratory Act of 1966)** — [LawPhil](https://lawphil.net/statutes/repacts/ra1966/ra_4688_1966.html)
- **DOH AO 2021-0037** (clinical-lab regulation; draft amendment in HFSRB consultation, unsigned) — [HFSRB advisory](https://hfsrb.doh.gov.ph/advisory-on-the-draft-amendment-ao-on-2021-0037/) · [HFSRB consultation](https://hfsrb.doh.gov.ph/3313-2/)
- **DOH AO 2022-0007** — Philippine Standards on Retention Period of Clinical-Laboratory Documents/Records — [PDF](https://www.dataguidance.com/sites/default/files/doh_administrative_order_2022-0007_philippine_standards_on_the_retention_period_of_documents_records_slides_and_specimens_in_clinical_laboratories-compressed.pdf)
- **Philippine Health Privacy Code** (Joint AO 2016-0002; DOH/PhilHealth/DOST) — [PDF](https://ehealth.doh.gov.ph/images/HealthPrivacyCode.pdf)
- **RA 3720 / RA 9711 + AO 2018-0002** (medical-device definition incl. software) & **FDA Draft MDSW Circular** (draft/unsigned) — [AO 2018-0002 (SC E-Library)](https://elibrary.judiciary.gov.ph/thebookshelf/showdocs/10/89924) · [FDA draft MDSW](https://www.fda.gov.ph/wp-content/uploads/2025/05/Draft-FDA-Circular-FDA-Medical-Device-Software.pdf)
- **DICT draft "Policy Guidelines on Data Residency for Government Agencies"** (draft/unsigned as of 2026-06-24; government data only) — [DICT](https://dict.gov.ph/Data-Residency)
- **ISO 15189:2022** (official standard; copyrighted — purchase) — [iso.org](https://www.iso.org/standard/76677.html)

### Reference / secondary (analysis; used where primary PDFs returned 403/TLS errors)

- ISO 15189:2022 clause summaries — [SADCAS F134(a)](https://www.sadcas.org/sites/default/files/2025-10/SADCAS%20F%20134%28a%29%20-%20Management%20%20Requirements%20for%20Medical%20laboratories%20ISO%2015189-2022%20%5BIssue%203%5D.pdf) · [ANAB/ANSI](https://blog.ansi.org/anab/changes-in-the-new-iso-15189-2022/) · [SimplerQMS](https://simplerqms.com/iso-15189/)
- Rule X / outsourcing — [pnl-law](https://pnl-law.com/blog/outsourcing-and-subcontracting-agreements-rule-x-data-privacy-act/)
- NPC registration analysis — [Cruz Marcelo](https://cruzmarcelo.com/mandatory-registration-of-data-processing-systems-and-data-protection-officer-due-on-10-july-2023/) · [Alburo](https://www.alburolaw.com/registration-of-data-processing-system-and-designation-of-data-protection-officer-mandated-by-npc-circular-no-2022-04/) · [Baker McKenzie / Global Compliance News](https://www.globalcompliancenews.com/2023/01/14/https-insightplus-bakermckenzie-com-bm-technology-media-telecommunications_1-philippines-new-npc-circular-on-registration-of-data-protection-officers-and-data-processing-systems-takes-effect_0111202/)
- Breach handling — [Alburo](https://www.alburolaw.com/procedure-for-handling-data-privacy-breach/) · [Legal Resource PH](https://legalresource.ph/data-breach-notification-data-privacy-law/)
- NPC Circular 2023-06 security measures — [Baker McKenzie / Global Compliance News](https://www.globalcompliancenews.com/2024/04/19/https-insightplus-bakermckenzie-com-bm-data-technology-philippines-minimum-requirements-for-security-of-personal-data-issued-by-the-national-privacy-commission_04032024/) · [Thales](https://cpl.thalesgroup.com/compliance/apac/data-security-compliance-npc-circular-2023-06)
- Cross-border / no-localization — [DLA Piper PH (Transfer)](https://www.dlapiperdataprotection.com/index.html?t=transfer&c=PH) · [Baker McKenzie Data & Cyber Handbook — PH localization](https://resourcehub.bakermckenzie.com/en/resources/global-data-and-cyber-handbook/asia-pacific/philippines/topics/data-localization-and-regulation-of-non-personal-data)
- DSA clarification — [eLegal](https://elegal.ph/npc-clarifies-data-sharing-agreement-requirements-under-npc-circular-no-2020-03/) · [Baker McKenzie InsightPlus](https://insightplus.bakermckenzie.com/bm/data-technology/philippines-data-sharing-agreement-not-mandatory-per-the-npc)
- DOH AO 2021-0037 summaries — [mt-lectures](https://mt-lectures.blogspot.com/2023/05/administrative-order-no-2021-0037_8.html) · [jur.ph](https://jur.ph/laws/summary/new-rules-and-regulations-governing-the-regulation-of-clinical-laboratories-in-the-philippines)
- SaMD/MDSW analysis — [Asia Actual](https://asiaactual.com/blog/philippines-medical-device-software-regulation/) · [Andaman Medical](https://andamanmed.com/regulatory-services/medical-device-registration/philippines/) · [IMDRF N12](https://www.imdrf.org/sites/default/files/docs/imdrf/final/technical/imdrf-tech-140918-samd-framework-risk-categorization-141013.pdf)

> **Source-fetch caveat:** several primary NPC/DOH PDFs returned HTTP 403/TLS errors to automated fetch during
> research; verbatim section text and exact circular wording (esp. NPC Circular 2023-06 physical-security &
> any at-rest-encryption mandate; Rule X / IRR section numbering in the 2023 consolidated "as amended" IRR) were
> corroborated via the Official Gazette PDFs, the SC E-Library, and reputable firm analyses, **not always read
> line-by-line from the live NPC source.** Confirm all verbatim quotes and section numbers against the live
> issuances before citing in any binding document.
