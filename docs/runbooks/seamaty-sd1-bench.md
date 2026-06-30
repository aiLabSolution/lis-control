# Runbook — Seamaty SD1 bench test (LIS-79 / S2.9 · Stage-1 checklist Action #4)

Bring a **physical Seamaty SD1** dry-chemistry analyzer onto the bench, connect it to the
same Wi-Fi LAN as the bench PC, and drive one real `ORU^R01` result through the production
edge **bridge** -> **OpenELIS** core, then **graduate** the synthetic fixture
`seamaty-sd1-oru-r01` to a real capture.

This is the field execution of **Action #4** in
[`docs/testing/stage-1-3-machine-access-checklist.md`](../testing/stage-1-3-machine-access-checklist.md):
> *Real-instrument capture to lock the operator-set **TCP port**, confirm **MLLP framing** +
> ASCII-vs-UTF-8 encoding, and verify the patient/sample identifier layout on the wire.*

Related: the SD1 parser quirks (PID-2 fallback, in-band `Alarm` routing) already landed in the
bridge — **LIS-86**, pin `a98db88`. Unit→UCUM + full code→LOINC core seed is **LIS-87** (open).

---

## 0. TL;DR — the six phases

| # | Phase | Goal | Gate |
|---|---|---|---|
| **0** | **Oracle** | Run `edge-sim` to print the known-good expected output you will diff against. | 17 SD1 tests green |
| **1** | **Link** | Same Wi-Fi LAN, firewall, SD1 LIS Server / Host IP -> this PC's Wi-Fi IP:port. | SD1 can reach the listener |
| **2** | **Raw capture (FIRST)** | Point SD1 at a *dumb* TCP listener; lock the operator-set port; confirm MLLP framing + encoding + identifier fields on the wire. | `0x0B …0x1C 0x0D` frame saved |
| **3** | **Bridge** | Build the bridge **from the pinned source** (LIS-86), enable MLLP on 2575, point it at OpenELIS. | `/actuator/health/mllp` = UP |
| **4** | **Core** | Bring up OpenELIS, register the SD1 analyzer. | UI login + analyzer ACTIVE |
| **5** | **Live E2E** | SD1 → bridge (ACK) → FHIR `/analyzer/fhir` → results stage in OpenELIS. | result row visible in UI |
| **6** | **Graduate** | Diff capture vs oracle; flip fixture `synthetic:false`; two-level PR; log LIS-79. | PR open, Plane updated |

> **Do Phase 2 before Phase 3.** A raw byte-capture is the cheapest way to learn the truth
> (port, framing, encoding, field layout) *without* the bridge masking it. The bridge expects a
> well-formed MLLP frame; if the SD1 frames differently you want to see that raw.

**What this proves today vs. what is a known follow-up** — read §1 "Expectation setting" before you
judge results. In short: connectivity, framing, ACK, OBR/PID identifier routing, Alarm routing,
and *results staging* are deterministic today; **full LOINC/UCUM normalization of the whole panel is not**
(only `GLU` is seeded in core; the rest are LIS-87) — results will still arrive, just flagged
unmapped.

---

## 1. The mental model (read this first)

```
  Seamaty SD1                same Wi-Fi LAN             Bench PC
 (TCP CLIENT)  ─────── MLLP / HL7 v2.3.1 ───────▶  [ bridge :2575 ]  (LISTENS)
  upload-only        <SB>0x0B … payload … 0x1C 0x0D       │ parse + build FHIR R4 bundle
  ORU^R01  ◀── ACK^R01 (MSA-1=AA) ──────────────          ▼
                                                  POST /api/OpenELIS-Global/analyzer/fhir
                                                          ▼
                                                  [ OpenELIS core ] → ANALYZER_RESULTS staging
                                                          ▼  operator reviews & accepts
                                                  Results → analysis/result tables
```

Facts that drive every step below (all verified against the pin):

- **The SD1 is the TCP *client*.** It *dials out* to a host IP:port you set in its LIS menu.
  Your PC **listens**. Upload-only: it sends `ORU^R01`, expects an `ACK` back. No worklist/host-query.
  *(`edge/sim/fixtures/seamaty-sd1-oru-r01/manifest.json`)*
- **On the Wi-Fi bench, the SD1's `LIS Server` / `Host IP` is the bench PC's Wi-Fi IP.**
  Current verified bench value (2026-06-30): `wlan0` = `192.168.1.128/24`.
- **HL7 v2.3.1 over MLLP.** Frame = `SB(0x0B)` + payload + `EB(0x1C)` + `CR(0x0D)`.
  *(`edge/drivers/src/main/java/org/itech/ahb/mllp/MLLPConfig.java`)*
- **Bridge MLLP listener: port `2575`**, but `org.itech.ahb.mllp.enabled` defaults to **false**
  — the `dev` Spring profile flips it on. *(`configuration.yml:127`, `application-dev.yml:21-23`)*
- **HL7/MLLP forwards as FHIR.** The bridge parses HL7, builds a FHIR R4 bundle, and POSTs to
  **`/analyzer/fhir`** (FHIR routing is on by default), *not* raw HL7 to `/analyzer/hl7`.
  *(`FhirRoutingConfig.java:27` `useFhir=true`; `HttpForwardingRouter.java:177`)*
- **Three SD1 quirks are already handled (LIS-86):**
  1. **PID-2 MRN fallback** — accession resolves OBR → PID-3.1 → **PID-2.1**; a real PID-3 still wins.
     *(`HL7ResultParser.java:88-103`)*
  2. **In-band `Alarm` OBX** (`OBX-3='Alarm'`) → `DiagnosticReport.conclusion` + `conclusionCode`,
     **never** a numeric Observation. *(`HL7ResultParser.java:173`, `FhirBundleBuilder.java:127-235`)*
  3. Dry-chem codes/units recognized (seeded in the *sim's* `normalize.py`; see the core caveat below).

2026-06-30 bench finding: the first real Wi-Fi capture had valid MLLP framing and `MSH-18=ASCII`,
but **PID-2 and PID-3 were both blank**. The bridge should use the OBR accession path first
(`OBR-3`, then `OBR-2`) rather than the PID fallback for that message. Do not treat a blank
PID-2 as a capture failure; treat it as the real SD1 identifier layout for this sample mode.

### Expectation setting — what a real run shows *today*

The bridge pulls each analyzer's `codeToLoinc` map from OpenELIS on startup
(`AnalyzerRegistryBootstrap` → `/rest/analyzer/analyzers`). So **LOINC/UCUM coding in the
produced bundle is only as complete as what OpenELIS has seeded.**

| Behaviour | Today | Source |
|---|---|---|
| SD1 connects, MLLP frame parsed, **ACK returned** | ✅ deterministic | bridge |
| OBR accession parsing + PID-3/PID-2 fallback | ✅ deterministic (parser-side, no core dep) | LIS-86 |
| **Alarm → conclusion** when an `Alarm` OBX is present | ✅ deterministic (parser-side, no core dep) | LIS-86 |
| Results **forwarded & staged** in OpenELIS (even if unmapped) | ✅ never dropped | core |
| `GLU` → LOINC `2345-7` | ✅ seeded in our `lis-8` core build | core `vendor_code_mapping` |
| `BUN/CREA/AST/ALT/TP` → LOINC, `U/L`→UCUM | ❌ **not yet** → stage as `read_only` unmapped | **LIS-87** |

So: **do not treat unmapped BUN/CREA/AST/ALT/TP rows as a failure.** That is the expected,
known gap. The bench test's job is to prove *the pipe and the quirks*, capture the real wire,
and graduate the fixture — the core LOINC seed is a separate PR (LIS-87).

> The **`edge-sim` oracle normalizes the whole panel** because the simulator carries its own
> hardcoded maps. Use the oracle to validate **protocol/parse fidelity** (patient id, specimen,
> codes, values, Alarm routing) — *not* to predict what OpenELIS core will have mapped.

---

## 2. What you need

**Hardware**
- Seamaty SD1, powered, with a tested sample loaded (so you can trigger a real result send).
- Wi-Fi access for the SD1 on the same LAN used by the bench PC.
- The bench PC (this box), already joined to the bench Wi-Fi.

**Software (already on this box)**
- Docker Engine + Compose v2 (`docker compose version`).
- The `lis-control` checkout with **both** submodules initialised:
  ```bash
  cd /home/marloeu/projects/lis-control
  git submodule update --init edge/drivers core/openelis
  ```
- `socat` and `tcpdump`/`hexdump` for the raw capture (Phase 2). `ncat` is optional if installed.
- Python venv for the oracle is pre-built at `edge/sim/.venv` (Phase 0).

**Docs**
- Seamaty **LIS Interface Manual** (Edition B/0) — `manuals-and-lis-protocol/RAYTO/SEAMATY/lis-protocol.pdf`.
  §1.6/§1.7 = MLLP framing/encoding; §3.x = the SD1 LIS settings menu; §4.1.1 = the worked example
  the fixture is modeled on.

---

## 3. Phase 0 — Prepare the oracle (offline, do this first)

Print the known-good reference the real capture must match. Nothing is plugged in yet.

```bash
cd /home/marloeu/projects/lis-control/edge/sim
source .venv/bin/activate

python -m edge_sim list | grep seamaty            # confirm the fixture is present
python -m edge_sim normalize seamaty-sd1-oru-r01  # parse → LOINC/UCUM rows
python -m edge_sim milestone seamaty-sd1-oru-r01  # E2E: MLLP replay + ACK + ingest DTO
python -m edge_sim ack       seamaty-sd1-oru-r01  # the ACK^R01 the listener returns
python -m edge_sim roundtrip seamaty-sd1-oru-r01 --transport mllp
python -m pytest tests/test_seamaty_sd1.py -q     # 17 tests must pass
```

**Expected output (captured from this repo — your real capture is "correct" when it matches the
shape of these rows):**

```
# normalize
seamaty-sd1-oru-r01     ORU^R01 patient=SD1-0042  specimen=SD1-SPEC-0007
  OBX-1 GLU 95 mg/dL    -> LOINC 2345-7 / UCUM mg/dL  [NORMALIZED]
  OBX-2 BUN 14 mg/dL    -> LOINC 3094-0 / UCUM mg/dL  [NORMALIZED]
  OBX-3 CREA 0.9 mg/dL  -> LOINC 2160-0 / UCUM mg/dL  [NORMALIZED]
  OBX-4 AST 28 U/L      -> LOINC 1920-8 / UCUM U/L    [NORMALIZED]
  OBX-5 ALT 33 U/L      -> LOINC 1742-6 / UCUM U/L    [NORMALIZED]
  OBX-6 TP 7.2 g/dL     -> LOINC 2885-2 / UCUM g/dL   [NORMALIZED]
  OBX-7 Alarm           -> [WARNING note] Reagent rotor is not allowed to be re-used. Please re-test with a new one.

# milestone
milestone seamaty-sd1-oru-r01 via mllp: ACCEPTED (ACK^R01 MSA-1=AA)
  ... 6 NORMALIZED (final) rows ... OBX-7 Alarm -> [WARNING note] ...
  ingest contract (core ADR-0003): 6 observation(s)        # warning excluded by kind filter

# ack
MSH|^~\&|||SMT|SD1|<ts>||ACK^R01^ACK|1|P|2.3.1
MSA|AA|1|

# roundtrip --transport mllp
roundtrip seamaty-sd1-oru-r01 via mllp: bytes OK | src 68d085f70c4f -> result 616353038dae
  ... expected: OK

# pytest
17 passed
```

Note the **source digest `68d085f70c4f`** is the SHA-256 of the *synthetic* payload. After Phase 6
your captured payload will produce a **different** digest — that's how you'll know the seed was
replaced by real bench bytes.

---

## 4. Phase 1 — Link bring-up (Wi-Fi/LAN)

> Current bench snapshot (checked 2026-06-30): `wlan0` is UP at `192.168.1.128/24`,
> with the default route via `192.168.1.1`. `192.168.1.155` also replies on the Wi-Fi
> LAN, but it is not this host in the current routing table. If the address changes,
> use `ip -br addr show wlan0` as the source of truth.

1. **Join the SD1 to the same Wi-Fi LAN as the bench PC.**
   In the SD1 network / communication settings, set the connection type to **Wi-Fi/WLAN**
   rather than Ethernet or RS-232.
2. **Verify the PC's Wi-Fi IP before touching the SD1 LIS menu:**
   ```bash
   ip -br addr show wlan0           # current bench: wlan0 UP 192.168.1.128/24
   ip route                         # expect default route via wlan0
   ```
3. **Configure the SD1's LIS menu** (Settings -> LIS / Communication; SD1 manual §3.x):
   - **Connection:** Wi-Fi/WLAN.
   - **Mode/Protocol:** HL7 (MLLP / TCP-IP). RS-232 is the alternative; do not use it for this bench.
   - **LIS Server / Host IP:** `192.168.1.128` (the bench PC's current Wi-Fi IP). If `wlan0`
     reports a different address, use that address instead. Do **not** enter `192.168.1.155`
     unless that is currently the PC's Wi-Fi IP.
   - **Port:** `2575` (match the bridge MLLP port). **Write down whatever the operator field
     actually allows** — this *operator-set port is one of the things this bench locks (Action #4).*
   - **Patient sample mode** (`MSH-16=0`).
   - Record the SD1's own Wi-Fi IP as `<SD1_WIFI_IP>`; DHCP is fine as long as it stays on
     `192.168.1.0/24`.
4. **Open the firewall** on the listener port:
   ```bash
   sudo ufw allow 2575/tcp        # UFW
   # or: sudo firewall-cmd --add-port=2575/tcp && sudo firewall-cmd --reload
   ```
5. **Prove the Wi-Fi path** (from the PC):
   ```bash
   ping -c3 <SD1_WIFI_IP>         # the SD1; some firmware will not answer ICMP

   # TCP 2575 succeeds only while the Phase-2 raw listener or Phase-3 bridge is running.
   timeout 3 bash -c '</dev/tcp/192.168.1.128/2575'
   ```

   If the TCP check returns `Connection refused` before Phase 2/3, the route is fine but no
   LIS listener is up yet. Start the raw `socat` listener or the bridge before testing SD1 upload.

---

## 5. Phase 2 — Raw capture **first** (lock port, framing, encoding, identifiers)

The de-risking step. Stand up a *dumb* TCP listener on the port, trigger one SD1 send, and read
the bytes. This is what closes **Action #4**.

1. **Listen + save raw bytes** on the PC (pick one):
   ```bash
   mkdir -p ~/bench-runs/$(date -u +%Y%m%dT%H%M%SZ) && cd $_

   # Option A — socat: one-way capture from the SD1 socket to a file.
   # -u is required because CREATE is write-only; without it socat tries to read
   # back from sd1-raw.bin and exits with "Bad file descriptor".
   rm -f sd1-raw.bin
   socat -u -x -v TCP-LISTEN:2575,reuseaddr,fork CREATE:sd1-raw.bin

   # Option B — ncat: one connection, dump to file (if ncat is installed)
   ncat -l 0.0.0.0 2575 > sd1-raw.bin

   # Option C — packet-level pcap (run alongside A/B, full evidence)
   sudo tcpdump -i wlan0 -w sd1-flow.pcap tcp port 2575
   ```
2. **On the SD1, send a result** (re-print / re-transmit the loaded sample to LIS).
3. **Inspect the frame:**
   ```bash
   hexdump -C sd1-raw.bin | head -40
   ```
   **Confirm, and record in your bench notes:**
   - [ ] First byte is **`0b`** (`SB`/VT); the payload ends with **`1c 0d`** (`EB FS` + `CR`).
         *If not, the SD1's LIS mode is wrong or it speaks raw HL7/another framing — note it.*
   - [ ] **Encoding** — `file sd1-raw.bin` (ASCII vs UTF-8). The manual conflicts (§1.6 ASCII vs a
         p4 UTF-8 remark); **this capture is the tie-breaker.** Record the answer.
   - [ ] **The operator-set port actually used** (you set it; confirm the SD1 connected to it).
   - [ ] **Identifier layout** — strip the framing and eyeball the segments:
         ```bash
         # drop 0x0B prefix and 0x1C 0x0D suffix, show segments one per line
         sed 's/^\x0b//; s/\x1c\x0d$//' sd1-raw.bin | tr '\r' '\n'
         ```
        Record whether **`PID-2`** or **`PID-3`** carries an identifier. In the 2026-06-30 Wi-Fi
        capture both were blank, with patient demographics in `PID-5`/`PID-7`/`PID-8` and the
        analyzer/order identifiers in `OBR`. Capture `MSH-18` (character set token), the `OBX`
        codes/units, and whether an `Alarm` OBX is present. Do not paste patient-identifying
        values into repo docs, tickets, or PR comments.
4. **Keep `sd1-raw.bin` and `sd1-flow.pcap`** — these are your evidence *and* the seed for the
   Phase-6 fixture.

> If anything here disagrees with the fixture (different port field, UTF-8 not ASCII, MRN not in
> PID-2, extra/renamed segments), **that is a finding** — it's exactly why we capture before
> trusting the synthetic seed. Note it; it may require a bridge tweak (two-level PR) in Phase 6.

---

## 6. Phase 3 — Bring up the bridge (from the pinned source)

> ⚠️ **Build from source — do not pull `itechuw/openelis-analyzer-bridge:latest`.** The upstream
> image predates **LIS-86**; it lacks the SD1 PID-2 fallback + Alarm routing. The default
> `docker-compose.yml` uses that upstream image. Use **`docker-compose-dev.yml`**, which builds
> the container from `edge/drivers/` at the checked-out pin (`a98db88`).

**One-time fix:** `docker-compose-dev.yml` is missing the MLLP port mapping. Add `2575:2575`:

```yaml
# edge/drivers/docker-compose-dev.yml — under services.openelis-analyzer-bridge.ports
    ports:
      - "8442:8443"
      - "12000:12001"
      - "8000:8000"
      - "2575:2575"     # ← ADD: MLLP HL7 listener (the SD1 dials this)
```

You also need the bridge container to **reach OpenELIS** (Phase 4) and to enable MLLP. The `dev`
profile already sets `mllp.enabled=true`. Point the forward URI at a host-reachable address —
**`localhost` inside the container is the container, not OpenELIS.** Easiest: set the host's LAN/bridge
IP. Edit `edge/drivers/configuration.yml`:

```yaml
org:
  itech:
    ahb:
      forward-http-server:
        # was http://localhost:8080/...  — localhost won't reach OE from inside the container.
        uri: http://<HOST_IP>:8080/api/OpenELIS-Global/analyzer   # current Wi-Fi bench: 192.168.1.128
      mllp:
        enabled: true     # belt-and-suspenders; dev profile sets this too
        port: 2575
```

*(Alternative to host-IP addressing: attach the bridge to the OpenELIS compose network and use the
service name `oe.openelis.org`. Host-IP is simpler for a one-box bench.)*

**Optionally register the SD1 by source IP** so the bridge tags it deterministically (otherwise the
analyzer is identified from `MSH-3/MSH-4`):

```yaml
# edge/drivers/configuration.yml — bridge.analyzers
bridge:
  analyzers:
    "<SD1_WIFI_IP>":
      id: SEAMATY-SD1-001
      name: "Seamaty SD1"
      expectedProtocol: HL7
```

**Run it & verify the listener:**

```bash
cd /home/marloeu/projects/lis-control/edge/drivers
docker compose -f docker-compose-dev.yml up -d --build      # builds OUR pinned source
docker logs -f openelis-analyzer-bridge                     # watch for the MLLP listener line

curl -s http://localhost:8442/actuator/health/mllp | jq .   # expect status: UP, port 2575
curl -s http://localhost:8442/actuator/health/httpforward | jq .   # UP ⇒ bridge can reach OE
docker ps | grep openelis-analyzer-bridge                   # expect 0.0.0.0:2575->2575/tcp
```

- `/actuator/health/mllp` = **UP** → listener is accepting connections.
- `/actuator/health/httpforward` = **UP** → the forward URI reaches OpenELIS (do Phase 4 first if DOWN).

---

## 7. Phase 4 — Bring up OpenELIS & register the analyzer

Use the **verified** local bring-up (see the `local-openelis-bringup` note). The box is
RAM-tight — **stop co-resident stacks first** and drop FHIR to save ~2 GiB.

```bash
# 1) Free the ports/RAM — OpenELIS binds :8080 like the ERPNext frontends do.
docker stop erpnext erpnexttrial crate-db-demo 2>/dev/null || true
docker network rm erpnexttrial_default 2>/dev/null || true   # frees the 172.20.x overlap

# 2) Lean bring-up (digest-pinned images; FHIR dropped).
cd /home/marloeu/projects/lis-control
C="-f core/openelis/docker-compose.yml -f core/openelis/.github/ci/ci.memory-limits.yml -f deploy/ci/compose.bootstrap.yml"
docker compose --project-directory core/openelis $C up -d certs db.openelis.org oe.openelis.org frontend.openelis.org proxy
bash deploy/ci/healthcheck.sh        # waits: db healthy + webapp running + UI 200
```

- **UI:** https://localhost (self-signed) · also http://localhost:8080 · DB on :15432.
- **Login:** `admin` / `adminADMIN!`.
- **Teardown later (keep data):** `docker compose --project-directory core/openelis $C down`
  — **never `-v`** (that wipes the `openelis_db-data` volume).
- **Current Wi-Fi LAN check:** `https://192.168.1.128` should reach the same OpenELIS proxy
  while this box keeps that `wlan0` address.

> To exercise the **full LOINC seed** beyond `GLU`, run the from-source `openelis-dev` build
> (`lis-8`) per the bring-up note — but for *this* bench, the prebuilt webapp is fine; treat the
> unmapped panel rows as the LIS-87 follow-up (see §1).

**Register the SD1 analyzer** so its codes can map and its results are reviewable:
1. UI → **Admin → Analyzer Configuration** (`/analyzers`). The first SD1 bundle from an unknown
   source auto-creates a **`PENDING_REGISTRATION`** stub keyed on the source IP — promote it, or
   create the profile up front.
2. Name `Seamaty SD1`; protocol `HL7`; status `ACTIVE`.
3. Under **Test Mappings**, map each analyte to its OpenELIS test / LOINC
   (`GLU 2345-7`, `BUN 3094-0`, `CREA 2160-0`, `AST 1920-8`, `ALT 1742-6`, `TP 2885-2`).
   Anything left unmapped will still **stage** (as `read_only=true`, `import_issue_reason=unmapped_loinc:<code>`),
   just not be acceptable until mapped.

---

## 8. Phase 5 — Live end-to-end ingest

Now point the real SD1 at the **bridge** (Phase 2 used a dumb listener; both can't hold 2575 at
once — stop the `ncat`/`socat` listener first).

1. Keep a `tcpdump` running for evidence:
   `sudo tcpdump -i wlan0 -w sd1-e2e.pcap tcp port 2575`
2. On the SD1, **send the sample result** again (now the bridge is the listener).
3. **Watch the bridge** ingest and forward:
   ```bash
   docker logs -f openelis-analyzer-bridge | grep -Ei "mllp|processing|fhir|routed|MSA"
   ```
   Expect: message received from `<SD1_WIFI_IP>` -> FHIR bundle built -> `POST …/analyzer/fhir`
   → `ACK` returned (`MSA|AA`).
4. **Confirm the ACK on the wire** (the SD1 should report a successful upload; or read the pcap):
   ```bash
   tcpdump -r sd1-e2e.pcap -A 'tcp src port 2575' 2>/dev/null | grep -m1 "MSA|AA"
   ```
5. **Confirm results staged in OpenELIS:**
   - **UI:** Menu → **Results → Analyzer Results** (`/AnalyzerResults?type=Seamaty%20SD1`).
     The panel rows appear; mapped ones are acceptable, unmapped ones show `read_only`.
   - **DB (optional, fast check):**
     ```bash
     docker exec openelisglobal-database psql -U clinlims -d clinlims -c \
       "select accession_number, test_name, result, read_only, import_issue_reason \
        from clinlims.analyzer_results order by id desc limit 10;"
     ```
6. **Verify the SD1 parser behaviours landed:**
   - **Identifier routing** — confirm the bridge used the expected accession/source field. For the
     2026-06-30 Wi-Fi capture, PID-2/PID-3 were blank and the bridge should resolve from OBR before
     considering the PID fallback.
   - **Alarm** — if this run includes an `Alarm` OBX, confirm it is **not** a result row; it should
     ride through as a report **conclusion** (FHIR `DiagnosticReport.conclusion`/`conclusionCode`),
     never an analyte. If the run has no `Alarm` OBX, record that Alarm handling was not exercised
     by this particular bench upload.
7. **Accept** the mapped results in the UI (checkbox → **Save**, `POST /rest/AnalyzerResults`) to push
   them into the analysis/result tables.

---

## 9. Phase 6 — Conformance & graduate the fixture (closes LIS-79)

Replace the synthetic seed with the real capture so the conformance suite now rides on real bytes.
Edge slices are **two-level** — land in both the sim mirror *and*, if the wire differed, the bridge.

1. **Extract the HL7 application payload** from your Phase-2 capture (strip MLLP framing):
   ```bash
   sed 's/^\x0b//; s/\x1c\x0d$//' ~/bench-runs/<ts>/sd1-raw.bin \
     > edge/sim/fixtures/seamaty-sd1-oru-r01/message.hl7
   ```
   *(The fixture stores payload only — framing is applied by the transport at replay time.)*
   If the captured payload contains patient-identifying values, de-identify it before committing:
   preserve the field layout, timestamp shape, code/unit/value shape, blank PID-2/PID-3 state,
   and OBR/OBX structure, but replace names and other direct identifiers with safe fixture values.
2. **Flip the manifest to captured** — `edge/sim/fixtures/seamaty-sd1-oru-r01/manifest.json`:
   - `"synthetic": false`
   - `message.encoding`: the value you **confirmed** in Phase 2 (`ascii` or `utf-8`).
   - `source.reference`: the bench session id (e.g. `bench-2026-07-01T0930Z`) + instrument SN/firmware.
   - Add a capture note: operator, date, sample id, the confirmed port, framing, encoding, and
     identifier layout (`PID-2`/`PID-3` present or blank; OBR accession fields observed).
   - Update `expected.*` only if the real values legitimately differ from the seed.
3. **Re-validate against the oracle** (the digest *will* change — that's the point):
   ```bash
   cd edge/sim && source .venv/bin/activate
   python -m edge_sim validate
   python -m edge_sim roundtrip seamaty-sd1-oru-r01 --transport mllp   # expect: bytes OK / expected: OK
   python -m pytest tests/test_seamaty_sd1.py -q                       # still green
   ```
4. **If the wire differed from the parser's assumptions** (encoding, an unexpected segment, a
   different Alarm shape), open a bridge PR on `aiLabSolution/openelis-analyzer-bridge` first, then
   bump the umbrella pin (two-level, per ADR-0001).
5. **PR + Plane:** open the fixture PR off a slice branch/worktree (never commit on `main`), and
   update **LIS-79** with the capture artifacts. If full normalization matters for the pilot,
   reference **LIS-87** for the core code→LOINC / U/L→UCUM seed.

---

## 10. Acceptance checklist

Bench is **done** when:

- [ ] **Phase 0** oracle green: `pytest tests/test_seamaty_sd1.py` = 17 passed.
- [ ] **Phase 1** Wi-Fi link verified: SD1 connection is Wi-Fi/WLAN, and SD1 `LIS Server` /
      `Host IP` equals this PC's current Wi-Fi IP (`192.168.1.128` on the 2026-06-30 check).
- [ ] **Phase 2** raw frame captured: starts `0x0B`, ends `0x1C 0x0D`; **encoding recorded**;
      **operator-set port recorded**; **identifier layout recorded** (`PID-2`/`PID-3` present
      or blank, OBR accession fields observed). *(Action #4 closed.)*
- [ ] **Phase 3** bridge built **from source** (LIS-86), `/actuator/health/mllp` = UP, `2575` mapped.
- [ ] **Phase 4** OpenELIS up, SD1 analyzer registered (ACTIVE).
- [ ] **Phase 5** live `ORU^R01` → **ACK `MSA|AA`** → results **staged** in `analyzer_results`.
- [ ] **Phase 5** parser behaviours verified: message accepted via OBR/PID identifier routing;
      if an `Alarm` OBX is present, **Alarm** routed to conclusion, not a result.
- [ ] **Phase 6** fixture graduated (`synthetic:false` + real `message.hl7`), oracle re-validated,
      PR open, **LIS-79** updated.

Known, accepted non-blockers (LIS-87): `BUN/CREA/AST/ALT/TP` and `U/L`→UCUM may stage **unmapped**
until the core seed lands. That is *not* a bench failure.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| SD1 says `LIS Server disconnected` after switching to Wi-Fi | Correct IP but no listener on `2575`, or the SD1 points at another LAN host | Verify `ip -br addr show wlan0`; set SD1 `LIS Server` / `Host IP` to this PC's Wi-Fi IP (current check: `192.168.1.128`); start Phase-2 `socat` or the Phase-3 bridge; verify `ss -ltnp | grep :2575` |
| SD1 won't connect / no bytes in Phase 2 | Wrong host IP/port on the SD1; firewall; Wi-Fi isolation; SD1 not on the same subnet | Re-check SD1 LIS menu host=`<PC_WIFI_IP>` port=`2575`; `ufw allow 2575/tcp`; `ip -br addr show wlan0`; confirm SD1 Wi-Fi IP is on `192.168.1.0/24` |
| Captured bytes don't start with `0x0B` | SD1 in a non-MLLP mode, or raw HL7/serial | Check SD1 LIS mode = HL7/MLLP-TCP; note the actual framing (a real finding) |
| `file sd1-raw.bin` says UTF-8, manifest says ASCII | The §1.6-vs-p4 encoding conflict | Record UTF-8 in the captured manifest; flag to LIS-87 (bridge encoding handling) |
| Bridge `health/mllp` = DOWN | MLLP not enabled, or port not mapped | Confirm `mllp.enabled=true` (dev profile), and `2575:2575` is in `docker-compose-dev.yml` |
| Bridge `health/httpforward` = DOWN | `forward…uri` points at `localhost` (= the container) | Set `<HOST_IP>` (or attach to the OE network + use `oe.openelis.org`) |
| Quirks missing (msg rejected / Alarm as a result) | Running the upstream `itechuw:latest` image (no LIS-86) | Rebuild from source via `docker-compose-dev.yml` at pin `a98db88` |
| Results never appear in OpenELIS | Analyzer unregistered, or no matching sample/accession | Register SD1 in `/analyzers`; ensure a sample/accession exists; check `analyzer_results` + bridge logs |
| Panel rows show `read_only` / `unmapped_loinc` | Core code→LOINC not seeded (expected) | Map tests in `/analyzers`, or accept as the LIS-87 follow-up |
| OpenELIS won't start / "Pool overlaps" / :8080 busy | ERPNext stacks running; `172.20.x` net overlap | `docker stop erpnext erpnexttrial`; `docker network rm erpnexttrial_default` |

---

## 12. Evidence to keep (ISO 15189 traceability)

Save under `~/bench-runs/<ISO8601>/`:
- `sd1-raw.bin` (raw MLLP frame) and the extracted `message.hl7`.
- `sd1-flow.pcap` / `sd1-e2e.pcap` (full wire, Wireshark-readable).
- `bridge.log` (`docker logs openelis-analyzer-bridge > bridge.log`).
- Screenshot of the SD1 network + LIS settings (Wi-Fi connection, LIS Server/Host IP, port,
  protocol) and of the OpenELIS Analyzer Results row.
- Operator notes: instrument SN + firmware, sample id(s), confirmed **port / framing / encoding /
  identifier layout**, timestamp, anyone present.

These become the `source.reference`/`note` on the graduated fixture and the LIS-79 audit trail.

---

## 13. References

- **Fixture & oracle:** `edge/sim/fixtures/seamaty-sd1-oru-r01/{manifest.json,message.hl7}`,
  `edge/sim/tests/test_seamaty_sd1.py`, `edge/sim/src/edge_sim/{normalize,oru,milestone,mllp}.py`.
- **Bridge (pin `a98db88`):** `edge/drivers/configuration.yml`, `docker-compose-dev.yml`,
  `src/main/java/org/itech/ahb/mllp/{MLLPConfig,HapiMLLPListener,HapiReceivingApplication}.java`,
  `fhir/{HL7ResultParser,FhirBundleBuilder}.java`, `config/FhirRoutingConfig.java`,
  `routing/HttpForwardingRouter.java`, `startup/AnalyzerRegistryBootstrap.java`.
- **Core ingest:** `core/openelis/.../analyzerimport/action/AnalyzerFhirImportController.java`
  (`@PostMapping("/analyzer/fhir")`), `.../result/controller/AnalyzerResultsController.java`.
- **Context & decisions:** `contexts/edge-drivers/CONTEXT.md` (ADR-0015 transport seam),
  `docs/testing/stage-1-3-machine-access-checklist.md` (Action #4), ADR-0005 (MLLP/ACK), ADR-0008.
- **Plane:** **LIS-79** (graduate SD1 fixture), **LIS-86** (SD1 quirks — done), **LIS-87** (UCUM/LOINC seed).
- **Bring-up:** `docs/runbooks/core-bootstrap.md`, and the `local-openelis-bringup` ops note.
