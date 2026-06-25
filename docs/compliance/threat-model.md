# Threat Model — LabSolution LIS (PHI)

> **Stage-0 SCAFFOLD / BASELINE THREAT MODEL — prepared for LIS-10 (S0.8), drafted by an agent, pending human review. Date: 2026-06-23; revised 2026-06-24 for the deployment-topology decision.**
> This is the first-pass STRIDE threat model over the LabSolution LIS reference architecture. It establishes the security baseline that every later stage refines and that the **Stage-5 penetration test (REQ-SEC-04)** must exercise. It is NOT a completed security assessment: items needing a key-management decision, a PKI design, or a signed pen-test scope are marked **[NEEDS-HUMAN]**. Cross-referenced against the canonical requirement-ID seed / traceability matrix and the Stage-0 sibling issues (LIS-3 … LIS-9).

> **⮕ TOPOLOGY DECISION (2026-06-24) — [ADR-0006](../adr/0006-deployment-topology.md); resolves decision #3.** The
> **pilot attack surface is M1 — fully onsite, per site, no sync.** At the pilot **the sync boundary (TB-5) does
> not exist** and at-rest PHI (TB-7) lives **only inside each lab's perimeter** — the smallest surface. The
> **site↔central sync boundary and the central aggregated PHI store are the post-pilot M3 spoke** (LabSolution's own
> in-PH datacenter): the model below still analyzes them (so the spoke is pre-thought), but they are tagged
> **[M3 SPOKE — POST-PILOT]** and are **out of pilot scope**. Adding the M3 spoke triggers a **threat-model re-run
> under change control** (REQ-QMS-03) — gate-doc item M3-18 in [`m3-sync-compliance-gate.md`](m3-sync-compliance-gate.md).
> **Public-cloud sync (M2) is not selected**, so the third-party-cloud trust boundary is parked.

## Status legend

- **[DRAFTED]** — agent-drafted; ready for human review. The analysis stands on the reference architecture and the requirement seed.
- **[NEEDS-HUMAN]** — requires a human decision, design input, or sign-off (key management, TLS/PKI approach, deployment topology, pen-test scope sign-off) before it can be closed.

---

## 1. Scope & methodology — [DRAFTED]

**Method.** STRIDE (Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege) applied per **trust boundary** of the LabSolution LIS reference architecture (`diagrams/01-reference-architecture.png`). We first enumerate assets ranked by sensitivity (§2), then trust boundaries and data-flows (§3), then actors (§4), then STRIDE threats per boundary as a control-mapped table (§5). Each threat row carries a **Req ID** from the canonical seed and a **Verification level (L1–L6)** from the verification pyramid (`diagrams/08-verification-pyramid.png`). The traceability matrix is the **authoritative level registry**; this model's level cells are aligned to it (where a threat plausibly rolls up to L6 regulatory validation but the matrix does not assign L6 to that requirement, we defer to the matrix and do not inflate the level here).

**In scope — pilot (M1) baseline.** The fully-onsite reference data-flow: instrument edge (HL7 v2.x over MLLP / ASTM-family LIS serial / file-watch) → LabSolution-owned interface engine → normalization (LOINC/UCUM) → OpenELIS core + PostgreSQL → FHIR R4 (HAPI FHIR) / HL7 v2 outbound → EMR/HIS/PhilHealth; plus the cross-cutting RBAC + append-only audit + encryption controls. **All of it inside a single lab's perimeter.**

**In scope but DEFERRED — M3 spoke (post-pilot).** The **site↔central offline sync** (store-and-forward + replication) and the **central aggregated PHI store** at LabSolution's own in-PH datacenter. Analyzed below (TB-5, central-node TB-7) and tagged **[M3 SPOKE — POST-PILOT]**, but **not part of the pilot surface**; a threat-model re-run under change control precedes the spoke (REQ-QMS-03 / gate doc M3-18).

**Out of scope / deferred for this baseline.** Physical security of analyzer benches and edge appliances (referenced under L3 bench conformance but owned by per-site facility controls); detailed cryptographic key-management design (deferred, §8); the full PhilHealth / EMR partner integration security agreement (a contractual/legal item, not a code control). These become explicit pen-test and Stage-5 inputs.

**Lifecycle (change-managed).** This baseline is a **living artifact, re-run at each stage gate** — not a one-shot. The re-run cadence and revalidation-on-change are anchored to **REQ-QMS-03 (change control & revalidation)** so the "living" claim is traceable, not aspirational: a material architecture/topology/fleet change SHALL trigger a threat-model re-run under change control. Ownership of the living model (who schedules and signs off the re-runs) defers to the **regulatory/QA owner named by open decision #5** (§8). The model drives, and will be validated against, the **Stage-5 penetration test (REQ-SEC-04)**. Threat-model tooling and cadence specifics remain an open decision (§8).

**Topology (resolved — load-bearing).** Deployment topology (**decision #3**) is **resolved by [ADR-0006](../adr/0006-deployment-topology.md)**: the **pilot is M1 (fully onsite, per site, no sync)** and the **post-pilot spoke is M3 (LabSolution's own in-PH central sync)**; **M2 public-cloud is not selected.** The **pilot surface** is therefore the **smallest** of the candidates — PHI at rest only in the lab perimeter (TB-7 per-site), **no sync boundary (TB-5)**, no central node, no third-party-cloud boundary. The model still pre-analyzes the **M3** additions (the densest single PHI target at the central node, plus the sync links) so the spoke is pre-thought — but those rows are **[M3 SPOKE — POST-PILOT]** and excluded from the pilot pen-test scope. The M3 surface is finalized at the change-control re-run that gates the spoke (§8, gate doc M3-18).

---

## 2. Assets, ranked by sensitivity — [DRAFTED]

| # | Asset | Why it matters | Regime / Req |
|---|---|---|---|
| A1 | **PHI corpus** — patient demographics + Order/Requisition + Specimen + **Result** (raw_value/raw_unit/raw_code, loinc, ucum_value, status, verified_by, flags) + QCResult | Highest-value asset. Patient identifiers + clinical results = RA 10173 **sensitive personal information**. Any real LIS clears the NPC registration threshold. | RA 10173 / NPC; REQ-PRIV-01/03/04/05; REQ-DATA-01 |
| A2 | **Raw message archive** — stored MLLP / ASTM-family payloads (message header/patient/order/result segments and records), including vendor-specific encoded segments | Also PHI: the raw frames contain patient identifiers and results before normalization. Easy to overlook because it sits at the edge, not in the core DB. Needed for L3/L4 evidence and replay, so it is retained — which makes it a standing breach target. | RA 10173; REQ-SEC-02; REQ-PRIV-03 |
| A3 | **Append-only audit log** — AuditEvent (who/what/when/before/after) | The integrity backbone for non-repudiation, ISO 15189 record control, and breach forensics. If it can be altered or suppressed, every other control becomes unprovable. | ISO 15189:2022; REQ-AUD-01/02; REQ-QMS-01 |
| A4 | **Signing / result-release authority** — pathologist/physician verify-and-release capability; verified_by; status transition to `final`/`corrected` | Misuse releases unverified or wrong results under a clinician's identity — direct patient-safety + RA 4688 / RA 5527 exposure. | RA 4688; RA 5527; REQ-RBAC-01; REQ-DATA-01 |
| A5 | **Credentials & sessions** — named-user accounts, session tokens, service/interface-engine creds, DB creds, sync creds | Compromise collapses RBAC and unlocks A1–A4. Includes machine identities (drivers, sync, FHIR API). Custody/lifecycle of these credentials is the secrets-management requirement. | REQ-RBAC-01; REQ-AUD-02; REQ-SEC-01/02; **REQ-SEC-05** |
| A6 | **Mapping tables** — LOINC/UCUM + vendor-code → canonical maps; analyzer/channel config | Integrity asset, not confidentiality: a silent mapping edit (e.g. mmol/L↔mg/dL, wrong LOINC) yields plausible but clinically wrong results at scale, with no obvious alarm. | ISO 15189:2022; REQ-QMS-02; REQ-DATA-02 |
| A7 | **Keys & secrets** — TLS private keys, at-rest encryption keys, signing material, service/DB/sync credentials | Root-of-trust for SEC-01/02. Key/secret **custody, rotation, and storage** are governed by **REQ-SEC-05 (secrets/credential management)**, which is currently undesigned — see §8. | REQ-SEC-01/02; **REQ-SEC-05**; **[NEEDS-HUMAN]** |

---

## 3. Trust boundaries & data-flow — [DRAFTED]

Boundaries (TB-n) where data crosses a change in trust level, following the reference architecture (`diagrams/01-reference-architecture.png`) left-to-right plus the sync path:

- **TB-1 — Analyzer ↔ interface engine (instrument edge).** HL7 v2.x over MLLP/TCP, ASTM-family LIS serial over RS232, and file-watch / vendor middleware. **This link is frequently PLAINTEXT** — MLLP framing carries no native crypto; serial is physical-layer only. Lowest-trust ingress for PHI. (The specific analyzer models, HL7 minor versions, and ASTM/CLSI standard designations are tracked as engineering assumptions, see `assumptions`.)
- **TB-2 — Interface engine ↔ normalization ↔ core.** The driver/interface layer is **architecturally separate from the OpenELIS core** (channel isolation): each analyzer runs on its own channel; a bad driver must not corrupt the core. Crossing here is "untrusted parsed edge data" → "trusted normalized clinical record."
- **TB-3 — Core ↔ PostgreSQL.** Persistence of Patient/Order/Specimen/Result, append-only result versions, AuditEvent, mapping tables. Encryption-at-rest boundary.
- **TB-4 — Core ↔ FHIR R4 / HL7 v2 outbound ↔ EMR/HIS/PhilHealth.** Egress of PHI to external organizations. Crosses the LabSolution org boundary entirely.
- **TB-5 — Site ↔ central offline sync. [M3 SPOKE — POST-PILOT].** Store-and-forward over the WAN, then replication. Append-only result versions with **explicit reconciliation — NO last-writer-wins**. Conflict and outage surface. **This boundary does NOT exist in the M1 pilot** — it appears only with the M3 spoke.
- **TB-6 — Users ↔ application (RBAC plane).** Medtech / pathologist / lab-admin sessions; the authn/authz boundary protecting A4 (release authority) and A1.
- **TB-7 — On-prem appliance / DB host ↔ physical world.** Edge boxes and per-site DB hosts can be stolen or imaged. **At the M1 pilot this is the per-site lab perimeter** (each lab holds only its own PHI). **[M3 SPOKE — POST-PILOT]** the M3 spoke adds the **central aggregated store** — the *densest single PHI target* (many labs' SPI in one place) on LabSolution's own premises, where NPC Circular 2023-06 **physical** custody duties bite hardest (gate doc M3-9/M3-11).

**Topology note (resolved — ADR-0006):** the **M1 pilot** has **no TB-5** and a per-site **TB-7** (each lab's own PHI only) — the smallest surface, tolerant of WAN loss. The post-pilot **M3 spoke** adds **TB-5** (the sync links) and a **central TB-7** (aggregated multi-lab PHI on LabSolution's own in-PH premises — the densest single target). **M2** (parked) would instead have placed that central store on a third-party, possibly-offshore cloud (extra trust boundary + cross-border posture) — not selected. The pilot model is final at M1; the M3 additions are finalized at the spoke's change-control re-run (§8).

---

## 4. Actors / threat agents — [DRAFTED]

| Actor | Trust | Primary concern |
|---|---|---|
| **Medtech** (RA 5527 scope) | Authorized internal | Over-broad rights; could release/edit beyond medtech scope if RBAC is weak (A4). |
| **Pathologist / physician** | Authorized, high-privilege (release authority A4) | Repudiation of release; credential theft of a high-value account; coerced/negligent release. |
| **Lab admin** | Authorized, high-privilege (config, users, mapping tables A6) | Insider misuse: silent mapping edits, audit suppression, RBAC self-elevation. |
| **External EMR / HIS / PhilHealth** | Semi-trusted partner across TB-4 | Spoofed endpoint, over-pull of PHI, weak partner auth, replay. |
| **Network attacker (LAN/WAN)** | Untrusted | Sniff/tamper plaintext MLLP/ASTM on the lab LAN (TB-1); MITM sync (TB-5). |
| **Malicious / negligent insider** | Authorized but hostile/careless | Bulk PHI exfiltration (A1/A2), audit tampering (A3), credential sharing. |
| **Compromised or buggy analyzer driver** | Edge code, partly third-party (incl. analyzer-bridge, **MPL-2.0** per ADR-0008) | Malformed/hostile messages attempting to corrupt the core or inject bad results across TB-2 (→ REQ-SEC-03 channel isolation). |

---

## 5. STRIDE threats per boundary — [DRAFTED]

Likelihood/Impact: H/M/L. Verification level maps to the pyramid (L1 unit · L2 component · L3 bench conformance · L4 integration E2E · L5 resilience/chaos · L6 validation/regulatory). **Levels are aligned to the authoritative traceability matrix per requirement** — see the reconciliation note under the table for REQ-SEC-03.

| Boundary | STRIDE | Threat | Affected asset | Lik/Imp | Mitigation (control) | Req ID | Verify |
|---|---|---|---|---|---|---|---|
| TB-1 edge | **I**nfo disclosure | Sniffing **plaintext MLLP/ASTM** on the lab LAN exposes patient identifiers + results in transit (RA 10173 breach) | A1, A2, A5 | TLS/MLLPS on MLLP + sync; segregated instrument VLAN; serial physically isolated where TLS impossible (compensating control) | REQ-SEC-01 | L4, L6 |
| TB-1 edge | **T**ampering | On-path attacker alters an OBX-equivalent result value / ASTM record before ingest → wrong clinical result | A1 | TLS integrity on the channel; checksum + structural validation at parse; conformance fixtures detect malformed frames | REQ-SEC-01, REQ-CONF-01 | L1, L3, L4 |
| TB-1 edge | **S**poofing | Rogue device impersonates a licensed analyzer and feeds fabricated results | A1, A6 | Per-channel device identity / allow-listed source (host:port, serial port binding); channel config locked; mutual TLS where supported | REQ-SEC-01, REQ-SEC-03 | L2, L3 |
| TB-2 core ingress | **E**levation / **T**ampering | **Buggy or hostile driver corrupts the core** — malformed payload, injection, or resource exhaustion crosses from edge code into clinical DB | A1, A3, A6 | **Channel isolation**: interface engine separated from core; per-analyzer channel; core accepts only validated normalized records; bad driver fails its channel without touching the core | **REQ-SEC-03** | **L5** (isolation proof; design L2 now — see note) |
| TB-2 normalize | **T**ampering | Silent mapping-table edit (vendor code → wrong LOINC, mmol/L↔mg/dL) yields plausible-but-wrong results at scale | A6, A1 | Mapping changes under RBAC + change control + audit; LOINC/UCUM map proven end-to-end (LIS-8); revalidation on map change | REQ-QMS-02, REQ-QMS-03, REQ-DATA-02 | L1, L4 |
| TB-6 RBAC | **E**levation / **S**poofing | **Unauthorized result release / privilege misuse** — non-pathologist releases or edits a `final` result | A4, A1 | **Named-user RBAC; unauthorized action denied 403 with recorded denial** (LIS-5); release gated to pathologist/physician role | **REQ-RBAC-01** | L4 |
| TB-6 RBAC | **S**poofing | **Credential theft / weak auth** — stolen or shared account, brute force, no MFA | A5, A1, A4 | Named-user accounts (no shared logins); strong auth policy; secrets/credential management (REQ-SEC-05); access/authentication logging; lockout. **MFA = [NEEDS-HUMAN]** policy decision | REQ-RBAC-01, REQ-SEC-05, REQ-AUD-02 | L2, L4 |
| TB-3 / all | **R**epudiation / **T**ampering | **Audit-log tampering or repudiation** — actor edits/deletes AuditEvent or denies an action | A3 | **Append-only audit (who/what/when/before/after); direct DB mutation FAILS at the DB layer** (LIS-6); access logging | **REQ-AUD-01**, REQ-AUD-02 | L2, L4 |
| TB-7 at rest | **I**nfo disclosure | **Lost/stolen on-prem box or DB image** discloses the entire PHI corpus + raw archive | A1, A2, A3 | **Encryption at rest** on DB + raw-message archive + backups; key custody per REQ-SEC-05 / §8 | REQ-SEC-02, REQ-SEC-05 | L6 |
| TB-5 sync **[M3]** | **T**ampering / D | **Sync conflict causes silent data loss / wrong result** — two sites edit the same result; last-writer-wins would silently drop one | A1 | **Append-only result versions + explicit reconciliation; NO last-writer-wins** (Stage 4); conflicting versions surfaced, never overwritten | **REQ-RES-02**, REQ-DATA-01 | L4, L5 |
| TB-5 sync **[M3]** | **D**enial of service | **WAN outage drops results** queued at a site | A1 | **Store-and-forward queue; zero loss across WAN outage**; replay on reconnect (Stage 4) | **REQ-RES-01** | L5 |
| TB-5 sync **[M3]** | **I**nfo disclosure / S | MITM or spoofed peer on the WAN sync link reads/forges PHI between site and central | A1, A5 | TLS on sync transport; mutual peer authentication; encrypted store-and-forward payloads; sync credential custody (REQ-SEC-05) | REQ-SEC-01, REQ-SEC-02, REQ-SEC-05 | L4, L6 |
| TB-4 egress | **S**poofing / I | Spoofed EMR/PhilHealth endpoint or over-broad FHIR pull exfiltrates PHI to a wrong party | A1, A5 | TLS + authenticated FHIR R4 API; scoped authorization per partner; egress audited; documented lawful basis | REQ-SEC-01, REQ-PRIV-05, REQ-AUD-02 | L4, L6 |
| TB-4 egress | **R**epudiation | No record of which PHI left to which partner when (RA 10173 accountability) | A3, A1 | Egress logged to append-only audit; Records of Processing Activities | REQ-AUD-02, REQ-PRIV-07 | L4, L6 |
| Supply chain | (non-security caveat) | analyzer-bridge license **confirmed MPL-2.0** (ADR-0008; earlier "TBD" was a GitHub `NOASSERTION` false-negative); OpenELIS is MPL-2.0 file-level copyleft — both honored under one inventory, not a runtime exploit | A6, build | MPL-2.0 file-level obligations honored across core + bridge (REQ-LIC-01); `NOTICE` + per-file headers on modified files; pinned submodule snapshot (ADR-0001) | **REQ-LIC-01**, **REQ-LIC-02**, REQ-VAL-02 | L6 |

**[M3] rows — post-pilot.** Every row whose boundary is **TB-5 sync [M3]** belongs to the post-pilot **M3 spoke**, not the pilot. They are kept here so the spoke is pre-thought, but they are **excluded from the pilot pen-test scope** and are (re)validated at the spoke's change-control threat-model re-run (REQ-QMS-03 / gate doc M3-18). The pilot's resilience testing covers **single-site** edge/analyzer restart only — not WAN-outage or sync-conflict.

**Reconciliation note — REQ-SEC-03 (channel isolation).** The traceability matrix is authoritative: **REQ-SEC-03 is verified at L5 (resilience/chaos) and gated/verified at Stage 5** ("fault-inject malformed/hostile analyzer messages; isolation holds under chaos"), with the **design baseline established in Stage 0**. The driver side may be exercised at **L2 component (driver vs simulated analyzer)** during Stages 1–3, but the **isolation proof itself is the L5 core-side chaos test**. This model defers to that: TB-2's verify cell reads **L5 (isolation proof; L2 design now)** and §6 records the same gating, so the three artifacts no longer diverge.

---

## 6. Mitigations summary — controls mapped to requirements & gating stage — [DRAFTED]

| Control | Req ID | Gated at | Status |
|---|---|---|---|
| Named-user RBAC; unauthorized → 403 + recorded denial | REQ-RBAC-01 | **Stage 0 — LIS-5 / S0.3** | Stage-0 gated |
| Append-only audit (who/what/when/before/after); direct mutation fails at DB | REQ-AUD-01 | **Stage 0 — LIS-6 / S0.4** | Stage-0 gated |
| Result store: raw + normalized + append-only versions | REQ-DATA-01 | **Stage 0 — LIS-7 / S0.5** | Stage-0 gated |
| LOINC/UCUM normalization proven end-to-end | REQ-DATA-02 / REQ-QMS-02 | **Stage 0 — LIS-8 / S0.6** | Stage-0 gated |
| Channel isolation — bad driver cannot corrupt core | REQ-SEC-03 | Design baseline Stage 0; **isolation proven at L5 (chaos), gated/verified Stage 5** | Design baseline now; verified Stage 5 |
| Reproducible pinned-submodule snapshot | REQ-VAL-02 | **Stage 0 — LIS-4 / S0.2** (ADR-0001) | Stage-0 gated |
| MPL-2.0 honored across core + bridge | REQ-LIC-01, REQ-LIC-02 | Stage 0 — LIS-3 | **Resolved:** bridge = MPL-2.0 (ADR-0008); HOLD-001 lifted |
| Secrets / credential management (key & service-cred custody, rotation) | REQ-SEC-05 | Designed pre-Stage-5; verified **Stage 5** | Undesigned — [NEEDS-HUMAN] (§8) |
| Per-analyzer bench conformance before "supported" | REQ-CONF-01 | Stages 1–3 | Later |
| Store-and-forward; zero loss on WAN outage | REQ-RES-01 | **[M3 spoke — post-pilot]** (pilot covers single-site edge restart only) | Deferred to M3 gate |
| Append-only result versions + explicit reconciliation (no LWW) | REQ-RES-02 | **[M3 spoke — post-pilot]** | Deferred to M3 gate |
| TLS on MLLP edge (encryption in transit) | REQ-SEC-01 | **Stage 5** verified (pilot); **+ sync channel at the M3 spoke** | Later |
| Encryption at rest (per-site DB) | REQ-SEC-02 | **Stage 5** verified (pilot, lab box); **+ central store at the M3 spoke** | Later |
| Access / authentication logging | REQ-AUD-02 | Stage 0 baseline → Stage 5 hardened | Partial |
| Penetration test + remediation | REQ-SEC-04 | **Stage 5** | Later |
| NPC registration / breach runbook / DSR / retention | REQ-PRIV-01/02/03/04/05/06/07 | **Stage 5** (file before go-live) | Later — mostly [NEEDS-HUMAN] |

**Reading of the table:** the integrity spine (RBAC, append-only audit, raw+normalized result store, reproducible snapshot) is enforced **now, in Stage 0**. The confidentiality spine (TLS in transit, encryption at rest, secrets management) and the privacy filings are **Stage-5-verified** but their requirements are declared from sprint 1 so they are designed into, not bolted onto, the system. Channel isolation (REQ-SEC-03) is **designed in Stage 0 and proven at L5 in Stage 5**, consistent with the matrix.

---

## 7. Residual risks, assumptions & Stage-5 pen-test scope — [DRAFTED] / [NEEDS-HUMAN]

**Residual risks accepted at Stage 0:**

- **R1 — Plaintext edge links remain until REQ-SEC-01 lands (Stage 5).** Many analyzers (serial ASTM-family units; older HL7 v2.x units that may not support TLS natively) may never support TLS → permanent reliance on compensating controls (segregated VLAN, physical isolation). The pen-test must validate the segmentation, not assume TLS everywhere. **[NEEDS-HUMAN]** to accept the compensating-control posture.
- **R2 — Key/secret custody undesigned (A7, REQ-SEC-05).** Encryption-at-rest and TLS are only as strong as key/secret management, which does not yet exist (§8). Until decided, REQ-SEC-02 is "checkbox-present, root-of-trust-unproven."
- **R3 — Insider with lab-admin rights** can still edit mapping tables and user roles. Mitigated by audit + change control, but not prevented; needs separation-of-duties policy (post-Stage-0 RBAC refinement).
- **R4 — analyzer-bridge license RESOLVED (was HOLD-001).** The bridge is **MPL-2.0** (ADR-0008); reuse is permitted and the obligation folds into the REQ-LIC-01 MPL-2.0 inventory. Residual: add `NOTICE` + per-file MPL headers on modified files (hygiene, not a blocker).
- **R5 — Topology (#3) ✅ RESOLVED (ADR-0006).** The **pilot** surface is final at **M1** (no TB-5; per-site TB-7). The TB-5 sync boundary and the central TB-7 are introduced **only** by the post-pilot **M3 spoke** and carry their own residual-risk pass at the spoke's change-control threat-model re-run (gate doc M3-18) — they are **not** open risks for the pilot.

**Assumptions** are listed in the structured `assumptions` field.

**The Stage-5 penetration test (REQ-SEC-04) must, at minimum, cover:**
1. MLLP/ASTM interception & tampering on the lab LAN; verify TLS + VLAN segmentation (R1).
2. RBAC bypass / privilege escalation, especially unauthorized result release (REQ-RBAC-01, A4).
3. Audit-log tampering — attempt direct DB mutation; confirm it fails (REQ-AUD-01, A3).
4. Hostile-driver fuzzing across TB-2; confirm channel isolation holds (REQ-SEC-03, proven at L5 chaos).
5. **[M3 SPOKE — POST-PILOT]** Sync conflict + WAN-outage chaos; confirm no silent loss / no LWW (REQ-RES-01/02) — overlaps L5. *(Not in the pilot pen-test; part of the M3 spoke's change-control validation.)*
6. Encryption-at-rest validation on a seized/imaged box (REQ-SEC-02, A2/A7).
7. FHIR R4 / partner-egress authz and PHI over-pull (TB-4).
8. Credential/auth attacks; secrets-management posture incl. key/credential exposure and rotation; MFA posture (REQ-SEC-05, REQ-AUD-02).

---

## 8. Deferred decisions (HITL)

- **Key & secrets management (REQ-SEC-05)** — where TLS private keys, at-rest encryption keys, and service/DB credentials live (HSM? KMS? OS keystore?), rotation, and custody. At **M1** this is **per-site** (the lab holds its own keys); **[M3 SPOKE]** the central node adds LabSolution's custody of keys to **aggregated multi-lab PHI** on its own premises (gate doc M3-11). Blocks the root-of-trust for REQ-SEC-01/02 (A7, R2). **[NEEDS-HUMAN]**
- **TLS / PKI approach** — CA model (internal CA vs per-site self-signed vs managed), mutual-TLS for analyzers/sync, and the fallback for analyzers that cannot do TLS. Shapes REQ-SEC-01 + R1. **[NEEDS-HUMAN]**
- **Deployment topology (open decision #3)** — ✅ **RESOLVED by [ADR-0006](../adr/0006-deployment-topology.md):** pilot = M1 (fully onsite, no TB-5); post-pilot spoke = M3 (own in-PH central sync, adds TB-5 + central TB-7); M2 (public cloud) not selected. The **pilot** model is final; the **M3** additions are finalized at the spoke's change-control re-run ([gate doc](m3-sync-compliance-gate.md) M3-18). No longer blocking.
- **v1 fleet scope (open decision #4)** — ✅ **RESOLVED by [ADR-0008](../adr/0008-interface-engine-stack-and-fleet-scope.md):** minimal **HL7-v2.x/MLLP-first** v1 fleet (anchor RAYTO RAC-050, result-ingestion first; exact machines pinned at pilot-fleet confirmation). The **ASTM-serial group, proprietary middleware (Snibe/Mindray DMS), and bidirectional host-query are deferred post-pilot under change control (REQ-QMS-03)** — keeping the pilot TB-1/TB-2 surface and REQ-CONF-01 burden minimal.
- **MFA / strong-auth policy** for high-privilege roles (pathologist release authority A4, lab admin). **[NEEDS-HUMAN]**
- **Threat-model tooling & cadence** — adopt a tool/format (e.g. a STRIDE/data-flow tool — confirm choice) and the re-run cadence (per stage gate vs per quarter), anchored to **REQ-QMS-03 (change control & revalidation)**; ownership of the living model defers to the regulatory/QA owner (decision #5). **[NEEDS-HUMAN]**
- **Regulatory ownership (open decision #5)** — ✅ **RESOLVED by [ADR-0007](../adr/0007-regulatory-ownership-and-responsibility-allocation.md):** **Artis Lindy Pinote** (accountable QA/regulatory owner) owns the security-posture sign-off, the living-threat-model ownership, and the pen-test engagement scope (REQ-SEC-04). No longer blocks closing LIS-10.

## Reading

- RA 10173 (Data Privacy Act of 2012) + NPC breach-notification rules — basis for PHI breach threats and A1/A2 classification.
- NPC Circular 2022-04 (registration via NPCRS) — threshold and filing context for REQ-PRIV-01 (Circular 17-01 is obsolete).
- ISO 15189:2022 — record control, audit trail, equipment/result traceability, change control (drives REQ-AUD-01, REQ-QMS-01/02/03; :2012 retired end-2025).
- OWASP Threat Modeling / STRIDE reference — methodology baseline for §1.
- HL7 v2.x MLLP transport and ASTM-family LIS interface standards — to ground TB-1 plaintext/tampering analysis. Specific HL7 minor versions, CLSI/ASTM standard designations, and analyzer models are drawn from the engineering research report and are pending confirmation (see `assumptions`).
- LabSolution reference architecture (`diagrams/01-reference-architecture.png`) and regulatory-controls map (`diagrams/06-regulatory-controls-map.png`); verification pyramid (`diagrams/08-verification-pyramid.png`).
- ADR-0001 (`docs/adr/0001-repository-topology-submodule-umbrella.md`) — pinned-snapshot basis for REQ-VAL-02.
- Research report §5.2 (channel isolation/layering) and §10 (design obligations) — `LIS_BUILD_AND_INTEGRATION_RESEARCH.md`.
- HOLD-001 **lifted (2026-06-25)** — openelis-analyzer-bridge license confirmed **MPL-2.0** (ADR-0008); folds into REQ-LIC-01.
