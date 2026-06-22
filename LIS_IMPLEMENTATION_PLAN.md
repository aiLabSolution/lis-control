# LIS Implementation Plan — Phased, Verifiable Delivery

> Companion to `LIS_BUILD_AND_INTEGRATION_RESEARCH.md`. Audience: LabSolution
> engineering + operations leadership. Status: **plan for execution** (2026-06-21).
>
> This plan expands the research report's §11 roadmap into executable stages. Its
> organizing rule: **no stage is "done" on code-complete — each closes on a
> verifiable output** (an automated test, a reproducible demo on staging, or a
> signed compliance artifact). The verification column is the contract.

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
| **C — API & Offline** | FHIR R4, outbound HL7 to HIS, store-and-forward, site↔central sync | Stage 4 (designed from Stage 0) |
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
| **1 — HL7 v2 edge** | *First result through the pipe* (RAC-050 + Mindray labXpert) | 1,2,3,4 | 4–6 wks |
| **2 — ASTM/serial edge** | Chemistry/electrolyte fleet (DiaSys + 5 serial units) | 1,2,3,4 | 6–8 wks |
| **3 — Proprietary tails** | MAGLUMI (SnibeLis) + Mindray BC (DMS) | 2,3,4 | 4–6 wks |
| **4 — FHIR API + offline** | EMR-ready + outage-proof + on-prem deploy kit | 1,4,5 | 4–6 wks |
| **5 — Validation + pilot** | IQ/OQ/PQ signed; pilot go-live; NPC registered | 3,4,5,6 | 4–6 wks |
| **6 — Scale-out (optional)** | 2nd site from kit; upstream generic plugins | 3,4,6 | ongoing |

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
**Goal:** one MLLP listener + HL7 v2.3 parser covers the whole clean-HL7 group;
prove it end-to-end on **RAYTO RAC-050** and **Mindray labXpert**.

**Key tasks**
- **MLLP listener:** frame `0x0B <msg> 0x1C 0x0D`; original **and** enhanced ACK modes.
- **HL7 v2.3 parser** (tolerant): MSH/PID/PV1/ORC/OBR/OBX/NTE/MSA/ERR/SPM.
- **Normalization service:** vendor code → LOINC, unit → UCUM, QC flags; persist raw + normalized.
- **Bidirectional** host-query for labXpert (TCP server/client) + **file-mode** fallback ingest.
- Build conformance fixtures from the RAC-050 and labXpert manuals; raw-message archive + replay.

**Deliverables:** edge driver service; HL7 parser; normalization service; fixtures.

**✅ Verifiable output (exit gate)**
- 🎯 **Milestone — first result:** a captured RAC-050 `ORU^R01` replayed over MLLP
  produces a normalized **Result** row (raw_code+raw_unit preserved; LOINC+UCUM
  populated; status=final), asserted by an **automated E2E test**; the listener
  returns a correct **`ACK^R01` (MSA-1 = AA)**.
- **labXpert bidirectional:** a host-query is answered and a result returns; the
  **file-mode** path also yields a result (both transports tested).
- **Tolerant-parse negatives:** under-populated / mis-ordered-component variants ingest without crash.
- **Round-trip:** archived raw message re-ingests to a byte-identical normalized row.
- Demo on staging from a real or captured instrument message.

---

### Stage 2 — ASTM / serial edge
**Goal:** the ASTM E1381/E1394 stack (to the DiaSys ASTM-HOST spec) + the small
serial fleet via the analyzer-bridge RS232 connector.

**Key tasks**
- **Low level (ASTM E1381):** ENQ/ACK/NAK/EOT contention; framing; **modulo-256 checksum**; RS232 settings/unit.
- **High level (ASTM E1394):** records H→P→O→R→C/Q/L; query record for bidirectional.
- Route **ERBA EC90, GOLDSITE GPP-100, HETO Konig AP300, MEDICA ES, HORRON EA2000**; confirm direction per unit on the bench.
- **HORRON:** re-verify the vision-extracted serial/DB9 detail against the source PDF before coding.

**Deliverables:** ASTM driver; serial channel configs; per-unit conformance reports.

**✅ Verifiable output (exit gate)**
- A **DiaSys R920** ASTM session decodes: checksum validated, H→P→O→R→L parsed,
  result normalized; a **corrupted frame triggers NAK + retransmit** (negative test).
- Each serial unit has a **signed bench-conformance report** (direction confirmed,
  sample result captured + normalized, raw archived).
- 🚦 **HORRON gate:** driver **not merged** until source-PDF re-verification is signed off (explicit checklist item).
- DiaSys + ≥4 serial units **live on staging** with reports; checksum/NAK negatives pass in CI.

---

### Stage 3 — Proprietary middleware tails
**Goal:** the two non-vanilla families — **MAGLUMI via SnibeLis/SnibeLinker** and
**Mindray BC hematology via DMS** — at highest reverse-mapping effort.

**Key tasks**
- Prefer configuring **SnibeLis** to emit HL7/ASTM to the engine; fallback = ingest its export/DB.
- **Mindray DMS** export ingest for BC hematology; reverse-map analyte fields.
- Budget explicit reverse-engineering time; capture raw for replay.

**Deliverables:** SnibeLis channel; Mindray DMS ingest; mapping tables.

**✅ Verifiable output (exit gate)**
- A **MAGLUMI** immunoassay result flows MAGLUMI → SnibeLis → engine → normalized
  Result (LOINC/UCUM), asserted E2E; **QC results flagged** correctly.
- A **Mindray BC** result via DMS export produces a normalized **CBC panel** covering the documented analytes.
- Any unit lacking a clean interface has a **documented fallback** (export/DB parser) with a conformance test.
- ≥1 MAGLUMI model + ≥1 BC model **live on staging**; reverse-mapping documented.

---

### Stage 4 — FHIR R4 API + offline/sync
**Goal:** EMR-ready API and rural-ready resilience; the part that makes outages survivable.

**Key tasks**
- **HAPI FHIR R4:** ServiceRequest, Specimen, DiagnosticReport, Observation, Patient, Device; outbound HL7 v2 to HIS.
- **Store-and-forward** durable queue at the edge; **site↔central** replication with
  **append-only result versions + explicit reconciliation** (no last-writer-wins).
- Offline-durable audit; **on-prem deploy kit**.

**Deliverables:** FHIR API; sync service; deploy kit; chaos tests.

**✅ Verifiable output (exit gate)**
- **FHIR conformance:** a result returns as a valid R4 **DiagnosticReport + Observation**
  (passes `$validate`); an order posts as **ServiceRequest**.
- 🔌 **Outage test (key):** sever WAN → ingest N results at edge → restore link →
  **all N forwarded, zero loss**, audit merges with **no gaps**; queue survives an edge restart.
- **Sync-conflict test:** concurrent edits produce **versioned results + a reconciliation entry** (never silent LWW).
- **Deploy kit:** a single-site on-prem install completes on a clean box; smoke test green.

---

### Stage 5 — Validation + pilot (production at one site)
**Goal:** make it auditable and put it live at one lab under supervision.

**Key tasks**
- Execute **IQ/OQ/PQ** against the traceability matrix; resolve deviations.
- **QC engine:** Westgard multirules, Levey-Jennings, delta checks; autoverification gating.
- File **NPC registration**; **pen-test** + remediation; user training; cutover runbook.

**Deliverables:** validation dossier; QC config; pilot deployment; pen-test report; NPC confirmation.

**✅ Verifiable output (exit gate)**
- **Signed IQ/OQ/PQ dossier:** every requirement traced to a test case with evidence; deviations closed.
- **QC behavior:** a Westgard violation (e.g., 1₃s / 2₂s) **blocks autorelease**;
  Levey-Jennings renders; a delta-check flags an implausible change (test vectors).
- **Security:** pen-test criticals remediated; **TLS on MLLP/sync** + **encryption at rest** verified by test.
- **NPC registration** reference recorded; **breach runbook** tabletop-rehearsed.
- **Pilot UAT:** agreed parallel-run window with discrepancy rate ≤ threshold; **pathologist result-release** workflow exercised; go/no-go signed.

---

### Stage 6 — Scale-out (optional)
**Goal:** repeatable rollout + ride community maintenance.

**✅ Verifiable output**
- A **second site** is provisioned from the deploy kit within the target window; per-site conformance + validation **deltas** recorded.
- **Generic, standards-compliant analyzer plugins contributed upstream** (PR merged
  to `openelisglobal-plugins`); only LabSolution-specific tails kept private.

---

## 4. Milestones

| ID | Milestone | Closes |
|---|---|---|
| **M1** | Core boots reproducibly in CI; audit/RBAC proven | Stage 0 |
| **M2** | 🎯 *First result through the pipe* | Stage 1 |
| **M3** | Chemistry/electrolyte fleet live | Stage 2 |
| **M4** | Proprietary tails integrated | Stage 3 |
| **M5** | EMR-ready + outage-proof | Stage 4 |
| **M6** | Validated pilot go-live | Stage 5 |

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
3. **Deployment topology** — central-cloud + thin sites vs full on-prem per site + central sync.
4. **v1 fleet scope** — HL7 group only first, or commit to full ASTM + proprietary before pilot.
5. **Regulatory ownership** — who owns NPC registration + the ISO 15189 dossier.
6. **Build vs buy the interface engine** — adopt OIE vs minimal bespoke drivers on HAPI/python-hl7.

---

*Diagrams accompanying this plan: reference architecture, this staged roadmap with
its verifiable-output gates, and supporting views (fleet protocol map, data model,
message-exchange sequence, offline-sync topology) — see the Excalidraw set.*
