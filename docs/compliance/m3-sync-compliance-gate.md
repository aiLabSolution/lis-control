# Compliance Extra Work — Gate before the M3 on-prem central-sync spoke

> **Stage-0 SCAFFOLD / GATE CHECKLIST.** Drafted by an agent on **2026-06-24**, pending human
> review **and** confirmation by PH privacy/health-regulatory counsel. **Status:
> `[NEEDS-HUMAN]`.** This is the "**compliance extra work**" that must be completed **before**
> the on-prem central-sync (**M3**) spoke is implemented. It is **not** on the pilot critical
> path — the pilot ships on **M1 (fully onsite)** with none of this (see
> [ADR-0006](../adr/0006-deployment-topology.md)). It is **not formal legal advice.**

---

## 0. Why this gate exists

Per **ADR-0006**, the committed roadmap is:

```
M1 (pilot — committed, no sync)
        → [ THIS GATE: compliance extra work ]
                → M3 (own on-prem central-sync spoke, post-pilot)
```

In the M1 pilot LabSolution is a **software supplier** — **neither PIC nor PIP** under RA
10173 (subject to the zero-PHI-access premise, [§5](#5-the-load-bearing-m1-premise-confirm-before-relying-on-it)) —
so it carries **no** PHI-custody, NPC sync-DPS registration, breach, or cross-border duty
over the lab's data.

Building the M3 spoke **changes that**: LabSolution aggregates PHI from multiple labs onto a
central node it operates on its own PH premises, becoming a **PIP with physical custody**.
That flips on a block of direct statutory obligations. This checklist enumerates them so the
spoke **cannot be built ahead of the paperwork**. Implementing M3 is itself a
**change-control / revalidation delta on the M1 known base** (REQ-QMS-03) — not a
re-validation from zero.

Full requirement-by-requirement analysis and citations:
[`responsibility-and-deployment.md`](responsibility-and-deployment.md) §4.3, §5, §6.

## Status legend

| Marker | Meaning |
|---|---|
| `[GATE]` | A hard prerequisite — the M3 spoke must not go live until this is satisfied. |
| `[NEEDS-HUMAN]` | Requires a human decision, appointment, signature, filing, or counsel review. |
| `[DRAFTED]` | Can be drafted/built now; sign-off/execution is human. |

---

## 1. RA 10173 status & registration (LabSolution becomes a PIP)

| # | Extra-work item | Status | Owner | Req ID |
|---|---|---|---|---|
| M3-1 | **Re-characterize LabSolution as a PIP with physical custody** for the aggregation processing; record the change from the M1 "neither" position. Confirm with counsel (NPC advisory-opinion route is authoritative). | `[GATE]` `[NEEDS-HUMAN]` | DEC-01 owner + counsel | REQ-PRIV-01 |
| M3-2 | **Register LabSolution's own aggregation DPS with the NPC (NPCRS).** NPC Circular 2022-04 Sec. 5(B): "a PIP who uses its own system as a service to process personal data must register." Disclose the in-PH central node (no offshore sub-processor to name). Verify the aggregate-SPI threshold (≥1,000 across labs is likely crossed). | `[GATE]` `[NEEDS-HUMAN]` | DPO (DEC-02) | REQ-PRIV-01 |
| M3-3 | Confirm the **lab still registers the operational LIS as PIC** — M3 does not remove the lab's primary, non-delegable accountability (RA 10173 Sec. 21). | `[NEEDS-HUMAN]` | DPO + customer labs | REQ-PRIV-01 |

## 2. Contracts — head DPA + flow-down (Rule X)

| # | Extra-work item | Status | Owner | Req ID |
|---|---|---|---|---|
| M3-4 | **Execute the head PIC→PIP DPA** (lab → LabSolution) per IRR Rule X (Secs. 43–45): process only on documented instructions; confidentiality; security measures; further-processor only with prior authorization; assist with data-subject rights + breach; delete/return on termination; submit to audits; flag unlawful instructions; state subject-matter/duration/data types/data-subject categories/geographic location. **Use a DPA, not a DSA.** | `[GATE]` `[NEEDS-HUMAN]` | Counsel + DPO | REQ-PRIV-09 |
| M3-5 | **Back-to-back flow-down to any PHI-touching analyzer middleware** (e.g. Mindray DMS — SnibeLis/SnibeLinker dropped from the topology 2026-07-06, LIS-178) that transits the sync path. M3 has the **shortest** sub-processor chain (no public-cloud IaaS provider) — typically the head DPA only, plus middleware where PHI actually transits. | `[GATE]` `[NEEDS-HUMAN]` | Counsel + DPO | REQ-PRIV-09 |
| M3-6 | Confirm the **vendor PHI boundary per middleware component** — does PHI actually transit it, or only de-identified instrument data? Determines whether a flow-down DPA is required (DEC-17). | `[NEEDS-HUMAN]` | DPO + eng | REQ-PRIV-09 |

## 3. Breach apparatus (LabSolution's own, as PIP)

| # | Extra-work item | Status | Owner | Req ID |
|---|---|---|---|---|
| M3-7 | Stand up LabSolution's **own Security Incident Management Policy + Data Breach Response Team + incident documentation**, and file the **annual security-incident report** to the NPC. (The 72-h*-style* notification to NPC/data subjects stays the **lab's** as PIC; LabSolution-as-PIP notifies the lab per the DPA and a cloud/middleware breach flows up the chain.) *Confirm the live notification window + citing instrument (DEC-12) before finalizing the runbook.* | `[GATE]` `[NEEDS-HUMAN]` | DPO + security | REQ-PRIV-02 |
| M3-8 | Wire **detect-and-escalate** for the central node into LabSolution's own monitoring (the aggregated store raises the breach-impact profile — many labs' SPI in one place). | `[DRAFTED]` | Engineering | REQ-PRIV-02, REQ-AUD-02 |

## 4. Security & physical custody (NPC Circular 2023-06 bites hardest here)

| # | Extra-work item | Status | Owner | Req ID |
|---|---|---|---|---|
| M3-9 | **Datacenter physical / environmental controls** for LabSolution's own central node — physical access control, physical-media handling/logging, secure off-site storage. A **direct, non-delegable** PIP duty (cannot be delegated to a cloud provider as in M2). *(Confirm the exact 2023-06 physical-measure wording against the signed text.)* | `[GATE]` `[NEEDS-HUMAN]` | Eng + security | REQ-SEC-02, REQ-SEC-03 |
| M3-10 | **BCP / backup-restore with recovery-time objectives** for the aggregated store. **Watch:** if backups/DR replicate to an offshore region, M3 silently acquires an M2-style cross-border transfer — keep DR in-PH or treat it as a cross-border decision (REQ-PRIV-08). | `[GATE]` `[NEEDS-HUMAN]` | Eng + security | REQ-RES-01, REQ-PRIV-08 |
| M3-11 | **Central key custody & rotation** — LabSolution holds the at-rest encryption keys to **aggregated multi-lab PHI** on its own premises; a direct custody duty. Design before any M3 encryption verification (DEC-09). | `[GATE]` `[NEEDS-HUMAN]` | Eng lead | REQ-SEC-05, REQ-SEC-02 |
| M3-12 | **At-rest encryption of the aggregated central store** + **TLS / mutual-auth on the store-and-forward sync channel** (DEC-10). | `[DRAFTED]` / verified pre-go-live | Engineering | REQ-SEC-01, REQ-SEC-02 |
| M3-13 | **Per-site channel/tenant isolation in the central node** — segregate each lab's data; this is where the sync-boundary threat (TB-5) bites. | `[DRAFTED]` | Architecture | REQ-SEC-03 |
| M3-14 | **Pen-test LabSolution's own central/sync infrastructure** (each party pen-tests what it operates). | `[NEEDS-HUMAN]` | Security + external | REQ-SEC-04 |

## 5. Governance, RoPA/PIA, DPO for the new processing

| # | Extra-work item | Status | Owner | Req ID |
|---|---|---|---|---|
| M3-15 | Maintain LabSolution's **own RoPA + PIA** for the sync/aggregation processing it performs as a PIP. | `[NEEDS-HUMAN]` | DPO | REQ-PRIV-07 |
| M3-16 | Designate a **DPO / compliance officer for the LIS-PHI processing LabSolution performs as a PIP** (IRR Sec. 26), in addition to its corporate DPO. | `[NEEDS-HUMAN]` | DEC-01 owner | REQ-PRIV-06 |
| M3-17 | Confirm LabSolution's duty to **assist the lab** with data-subject rights and breach duties under the DPA (Rule X). | `[DRAFTED]` | DPO | REQ-PRIV-04 |

## 6. Validation / change control (the spoke is a delta on the M1 base)

| # | Extra-work item | Status | Owner | Req ID |
|---|---|---|---|---|
| M3-18 | **Re-run the threat model** for the M3 surface — add back TB-5 (sync boundary) and the central-node TB-7 (densest single PHI target); anchored to change control. | `[GATE]` | QA/regulatory owner | REQ-QMS-03 |
| M3-19 | **Validate the sync spoke as a change-control delta** (REQ-QMS-03) on the validated M1 snapshot: store-and-forward zero-loss across WAN outage (REQ-RES-01), append-only result versions + explicit reconciliation, **no last-writer-wins** (REQ-RES-02). Resilience/chaos at L5. | `[GATE]` | Validation lead + QA | REQ-RES-01, REQ-RES-02 |
| M3-20 | Update the **traceability matrix, NPC checklist, VMP, and PIA** to the M3 scope; supplier-qualify LabSolution's hosting under ISO 15189 Cl. 6.8 (the lab "remains responsible" for the externally-hosted system under Cl. 7.6). | `[NEEDS-HUMAN]` | QA + DPO | REQ-QMS-01 |

---

## 7. The load-bearing M1 premise (confirm before relying on it)

The M1 pilot's "neither PIC nor PIP" position — and therefore the fact that **none** of the
above applies to the pilot — holds **only if LabSolution genuinely never accesses, stores, or
receives PHI** in M1, including via remote-support sessions that view live data, **telemetry,
crash dumps, error logs, automatic backups, or update channels that pull data back**, and
including **offshore staff** remote access (itself a cross-border processing event). This is a
reasoned extrapolation from the broad RA 10173 Sec. 3(o) definition of "processing," **not
settled PH law**.

**Even for the M1 pilot:** confirm the actual data-flow with engineering, confirm the
characterization with counsel (an NPC advisory-opinion request is authoritative), and lock any
residual access down with a **scoped support DPA + break-glass controls** (DEC-17 /
REQ-PRIV-09). If the premise fails, M1 is a latent PIP and part of this gate already applies.

## 8. The one topology-invariant duty — FDA SaMD

If the LIS's **autoverification / QC-gating / clinical-decision-support** functions qualify the
product as Medical Device Software, the **legal manufacturer (LabSolution)** owes an FDA
**License to Operate + CMDN/CMDR** registration — **the same in M1, M2, and M3** (classification
follows function, not deployment). This is **not** part of the M3 gate; it is tracked
separately (REQ-REG-01) and may bite at the pilot regardless of topology. Needs an FDA
pre-submission classification (the MDSW circular is draft/unsigned as of 2026-06-24).

## Deferred decisions (HITL)

- **DEC-03 (topology)** — resolved by ADR-0006 (M1 pilot; M3 spoke; M2 parked). This gate is the
  consequence.
- **DEC-12** — live NPC breach-notification window + citing instrument (M3-7).
- **DEC-09 / DEC-10** — central key custody + TLS/PKI for the sync channel (M3-11, M3-12).
- **DEC-17** — vendor PHI boundary per middleware component (M3-5, M3-6) and the M1 support-access
  boundary (§7).
- **REQ-REG-01** — FDA SaMD classification (§8), topology-invariant.

## Reading

- [`responsibility-and-deployment.md`](responsibility-and-deployment.md) — full citations (RA
  10173 / IRR Rule X, NPC Circulars 2022-04 / 16-03 / 2023-06, NPC Advisories 2024-01 / 2025-01,
  ISO 15189:2022 Cl. 6.8 / 7.6, FDA draft MDSW circular).
- [ADR-0006](../adr/0006-deployment-topology.md) — the topology decision this gate implements.
- [`traceability-matrix.md`](traceability-matrix.md) — REQ-PRIV-09, REQ-REG-01, REQ-RES-01/02,
  REQ-SEC-* rows.
