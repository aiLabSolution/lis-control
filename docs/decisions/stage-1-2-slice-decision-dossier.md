# Stage 1 & 2 — Slice Decision Dossier (HITL)

> **Purpose.** Consolidates the **stage-1 and stage-2 slices that are blocked on a human
> decision or human action** — i.e. the slices currently parked in Plane states
> `ready-for-human` (*requires human implementation/action*) or `needs-info` (*waiting on
> information*), per [`docs/agents/triage-labels.md`](../agents/triage-labels.md). Each entry
> states the decision, why it matters, the options, a recommendation, the owner, and what it
> gates — so the call can be taken in one pass.
>
> **Scope.** Stages 1–2 only. The *fully-specified agent work* (`ready-for-agent`) and the
> *Done / In-Progress* slices are listed in §5 for context but need no decision.
>
> **Status:** drafted by an agent **2026-06-29**, **pending human review** (M. Uy = system/technical
> owner; A. L. Pinote = QA/regulatory owner, per [ADR-0007](../adr/0007-regulatory-ownership-and-responsibility-allocation.md)).
>
> **Sources:** [`LIS_IMPLEMENTATION_PLAN.md`](../../LIS_IMPLEMENTATION_PLAN.md) §3 (Stage 1–2),
> [`docs/testing/stage-1-3-machine-access-checklist.md`](../testing/stage-1-3-machine-access-checklist.md)
> (LIS-74 re-scope), [ADR-0008](../adr/0008-interface-engine-stack-and-fleet-scope.md) (engine + v1 fleet),
> [`docs/compliance/decisions-register.md`](../compliance/decisions-register.md) (DEC-04/06).
> Slice bodies in Plane are empty — the **title is the contract**; the detail lives in the sources above.

---

## 0. Read this first — one ruling unblocks half the list

There is a **cross-document conflict** that has to be resolved before the per-slice calls
mean anything:

- **[ADR-0008](../adr/0008-interface-engine-stack-and-fleet-scope.md) / DEC-06 (2026-06-27)** pins the
  **v1 pilot fleet** as **EDAN H60S/H99S + RAYTO RT-7600 — HL7-v2/MLLP, result-ingestion only**, and
  explicitly **defers ERBA EC90 (serial group), HETO AU120, and the bidirectional host-query /
  order-download path to post-pilot (v1.1) under change control**.
- **The availability re-scope (2026-06-26, LIS-74)** — the machine-access checklist and the
  implementation-plan stage table — makes **ERBA EC90 the Stage-2 in-pilot vehicle** and treats
  the whole ASTM/serial stack as pilot work.

**These disagree.** Taken literally, ADR-0008 puts *all of Stage 2* (LIS-23…30) and Stage-1's
bidirectional slice (LIS-18) **outside** the M1 pilot — yet they are being actively built
(LIS-23 Done; LIS-24/26 urgent). **Decision SD-0 below is the meta-call** that determines whether
the rest of Stage 2 is pilot-critical or post-pilot, and therefore how urgent every Stage-2 row in
this dossier is.

---

## 1. Decision summary

**Urgency:** 🔴 on the pilot critical path / blocks a milestone · 🟠 needed before its stage gate ·
🟡 cheap confirmation / cleanup. **Type:** *Decide* = a real choice · *Act* = a human action
(bench/procurement) with the call already implied.

| ID | Slice | Decision / action | Urg. | Type | Recommendation (1-liner) |
|---|---|---|---|---|---|
| **SD-0** | scope (ADR-0008 ↔ LIS-74) | Is **Stage 2 / ERBA EC90 / bidirectional** in the **M1 pilot** or **post-pilot v1.1**? | 🔴 | Decide | **Build the ASTM stack now, keep EC90 *bench-validated but post-pilot* for go-live** — reconcile the two docs explicitly. |
| **SD-1** | **LIS-12** (S1.0) | Edge-driver **transport substrate** ADR (OIE vs bespoke) | 🟠 | Decide | **Superseded by ADR-0008** (reuse `analyzer-bridge`). **Rescope** LIS-12 to "record the substrate ADR: how serial/file transports attach to the HTTP-fronted bridge," or close it. |
| **SD-2** | **LIS-27** (S2.5) | Bidirectional ASTM coverage — source a **DiaSys RESPONS** or stay simulator-only? | 🟠 | Decide | **Simulator-only** for the pilot; only buy a bidirectional ASTM unit if a pilot site actually has one. |
| **SD-3** | **LIS-19** (S1.7) | Mindray **labXpert file-mode** ingest — defer or wontfix? | 🟡 | Decide | **Defer** (keep the contract; no available file-drop unit). Clear `needs-info`. |
| **SD-4** | **LIS-29** (S2.7) | **HORRON EA2000** re-verification gate | 🟡 | Decide | **Defer + reclassify** — HORRON is HL7/TCP, not ASTM; it doesn't belong in Stage 2. |
| **SD-5** | **LIS-24** (S2.2) | ASTM E1394 parser thread — why `ready-for-human`? | 🟠 | Decide | **Re-triage to `ready-for-agent`**: build against a spec-synthesized EC90 fixture now; back-fill the real capture from the bench (SD-7). |
| **SD-6** | **LIS-20** (S1.8) | **EDAN H60S** signed bench-conformance | 🔴 | Act | **Schedule the bench session** — retrieve H60S from warehouse; gates the Stage-1 "supported" milestone. |
| **SD-7** | **LIS-30** (S2.8) | **ERBA EC90** signed bench-conformance | 🟠 | Act | Retrieve EC90; capture the undocumented RS-232 baud/pinout; sign. (Urgency follows SD-0.) |
| **SD-8** | **LIS-21 + LIS-77** (S1.9/S1.10) | **HETO AU120** second-vendor confirm + bench | 🟠 | Act | On arrival (~now): confirm HL7/MLLP screen, pin port + listener role, resolve 2.3.1-vs-2.5, then bench. |
| **SD-9** | **LIS-78 + LIS-79** (S1.11/S2.9) | **EDAN H99S** + **Seamaty SD1** missing specs | 🟠/✅ | Act | **H99S: read nameplate first, then chase EDAN — it's a *v1 anchor*** (DEC-06), so it's on the pilot path. **SD1: ✅ spec obtained** (HL7 v2.3.1/MLLP; vendor LIS manual on file) — now a **v1 fleet** member (DEC-06, 2026-06-29), seed fixture landed (PR #28); only the bench capture remains. |

---

## 2. Stage-1 decisions

### SD-1 · LIS-12 [S1.0] — Edge-driver transport substrate ADR  · `ready-for-human`, high
**Decision.** Choose the transport substrate ("OIE channels vs bespoke drivers") and record an ADR.

**Status / why this is mostly already decided.** [ADR-0008](../adr/0008-interface-engine-stack-and-fleet-scope.md)
(DEC-04) already settled the engine: **reuse `openelis-analyzer-bridge`** — *not* a Mirth/OIE fork,
*not* bespoke-from-scratch. So LIS-12 as titled is **superseded**. What is **genuinely still open**
is narrower and worth an ADR: the bridge is the **"ASTM-HTTP Bridge"** — it is **HTTP-fronted**, so
the substrate question is *how the non-HTTP transports attach to it*:
- **HL7/MLLP (Stage 1):** does the bridge listen MLLP directly, or do we front it with a thin MLLP→HTTP shim?
- **Serial/ASTM (Stage 2) and the SnibeLis PC (Stage 3):** what feeds the bridge — a serial-listener sidecar, a file/DB poller, or a per-channel adapter?

**Options.** (a) **Rescope LIS-12** to "record the substrate ADR for how MLLP / serial / file transports
attach to the analyzer-bridge" (recommended); (b) close LIS-12 as resolved-by-ADR-0008 and fold the
substrate note into each stage's edge slice; (c) re-open the engine choice (not recommended — ADR-0008 is Accepted).

**Recommendation.** **(a)** — keep the slice but rescope its title; the channel/transport attachment is a real,
undecided design point that the conformance + threat surface (REQ-SEC-03 channel isolation) depends on.

**Owner.** M. Uy (system owner) · **Gates.** the validated edge boundary, REQ-SEC-03 wording, Stage-2/3 edge slices.

---

### SD-3 · LIS-19 [S1.7] — Mindray labXpert file-mode (shared-folder) ingest · `needs-info`, medium
**Decision.** Keep, defer, or drop the file-drop ingestion path.

**Context.** "labXpert" is **Mindray middleware, not an analyzer**, and **no available unit speaks file-mode** —
EDAN H60S and HETO AU120 are MLLP-only. So nothing in the current fleet can exercise this path.

**Options.** (a) **Defer** — keep the slice + the file-mode contract for when a file-drop unit appears
(e.g. MEDICA EasyStat's proprietary text dump); (b) **wontfix**; (c) build it now against a synthetic
file-drop fixture.

**Recommendation.** **(a) Defer, not wontfix** — file-drop is a real ingestion pattern we'll meet again.
Move out of `needs-info` with the note "no available file-mode unit; parked under change control (REQ-QMS-03)."

**Owner.** M. Uy · **Gates.** nothing on the pilot path.

---

### SD-6 · LIS-20 [S1.8] — EDAN H60S signed bench-conformance · `ready-for-human`, high  🔴
**Action (call is implied).** Run the physical-instrument bench-conformance and sign the report.

**Context.** This is the **gate from "code-green" to "supported"** for the Stage-1 anchor analyzer, and the
real-world half of the Stage-1 *first-result* milestone (the E2E LIS-17 is In Progress). H60S is **in the
warehouse** — retrieve it, stand up the edge listener on TCP 7999, confirm direction + a sample result +
raw archive, and sign.

**Decision content.** Who runs it and when; firmware ≥ APP V1.10; cable/switch logistics.

**Owner.** M. Uy (validation lead) + bench operator · **Gates.** Stage-1 "supported" matrix row; the milestone demo.

---

### SD-8 · LIS-21 [S1.9] + LIS-77 [S1.10] — HETO AU120 second-vendor · `ready-for-human`  🟠
**Action.** On arrival, confirm the interface (LIS-77), then run + sign bench-conformance (LIS-21).

**Context.** AU120 was **"incoming ~next week" as of 2026-06-26** → likely arriving the week of this dossier.
It is the **second-vendor HL7/MLLP** unit that proves the parser isn't EDAN-specific. Open unknowns to resolve
**on arrival**: (i) does the AU120 expose the same **HETO AU-series HL7/MLLP** screen (KB only documents the AU400 / Konig AP300)?
(ii) **pin the TCP port + listener role** (the manual omits both); (iii) resolve the **HL7 2.3.1-vs-2.5** wire version.

**Decision content.** Confirm arrival; assign the on-arrival capture. *Note the SD-0 scope question:* under a strict
ADR-0008 reading AU120 is a **deferred** unit — confirm whether the second-vendor proof is in the pilot or post-pilot.

**Owner.** M. Uy + bench operator · **Gates.** the "vendor-tolerance" exit-gate item for Stage 1.

---

### SD-9a · LIS-78 [S1.11] — EDAN H99S nameplate + LIS spec · `ready-for-human`  🟠
**Action.** Read the unit's **nameplate / serial** to disambiguate the model (it is **not in the KB**, and "H99S"
is not a recognized EDAN catalog model — documented EDAN siblings are H60S/I15/M16), then obtain the LIS interface spec from EDAN.

**Why it matters.** **DEC-06 pins H99S as a *v1 pilot anchor*** (EDAN H60S/H99S + RT-7600), so a missing protocol
spec is **on the pilot critical path**, not a nice-to-have. The cheap first move (read the nameplate) may collapse this to
"it's an H60S/M16, we already have the doc."

**Recommendation.** Read the nameplate **now** (free); only open a vendor-spec request to EDAN if it's a genuinely distinct model.

**Owner.** M. Uy + LabSolution warehouse · **Gates.** the H99S driver confirm (one of ADR-0008's four `[NEEDS-HUMAN]` protocol confirms).

---

## 3. Stage-2 decisions

> **All Stage-2 urgencies are conditional on SD-0.** If Stage 2 is post-pilot (strict ADR-0008), drop these to 🟡 and sequence after the pilot.

### SD-2 · LIS-27 [S2.5] — DiaSys bidirectional Q-record thread · `needs-info`, medium
**Decision.** Source a **bidirectional ASTM analyzer** (e.g. DiaSys RESPONS 920) for the live host-query /
NAK-retransmit negatives, or keep that path **simulator-only**?

**Context.** **ERBA EC90 is upload-only** — it cannot exercise the Q-record query or the NAK-retransmit path on
the bench. The richest bidirectional ASTM spec (DiaSys 920) is **not in the available fleet**. The ASTM simulator
harness (LIS-25) can drive both paths in CI without hardware.

**Options.** (a) **Simulator-only** — keep the bidirectional/NAK path proven against LIS-25, mark LIS-27
simulator-scoped, defer the live bidirectional test under change control (matches the plan's stated stance);
(b) **acquire a DiaSys RESPONS** (cost + lead time) for a real bench bidirectional test.

**Recommendation.** **(a)** for the pilot — ADR-0008 already defers bidirectional/order-download to v1.1, so a
simulator-validated path is sufficient for M1. Only buy a bidirectional unit if a **pilot site actually operates one**.

**Owner.** M. Uy + Pinote (procurement) · **Gates.** the Stage-2 bidirectional exit-gate item (currently simulator-driven).

---

### SD-4 · LIS-29 [S2.7] — HORRON EA2000 re-verification gate · `needs-info`, medium
**Decision.** Defer, and **reclassify out of Stage 2**.

**Context.** HORRON EA2000 is **not available**, and the cross-check found it is **HL7/TCP native (or legacy
serial+middleware), not ASTM** — so even when acquired it belongs in the **Stage-1 (HL7)** group, not Stage 2.
Its image-native source PDF carries a **re-verification gate** (driver not merged until the source PDF is re-verified and signed).

**Recommendation.** **Defer**; record "not available; re-files under Stage 1 (HL7) when acquired; source-PDF
re-verification gate retained." Clears `needs-info`.

**Owner.** M. Uy · **Gates.** nothing on the pilot path.

---

### SD-5 · LIS-24 [S2.2] — ASTM E1394 parser thread · `ready-for-human`, **urgent**
**Decision.** Confirm whether this genuinely needs a human, or can proceed as agent work.

**Context.** A typed-record-tree ASTM E1394 parser (H→P→O→R→L, tolerant of spec deviation) is **agent-implementable
given a fixture**. The likely reason it sits in `ready-for-human` is that it wants a **real captured ERBA EC90 frame**
as the fixture — which depends on the bench (SD-7). But the low-level codec (LIS-23) is already **Done**.

**Options.** (a) **Re-triage to `ready-for-agent`** — build the parser against a **spec-synthesized** EC90 fixture
now (it's marked *urgent*), and back-fill the real captured frame from the SD-7 bench session; (b) hold it for the
physical capture (serializes the urgent work behind hardware retrieval).

**Recommendation.** **(a)** — don't block urgent parser work on hardware; validate against the spec-derived fixture,
then add the captured-frame fixture as a conformance back-fill.

**Owner.** M. Uy · **Gates.** the Stage-2 parser deliverable (LIS-26 channel thread depends on it).

---

### SD-7 · LIS-30 [S2.8] — ERBA EC90 signed bench-conformance · `ready-for-human`, high
**Action.** Retrieve EC90 from the warehouse, **capture the undocumented RS-232 baud/pinout** on the bench, run
conformance (direction + sample + raw), sign; record traceability rows.

**Decision content.** **RS-232 vs Ethernet** path (both supported by the unit); who runs it and when. Urgency
inherits from **SD-0** (pilot vs post-pilot).

**Owner.** M. Uy + bench operator · **Gates.** the Stage-2 "supported" matrix row.

---

### SD-9b · LIS-79 [S2.9] — Seamaty SD1 LIS spec · `ready-for-human`
**Action.** ✅ **Done — the SD1-specific LIS Interface Manual is on file** (`manuals-and-lis-protocol/RAYTO/SEAMATY/lis-protocol.pdf`,
Ed. B/0). Remaining: a real-instrument bench capture (operator-set TCP port + MLLP framing + ASCII-vs-UTF-8 encoding).

**Context.** Protocol **confirmed**: HL7 v2.3.1 / MLLP over TCP/IP (RS-232 also) / upload-only (ORU^R01 + ACK, no worklist).
SD1 is now a **pinned v1 fleet member** (DEC-06, added 2026-06-29) — a Stage-1 second-vendor (dry-chem) vehicle, no longer
provisional. Two ingestion quirks to handle in the SD1 slice: MRN rides in **PID-2** (parser reads PID-3 → empty until a
fallback), and the biochem codes + `U/L` unit need LOINC/UCUM maps. Seed conformance fixture `seamaty-sd1-oru-r01` landed (PR #28).

**Recommendation.** Proceed: schedule the SD1 bench-conformance (one REQ-CONF-01 report, like the H60S/EC90 sessions) and the
SD1 ingestion slice (PID-2 fallback + biochem maps).

**Owner.** Pinote (vendor liaison) + M. Uy · **Gates.** SD1 now on the pilot path (v1); bench capture + ingestion slice remain.

---

## 4. Suggested decision order

1. **SD-0** (scope) — one call that re-prioritizes every Stage-2 row. *Decide first.*
2. **SD-6 / SD-9a** — H60S bench + H99S nameplate: both on the **Stage-1 pilot critical path**; H60S gates the milestone, H99S is a v1 anchor with no spec.
3. **SD-8** — HETO AU120 on-arrival confirm (time-boxed by the delivery, ~now).
4. **SD-1, SD-5** — cheap re-triage/rescope calls that unblock active work (transport ADR; LIS-24 to agent).
5. **SD-2, SD-3, SD-4, SD-7, SD-9b** — defer/confirm + procurement-lead-time items; resolve after SD-0 sets their urgency.

---

## 5. Context — non-decision Stage 1–2 slices (no action needed)

| Slice | State | Note |
|---|---|---|
| LIS-13 / S1.1 — MLLP frame + ACK^R01 | **Done** | transport merged |
| LIS-14 / S1.2 — H60S ORU^R01 → LOINC/UCUM | **Done** | |
| LIS-15 / S1.3 — append-only Result store | **Done** | |
| LIS-16 / S1.4 — raw-archive + replay round-trip | **Done** | |
| LIS-17 / S1.5 — **milestone E2E** (H60S → Result + ACK) | **In Progress** (urgent) | the Stage-1 *first-result* milestone, in flight |
| LIS-18 / S1.6 — H60S bidirectional QRD/QRF | `ready-for-agent` | ⚠ ADR-0008 defers bidirectional to v1.1 — see **SD-0** |
| LIS-23 / S2.1 — ASTM E1381 codec | **Done** | low-level framing/checksum |
| LIS-25 / S2.3 — ASTM simulator harness | `ready-for-agent` | drives the bidirectional/NAK negatives for **SD-2** |
| LIS-26 / S2.4 — ERBA EC90 channel thread | `ready-for-agent` | depends on LIS-24 (**SD-5**) |
| LIS-28 / S2.6 — EC90 branched channel → electrolyte Result | `ready-for-agent` | |

---

*Cross-references: [`LIS_IMPLEMENTATION_PLAN.md`](../../LIS_IMPLEMENTATION_PLAN.md) §3,
[`docs/testing/stage-1-3-machine-access-checklist.md`](../testing/stage-1-3-machine-access-checklist.md),
[ADR-0008](../adr/0008-interface-engine-stack-and-fleet-scope.md),
[`docs/compliance/decisions-register.md`](../compliance/decisions-register.md). RT-7600 wire-format capture
(LIS-76, a v1 anchor with unconfirmed format) is Stage 3 — tracked there, but note it is also on the pilot fleet path.*
