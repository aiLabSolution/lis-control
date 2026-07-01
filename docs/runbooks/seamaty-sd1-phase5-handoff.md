# Phase 5 handoff — Seamaty SD1 live E2E (do this at the bench with the physical SD1)

**Prepared 2026-07-01 (overnight) after executing Phase 3 + Phase 4 of
[`seamaty-sd1-bench.md`](seamaty-sd1-bench.md).** Companion to that runbook — read the
"Key findings" section below, several things differ from the runbook's happy path.

---

## 0. Status — what is already done vs. what is yours to do tomorrow

| Phase | State | Who |
|---|---|---|
| **0 Oracle** | not re-run tonight (not needed for 3/4) | — |
| **1 Link** | done earlier today — SD1 was on the Wi-Fi LAN; a real capture exists | you (re-verify) |
| **2 Raw capture** | **done** — real frame at `~/bench-runs/20260630T100724Z/` (`sd1-raw.bin`, `message.hl7`, `sd1-flow.pcap`) | ✅ |
| **3 Bridge** | **done & verified** — built from pin `a98db88`, MLLP `:2575` UP, `httpforward` UP, container **healthy** | ✅ (me) |
| **4 Core** | **up & verified** — OpenELIS `lis-8` build healthy; analyzer **registration deferred to you** (see §5, this is correct — see finding F1) | ✅ bring-up / you register |
| **5 Live E2E** | **YOURS** — connect the physical SD1, send a result, watch it flow | ⬅ **you, tomorrow** |
| **6 Graduate** | pending — the real capture already **differs** from the synthetic fixture; see §7 | you |

I also ran a **full dress rehearsal** tonight by replaying the real captured frame through the
live bridge → OpenELIS: **20 results staged, `ACK^R01 MSA|AA` returned.** Then I cleaned the DB
back to a 0-results / 0-analyzers baseline so your live run tomorrow starts pristine. Details §6.

**Bottom line: the whole software pipe is proven working. Tomorrow is just: point the physical
SD1 at this PC and press send.**

---

## 1. Preflight — verify the bench is still ready (run these first tomorrow)

The bridge + OpenELIS are left **running**. Neither has a restart policy, so if the box rebooted
overnight you'll need to restart them (commands in §8).

```bash
# a) Both stacks up? bridge must be (healthy); OE containers up.
docker ps --format '{{.Names}} | {{.Status}}' | grep -E 'bridge|openelisglobal'
#   want: openelis-analyzer-bridge | Up ... (healthy)   + the 4 openelisglobal-* up

# b) Bridge gates (from the host, HTTP on 8442 — NOTE: http, not https; SSL is disabled):
curl -s http://localhost:8442/actuator/health | python3 -m json.tool | grep -A1 -E 'mllp|httpforward|"status"'
#   want overall UP, mllp UP (accepting connections, port 2575), httpforward UP

# c) MLLP port open + OE UI:
timeout 3 bash -c '</dev/tcp/localhost/2575' && echo "2575 OPEN"
curl -sk -o /dev/null -w 'OE %{http_code}\n' https://localhost/          # want 200

# d) This PC's Wi-Fi IP (the SD1 dials this). Was 192.168.1.128/24 tonight:
ip -br addr show wlan0
```

If (a)/(b) are not green, go to **§8 restart**. If the Wi-Fi IP changed, that's fine for the
bridge (it forwards to OE via `host-gateway`, not the Wi-Fi IP) — you only need the current IP for
the **SD1's LIS Server / Host IP** setting (Phase 1).

---

## 2. Phase 5 — the live run (physical SD1)

Prereq: the SD1 is joined to the **same Wi-Fi LAN**, its **LIS Server / Host IP = this PC's Wi-Fi
IP** (from preflight d), **Port `2575`**, **HL7/MLLP-TCP** mode, patient-sample mode. (That's Phase
1 of the main runbook §4 — re-confirm on the instrument; the bench PC side is already listening.)

1. **Start a pcap for evidence** (optional but do it — ISO trail):
   ```bash
   mkdir -p ~/bench-runs/$(date -u +%Y%m%dT%H%M%SZ)-live && cd $_
   sudo tcpdump -i wlan0 -w sd1-e2e.pcap tcp port 2575 &
   ```
2. **Watch the bridge** in another terminal:
   ```bash
   docker logs -f openelis-analyzer-bridge | grep -Ei 'Processing HL7|analyzer:|FHIR routing|accepted by OE|MSA|error'
   ```
3. **On the SD1, send / re-transmit the sample to LIS.**
4. **Expect in the bridge log** (this is exactly what the rehearsal produced):
   ```
   Processing HL7 message from 172.21.0.1 (analyzer: SMT-SD1), <N> bytes
   FHIR routing 20 results for accession 2 from 172.21.0.1 to https://oe.openelis.org:8443/.../analyzer/fhir
   FHIR Bundle accepted by OE (20 results)
   Successfully processed HL7 message from 172.21.0.1 (analyzer: SMT-SD1)
   ```
   The SD1 should report a **successful upload** (it received `ACK^R01 MSA|AA`).
   > `172.21.0.1` is **not** a bug — see finding **F1**. The real SD1 shows up as that address too.
5. **Confirm results staged** (they will be `read_only` / `unmapped` — that is expected, finding F3):
   ```bash
   docker exec openelisglobal-database psql -U clinlims -d clinlims -c \
     "select accession_number, test_name, result, units, read_only, import_issue_reason \
      from clinlims.analyzer_results order by id desc limit 25;"
   ```
   Or in the UI: **Results → Analyzer Results**. Login `admin` / `adminADMIN!` at https://localhost.
6. **A `PENDING_REGISTRATION` analyzer stub auto-appears** (name `SMT-SD1`, keyed on source
   `172.21.0.1`). That's your entry point for §5 registration.

**Success for Phase 5 = ACK returned + rows appear in `analyzer_results`.** Mapping/acceptance is
the follow-on (§5), not the gate.

---

## 3. Key findings from tonight (READ — they change the runbook's expectations)

**F1 — The bridge/OE see the SD1 as `172.21.0.1`, not its Wi-Fi IP.** Docker publishes `2575`
via NAT, which masquerades the client source to the docker-bridge gateway. So `discovered_source_id`
and all "source IP" logging will be `172.21.0.1` for the *real* SD1 too. Consequence: **do not try
to register the SD1 "by its Wi-Fi IP"** (the runbook §6/§7 optional step) — it won't match. Register
by promoting the auto-created stub, or (if you want deterministic tagging) key `bridge.analyzers` on
`172.21.0.1`. Identity otherwise falls back to the in-message sender `MSH-3/4 = SMT/SD1`
(`protocolHint=SMT-SD1`), which is what's working now.

**F2 — The real SD1 message structure differs from the synthetic fixture.** From tonight's capture
(`~/bench-runs/20260630T100724Z/message.hl7`):
- **`PID-2` and `PID-3` are EMPTY**; the patient name (`Suanque, Ari Ben`) is in **`PID-5`**. So this
  unit/firmware does **not** put an MRN in PID-2 — the runbook's whole "PID-2 MRN quirk" premise
  (Action #4) is **not exercised** by this message. The **accession came from `OBR-3` = `2`**
  (the instrument's internal sequence number), so the PID-2/PID-3 fallback is never reached.
- **20 analytes** (not the fixture's 6): LDL, AMY, GLU, TB, TC, TG, DB, CHE, ALB, ALP, TP, CK, GGT,
  HDL, BUN, UA, TBA, AST, ALT, Crea — with units `mg/dL`, `U/L`, `g/L`, `mmol/L`, `umol/L`.
- **No `Alarm` OBX** in this sample, so the LIS-86 "Alarm → DiagnosticReport.conclusion" quirk isn't
  exercised either (it only fires when the instrument emits an alarm).
- **Encoding = ASCII** (`MSH-18=ASCII`) — this **resolves the manual's §1.6-vs-p4 conflict in favour
  of ASCII.** Firmware `V1.00.01.49`; `MSH-16=0` (patient-sample mode). ✅ good for the graduated
  manifest (§7).

**F3 — Every result stages `read_only` / `unmapped_loinc:<code>` — including GLU.** This surprised
me and corrects the runbook's "GLU → 2345-7 ✅ deterministic today." Mechanism (verified in core
`AnalyzerFhirImportController`): OE maps a result **only if the incoming FHIR Observation carries a
`http://loinc.org` coding** (`TestService.getTestsByLoincCode`). The bridge stamps LOINC codes from
its **per-analyzer `codeToLoinc` map, pulled from OE at startup** — and with **zero analyzers
registered** the bridge log says *"no analyzers found in OE — registry empty"*, so the bundle carries
**raw codes only** → OE can't resolve a LOINC → everything (GLU included) stages unmapped. The global
`clinlims.vendor_code_mapping` (which does hold `GLU→2345-7`) is **not consulted on the FHIR path**
("no analyzer-code fallback"). To get GLU mapped you must register/promote the analyzer with a test
mapping (§5), not rely on the seed.

**F4 — OE upserts by (accession, test).** Re-sending the same sample updates the existing rows rather
than piling up duplicates — so you can safely re-send during troubleshooting.

**F5 — "unhealthy" was a false alarm (now fixed).** The image's `healthcheck.sh` uses `curl`
(absent in the alpine JRE) over HTTPS (SSL is disabled). I overrode it with a `wget` HTTP check, so
the container now reports **healthy** truthfully.

---

## 4. What I changed to bring the bridge up (as-built — for audit / reproducibility)

I did **not** edit the pinned submodule working tree (`edge/drivers` stays clean at `a98db88`).
All four fixes live in a **compose override**: `~/bench-runs/bridge-phase34/compose.override.yml`.
Build log: `~/bench-runs/bridge-phase34/build.log`. Test client: `~/bench-runs/bridge-phase34/mllp_send.py`.

Why each override (all discovered empirically — the runbook's happy path would have hung or failed):

1. **`ports: 2575:2575`** — the base `docker-compose-dev.yml` omits the MLLP port mapping.
2. **`JAVA_OPTS … suspend=n`** — base is `suspend=y`; the JVM blocks at boot waiting for a debugger
   on `:8000`. No debugger on the bench → it would hang forever.
3. **`SERVER_SSL_ENABLED=false`** — the `dev` profile enables SSL on 8443 pointing at a keystore
   (`/etc/openelis-global/keystore`) that is **neither mounted nor in the image** → SSL init fails →
   app won't start. Disabling it serves actuator over plain HTTP 8443 → host **8442**. MLLP and
   forwarding are unaffected. (This is why preflight uses `http://localhost:8442`, not https.)
4. **`SPRING_APPLICATION_JSON`** forward overrides (the runbook's `configuration.yml` edit is
   *low-precedence* `@PropertySource` and gets overridden by the dev profile, so it wouldn't stick):
   - `uri = https://oe.openelis.org:8443/api/OpenELIS-Global/analyzer` — **OE answers only over
     HTTPS**; host `:8080` HTTP is dead (000). Hostname `oe.openelis.org` matches OE's cert SAN
     `*.openelis.org` (the bridge's `insecure-tls` disables cert-chain trust but **not** JDK
     hostname verification, so `host.docker.internal` fails the handshake). Mapped to `host-gateway`
     so it survives a Wi-Fi IP change.
   - `username/password = admin/adminADMIN!` — **OE requires HTTP Basic** on the analyzer endpoints
     (unauth → 302).
   - `health-uri = …/rest/analyzer/analyzers` — the httpforward indicator only reports **UP on a 200**
     and defaults to `null → UNKNOWN`; this GET returns 200 with auth, so the gate is meaningful.
   - `insecure-tls = true` — OE's cert is self-signed.

---

## 5. Registering / promoting the SD1 analyzer (the Phase-4 "ACTIVE" step — do it in the UI)

I deliberately did **not** pre-create the analyzer: its source identity only exists once it connects
(and per F1 that's `172.21.0.1`), so the **auto-create-on-first-bundle** path is the correct trigger.
After your first live send (§2), a `PENDING_REGISTRATION` stub `SMT-SD1` exists. Then:

1. UI → **Admin → Analyzer Configuration** (`/analyzers`). Find `SMT-SD1` (PENDING_REGISTRATION).
2. **Promote** it: set name `Seamaty SD1`, protocol `HL7`, status **ACTIVE**.
3. Under **Test Mappings**, map at least **`GLU → 2345-7`** (the one LOINC seeded). The rest
   (`BUN/CREA/AST/ALT/TP/…`) have no core LOINC seed yet → **LIS-87**; leave them unmapped.
4. **To make the mapping take effect on the wire**, the bridge must re-pull `codeToLoinc`. Registering
   via the UI pushes the transport mapping to the bridge, but the code→LOINC map is loaded at bridge
   **startup**, so simplest is to **restart the bridge** (§8) and **re-send** from the SD1. Then GLU
   should arrive mapped (acceptable), the rest still `read_only` (F3). *Verify this — it's the one
   thing I couldn't fully confirm tonight without the analyzer registered.*

Accepting mapped rows (checkbox → **Save**) pushes them into the analysis/result tables. Note the
accession is the instrument's sequence number (`2`), which won't match a pre-existing OE order — for
the bench, **staged rows are the success criterion**, not a full accession match.

---

## 6. Dress-rehearsal evidence (what "working" looks like)

I replayed the real captured frame through the live bridge tonight:

```bash
python3 ~/bench-runs/bridge-phase34/mllp_send.py localhost 2575 ~/bench-runs/20260630T100724Z/sd1-raw.bin
```
Result — the ACK the SD1 will get:
```
MSH|^~\&|||SMT|SD1|20260701003321.734+0000||ACK^R01^ACK|2|P|2.3.1
MSA|AA|52          ← Application Accept, acknowledging the SD1's control-ID (MSH-10=52)
```
…and 20 rows staged under accession `2` (all `read_only`, `unmapped_loinc:*`). I then deleted those
rows + the stub to restore the **0/0 baseline**. You can re-run the command above any time to exercise
the pipe **without the physical SD1** (it will re-create the stub + rows; upserts per F4).

---

## 7. Phase 6 preview — graduating the fixture will surface real findings

The captured `message.hl7` is a genuine bench artifact and **differs materially** from the synthetic
`edge/sim/fixtures/seamaty-sd1-oru-r01/message.hl7`. When you do Phase 6 (main runbook §9):
- The digest **will** change (that's the point) — real bytes replace the seed.
- Set `message.encoding = ascii` (confirmed, F2), `synthetic:false`, and record firmware `V1.00.01.49`.
- **Update `expected.*`** — the real panel is 20 analytes, patient in PID-5, accession from OBR-3,
  no Alarm. The synthetic fixture's PID-2 MRN / 6-analyte / Alarm shape does **not** match this unit.
- These divergences (esp. PID-2 empty) may warrant a **bridge parser note or tweak** → two-level PR
  (bridge repo first, then umbrella pin), and they change what Action #4 "locked" (it locked: port
  `2575`, MLLP framing `0x0B…0x1C0x0D`, **ASCII**, and that the accession rides in **OBR-3**, not PID-2).

---

## 8. Restart / teardown

**Restart the bridge** (e.g., after box reboot, or to reload analyzer mappings per §5):
```bash
DOCKER_BUILDKIT=1 docker compose \
  --project-directory /home/marloeu/projects/lis-control/edge/drivers \
  -f /home/marloeu/projects/lis-control/edge/drivers/docker-compose-dev.yml \
  -f /home/marloeu/bench-runs/bridge-phase34/compose.override.yml \
  up -d            # add --build only if the image is gone
```
**Restart OpenELIS** (if the box rebooted) — lean bring-up (see `local-openelis-bringup` note):
```bash
docker start openelisglobal-database openelisglobal-webapp openelisglobal-front-end openelisglobal-proxy
# or full: see seamaty-sd1-bench.md §7 (never `down -v` — it wipes the DB volume)
```
**Stop the bridge:** `docker compose … <same -f flags> down`  (leaves OE untouched).

---

## 9. Troubleshooting (bench-specific, from tonight)

| Symptom | Cause | Fix |
|---|---|---|
| `docker ps` shows bridge **(unhealthy)** | (should be fixed) baked healthcheck uses curl/https | override already applies a wget/http check; if it recurs, `docker logs` for the real error |
| `httpforward` = **DOWN** | can't reach OE (cert hostname, auth, or IP) | ensure forward host is `oe.openelis.org` (SAN match) + `insecure-tls` + admin creds; `host-gateway` resolves the host |
| `httpforward` = **UNKNOWN** | `health-uri` unset | must point at a **200** endpoint (`…/rest/analyzer/analyzers` with auth) |
| bridge won't start / hangs at boot | `suspend=y` in JAVA_OPTS | override sets `suspend=n` |
| bridge exits at boot, keystore error | dev-profile SSL, no keystore | override sets `SERVER_SSL_ENABLED=false` |
| SD1 `LIS Server disconnected` | wrong host IP/port on the SD1, or bridge down | SD1 Host IP = this PC's **Wi-Fi** IP, port `2575`; confirm `ss -ltnp | grep 2575` and bridge healthy |
| results never appear | forward failed | `docker logs openelis-analyzer-bridge | grep -i 'accepted by OE\|error'`; check `httpforward` UP |
| GLU shows `unmapped` | expected until analyzer registered (F3) | §5 register + map GLU + restart bridge + re-send |
| `/actuator/health/mllp` returns 401 | sub-component paths are auth-secured | use the **aggregate** `/actuator/health` (shows all components) |

---

## 10. Evidence to keep (ISO 15189)

- `~/bench-runs/20260630T100724Z/` — the real Phase-2 capture (`sd1-raw.bin`, `message.hl7`, `sd1-flow.pcap`).
- `~/bench-runs/bridge-phase34/` — `compose.override.yml` (as-built config), `build.log`, `mllp_send.py`.
- Tomorrow: `~/bench-runs/<ts>-live/sd1-e2e.pcap`, a `docker logs openelis-analyzer-bridge > bridge.log`,
  and UI screenshots (SD1 LIS settings + Analyzer Results row).
- The ACK (`MSA|AA|52`) and the 20-analyte breakdown above.
