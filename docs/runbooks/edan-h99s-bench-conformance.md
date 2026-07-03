# Runbook - EDAN H99S bench conformance (LIS-78)

Drafted 2026-07-01 for the physical EDAN H99S bench run. This is the L3
bench-conformance plan for REQ-CONF-01: prove that the physical analyzer speaks
as documented, that the LIS edge acknowledges it correctly, that raw wire
evidence is captured, and that a representative sample result can be replayed
through the Stage-1 pipeline. The production bridge -> OpenELIS path is shipped
(EDAN H90-series parse profile at `edge/drivers` pin `4db3c9e`) and was verified
end-to-end with the synthetic seed on 2026-07-02; this bench validates it against
real instrument bytes.

## References

- Vendor source of truth: EDAN `H90 LIS Communication Protocol`, document
  `EDAN\WI\82-01.54.460907`, version 1.0, covering
  H90/H90S/H95/H95S/H96/H96S/H98S/H99S.
- Slice KB note, if available locally: `/tmp/EDAN_H99S_LIS_Integration_KB.md`
  (non-durable working note only; do not use it as bench evidence).
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
  analyte name in OBX-4). Exercise the shipped EDAN H90-series parse profile with
  `cd edge/sim && uv run edge-sim normalize edan-h99s-oru-r01` (all six rows read
  their OBX-4 code and normalize to LOINC).

## Scope

Bench evidence target for this run:

- H99S over MLLP/TCP, analyzer as TCP client and LIS edge as TCP server.
- HL7 v2.4 `ORU^R01` patient-sample result upload.
- Original-mode HL7 `ACK` with `MSA-1=AA` and `MSA-2` echoing the inbound
  `MSH-10`.
- Raw-message capture plus deterministic replay into normalized Stage-1 result
  rows.

The production bridge gap is **closed**: the umbrella `edge/drivers` pin is
`4db3c9e`, which contains the H99S/H90-series `HL7ResultParser` branch
(`isEdanH90Series`) that reads analyte code from OBX-4 and the EDAN OBR-2/PID-2
positions. This bench therefore **validates** the shipped profile against real
instrument bytes rather than reproducing a parser gap. See the Readiness section
for the verified end-to-end result staging on 2026-07-02.

Characterization only, not a pilot go-live blocker unless explicitly promoted:

- QC result upload (`MSH-16=1`), because the QC engine/autoverification surface
  is a later validation stream.
- SOAP transport. The pilot edge substrate is MLLP/TCP.

**DEC-06 change-control release (2026-07-04 / LIS-149):** the H99S
worklist/order-download path (`QRY^R02` -> `ORF^R04`, `MSH-16=3`) is promoted
from characterization-only into active build and bench scope. This is narrow to
H99S barcode-to-accession order download; it is not a generic bidirectional fleet
release. The path is not bench-conformant until the request/response wire bytes,
OpenELIS pending-order lookup, and validation-owner sign-off are in the evidence
packet.

## Readiness and EDAN H90-series parse profile (READ BEFORE THE BENCH)

Transport + ACK are ready, and **result parsing/normalization is ready in both the
production bridge and `edge/sim`** via the **EDAN H90-series parse profile**. The
umbrella `edge/drivers` pin is **`4db3c9e`**, which contains the bridge
`HL7ResultParser` EDAN branch (`isEdanH90Series`); production bridge result staging
was verified end-to-end on 2026-07-02 (the synthetic seed replayed over MLLP →
bridge → OpenELIS staged all six CBC rows, each mapped to its LOINC test with
`read_only=false`). The H90-series protocol repurposes standard HL7
field positions, so the generic parser reads the wrong fields — sharper than "a
code->LOINC seed is missing": for EDAN the analyte code is not even in the field
the generic parser reads. The profile is gated on `MSH-3.1 == H90` or
`MSH-4 == EDANLAB` (so standard-HL7 analyzers, including the EDAN H60S seed, are
untouched) and reads the EDAN positions. Verified against the synthetic seed
`edge/sim/fixtures/edan-h99s-oru-r01` (run `uv run edge-sim normalize
edan-h99s-oru-r01` — all six rows read their OBX-4 code and normalize to LOINC).

| Field | KB | Position the generic parser read (pre-profile) | EDAN H90-series position the profile now reads | Status |
|---|---|---|---|---|
| **Analyte code** | §5.4 | OBX-3.1 (`extractTestCode(fields[3])`; `edge/sim raw_code=OBX-3.1`) — every row collapsed to code `0`, none mapping to LOINC | **OBX-4** (name); OBX-3 = suspect flag `0`/`1` | **Closed** (bridge `4db3c9e` + `edge/sim`) |
| Sample ID | §5.3a | accession OBR-3 -> OBR-2 (bridge); OBR-3 only (edge/sim) -> blank specimen | **OBR-2** (OBR-3 = reviewing doctor); edge/sim now has the OBR-2 fallback | **Closed** (bridge `4db3c9e` + `edge/sim`) |
| Patient number | §5.2 | PID-3.1 -> PID-2.1 — a populated PID-3 age (e.g. `35^Year`) shadowed the id | **PID-2** (PID-3 = Age^unit); the profile never uses PID-3 age for EDAN | **Closed** (bridge `4db3c9e` + `edge/sim`) |

**Shipped (two-level per ADR-0001 — bridge + `edge/sim`):**

- Analyte code read from **OBX-4** for EDAN H90-series messages — `edge/sim oru.py`
  (`_is_edan_h90` + `_observation(edan)`) via **PR #46**, and the bridge
  `HL7ResultParser` (`isEdanH90Series`) via bridge **PR #4** (umbrella `edge/drivers`
  pin `4db3c9e`). The LOINC/UCUM map already knew the EDAN
  codes/units (`edge/sim normalize.py` covers WBC/RBC/HGB/HCT/MCV/PLT +
  `10^9/L`/`10^12/L`/`g/L`), so once the code is read from OBX-4 normalization
  resolves.
- **OBR-2** sample-id preference added to `edge/sim` (`_specimen_id(edan)`); a populated
  OBR-3 (reviewing doctor) no longer shadows the accession for EDAN in the simulator.
- **PID-2** patient number preferred for EDAN so a populated PID-3 age cannot shadow it.

**Still open — documented gaps (confirm/close against the real bench capture):**

- **OBX-11 finality (harness-only):** EDAN uses OBX-11 as a "modified?" flag, not HL7
  Table-0085 finality (F/P/C), so EDAN rows carry no `F` and the `edge/sim` milestone's
  finality-gated ingest holds them back (`ingest_payload()` is empty for this seed).
  This is an `edge/sim` oracle nuance only — the production bridge -> OpenELIS path is
  not finality-gated this way. Closing it (treat completed EDAN uploads as final) is a
  separate profile step.
- **H60S real wire:** the `edan-h60s-oru-r01` seed uses a standard-HL7 OBX-3 code and is
  deliberately **not** routed through the H90-series profile; whether the real H60S wire
  also repurposes fields (the KB notes H90 reused the H60 protocol as its base) is
  unverified — confirm it at the H60S bench.
- **Image OBX** (`XXX_PNG_BASE64` in OBX-4) archive/display policy.

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
- OpenELIS has an analyzer registry entry for the H99S. Because the analyzer's
  MLLP source IP is NAT'd by the bridge's docker publish, do **not** pre-create it
  by IP — let the bridge auto-create the `PENDING_REGISTRATION` stub on first
  contact, then promote and map it per **Test Plan §3**. Target configuration:
  - vendor/model: `EDAN H99S`
  - protocol: `HL7` (`HL7_V2_3_1`); transport: `MLLP`; communication mode:
    `ANALYZER_INITIATED`
  - identifier pattern: `^H90-EDANLAB$` (the in-message sender the bridge routes on
    when the source IP is unregistered)
  - mapping profile: the EDAN H90-series parse profile plus the EDAN hematology map
    (analyte code in OBX-4, sample ID in OBR-2, patient number in PID-2). Do **not**
    use the H60S standard-HL7 profile for H99S. This is shipped at `edge/drivers`
    pin `4db3c9e` and verified end-to-end (see Readiness).
  - test mappings: WBC, RBC, HGB, HCT, MCV, PLT → the OpenELIS tests carrying LOINC
    6690-2 / 789-8 / 718-7 / 4544-3 / 787-2 / 777-3.
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
| `h99s-mllp.pcap` | Full packet capture for connection test, ORU, optional QC, and the released worklist query if run. |
| `oru-message.hl7` | De-framed inbound application payload, no MLLP bytes. |
| `ack.hl7` | ACK returned by the LIS edge for the ORU. |
| `qry-worklist.hl7` | De-framed H99S `QRY^R02` order-download request (`MSH-16=3`, QRD barcode subject). Required if claiming LIS-149 support. |
| `orf-worklist.hl7` | De-framed LIS `ORF^R04` order-download answer with `MSA-1=AA`, `MSA-2` echo, `PID`, and `OBR` rows. Required if claiming LIS-149 support. |
| `openelis-pending-order.json` | OpenELIS pending-order lookup evidence for the queried barcode, showing the reconciled accession and mapped LOINC/test rows. |
| `openelis-result.png` | OpenELIS proof of the ingested normalized result under **Results → Analyzer → EDAN H99S** (rows mapped to LOINC, `read_only=false`). The production bridge H90-series profile is shipped at pin `4db3c9e`, so this is a required artifact. |
| `analyzer-registry.json` | `GET /rest/analyzer/analyzers` after promotion + test mapping (records the registry entry and the six CBC mappings used for the run). |
| `edge-sim-roundtrip.txt` | `edge-sim validate`, `normalize`, `roundtrip`, and `milestone` output after fixture creation. `milestone` is expected to exit nonzero until EDAN OBX-11 finality handling is closed; keep its output as diagnostic evidence. |
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
- If the connection test emits an HL7 application payload, it uses `MSH-16=2`
  and the host ACK echoes the inbound `MSH-10` in `MSA-2`.

### 3. Register and map the analyzer in OpenELIS

The bridge does not know the analyzer until it sends an HL7 message. Only then does
OpenELIS find-or-create a `PENDING_REGISTRATION` stub from the message's sender
(`H90-EDANLAB`) — **not** from the source IP, which docker NAT rewrites to the
bridge gateway. A bare connection test (TCP handshake with no ORU payload) does
**not** create the stub, so this section requires at least one inbound message
first. Promote and map that stub before accepting results.

1. Ensure the stub exists: `GET /rest/analyzer/analyzers` shows an entry named
   `H90-EDANLAB`, status `PENDING_REGISTRATION`. **If it is absent** — the §2
   connection test carried no HL7 payload — send one *priming* ORU now (run §4
   steps 1–4) using a **scratch sample you will discard**, not the conformance
   sample. Its rows stage as unmapped / `read_only` and **persist** — mapping the
   analyzer below does **not** retroactively remap or remove them, and re-sending
   adds new staging rows rather than updating the old ones. So do the real §4
   conformance run with a *fresh* bench sample **after**
   this section, and treat any pre-mapping scratch rows as inert staging noise to
   ignore or delete — never as conformance results.
2. Promote it (Analyzer management UI, or `PUT /rest/analyzer/analyzers/<id>`):
   name `EDAN H99S`, type `HEMATOLOGY`, protocol `HL7_V2_3_1`, communication mode
   `ANALYZER_INITIATED`, identifier pattern `^H90-EDANLAB$`, status `SETUP`.
3. Add the six CBC test mappings (analyzer test name → OpenELIS test): WBC, RBC,
   HGB, HCT, MCV, PLT → the tests carrying LOINC 6690-2 / 789-8 / 718-7 / 4544-3 /
   787-2 / 777-3.
4. **Make the analyzer visible under Results → Analyzer.** A bridge-created /
   PUT-promoted analyzer does **not** get its `Results → Analyzer → <name>` menu
   entry until the webapp re-runs its startup menu registration — known limitation
   **LIS-105**. Either restart the OpenELIS webapp, or navigate directly to
   `/AnalyzerResults?id=<id>`. Without this, the staged rows are in the database and
   reachable via `GET /rest/AnalyzerResults?id=<id>` but have no UI link, which reads
   as "results missing".
5. Restart the bridge (or wait for its next registry sync) so it pulls the promoted
   entry and identifier pattern.

Pass criteria:

- The registry entry is `EDAN H99S`, `SETUP`, identifier pattern `^H90-EDANLAB$`,
  with the six CBC test mappings present.
- `Results → Analyzer → EDAN H99S` appears in the OpenELIS menu (after the webapp
  restart) and opens the analyzer's staged-results page.
- `analyzer-registry.json` is captured for the evidence packet.

### 4. Patient-sample ORU upload

1. Create or select a bench-only sample ID, for example `H99S-BENCH-001`.
2. Run the analyzer result workflow under bench-operator control.
3. Send the result manually or via auto-communication.
4. Capture the inbound `ORU^R01` and outbound `ACK`.
5. Verify the OpenELIS/bridge ingestion path received the result: the rows appear
   under **Results → Analyzer → EDAN H99S** (registered in §3), mapped to LOINC.

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
- OpenELIS receives the staged rows, mapped to LOINC via the shipped profile
  (analyte code read from OBX-4), `read_only=false`.
- Confirm the real wire actually matches the profile the seed encodes: analyte
  name in **OBX-4** with a suspect flag in OBX-3, the sample id in **OBR-2**
  (OBR-3 = reviewing doctor), and the patient number in **PID-2** (PID-3 = age)
  — see the readiness table. Record any deviation as a follow-up.

### 5. Raw archive and simulator fixture

> A **synthetic seed already exists** at `edge/sim/fixtures/edan-h99s-oru-r01`
> (KB-faithful: `MSH-3 = H90^^507`, analyte name in OBX-4, `synthetic: true`). It
> exercises the shipped EDAN H90-series parse profile above. **Graduate it** to the
> real capture below rather than creating it from scratch.

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
uv run edge-sim normalize edan-h99s-oru-r01
uv run edge-sim ack edan-h99s-oru-r01
uv run edge-sim roundtrip edan-h99s-oru-r01 --transport mllp
uv run edge-sim milestone edan-h99s-oru-r01 || true
uv run pytest -q
```

Pass criteria:

- Manifest validates.
- ACK builder echoes the H99S `MSH-10`.
- Normalize shows the H99S analytes read from OBX-4 and mapped to LOINC/UCUM.
- Roundtrip preserves bytes through MLLP framing.
- Milestone is accepted (`MSA-1=AA`) and prints normalized rows. Until EDAN
  OBX-11 finality handling is closed, the command is expected to exit nonzero
  with `ingest contract ... 0 observation(s)` because finality is `unknown`.
- Any parser or normalization gap is converted into a follow-up slice before the
  unit is marked supported.

### 6. QC upload characterization

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

### 7. Worklist query change-control gate (LIS-149)

Run after the ORU path is stable and only with bench-only identifiers. This is a
DEC-06 released implementation gate for H99S, but it still requires real wire
evidence before support is claimed.

1. Configure a bench-only OpenELIS order with a known barcode and accession. The
   LIS-149 synthetic fixture uses barcode `DEV01260000000000002`, reconciled to
   accession `2`, patient id `17`, and analyzer tests `WBC`/`HGB`.
2. Trigger `QRY^R02` from the H99S.
3. Return an `ORF^R04` response from the bridge/OpenELIS host resolver.
4. Capture request and response as `qry-worklist.hl7` and `orf-worklist.hl7`.
5. Capture the pending-order lookup or equivalent OpenELIS evidence as
   `openelis-pending-order.json`.
6. Mirror the synthetic contract locally:

```bash
cd edge/sim
uv run edge-sim worklist-query edan-h99s-worklist-query-qry-r02 \
  --accession 2 \
  --patient 17 \
  --codes WBC,HGB
```

Pass criteria:

- Query is HL7 v2.4 `QRY^R02` with `MSH-16=3`, `QRD`, and a barcode subject in
  `QRD-8`.
- Response is HL7 v2.4 `ORF^R04` with `MSH-16=3`.
- `MSA-1=AA`; `MSA-2` exactly equals the inbound `QRY^R02` `MSH-10`.
- `QRD-4` and `QRD-8` are echoed so the analyzer can correlate the answer to the
  request.
- Barcode-to-accession reconciliation is explicit: the `QRD-8` barcode may be
  `DEV01260000000000002`, while returned `OBR-2/3` is accession `2`.
- Reconciliation is deliberately narrow: only barcode-shaped identifiers (short
  alpha prefix + long digit run, e.g. `DEV…`) are canonicalized; anything else
  (QC labels, typos, plain accessions) is exact-match only, and a barcode whose
  digit candidates match more than one sample is refused (no worklist answer)
  rather than guessed. If the bench query gets no `ORF` order rows, check the
  OpenELIS log for an "ambiguous host-query lookup" warning before assuming a
  mapping gap.
- `PID` identifies the bench-only patient, and every `OBR` order row maps to an
  OpenELIS pending test configured for the analyzer (`WBC`/`HGB` in the fixture
  example).
- The `edge-sim worklist-query` demo exits 0 and prints `correlates=True`.

### 8. Failure and retry observation

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
- Raw message, ACK, pcap, bridge config, analyzer registry, and OpenELIS result
  proof are in the evidence packet. (The bridge H90-series profile is pinned at
  `edge/drivers` `4db3c9e`, so OpenELIS result proof is expected, not deferred.)
- `edge/sim` has a captured H99S fixture or an explicit follow-up to add it.
- Parser/normalization gaps are either closed or tracked as blocking follow-ups.
- Validation owner signs the conformance report.

The H99S order-download path can be marked supported only when, in addition to
the sample-result evidence above:

- `qry-worklist.hl7`, `orf-worklist.hl7`, and `openelis-pending-order.json` are in
  the evidence packet.
- The request/response satisfies §7 pass criteria, including `MSA-2` echo and
  barcode-to-accession reconciliation.
- The bridge/OpenELIS implementation used for the run is recorded by git SHA.
- The validation owner signs the LIS-149 change-control evidence.

## Follow-Up Slices to File if Needed

- EDAN OBX-11 finality handling in `edge/sim` if H99S milestone ingest must
  become a green exit criterion.
- Register the `Results → Analyzer` menu on analyzer promotion / bridge
  find-or-create, so a bench analyzer is UI-visible without a webapp restart
  (**LIS-105**).
- H99S fixture seed and parser assertions if the bench capture differs from the
  H90-series EDAN hematology fixture.
- H99S code-to-LOINC/UCUM mapping updates if OBX names/units differ from H60S.
- Image OBX display/archive policy if the lab requires WBC/DIFF/other plots in
  the LIS.
- QC routing if H99S QC upload is in scope before Stage 5.
- General bidirectional query support for analyzers beyond the released H99S
  worklist path remains change-controlled.
