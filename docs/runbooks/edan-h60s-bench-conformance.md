# Runbook - EDAN H60S bench conformance (LIS-20)

Drafted 2026-07-03 for the physical EDAN H60S bench run. This is the L3
bench-conformance plan for the Stage-1 H60S anchor: prove that the physical
analyzer reaches the LIS edge over MLLP/TCP, that the edge returns the expected
HL7 original-mode ACK, that raw wire evidence is captured, and that a real H60S
message can replace the synthetic simulator fixture.

## Bench outcome — 2026-07-06 (signed off; supersedes pre-bench expectations below)

The bench ran and passed. **The physical H60S speaks the EDAN H90-family EDANLAB
profile, not the clean-HL7 layout this runbook was drafted against.** Where the
"Expected H60S profile" and pass-criteria sections below assume `MSH-3 H60S` /
`MSH-4 EDAN` / code in OBX-3 / PID-3 / OBR-3 / `OBX-11=F`, the **confirmed real wire
supersedes them**:

| Field | Pre-bench assumption | **Confirmed on the wire (2026-07-06)** |
|---|---|---|
| `MSH-3` | `H60S` | **`H60^7907`** |
| `MSH-4` | `EDAN` | **`EDANLAB`** |
| Analyte code | OBX-3.1 | **OBX-4** (OBX-3 = 0/1 suspect flag) |
| Patient id | PID-3 | **PID-2** (PID-3 = Age^unit) |
| Specimen id | OBR-3 | **OBR-2** |
| Finality | `OBX-11=F` | **empty** — EDAN OBX-11 is a "modified?" flag, no Table-0085 finality → results held back by the sim's finality gate (production FHIR path is not finality-gated) |
| No-result | (n/a) | `***` sentinel; `MSH-16=2` on the MSH-only connection-test ping; undocumented OBX-12 `value^unit` trailer; ~33 analytes on a full frame |

**Results:** `ACK^R01` / `MSA-1=AA`; a real send staged **mapped** in OpenELIS
(`read_only=f`, LOINC-resolved WBC/RBC/HGB/PLT) after the OE stack was updated
(webapp rebuilt from the core pin; `analyzer.bridge.url` set via
`host.docker.internal:8442` — do NOT attach OE to the bridge's docker network, it
breaks the bridge→OE FHIR hop; re-register with a warm DB so `testCodeLoinc` is
pushed). The `edge/sim/fixtures/edan-h60s-oru-r01` fixture was graduated to the real
EDANLAB wire (the milestone vehicle moved to RAYTO RAC-050). Evidence:
`~/bench-runs/20260703T134217Z-h60s/` (`FINDINGS.md`, `real-send-mapped-proof.txt`);
umbrella **PR #91**; **ADR-0013 addendum (2026-07-06)**.

## References

- Slice: LIS-20, ruled in the Stage 1/2 decision dossier as "H60S retrieved from
  the warehouse; bench this week."
- Existing synthetic fixtures:
  - `edge/sim/fixtures/edan-h60s-oru-r01`
  - `edge/sim/fixtures/edan-h60s-host-query-qry-r02`
- Architecture:
  - `contexts/edge-drivers/CONTEXT.md`
  - `docs/adr/0005-mllp-framing-and-ack-modes.md`
  - `docs/adr/0011-oru-parse-and-normalization.md`
  - `docs/adr/0012-raw-message-archive-and-deterministic-replay.md`
  - `docs/adr/0015-edge-transport-substrate-and-channel-attachment.md`
- Precedent runbooks:
  - `docs/runbooks/edan-h99s-bench-conformance.md`
  - `docs/runbooks/seamaty-sd1-bench.md`

## Scope

Required for this bench:

- EDAN H60S over HL7 v2.4 MLLP/TCP, analyzer as TCP client and LIS edge as TCP
  server.
- Patient-sample `ORU^R01` CBC result upload.
- Original-mode HL7 `ACK^R01` with `MSA-1=AA` and `MSA-2` echoing inbound
  `MSH-10`.
- Raw-message capture, packet capture, bridge log, OpenELIS staging proof, and
  deterministic replay through `edge/sim`.

Characterization only unless explicitly promoted:

- H60S `QRY^R02` host-query. The simulator has a synthetic query fixture, but
  bidirectional host-query is deferred post-pilot under ADR-0008/ADR-0015.
- Non-MLLP transports. The H60S pilot path is MLLP/TCP.

## Current Bench Snapshot

Checked on 2026-07-03 before the run:

| Item | Value |
|---|---|
| Bench host active interface | `wlan0` |
| Bench host Wi-Fi IP | `192.168.1.65/24` |
| Default gateway | `192.168.1.1` via `wlan0` |
| H60S documented bench port | `7999` |
| Bridge default MLLP port currently listening | `2575` |
| Existing bridge container | `openelis-analyzer-bridge` |
| Existing OpenELIS webapp container | `openelisglobal-webapp` |

Use `192.168.1.65` as the LIS/host IP on the H60S while this snapshot remains
true. Re-check it at the start of every bench session:

```bash
ip -br addr show wlan0
ip route
ss -ltnp | grep -E ':(7999|2575)\b' || true
docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'
```

Important port distinction:

- `7999` is the documented H60S bench channel in ADR-0015 and is free in the
  current snapshot. Use it for raw reachability and first-byte capture.
- `2575` is the bridge's default MLLP listener and is already published by the
  running bridge container. Use it for bridge-backed ACK/result testing unless
  the bridge is reconfigured and restarted to listen on `7999`.

Do not run the raw `socat` listener and the bridge on the same port at the same
time.

## Evidence Packet

Create one run directory before touching the analyzer:

```bash
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-h60s"
mkdir -p "$HOME/bench-runs/$RUN_ID"
cd "$HOME/bench-runs/$RUN_ID"
```

Collect at minimum:

| Artifact | Required content |
|---|---|
| `identity.md` | Model, serial, firmware/software build, LIS protocol version, operator names, date/time. |
| `nameplate.jpg` | Physical nameplate or device identity screen. |
| `network-settings.png` | Analyzer IP/gateway/netmask and LIS IP/port settings. |
| `h60s-connectivity.pcap` | Packet capture for raw TCP/MLLP reachability on `7999`. |
| `h60s-raw.bin` | Raw inbound bytes from the raw listener, including MLLP framing if emitted. |
| `h60s-oru-message.hl7` | De-framed inbound `ORU^R01` application payload, no MLLP bytes. |
| `h60s-ack.hl7` | ACK returned by the bridge for the ORU. |
| `bridge-h60s.log` | Bridge log covering the ORU and northbound forward. |
| `analyzer-registry.json` | `GET /rest/analyzer/analyzers` after H60S registration/mapping. |
| `openelis-result.png` | OpenELIS proof of staged H60S analyzer results. |
| `edge-sim-roundtrip.txt` | `validate`, `normalize`, `roundtrip`, and `milestone` output after fixture replacement. |
| `signed-conformance-report.pdf` | Validation sign-off. |

Use bench/test identifiers only. Do not use real patient PHI. If a capture
contains PHI, keep it out of git and redact before sharing outside the validation
evidence store.

## 1. Physical Identity

1. Photograph the H60S nameplate and identity/firmware screen.
2. Record serial number, software version, LIS protocol document/version, and
   operator names in `identity.md`.
3. Confirm the unit is EDAN H60S. **Resolved 2026-07-06:** the real H60S does NOT use
   the standard OBX-3 layout the synthetic seed modeled — it emits the H90-family
   EDANLAB profile (`MSH-4 EDANLAB`, code in OBX-4), the same parser path as the H99S.
   The fixture is now graduated to that layout (see Bench outcome above).

Pass criteria:

- Identity evidence is complete.
- Any model/protocol deviation is recorded before network testing continues.

## 2. Bench Network Setup

1. Connect the H60S and bench host to the same LAN.
2. Confirm this host's active Wi-Fi IP:

   ```bash
   ip -br addr show wlan0
   ```

   Current value: `192.168.1.65/24`.

3. Configure H60S LIS settings for the raw reachability test:

   | H60S setting | Value |
   |---|---|
   | Transport/protocol | HL7 / MLLP over TCP/IP |
   | Mode | Analyzer initiated / analyzer is TCP client |
   | LIS server IP | `192.168.1.65` |
   | LIS server port | `7999` |
   | ACK mode | Original mode, `ACK^R01` |

4. If a host firewall is enabled, allow the selected bench port:

   ```bash
   sudo ufw allow 7999/tcp
   # or the local firewall equivalent
   ```

Pass criteria:

- H60S and bench host are on the same subnet or otherwise routable.
- The H60S LIS screen shows host `192.168.1.65`, port `7999` for the raw test.

## 3. Raw TCP/MLLP Reachability on 7999

This phase proves the analyzer can reach the bench host without involving
OpenELIS or the bridge.

1. Start packet capture:

   ```bash
   sudo tcpdump -i wlan0 -s0 -w h60s-connectivity.pcap tcp port 7999
   ```

   If the shell cannot capture packets because `CAP_NET_RAW` is unavailable,
   continue with the raw listener below, record the missing pcap as an environment
   limitation, and keep `h60s-raw.bin` plus listener logs as the first-line
   connectivity evidence.

2. In another shell, start a raw listener:

   ```bash
   socat -u -x -v TCP-LISTEN:7999,bind=0.0.0.0,reuseaddr,fork OPEN:h60s-raw.bin,creat,append
   ```

3. On the H60S, run its LIS connection test if available. If the connection test
   does not send application bytes, send one bench-only sample result.

4. Stop the listener and packet capture after one connection/test attempt.

Pass criteria:

- Packet capture shows the H60S as TCP client and this host as TCP server.
- If application bytes are emitted, `h60s-raw.bin` contains an MLLP frame:
  `0x0B ... 0x1C 0x0D`.
- De-framed payload starts with `MSH`, has `MSH-3`/`MSH-4` consistent with H60S
  and EDAN, and has `MSH-12=2.4`.

Notes:

- A raw listener does not ACK. If the H60S connection test requires an HL7 ACK,
  the analyzer UI may report failure even though TCP reachability and inbound
  bytes are proven. Move to Phase 4 for ACK-backed testing.
- If `h60s-raw.bin` is empty but the pcap shows a completed TCP handshake, record
  the connection test as TCP-only and send a bench sample in Phase 4.

## 4. Bridge-Backed ACK and Result Flow

Use the running bridge on `2575`, or reconfigure the bridge to `7999` and record
that config. The current local bridge is published as:

```text
openelis-analyzer-bridge 0.0.0.0:2575->2575/tcp 0.0.0.0:8442->8443/tcp
```

Option A - use existing bridge listener:

1. Reconfigure the H60S LIS server port to `2575`.
2. Keep LIS server IP as `192.168.1.65`.

Option B - keep H60S on `7999`:

1. Stop any raw listener on `7999`.
2. Reconfigure and restart the bridge so its MLLP host port is `7999`.
3. Capture the resulting bridge config as `bridge-config.yml`.

For either option:

1. Start bridge logs:

   ```bash
   docker logs -f openelis-analyzer-bridge > bridge-h60s.log
   ```

2. Start packet capture on the selected port:

   ```bash
   sudo tcpdump -i wlan0 -s0 -w h60s-e2e.pcap tcp port <selected-port>
   ```

3. Send a bench-only H60S sample result.
4. Save the ACK payload as `h60s-ack.hl7` from the pcap or bridge log.

Pass criteria:

- Bridge accepts the H60S MLLP connection.
- Bridge returns `ACK^R01` with `MSA-1=AA`.
- `MSA-2` equals the inbound `MSH-10` control id.
- Bridge logs show FHIR bundle construction and POST to
  `/api/OpenELIS-Global/analyzer/fhir`.

## 5. Register and Map H60S in OpenELIS

The bridge pulls analyzer registry and test mappings from OpenELIS. The exact
stub name/source id should be captured from the first real message; do not guess
if the bridge auto-creates a `PENDING_REGISTRATION` entry.

H60S profile — **confirmed on the wire 2026-07-06** (this table originally carried the
synthetic seed's clean-HL7 guesses; corrected to the real EDANLAB layout):

| Field | Confirmed value/layout |
|---|---|
| `MSH-3` | `H60^7907` |
| `MSH-4` | `EDANLAB` |
| Message type | `ORU^R01` |
| Version | `2.4` (encoding UTF-8) |
| Patient id | `PID-2` (PID-3 = Age^unit) |
| Specimen/sample id | `OBR-2` (OBR-3 = reviewing doctor) |
| Analyzer test code | `OBX-4` (OBX-3 = 0/1 suspect flag) |
| Finality | `OBX-11` empty — EDAN "modified?" flag, not Table-0085 finality |
| No-result / mode | `***` no-result sentinel; `MSH-16=0` data / `=2` connection-test ping |

Target CBC mappings:

| H60S code | LOINC | Meaning |
|---|---|---|
| `WBC` | `6690-2` | Leukocytes |
| `RBC` | `789-8` | Erythrocytes |
| `HGB` | `718-7` | Hemoglobin |
| `HCT` | `4544-3` | Hematocrit |
| `MCV` | `787-2` | Mean corpuscular volume |
| `PLT` | `777-3` | Platelets |

Registration steps:

1. After first inbound ORU, fetch the analyzer registry and save it:

   ```bash
   curl -ks https://oe.openelis.org:8443/api/OpenELIS-Global/rest/analyzer/analyzers \
     > analyzer-registry.before.json
   ```

2. Promote the H60S stub or create the analyzer entry:
   - name: `EDAN H60S`
   - type: hematology
   - protocol: HL7 v2.4 / MLLP
   - communication mode: analyzer initiated
   - identifier pattern/source id: use the actual value observed from the bridge
     registry entry, expected to correspond to `H60S`/`EDAN`
   - mappings: the six CBC rows above

3. Restart the bridge or wait for registry sync so it pulls the promoted entry.
4. Send a fresh bench sample after mapping. Do not use pre-mapping scratch rows
   as conformance results.
5. Capture the final registry:

   ```bash
   curl -ks https://oe.openelis.org:8443/api/OpenELIS-Global/rest/analyzer/analyzers \
     > analyzer-registry.json
   ```

Pass criteria:

- OpenELIS has an active `EDAN H60S` analyzer entry with all six CBC mappings.
- A post-mapping ORU stages rows under Results -> Analyzer for H60S.
- Staged rows are mapped to the expected OpenELIS tests and are not marked
  unmapped/read-only because of missing H60S mappings.

## 6. Fixture Graduation

Once real bytes are captured, replace the synthetic H60S ORU fixture with the
de-framed real payload.

1. Extract the application payload from the raw MLLP frame:

   ```bash
   python3 - <<'PY'
from pathlib import Path

raw = Path("h60s-raw.bin").read_bytes()
start = raw.find(b"\x0b")
end = raw.find(b"\x1c\x0d", start + 1)
if start < 0 or end < 0:
    raise SystemExit("no complete MLLP frame found")
Path("h60s-oru-message.hl7").write_bytes(raw[start + 1:end])
print(f"wrote {end - start - 1} bytes")
PY
   ```

2. Diff the real payload against the synthetic fixture:

   ```bash
   diff -u edge/sim/fixtures/edan-h60s-oru-r01/message.hl7 h60s-oru-message.hl7 || true
   ```

3. Update `edge/sim/fixtures/edan-h60s-oru-r01/message.hl7` with the real,
   de-framed payload after PHI review/redaction.
4. Update the manifest:
   - `synthetic: false`
   - `source.reference`: bench run id, serial number, firmware/software build
   - `source.note`: observed port, framing, ACK, and any parser deviations
   - `expected`: real patient/specimen test identifiers replaced with bench-safe
     IDs if needed, while preserving analyzer code/unit behavior
5. Run the simulator checks:

   ```bash
   cd edge/sim
   uv run --frozen --python 3.12 edge-sim validate
   uv run --frozen --python 3.12 edge-sim normalize edan-h60s-oru-r01
   uv run --frozen --python 3.12 edge-sim roundtrip edan-h60s-oru-r01 --transport mllp
   uv run --frozen --python 3.12 edge-sim milestone edan-h60s-oru-r01
   uv run --frozen --python 3.12 pytest -q
   ```

Pass criteria:

- Fixture validates and round-trips.
- `normalize` resolves all six CBC rows to expected LOINC/UCUM values.
- `milestone` accepts the fixture and emits six ingest-contract observations.
- Any real-wire parser deviation is either handled in a bridge/simulator PR or
  recorded as a follow-up before the fixture is marked conformant.

## Done Criteria

- H60S identity and network settings captured.
- Raw reachability proven from H60S to bench host.
- Bridge-backed ORU returns `ACK^R01` / `MSA-1=AA`.
- OpenELIS stages a post-mapping H60S CBC result.
- Real H60S ORU fixture replaces the synthetic seed, with `synthetic:false`.
- `edge/sim` validation, normalize, roundtrip, milestone, and pytest output saved.
- LIS-20 is updated with the evidence packet path, deviations, and follow-up issues.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| H60S cannot connect to `192.168.1.65:7999` | Wrong LIS IP/port, Wi-Fi isolation, firewall, raw listener not running | Re-check `ip -br addr show wlan0`; start `socat`; allow `7999/tcp`; confirm H60S is on `192.168.1.0/24`. |
| `tcpdump` cannot capture on `wlan0` | Shell lacks packet-capture capability (`CAP_NET_RAW`) | Continue with `socat` raw-byte capture; run tcpdump from a host shell with capture permissions if pcap evidence is mandatory. |
| TCP handshake succeeds but H60S UI says connection failed | Raw listener does not send HL7 ACK | Move to bridge-backed Phase 4 or use an ACK-capable test listener. |
| Bridge on `2575` receives nothing | H60S still points to `7999`, firewall, wrong host IP | Set H60S port to `2575` for existing bridge, or reconfigure bridge to `7999`; capture with `tcpdump`. |
| ACK is not `AA` | Bridge rejected or could not route/process message | Inspect `bridge-h60s.log`, inbound `MSH`, registry status, and analyzer mappings. |
| Results stage unmapped/read-only | Analyzer entry or mappings missing/stale | Promote H60S registry entry, add six CBC mappings, restart or sync bridge, resend a fresh sample. |
| Real H60S fields do not match the synthetic fixture | Vendor protocol differs from seed | Record the deviation; update simulator/bridge profile before fixture graduation. |
