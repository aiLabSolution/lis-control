# Runbook - EDAN H99S bench conformance (LIS-78)

Drafted 2026-07-01 for the physical EDAN H99S bench run. This is the L3
bench-conformance plan for REQ-CONF-01: prove that the physical analyzer speaks
as documented, that the LIS edge acknowledges it correctly, that raw wire
evidence is captured, and that a representative sample result can be replayed
through the Stage-1 pipeline.

## References

- H99S KB supplied for this slice:
  `/tmp/EDAN_H99S_LIS_Integration_KB.md`.
- Vendor source named by the KB: EDAN `H90 LIS Communication Protocol`,
  document `EDAN\WI\82-01.54.460907`, version 1.0, covering H90/H90S/H95/H95S/H96/H96S/H98S/H99S.
- Architecture: `docs/adr/0005-mllp-framing-and-ack-modes.md`,
  `docs/adr/0011-oru-parse-and-normalization.md`,
  `docs/adr/0012-raw-message-archive-and-deterministic-replay.md`,
  `docs/adr/0015-edge-transport-substrate-and-channel-attachment.md`.
- SD1 precedent: LIS-79 captured the vendor LIS spec, seeded a simulator
  fixture, documented parser/normalization quirks, and left the real-instrument
  bench capture as the replacement evidence. Mirror that pattern here: capture
  the H99S wire, create `edge/sim/fixtures/edan-h99s-oru-r01`, mark it
  `synthetic: false`, and use the fixture to drive parser/normalization follow-up.
- Synthetic seed + oracle (already committed for this slice):
  `edge/sim/fixtures/edan-h99s-oru-r01` — KB-faithful `ORU^R01` (device code `507`,
  analyte name in OBX-4). Reproduce the parse gaps with
  `cd edge/sim && uv run edge-sim normalize edan-h99s-oru-r01`.

## Scope

Go-live support claim for this bench run:

- H99S over MLLP/TCP, analyzer as TCP client and LIS edge as TCP server.
- HL7 v2.4 `ORU^R01` patient-sample result upload.
- Original-mode HL7 `ACK` with `MSA-1=AA` and `MSA-2` echoing the inbound
  `MSH-10`.
- Raw-message capture plus deterministic replay into normalized Stage-1 result
  rows.

Characterization only, not a pilot go-live blocker unless explicitly promoted:

- QC result upload (`MSH-16=1`), because the QC engine/autoverification surface
  is a later validation stream.
- Worklist/query (`QRY^R02` -> `ORF^R04`, `MSH-16=3`), because bidirectional
  host-query is deferred post-pilot by ADR-0008/ADR-0015 even though the H99S
  protocol supports it.
- SOAP transport. The pilot edge substrate is MLLP/TCP.

## Readiness and known parser gaps (READ BEFORE THE BENCH)

Transport + ACK are ready; **result staging is not, because the EDAN H90-series
protocol repurposes standard HL7 field positions** and the generic parser reads the
standard positions. This is sharper than "a code->LOINC seed is missing": for EDAN
the analyte code is not even in the field the parser reads. Verified 2026-07-01
against the pinned bridge (`edge/drivers` @ `a98db88`) and `edge/sim`, and reproduced
by the synthetic seed `edge/sim/fixtures/edan-h99s-oru-r01` (run
`uv run edge-sim normalize edan-h99s-oru-r01` — all six rows come back code `0` /
LOINC unmapped).

| Gap | KB | Standard-HL7 position the parser reads | EDAN H90-series actual position | Effect | Severity |
|---|---|---|---|---|---|
| **Analyte code** | §5.4 | OBX-3.1 (`HL7ResultParser.extractTestCode(fields[3])`; `edge/sim oru.py raw_code=OBX-3.1`) | **OBX-4** (name); OBX-3 = suspect flag `0`/`1` | Every numeric OBX resolves to code `0` — nothing maps to LOINC, all rows collide on one code | **Blocker (unconditional)** |
| Sample ID | §5.3a | accession OBR-3 -> OBR-2 (bridge); OBR-3 only (edge/sim) | **OBR-2** (OBR-3 = reviewing doctor) | Bridge resolves via OBR-2 only when OBR-3 blank; a reviewing doctor in OBR-3 becomes the accession. edge/sim has no OBR-2 fallback -> blank specimen | Conditional |
| Patient number | §5.2 | PID-3.1 -> PID-2.1 (both parsers) | **PID-2** (PID-3 = Age^unit) | A populated PID-3 age (e.g. `35^Year`) is mistaken for the patient id; only a blank/`^0` PID-3 lets the PID-2 fallback work | Conditional |

**Consequence for the bench:** you can prove transport, framing, and ACK echo today,
and (for the bridge) the accession resolves as long as OBR-3 is blank. But numeric
results will stage under test code `0` and never map to LOINC until the EDAN OBX-4
code source lands. Do **not** read that as a bad capture — it is the expected gap.

**Remediation (a follow-up slice, two-level per ADR-0001 — bridge + `edge/sim`):**

- Read the analyte code from **OBX-4** for EDAN-family analyzers (identified by
  `MSH-3` device code `507`/`H90`, or by registered source IP). The LOINC/UCUM map
  already knows the EDAN codes/units (`edge/sim normalize.py` and the core
  `vendor_code_mapping` seed cover WBC/RBC/HGB/HCT/MCV/PLT + `10^9/L`/`10^12/L`/`g/L`),
  so once the code is read from the right field, normalization should resolve.
- Add the **OBR-2** sample-id fallback to `edge/sim` (the bridge already has it) and
  guard against a populated OBR-3 (reviewing doctor) shadowing the accession.
- Guard the **PID-3** age from shadowing the PID-2 patient number for EDAN.

The `edan-h60s-oru-r01` seed uses a standard-HL7 OBX-3 code, so it does **not** exercise
these gaps. Whether the real H60S wire also repurposes fields (the KB notes H90 reused
the H60 protocol as its base) is itself unverified — confirm it at the H60S bench.

## Bench Roles

| Role | Responsibility |
|---|---|
| Bench operator | Analyzer UI, sample/QC handling, screenshots, nameplate/firmware photo. |
| LIS edge engineer | Bridge listener, OpenELIS analyzer registry/config, packet capture, raw-message extraction. |
| Validation owner | Pass/fail call, evidence packet review, signed conformance report. |

Use bench/test identifiers only. Do not use real patient PHI for this run.

## Prerequisites

- Physical EDAN H99S is powered on and ready.
- Nameplate, serial number, software/firmware build, network MAC, and LIS
  protocol document version are recorded in the evidence packet.
- Analyzer and LIS edge host are on the same routable bench network and can ping
  each other.
- Bridge MLLP listener is enabled. Use TCP `7999` unless the bench needs another
  free port; record the actual port in the evidence packet.
- OpenELIS analyzer registry has a draft H99S entry:
  - vendor/model: `EDAN H99S`
  - expected protocol: `HL7`
  - transport: `MLLP`
  - source: analyzer IP or bench network allow-list
  - mapping profile: start with the EDAN hematology map used by H60S, then
    adjust after the captured H99S OBX rows are inspected.
- Packet capture is ready on the bridge host:

```bash
sudo tcpdump -i <bench-interface> -s0 -w h99s-mllp.pcap tcp port <mllp-port>
```

## Evidence Packet

Create one run directory before starting, named with date and serial number:

```text
evidence/bench/edan-h99s/<YYYYMMDD>-<serial>/
```

Collect at minimum:

| Artifact | Required content |
|---|---|
| `identity.md` | Model, serial, firmware/software build, KB/protocol version, operator names, date/time. |
| `nameplate.jpg` | Physical nameplate or equivalent device identity screen. |
| `network-settings.png` | Analyzer IP/gateway/netmask and LIS IP/port setting. |
| `bridge-config.yml` | Listener port and analyzer registry/mapping profile used for the run. |
| `connection-test.png` | Device UI proof that the LIS connection test succeeded. |
| `h99s-mllp.pcap` | Full packet capture for connection test, ORU, optional QC/query. |
| `oru-message.hl7` | De-framed inbound application payload, no MLLP bytes. |
| `ack.hl7` | ACK returned by the LIS edge for the ORU. |
| `openelis-result.png` | OpenELIS UI/API proof of the ingested normalized result. |
| `edge-sim-roundtrip.txt` | `edge-sim validate`, `roundtrip`, and `milestone` output after fixture creation. |
| `signed-conformance-report.pdf` | Final validation sign-off. |

If any artifact contains PHI, do not commit it to the repo. Redact before sharing
outside the validation evidence store.

## Test Plan

### 1. Physical identity and protocol confirmation

1. Photograph the nameplate and record serial/software build.
2. Confirm the unit is EDAN H99S, not a sibling mislabeled in inventory.
3. Confirm the H99S is covered by the H90-series protocol and should identify as
   device subtype `507` in `MSH-3` component 3, for example `H90^^507`.

Pass criteria:

- Evidence packet records model, serial, and software build.
- Captured HL7 later shows `MSH-3` consistent with H99S subtype `507`, or the
  deviation is recorded as a follow-up.

### 2. Network and MLLP setup

1. Configure analyzer static IP, gateway, and netmask.
2. Configure LIS settings on the analyzer:
   - transport: MLLP
   - LIS IP: bridge host IP
   - LIS port: bench MLLP listener port
   - auto-communication: enabled for the sample-result send
3. Start packet capture.
4. Start or verify the bridge MLLP listener.
5. Run the analyzer connection test.

Pass criteria:

- Analyzer and bridge host can ping each other.
- Analyzer UI reports successful connection test.
- Packet capture shows analyzer as TCP client and bridge as TCP server.
- MLLP framing is `0x0B ... 0x1C 0x0D`.

### 3. Patient-sample ORU upload

1. Create or select a bench-only sample ID, for example `H99S-BENCH-001`.
2. Run the analyzer result workflow under bench-operator control.
3. Send the result manually or via auto-communication.
4. Capture the inbound `ORU^R01` and outbound `ACK`.
5. Verify the OpenELIS/bridge ingestion path received the result.

Pass criteria:

- Inbound message is HL7 v2.4 `ORU^R01`.
- `MSH-3` identifies EDAN/H99S, preferably `H90^^507`.
- `MSH-4=EDANLAB`, `MSH-11=P`, `MSH-12=2.4`, and `MSH-18=UTF8` or an observed
  equivalent that is documented.
- `MSH-16=0` for patient-sample result.
- PID/OBR/OBX structure is present.
- Numeric OBX rows carry expected hematology parameters such as WBC, RBC, HGB,
  HCT, MCV, and PLT, with raw EDAN units preserved.
- Image OBX rows, if present, are archived and ignored for numeric result
  normalization unless a display requirement is explicitly added later.
- Outbound ACK has `MSA-1=AA`.
- ACK `MSA-2` exactly equals inbound `MSH-10`.
- OpenELIS receives the staged rows. Expect them under **test code `0`** (the
  OBX-3/OBX-4 gap in "Readiness and known parser gaps") until the EDAN OBX-4 code
  source lands — that isolates the remaining gap to analyzer-code field mapping, not
  transport or framing. Confirm the wire actually carries the analyte name in **OBX-4**
  and a suspect flag in OBX-3, and whether OBR-3 (reviewing doctor) and PID-3 (age)
  are populated (they change accession/patient resolution — see the readiness table).

### 4. Raw archive and simulator fixture

> A **synthetic seed already exists** at `edge/sim/fixtures/edan-h99s-oru-r01`
> (KB-faithful: `MSH-3 = H90^^507`, analyte name in OBX-4, `synthetic: true`). It
> reproduces the parser gaps above. **Graduate it** to the real capture below rather
> than creating it from scratch.

1. Extract the application payload from the pcap with MLLP bytes removed.
2. Overwrite `edge/sim/fixtures/edan-h99s-oru-r01/message.hl7` with the de-framed payload.
3. Update `edge/sim/fixtures/edan-h99s-oru-r01/manifest.json` (already present; flip to captured):
   - `analyzer.vendor`: `EDAN`
   - `analyzer.model`: `H99S`
   - `protocol`: `hl7v2`
   - `transport`: `mllp`
   - `direction`: `analyzer-to-host`
   - `message.encoding`: `utf-8` unless the capture proves otherwise
   - `message.framing`: `mllp`
   - `synthetic`: `false`
   - `source.reference`: evidence packet ID and protocol document ID
   - `expected`: message type, patient/specimen IDs, and normalized rows that
     are confirmed by the capture
4. Run:

```bash
cd edge/sim
uv run edge-sim validate
uv run edge-sim ack edan-h99s-oru-r01
uv run edge-sim roundtrip edan-h99s-oru-r01 --transport mllp
uv run edge-sim milestone edan-h99s-oru-r01
uv run pytest -q
```

Pass criteria:

- Manifest validates.
- ACK builder echoes the H99S `MSH-10`.
- Roundtrip preserves bytes through MLLP framing.
- Milestone succeeds once H99S raw codes/units are mapped.
- Any parser or normalization gap is converted into a follow-up slice before the
  unit is marked supported.

### 5. QC upload characterization

Run only after the sample ORU path is stable.

1. Send one QC result if the bench operator can do so without disrupting routine
   QC controls.
2. Capture the inbound message and ACK.
3. Confirm the QC variant:
   - `MSH-16=1`
   - PID absent or unused
   - OBR fields follow the QC semantics in the KB

Pass criteria:

- Transport and ACK behavior match the patient-sample ORU path.
- QC message is archived and labeled as characterization evidence.
- If the current ingestion path would mix QC into patient results, stop and file
  a QC-routing follow-up; do not mark QC ingestion supported from this bench run.

### 6. Worklist query characterization

Run only if the operator can trigger the H99S query workflow and the host can
respond safely.

1. Configure a bench-only patient/sample lookup.
2. Trigger `QRY^R02` from the H99S.
3. Return an `ORF^R04` response from the host, if available.
4. Capture request and response.

Pass criteria:

- Query contains `QRD`, with QRD-8 or QRD-9 populated.
- Response, if sent, has `MSA-1=AA` and correlates to the query.
- The result is recorded as characterization only unless bidirectional support is
  promoted through change control.

### 7. Failure and retry observation

Do not manufacture unsafe analyzer states. If practical, perform one controlled
negative observation:

- stop the listener and trigger a connection attempt; confirm the analyzer reports
  connection failure and reconnects on the next send after the listener returns; or
- return an `AE`/`AR` ACK from a test host and confirm the analyzer displays the
  error without altering patient-result state.

Pass criteria:

- Failure behavior is observed and documented.
- The analyzer does not silently drop a result without an operator-visible error.

## Exit Criteria

The H99S can be marked bench-conformant for the pilot sample-result path only when:

- Identity evidence proves the physical unit is H99S.
- MLLP/TCP wire capture matches the vendor protocol.
- One patient-sample `ORU^R01` is accepted with an ACK that echoes `MSH-10`.
- Raw message, ACK, pcap, bridge config, and OpenELIS result proof are in the
  evidence packet.
- `edge/sim` has a captured H99S fixture or an explicit follow-up to add it.
- Parser/normalization gaps are either closed or tracked as blocking follow-ups.
- Validation owner signs the conformance report.

## Follow-Up Slices to File if Needed

- H99S fixture seed and parser assertions if the bench capture differs from the
  H60S-style EDAN hematology fixture.
- H99S code-to-LOINC/UCUM mapping updates if OBX names/units differ from H60S.
- Image OBX display/archive policy if the lab requires WBC/DIFF/other plots in
  the LIS.
- QC routing if H99S QC upload is in scope before Stage 5.
- Bidirectional query support if H99S worklist pull becomes a pilot requirement.

