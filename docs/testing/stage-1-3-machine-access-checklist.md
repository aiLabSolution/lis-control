# Stage 1–3 Machine Access Checklist & Re-scoped Test Plan

> **Purpose:** the machines (and middleware PCs) we need for bench/integration testing
> across Stages 1–3 of `LIS_IMPLEMENTATION_PLAN.md`, cross-checked against the
> `manuals-and-lis-protocol` knowledgebase (KB), and **re-scoped against the units we
> actually have**.
>
> **Status:** drafted 2026-06-26 · **availability received 2026-06-26.**
>
> **Headline:** the available fleet **covers all three stages** — but **5 of the 7
> available units are not the machines the plan originally named.** The plan's Stage-1
> targets (RAC-050, "Mindray labXpert") and most Stage-2/3 targets are **not on hand**,
> so we substitute available HL7-equivalents. Net effect: a **stronger, multi-vendor
> Stage 1**, a **thinner Stage 2** (one confirmed-ASTM unit), and a **Stage 3 gated on
> middleware** (SnibeLis PC + license).

---

## 0. TL;DR — re-scoped stages

| Stage | Goal | **Primary vehicle (available)** | Ready? |
|---|---|---|---|
| **1 — HL7/MLLP "first result"** | one MLLP listener + HL7 parser, first normalized result | **EDAN H60S** (HL7 v2.4 / MLLP / port 7999) | ✅ unit in warehouse; matches existing edge (LIS-13) |
| **2 — ASTM / serial** | ASTM E1381/E1394 stack | **ERBA EC90** (ASTM, RS232 or Ethernet) | ✅ unit in warehouse |
| **3 — proprietary tail** | middleware-brokered result + QC | **SNIBE MAGLUMI X3** + **SnibeLis** | 🟡 analyzer on hand; **blocked on SnibeLis PC + license** |

**Bonus coverage now possible:** **HETO AU120** gives a *second-vendor* HL7/MLLP unit for
Stage 1 (proves the parser isn't EDAN-specific); **RAYTO RT-7600** is a second
proprietary-TCP tail for Stage-3 reverse-mapping practice.

**The good news:** we can now exercise Stage 1 across **three vendors** (EDAN confirmed,
HETO likely, Seamaty/RAYTO provisional) — better vendor-tolerance proof than the
original RAC-050-only plan. **The gap:** Stage 2 rests on a **single, upload-only ASTM
unit** (ERBA EC90); the richest ASTM spec (DiaSys 920) is not available.

---

## 1. Available machines — verified against the KB

Availability tiers from your 2026-06-26 status: **on hand** · **in warehouse** (retrieve) · **incoming** (~next week).

| Machine | Availability | Type | Documented interface (KB) | Stage fit | Readiness / blocker |
|---|---|---|---|---|---|
| **EDAN H60S** | In warehouse | Hematology (CBC) | **HL7 v2.4 over MLLP/TCP**, **port 7999**, bidirectional; analyzer = **TCP client**, LIS listens. ✅ clean. | **1** | ✅ **Best Stage-1 target.** Retrieve from warehouse. Our edge runs the listener. |
| **ERBA EC90** | In warehouse | Electrolyte / ISE | **ASTM E1381 + E1394**; RS232 **or** Ethernet; **unidirectional** upload. ✅ | **2** | ✅ Only confirmed-ASTM unit available. Capture RS232 baud/pinout on bench. |
| **SNIBE MAGLUMI X3** | On hand | Immunoassay (CLIA) | **ASTM E1394 via SnibeLis** middleware; bidirectional + **QC upload** ✅ | **3** | 🟡 **Needs SnibeLis PC + vendor license (machine-code→Reg-Code); SnibeLis→OpenELIS relay undocumented.** |
| **HETO AU120** | Incoming (~next wk) | Clinical chemistry | **HL7 v2.3.1 (doc also says v2.5) over MLLP/TCP**, bidirectional. ⚠️ **family doc only** — examples use **AU400**, no AU120-specific doc. | **1** | 🟡 Confirm on arrival the AU120 exposes this same HETO HL7 screen; port/listener-role undocumented. |
| **RAYTO RT-7600** | On hand | Hematology (CBC) | ❌ **No HL7/ASTM in docs.** Proprietary **TCP "Netport"** record stream (vendor LIS-sim, port configurable) **or** RS232 (115200/8/N/1). Bidirectional-capable. | **3** (prov.) | 🟡 **Byte-capture a "Send" to identify the wire format** before staging. Moves to St.1 if HL7, St.2 if serial/ASTM. |
| **Seamaty SD1** | On hand | Dry/whole-blood biochem | ⚠️ **No SD1 doc in KB** — only the **SG1** (a *different* instrument: handheld blood-gas/ISE). SG1 = HL7 "v2.1.3" over TCP/serial, upload-only. | **1** (prov.) | 🔴 **Obtain an SD1-specific LIS spec from Seamaty;** photograph the SD1's own LIS screen + wire-capture. |
| **EDAN H99S** | On hand | Unknown (likely hematology by name) | ❌ **Not in KB at all** — no EDAN/H99S, not a recognizable EDAN catalog model. (Documented EDAN siblings: H60S hematology, I15 blood-gas, M16 immunoassay.) | ? | 🔴 **Read the unit nameplate/SN to disambiguate** (H60S? M16?); obtain protocol doc from EDAN. |

---

## 2. Re-scoped Stage 1–3 plan

### Stage 1 — *first result through the pipe* → **EDAN H60S**
HL7 v2.4 over MLLP, analyzer dials our listener on **TCP 7999**, ACK returned — a textbook
fit for the **MLLP de-frame + HL7 ACK^R01** transport already merged (LIS-13/S1.1). The
H60S replaces the unavailable RAC-050 as the "first result" vehicle; it's a hematology
ORU^R01 instead of a coagulation one, but the pipe is identical.
- **Access to confirm:** retrieve H60S from warehouse · RJ45 cable + switch/crossover ·
  our edge listening on 7999 · firmware APP V1.10+.
- **Stretch (same stage, second vendor):** **HETO AU120** on arrival → prove the parser
  ingests a different vendor's HL7/MLLP without code changes. (Confirm AU120 = the AU-series
  HL7 screen; pin the port.)
- Provisional thirds: **Seamaty SD1** and **RAYTO RT-7600** *iff* their wire format turns
  out HL7 (both need a capture/vendor doc first).
- 📄 [EDAN H60S LIS-Communication-Protocol p.7 (MLLP, TCP client, ACK)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/EDAN/H60S/LIS/LIS-Communication-Protocol-h60.pdf#page=7) · [LIS Connection Training p.4 (port 7999)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/EDAN/H60S/LIS/PX-HA-0075-V1.0-H60%26H60-Vet-Series-LIS-Connection-Training.pdf#page=4)

### Stage 2 — ASTM / serial → **ERBA EC90**
The only confirmed-ASTM unit on the list. Exercises the ASTM E1381 low-level framing
(ENQ/ACK/checksum) + E1394 records — the core Stage-2 deliverable. **Caveat:** it's
**upload-only** (no host-query) and the richest bidirectional ASTM spec (DiaSys 920) isn't
available, so Stage-2 bench breadth is reduced to one analyzer.
- **Access to confirm:** retrieve EC90 from warehouse · decide **RS232 vs Ethernet** path
  (both supported) · for RS232: DB9 cable + USB-serial adapter (capture undocumented
  baud/pinout on bench) · an ASTM-speaking host that ACKs the frames.
- **Coverage gap to decide:** is one upload-only ASTM unit enough to call Stage 2 "done,"
  or do we source a second ASTM analyzer (e.g. a DiaSys RESPONS) for a bidirectional /
  NAK-retransmit negative test? (See Action #5.)
- 📄 [ERBA EC90 LIS Interface V1.01 p.4 (ASTM E1381/E1394)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/ERBA/EC90/EC90-LIS-communication.pdf#page=4)

### Stage 3 — proprietary tail → **SNIBE MAGLUMI X3 + SnibeLis**
Analyzer ↔ **SnibeLis middleware PC** speaks ASTM E1394 (TCP or RS232); SnibeLis is the
LIS client and also flags QC (Westgard). The analyzer is on hand — **the work and the risk
are the middleware**, not the instrument.
- **Access to confirm (the real blockers):** a **SnibeLis/SnibeLinker Windows PC** ·
  **SnibeLis install + vendor activation** (machine-code → Reg-Code from SNIBE) · confirm
  how SnibeLis **forwards to OpenELIS** (relay vs DB/export — undocumented in KB; ask SNIBE).
- **Second tail (bonus):** **RAYTO RT-7600**'s proprietary TCP "Netport" stream is another
  reverse-mapping exercise for the same Stage-3 muscle.
- 📄 [SnibeLis LIS User Manual V1.1 App.A (ASTM E1394) p.73](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/SNIBE/MAGLUMI-X3/SnibeLisLIS-User-ManualV1.1_EN-version_20191015.pdf#page=73) · [Guidance of LIS p.3 (TCP/IP mode + Upload QC)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/SNIBE/MAGLUMI-X3/Guidance-of-Snbie-LIS.pdf#page=3)

---

## 3. Action items / gaps to close

1. **Retrieve from warehouse:** EDAN H60S (Stage 1) and ERBA EC90 (Stage 2) are the two
   primary vehicles and are both in the warehouse — pull them first.
2. **Stage 3 unblock (critical path):** source a **SnibeLis PC**, get the **vendor license**
   (machine-code→Reg-Code), and ask SNIBE how SnibeLis **forwards results to OpenELIS**.
   Without this, MAGLUMI X3 can't be tested past the SnibeLis boundary.
3. **EDAN H99S — disambiguate:** read the physical **nameplate / serial** (it's not a
   documented EDAN model). If it's really an H60S/M16/I15, we already have docs; otherwise
   request the LIS spec from EDAN.
4. **Seamaty SD1 — get the doc:** the KB only has the **SG1** (different instrument).
   Obtain an **SD1-specific LIS/communication spec** from Seamaty; meanwhile photograph the
   SD1's LIS setup screen + capture a frame.
5. **HETO AU120 — confirm on arrival:** verify the AU120 exposes the same **HETO AU-series
   HL7/MLLP** interface (docs only show AU400); pin the **TCP port + listener role** (the
   manual omits them); confirm the **2.3.1-vs-2.5** wire version.
6. **RAYTO RT-7600 — byte-capture:** run a "Send" into a raw TCP listener (Netport, e.g.
   port 9102) **and** a serial capture (115200/8/N/1) to settle whether the wire format is
   HL7, ASTM, or proprietary — then file it into Stage 1/2/3.
7. **Stage 2 breadth decision:** decide whether **ERBA EC90 alone** (upload-only ASTM)
   satisfies Stage 2, or whether to acquire a **bidirectional ASTM** analyzer for the
   NAK-retransmit / host-query negative tests.
8. **Per-unit conformance:** each unit still needs the standard "supported" gate — protocol
   doc → simulator fixture → parser tests → bench-conformance (direction + sample + raw) →
   E2E green.

---

## 4. Availability of the plan's originally-named machines

For traceability — what the plan named vs what's reachable:

| Plan machine | Stage | Available? | Substitute |
|---|---|---|---|
| RAYTO RAC-050 | 1 | ❌ No | **EDAN H60S** (HL7/MLLP) |
| "Mindray labXpert" | 1 | ❌ No (and it's middleware, not a machine) | **HETO AU120** / EDAN H60S |
| DiaSys RESPONS 920 | 2 | ❌ No | *(none — ASTM breadth gap)* |
| ERBA EC90 | 2 | ✅ **Yes** (warehouse) | — (is the vehicle) |
| GOLDSITE GPP-100 | 2 | ❌ No | — |
| HETO Konig AP300 | 2 | 🟡 AU120 incoming (sibling, HL7 not ASTM) | **HETO AU120** (→ Stage 1) |
| MEDICA EasyStat | 2 | ❌ No | — |
| HORRON EA2000 | 2 | ❌ No | — |
| SNIBE MAGLUMI (any) | 3 | ✅ **Yes** — **X3** on hand | — (is the vehicle) |
| Mindray BC + DMS | 3 | ❌ No | RAYTO RT-7600 (other proprietary tail) |

---

## Appendix A — original cross-check of the plan-named machines (reference)

Kept for context; this is what drove the substitutions above. **Two findings still matter:**
(a) **"Mindray labXpert" is middleware, not an analyzer** — its real physical unit was never
pinned; (b) the plan's **Stage-2 "ASTM/serial fleet" was mostly mislabeled** — GOLDSITE,
HETO and HORRON are actually HL7/Ethernet, and MEDICA EasyStat is a proprietary text dump.

| Plan machine | Stage | Real documented interface (KB) | Note |
|---|---|---|---|
| RAYTO RAC-050 | 1 | HL7 v2.3.1 / MLLP / TCP (client, port 2000), bidir | ✅ as planned; ACK = original-only (not enhanced) |
| Mindray labXpert | 1 | **Middleware** (HL7 v2.3.1 or file-drop); unit unnamed | ⚠️ not a machine |
| DiaSys RESPONS 920 | 2 | ASTM E1381/E1394, RS232 or TCP:7777, bidir | ✅ ASTM; spec doc misfiled under RESPONS-940 |
| ERBA EC90 | 2 | ASTM E1381/E1394, RS232 or Ethernet, upload-only | ✅ ASTM (now a primary vehicle) |
| GOLDSITE GPP-100 | 2 | **HL7 v2.3.1 / TCP / MLLP / port 8000**, bidir | ❌ not ASTM |
| HETO Konig AP300 | 2 | **HL7 / MLLP / Ethernet**, bidir | ❌ not ASTM (sibling of incoming AU120) |
| MEDICA EasyStat | 2 | **Proprietary text dump, RS232 2400/8N1**, uni | ❌ not ASTM; needs cable Cat# 5637 + custom parser |
| HORRON EA2000 | 2 | **HL7/TCP** native, or legacy serial+middleware | ❌ not ASTM; image-native PDF re-verify gate |
| SNIBE MAGLUMI / SnibeLis | 3 | ASTM E1394 via SnibeLis PC, bidir + QC | ✅ as planned (X3 is the vehicle) |
| Mindray BC / DMS | 3 | **HL7/Ethernet direct** (DMS optional; KB DMS = vet only) | ❌ DMS not required for modern BC |

---

## Source citations (host/LIS docs)

**Available units:**
[EDAN H60S LIS Protocol](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/EDAN/H60S/LIS/LIS-Communication-Protocol-h60.pdf#page=7) ·
[EDAN H60S LIS Training (port 7999)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/EDAN/H60S/LIS/PX-HA-0075-V1.0-H60%26H60-Vet-Series-LIS-Connection-Training.pdf#page=4) ·
[ERBA EC90 LIS Interface V1.01](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/ERBA/EC90/EC90-LIS-communication.pdf#page=4) ·
[SNIBE SnibeLis LIS User Manual V1.1](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/SNIBE/MAGLUMI-X3/SnibeLisLIS-User-ManualV1.1_EN-version_20191015.pdf#page=73) ·
[HETO Konig LIS Protocol V2.1](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/HETO/Konig-AP300/Konig-LIS-Protocol-EN-V2.1.pdf#page=3) ·
[RAYTO RT-7600 LIS setup](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/RAYTO/RT-7600/How-to-setup-LIS-connection-on-RT-7600.pdf#page=1) ·
[RAYTO RT-7600 User Manual V1.4e (115200/8N1)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/RAYTO/RT-7600/RT-7600-User_-manual-V1.4e.pdf#page=41) ·
[Seamaty SG1 manual (HL7 v2.1.3)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/RAYTO/SEAMATY/SG1-_2023.pdf#page=24) ·
[EDAN M16 HIS/LIS Interface (HL7 v2.4/MLLP/port 8000)](file:///home/marloeu/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/EDAN/M16/m16-Manual-20171111.pdf#page=84) *(EDAN H99S has no KB doc)*

**Plan-named units (appendix):** RAC-050, DiaSys 920, GOLDSITE GPP-100, MEDICA EasyStat,
HORRON EA2000, Mindray BC — see prior revision / KB folders under each vendor.
</content>
