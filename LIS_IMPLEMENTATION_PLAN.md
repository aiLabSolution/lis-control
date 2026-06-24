# LIS Implementation Plan — Phased, Verifiable Delivery

> Companion to `LIS_BUILD_AND_INTEGRATION_RESEARCH.md`. Audience: LabSolution
> engineering + operations leadership. Status: **plan for execution** (2026-06-21).
>
> This plan expands the research report's §11 roadmap into executable stages. Its
> organizing rule: **no stage is "done" on code-complete — each closes on a
> verifiable output** (an automated test, a reproducible demo on staging, or a
> signed compliance artifact). The verification column is the contract.
>
> **⮕ DEPLOYMENT-TOPOLOGY DECISION (2026-06-24) — [docs/adr/0004-deployment-topology.md](docs/adr/0004-deployment-topology.md);
> resolves Open Decision #3 below.** The **pilot deploys fully on-site at each lab, with no sync (M1)**. A **central
> sync at LabSolution's own on-prem server (M3)** is a **separate post-pilot "spoke"**, decoupled from the pilot
> critical path and gated by a **compliance extra-work checklist**
> ([docs/compliance/m3-sync-compliance-gate.md](docs/compliance/m3-sync-compliance-gate.md)). **Public-cloud sync
> (M2) is not selected.** Effect on this plan: **Stage 4's site↔central sync moves out of the pilot to the M3
> spoke** (single-site edge store-and-forward + the deploy kit stay in the pilot); the **Stage-5 pilot runs on M1**;
> the M3 sync spoke is validated later as a **change-control delta on the validated M1 base.**

---

## 0. Approach in one screen

- **Strategy (decided in research §6):** fork **OpenELIS Global** (MPL-2.0) as the
  clinical core; build a **LabSolution-owned instrument-driver/interface layer** on
  the **Open Integration Engine** (MPL-2.0 Mirth 4.5.2 fork) + HL7/ASTM toolchain;
  **normalize at ingest** to LOINC/UCUM; expose **FHIR R4**; deploy **offline-first**.
- **Code home:** all forks and LabSolution code live under the GitHub org
  **[aiLabSolution](https://github.com/aiLabSolution/)** — the OpenELIS fork, the
  instrument-driver/interface layer, analyzer plugins, deploy kit, and CI all
  originate and are versioned here. Generic, standards-compliant plugins are
  contributed upstream *from* this org; LabSolution-specific tails stay private within it.
- **Four parallel workstreams** run across the stages, not strictly in series:

| Workstream | Owns | Runs during |
|---|---|---|
| **A — Core** | OpenELIS fork, orders/results/QC/reporting, RBAC, audit, data model | Stages 0→5 |
| **B — Edge/Integration** | Drivers, MLLP/ASTM/serial, normalization, per-analyzer conformance | Stages 1→3 |
| **C — API & Offline** | FHIR R4, outbound HL7 to HIS, single-site store-and-forward (pilot); **site↔central sync = post-pilot M3 spoke** | Stage 4 (pilot parts); M3 spoke (sync) |
| **D — Compliance/QA** | ISO 15189 validation, RA 10173/NPC, audit/RBAC evidence, pen-test | Stages 0→5 (continuous) |

- **Team assumption (from research):** ~2 engineers + 1 QA/regulatory, scaling
  cross-functional at validation. **Indicative total: ~6–9 months** to a validated
  single-site pilot.
- **Cadence:** every merge runs unit + component + E2E against **simulated
  analyzers**; physical instruments are exercised on a **bench-conformance** rig
  before any unit is declared "supported."

---

## 1. Verification model (how "verifiable output" is defined)

A six-level test pyramid; each stage names which levels gate it.

| Lvl | Layer | What it proves | Mechanism |
|---|---|---|---|
| 1 | **Unit** | Parsers/codecs correct (HL7 fields, ASTM records, modulo-256 checksum, LOINC/UCUM mapping) | Fast tests in CI |
| 2 | **Component** | A driver channel behaves against a **simulated analyzer** (replay captured messages) | Simulator harness in CI |
| 3 | **Bench conformance** | A **physical unit** speaks as documented: direction, sample result, raw archived | Signed per-unit conformance report (gate to "supported") |
| 4 | **Integration E2E** | instrument message → normalized result → FHIR resource | Automated on staging |
| 5 | **Resilience/chaos** | Survives WAN outage, edge restart, sync conflict with no data loss | Fault-injection tests |
| 6 | **Validation (regulatory)** | Requirement → test → evidence; auditable under ISO 15189 | IQ/OQ/PQ dossier, signed |

**Traceability matrix** (requirement → test → evidence) is maintained from Stage 0
and becomes the spine of the validation dossier in Stage 5.

---

## 2. Stages at a glance

| Stage | Goal | Gate levels | Effort |
|---|---|---|---|
| **0 — Foundations & compliance scaffold** | Core boots reproducibly; audit/RBAC proven; compliance plan drafted | 1,2,6 | 4–6 wks |
| **1 — HL7 v2 edge** | *First result through the pipe* — **EDAN H60S** (+ HETO AU120); RAC-050 / labXpert deferred | 1,2,3,4 | 4–6 wks |
| **2 — ASTM/serial edge** | Chemistry/electrolyte — **ERBA EC90** (sole available ASTM unit); DiaSys + serial fleet deferred | 1,2,3,4 | 6–8 wks |
| **3 — Proprietary tails** | **MAGLUMI X3** (SnibeLis) + RT-7600 candidate; Mindray BC deferred | 2,3,4 | 4–6 wks |
| **4 — FHIR API + offline** | EMR-ready + outage-proof + on-prem deploy kit *(site↔central sync descoped to the M3 spoke)* | 1,4,5 | 4–6 wks |
| **5 — Validation + pilot (M1, fully onsite)** | IQ/OQ/PQ signed on M1; pilot go-live; **lab files PIC NPC registration** | 3,4,5,6 | 4–6 wks |
| **M3 — On-prem central-sync spoke (post-pilot)** | site↔central sync to LabSolution's own in-PH server; **gated by the [compliance extra-work checklist](docs/compliance/m3-sync-compliance-gate.md)** + a change-control validation delta on the M1 base | 4,5,6 | after pilot |
| **6 — Scale-out (optional)** | 2nd site from kit; upstream generic plugins | 3,4,6 | ongoing |

> **⚠️ Availability re-scope (2026-06-26).** The physically-available test fleet
> (confirmed by Pinote/LabSolution) does **not** include most of the machines named in
> Stages 1–3. They are re-scoped onto available equivalents — **Stage 1 → EDAN H60S**
> (HL7/MLLP), **Stage 2 → ERBA EC90** (ASTM), **Stage 3 → SNIBE MAGLUMI X3** (SnibeLis).
> The named-but-unavailable machines (RAC-050, "Mindray labXpert", DiaSys R920, the
> serial fleet, Mindray BC) are **deferred, not dropped** — they re-enter when the
> hardware is on hand. The **protocol contract per stage is unchanged**; only the named
> instrument changes. Full cross-check, readiness, and per-machine access status:
> [`docs/testing/stage-1-3-machine-access-checklist.md`](docs/testing/stage-1-3-machine-access-checklist.md).
> Tracked as **LIS-74**; per-slice retargeting under LIS-11 / LIS-22 / LIS-31.

---

## 3. Stage detail

### Stage 0 — Foundations & compliance scaffold
**Goal:** a reproducible forked core with audit/RBAC proven and the compliance
skeleton in place — so every later stage validates *deltas on a known base*.

**Key tasks**
- Fork OpenELIS Global **into the `aiLabSolution` GitHub org**
  ([github.com/aiLabSolution](https://github.com/aiLabSolution/)); reproducible
  containerized build; CI pipeline; dev + staging envs.
- Seed **LOINC/UCUM** reference tables; design the result table to store **raw_code,
  raw_unit, loinc, ucum_value, status** side by side (research §5.1).
- Stand up the **analyzer simulator harness** + conformance-fixture repo skeleton.
- **License hygiene:** record MPL-2.0 obligations; open an issue/confirm the
  `openelis-analyzer-bridge` **undeclared license** before any reuse.
- Draft the **Validation Master Plan**, **NPC registration** checklist, threat model.

**Deliverables:** running fork; CI; data dictionary; compliance plan v0; simulator harness.

**✅ Verifiable output (exit gate)**
- `compose up` on a clean checkout brings the core to a **200 health check**; **CI green**.
- **Audit test:** create→update a record yields an append-only `AuditEvent`
  (who/what/when/before/after); a direct mutation of an audit row **fails**.
- **RBAC test:** named-user login enforced; a user lacking role X is **denied (403)** action Y.
- **Normalization seed test:** LOINC/UCUM tables load; ≥1 sample vendor code maps to LOINC + UCUM.
- Compliance artifacts (Validation Master Plan outline + NPC checklist) exist in-repo and are reviewed.

---

### Stage 1 — HL7 v2 edge (*first result through the pipe*)
**Goal:** one MLLP listener + HL7 v2.3 parser covers the whole clean-HL7 group.
**Re-scoped vehicle (2026-06):** prove it end-to-end on **EDAN H60S** (HL7 v2.4 / MLLP /
port 7999; the analyzer is the TCP client, our edge listens), with **HETO AU120** as a
second-vendor HL7 unit on arrival. *Original targets RAYTO RAC-050 + Mindray labXpert are
deferred — not in the available fleet, and "labXpert" is Mindray middleware, not an
analyzer. The protocol contract is unchanged. See the
[access checklist](docs/testing/stage-1-3-machine-access-checklist.md) / LIS-74.*

**Key tasks**
- **MLLP listener:** frame `0x0B <msg> 0x1C 0x0D`; original ACK (EDAN H60S uses
  original-mode ACK; enhanced-ACK only where a unit documents it).
- **HL7 v2.3/2.4 parser** (tolerant): MSH/PID/PV1/ORC/OBR/OBX/NTE/MSA/ERR/SPM.
- **Normalization service:** vendor code → LOINC, unit → UCUM, QC flags; persist raw + normalized.
- **Bidirectional** host-query on EDAN H60S (QRD/QRF). *labXpert's file-mode (shared-folder)
  fallback is deferred — no available unit speaks it (H60S / AU120 are MLLP-only).*
- Build conformance fixtures from the EDAN H60S (+ HETO AU120) LIS manuals; raw-message archive + replay.

**Deliverables:** edge driver service; HL7 parser; normalization service; fixtures.

**✅ Verifiable output (exit gate)**
- 🎯 **Milestone — first result:** a captured **EDAN H60S** `ORU^R01` replayed over MLLP
  produces a normalized **Result** row (raw_code+raw_unit preserved; LOINC+UCUM
  populated; status=final), asserted by an **automated E2E test**; the listener
  returns a correct **`ACK^R01` (MSA-1 = AA)**.
- **Second vendor:** the same parser ingests a **HETO AU120** HL7/MLLP message without
  code changes (vendor-tolerance proof).
- **Bidirectional:** an EDAN H60S host-query (QRD/QRF) is answered and a result returns.
- **Tolerant-parse negatives:** under-populated / mis-ordered-component variants ingest without crash.
- **Round-trip:** archived raw message re-ingests to a byte-identical normalized row.
- Demo on staging from a real or captured instrument message.

---

### Stage 2 — ASTM / serial edge
**Goal:** the ASTM E1381/E1394 stack + serial channels.
**Re-scoped vehicle (2026-06):** **ERBA EC90** is the sole available ASTM unit (ASTM
E1381/E1394; RS232 or Ethernet; **upload-only**). *DiaSys R920 and the GOLDSITE / HETO
Konig / MEDICA / HORRON serial units are deferred (not in the available fleet) — and the
cross-check found several are actually HL7/Ethernet or a proprietary text dump, not ASTM.
See the [access checklist](docs/testing/stage-1-3-machine-access-checklist.md) / LIS-74.*

**Key tasks**
- **Low level (ASTM E1381):** ENQ/ACK/NAK/EOT contention; framing; **modulo-256 checksum**; RS232 settings/unit.
- **High level (ASTM E1394):** records H→P→O→R→C/Q/L; query record for bidirectional.
- Route **ERBA EC90** (electrolyte/ISE); capture its undocumented RS232 baud/pinout on the bench.
- **Coverage gap:** ERBA EC90 is upload-only, so the **bidirectional Q-record + NAK-retransmit**
  negatives need a **bidirectional ASTM unit** (e.g. a DiaSys RESPONS) to be sourced — deferred.

**Deliverables:** ASTM driver; serial channel configs; per-unit conformance reports.

**✅ Verifiable output (exit gate)**
- An **ERBA EC90** ASTM session decodes: checksum validated, H→P→O→R→L parsed, result normalized.
- A **corrupted frame triggers NAK + retransmit**, proven against the **ASTM simulator**
  (EC90 is upload-only; the bidirectional/NAK path stays simulator-driven until a
  bidirectional ASTM unit is on hand).
- **ERBA EC90** has a **signed bench-conformance report** (direction confirmed, sample
  result captured + normalized, raw archived).
- 🚦 **HORRON gate** (when HORRON EA2000 becomes available): driver **not merged** until
  source-PDF re-verification is signed off.
- ERBA EC90 **live on staging** with its report; checksum/NAK negatives pass in CI.

---

### Stage 3 — Proprietary middleware tails
**Goal:** the proprietary middleware tails at highest reverse-mapping effort.
**Re-scoped vehicle (2026-06):** **SNIBE MAGLUMI X3 via SnibeLis** (ASTM E1394; bidirectional
+ QC) is the available tail. *Mindray BC/DMS is deferred (not available); **RAYTO RT-7600**
— available hematology with a proprietary TCP "Netport" stream — is the candidate 2nd tail,
pending a wire-format capture (LIS-76). See the
[access checklist](docs/testing/stage-1-3-machine-access-checklist.md) / LIS-74.*

**Key tasks**
- Stand up the **SnibeLis** middleware PC (vendor license) and prefer configuring it to emit
  to the engine; **fallback = ingest its export/DB** *(the SnibeLis→engine relay is
  undocumented — confirm with SNIBE; LIS-75)*.
- **RAYTO RT-7600:** byte-capture the Netport/serial stream, then reverse-map its CBC fields
  *(replaces the deferred Mindray DMS BC-hematology ingest; LIS-76)*.
- Budget explicit reverse-engineering time; capture raw for replay.

**Deliverables:** SnibeLis channel; RT-7600 ingest; mapping tables.

**✅ Verifiable output (exit gate)**
- A **MAGLUMI X3** immunoassay result flows MAGLUMI → SnibeLis → engine → normalized
  Result (LOINC/UCUM), asserted E2E; **QC results flagged** correctly.
- A **RAYTO RT-7600** result produces a normalized **CBC panel** covering the documented
  analytes *(or a Mindray BC via DMS, when available)*.
- Any unit lacking a clean interface has a **documented fallback** (export/DB parser) with a conformance test.
- ≥1 immunoassay tail (**MAGLUMI X3**) + ≥1 hematology tail (**RT-7600**) **live on staging**; reverse-mapping documented.

---

### Stage 4 — FHIR R4 API + single-site edge resilience
**Goal:** EMR-ready API and single-site resilience; the deploy kit that makes an on-prem
install repeatable. *(Site↔central sync is descoped from the pilot to the post-pilot M3 spoke,
ADR-0004 — see the M3 spoke detail below.)*

**Key tasks**
- **HAPI FHIR R4:** ServiceRequest, Specimen, DiagnosticReport, Observation, Patient, Device; outbound HL7 v2 to HIS.
- **Store-and-forward** durable queue **at the edge, within a site** — an analyzer/edge restart loses no result.
  *(The append-only result-version model is built now so the M3 spoke's cross-site reconciliation has a base; the
  site↔central replication itself is M3.)*
- Offline-durable audit; **on-prem deploy kit** (single-site, M1).

**Deliverables:** FHIR API; single-site edge queue; deploy kit; edge-resilience tests.

**✅ Verifiable output (exit gate)**
- **FHIR conformance:** a result returns as a valid R4 **DiagnosticReport + Observation**
  (passes `$validate`); an order posts as **ServiceRequest**.
- 🔌 **Edge-restart test:** ingest N results at the edge → restart the edge service →
  **all N persisted, zero loss**, audit with **no gaps**.
- **Deploy kit:** a single-site on-prem install completes on a clean box; smoke test green.

---

### Stage 5 — Validation + pilot (M1, fully onsite, production at one site)
**Goal:** make it auditable and put it live at one lab under supervision — **fully on-site, no
sync** (M1, ADR-0004).

**Key tasks**
- Execute **IQ/OQ/PQ** against the traceability matrix on the **M1 topology**; resolve deviations.
- **QC engine:** Westgard multirules, Levey-Jennings, delta checks; autoverification gating.
- **NPC registration:** the **customer lab files as PIC** for the LIS it operates; LabSolution files only its **own
  corporate** registration/sworn declaration if triggered — **no sync-service DPS** (that is the M3 spoke).
- **Pen-test** the on-prem deployment + remediation; user training; cutover runbook.
- **FDA SaMD check (REQ-REG-01):** if autoverification/CDS qualifies the product as a medical device, confirm the
  manufacturer registration path — **topology-invariant, may apply at the pilot.**

**Deliverables:** validation dossier (M1); QC config; pilot deployment; pen-test report; lab NPC confirmation.

**✅ Verifiable output (exit gate)**
- **Signed IQ/OQ/PQ dossier (M1):** every requirement traced to a test case with evidence; deviations closed.
- **QC behavior:** a Westgard violation (e.g., 1₃s / 2₂s) **blocks autorelease**;
  Levey-Jennings renders; a delta-check flags an implausible change (test vectors).
- **Security:** pen-test criticals remediated; **TLS on MLLP** + **encryption at rest (per-site DB)** verified by test.
- **NPC registration** reference recorded (lab PIC); **breach runbook** (the lab's, as PIC) tabletop-rehearsed.
- **Pilot UAT:** agreed parallel-run window with discrepancy rate ≤ threshold; **pathologist result-release** workflow exercised; go/no-go signed.

---

### M3 — On-prem central-sync spoke (post-pilot)
**Goal:** add cross-site aggregation by syncing PHI to **LabSolution's own on-prem server in PH** — **after** the
pilot, as a change-control **delta on the validated M1 base** (not a re-validation). **Public cloud (M2) is not
used.**

**Gate (must precede the spoke):** the **compliance extra work** in
[`docs/compliance/m3-sync-compliance-gate.md`](docs/compliance/m3-sync-compliance-gate.md) — LabSolution becomes a
**PIP with physical custody** and must register its **own aggregation DPS** (NPC), execute the **head DPA +
middleware flow-down**, stand up its **own breach apparatus**, design **central key custody** + datacenter
**physical-security/BCP**, and **re-run the threat model + PIA**.

**Key tasks**
- **Site↔central** store-and-forward replication with **append-only result versions + explicit reconciliation** (no
  last-writer-wins); central node on LabSolution's in-PH infrastructure with per-lab tenant isolation.
- At-rest encryption + key custody for the **aggregated** store; TLS + mutual peer auth on the sync channel.

**Deliverables:** sync service; central node; updated compliance artifacts (matrix/NPC/VMP/PIA at M3 scope); sync-spoke validation delta.

**✅ Verifiable output (exit gate)**
- **M3 compliance gate satisfied** (the checklist above signed off).
- 🔌 **Outage test:** sever WAN → ingest N results at a site → restore link → **all N forwarded to central, zero
  loss**, audit merges with **no gaps**.
- **Sync-conflict test:** concurrent cross-site edits produce **versioned results + a reconciliation entry** (never
  silent LWW).
- **Signed validation delta** on the M1 base (REQ-QMS-03); **LabSolution PIP NPC registration** filed; spoke go/no-go signed.

---

### Stage 6 — Scale-out (optional)
**Goal:** repeatable rollout + ride community maintenance.

**✅ Verifiable output**
- A **second site** is provisioned from the deploy kit within the target window; per-site conformance + validation **deltas** recorded.
- **Generic, standards-compliant analyzer plugins contributed upstream** (PR merged
  to `openelisglobal-plugins`); only LabSolution-specific tails kept private.

---

## 4. Milestones

> *Milestone IDs use an `MS` prefix to avoid collision with the deployment models M1/M2/M3 (ADR-0004).*

| ID | Milestone | Closes |
|---|---|---|
| **MS1** | Core boots reproducibly in CI; audit/RBAC proven | Stage 0 |
| **MS2** | 🎯 *First result through the pipe* | Stage 1 |
| **MS3** | Chemistry/electrolyte fleet live | Stage 2 |
| **MS4** | Proprietary tails integrated | Stage 3 |
| **MS5** | EMR-ready + single-site resilient | Stage 4 |
| **MS6** | Validated pilot go-live (M1, fully onsite) | Stage 5 |
| **MS7** | On-prem central-sync spoke live (post-pilot, after the compliance gate) | M3 spoke |

---

## 5. Cross-cutting execution

- **CI/CD:** unit + component + E2E on every merge against simulated analyzers; conformance fixtures versioned in-repo.
- **Environments:** dev → staging (simulators) → pilot (real instruments).
- **Per-analyzer "supported" checklist** (gate to production for any unit):
  ① protocol doc on file → ② simulator fixture → ③ parser/normalization tests →
  ④ bench-conformance report (direction + sample + raw) → ⑤ E2E green → ⑥ added to supported matrix.
- **Source control:** the **[aiLabSolution](https://github.com/aiLabSolution/)**
  GitHub org is the single home for every fork and all code changes — OpenELIS
  fork, driver/interface layer, plugins, deploy kit, and IaC. Track upstream
  releases; branch per analyzer channel so a unit ships without redeploying the core.
- **License hygiene:** honor MPL-2.0 file-level copyleft; resolve `analyzer-bridge`
  TBD license; keep LabSolution-specific tails private in the org, push generic
  plugins upstream.
- **Risk checkpoints** (research §12): PHI/RA-10173 controls from sprint 1; tolerant
  parsers for spec-deviating units; budget reverse-mapping for tails; append-only
  result versions for sync; verify every `requires_engineer_review` sidecar.

---

## 6. Open decisions to confirm before Stage 1 (research §13)

1. **Core strategy** — confirm "fork OpenELIS" vs greenfield.
2. **Stack language** — Java end-to-end vs polyglot edge (Python drivers + Java core).
3. ~~**Deployment topology**~~ — ✅ **RESOLVED ([ADR-0004](docs/adr/0004-deployment-topology.md), 2026-06-24):** pilot = **M1 fully onsite, no sync**; chosen sync model = **M3 own on-prem central sync** as a post-pilot spoke behind the [compliance extra-work gate](docs/compliance/m3-sync-compliance-gate.md); **M2 public cloud not selected.**
4. **v1 fleet scope** — HL7 group only first, or commit to full ASTM + proprietary before pilot.
5. **Regulatory ownership** — who owns NPC registration + the ISO 15189 dossier.
6. **Build vs buy the interface engine** — adopt OIE vs minimal bespoke drivers on HAPI/python-hl7.

---

*Diagrams accompanying this plan: reference architecture, this staged roadmap with
its verifiable-output gates, and supporting views (fleet protocol map, data model,
message-exchange sequence, offline-sync topology) — see the Excalidraw set.*
