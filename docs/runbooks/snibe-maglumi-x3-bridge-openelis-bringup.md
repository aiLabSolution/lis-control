# Runbook — MAGLUMI X3 → bridge → OpenELIS bring-up

Drafted 2026-07-17 off the LIS-75 bench capture. Where the LIS-75 capture runbook
(`snibe-maglumi-x3-bench.md`) deliberately used a **standalone listener** and stopped
at raw bytes on disk, this runbook takes the next step: the X3 talking to the **real
bridge**, forwarding into **OpenELIS**.

Every wire fact below is bench-verified against analyzer SN `0101010034012301113`
(2026-07-17), not inferred from the vendor manual.

## Topology

```
MAGLUMI X3 operation PC          bridge host                    OpenELIS
  (TCP client)                   (TCP server)
  Online screen                  snibe listener                 /analyzer/astm
  IP -> bridge:PORT   ────────►  :12021 in-container   ────►    HTTP forward
  Protocol = ASTM                (:12020 on host)
```

The analyzer is always the **TCP client**; the bridge listens. The X3 connects to the
**operation PC's** rear-panel NIC — not the analyzer chassis, which is a separate
private net.

## Prerequisites

- Bench capture (LIS-75) complete — you should already know the analyzer's Online-screen
  values and have a known-good capture to compare the bridge's behaviour against.
- Bridge host reachable from the operation PC (`ping` both ways).
- `docker` + `docker compose` on the bridge host.
- OpenELIS reachable from the bridge host.

---

## Step 1 — Enable the snibe listener (`edge/drivers/configuration.yml`)

The listener bean **only exists when the `snibe` block is present** — sites without an
X3 never open the port. Uncomment it under `org.itech.ahb.listen-astm-server`:

```yaml
      listen-astm-server:
        port: 12001
        e1381-95:
          port: 12011
        snibe:
          port: 12021
          direction: upload-only   # LIS-177 (send half) not implemented — do NOT set bidirectional
          checksum: false          # MUST mirror the analyzer's "Enable Checksum" (bench: OFF)
          so-timeout-seconds: 10   # ⚠️ SEE STEP 2 — do not ship this value
```

`checksum: false` matches the bench (`Enable Checksum` unchecked). If a site ever enables
checksums, `true` delegates the connection to the compliant E1381-95 path instead.

## Step 2 — ⚠️ Raise `so-timeout-seconds` before any real run

**This is the one setting most likely to bite you, and the bench proved it.**

`SnibeAstmCommunicator` applies `so-timeout-seconds` as a **single** SO_TIMEOUT to
*every* blocking read — including the idle wait for the *next* envelope's `ENQ`. On
timeout with at least one envelope already received, it returns `null` and the caller
**closes the connection** (`SnibeAstmCommunicator.java:163-180`).

The bench established that the X3 **reuses one long-lived connection for every
transaction while the channel stays healthy** — we observed two operator upload actions
~90 seconds apart sharing a single connection (AC6 session 002, six envelopes). Earlier
the same day, against the then serve-one-at-a-time listener, the software instead opened
a **fresh connection per upload attempt** while holding an idle status connection in
parallel — both patterns are bench-observed, and the receive path must handle both
(concurrent connections AND multi-envelope reuse across long idle gaps). At the default
`10`, the bridge tears a healthy reused channel down after 10s of idle, over and over.

The X3 does reconnect, so this is not a hard failure — it is worse: an **intermittent**
one. If an operator clicks upload in the window between the bridge's FIN and the analyzer
noticing, the analyzer writes into a dead socket, gets no ACK, retries `Resend Times`
(3) × `Communicate Timeout` (3s), and shows:

> **"Communication timeout between software and LIS!"**

…while the LAN is fine and the LIS indicator is green. We hit exactly this failure twice
on the bench with a **120s** timeout. At 10s, teardowns are ~12× more frequent, so the
race is hit ~12× more often.

**Root cause is conceptual:** the config comment reads *"parity with the analyzer's
Communicate Timeout(s)"*, but the analyzer's `Communicate Timeout` (3s) is how long the
**analyzer** waits for an **ACK inside an active transaction**. It is not an
idle-connection budget. The two are being conflated. A correct design needs them split:

| Wait | Correct budget |
|---|---|
| Next byte **inside** an envelope | ~10s is fine (generous vs the analyzer's 3s) |
| `ENQ` for the **next** envelope (idle) | effectively unbounded — hours |

Until that split exists in code, set the idle budget high:

```yaml
          so-timeout-seconds: 3600
```

The trade-off: a genuinely dead peer is held open for an hour. That is strictly better
than severing a live channel — TCP keep-alive or an accept loop bound handles dead peers.

> Tracked as a wire-fact from LIS-75. This warrants its own follow-up issue against
> LIS-174 rather than living only in this runbook.

## Step 3 — Register the analyzer

The registry is keyed on the **analyzer's source IP**. Bench values:

```yaml
    "[192.168.1.100]":            # operation PC's static NIC — NOT the chassis
      id: SNIBE-MAGLUMI-X3-001
      name: "Maglumi X3"          # bench-verified; corrects the "Maglumi User" placeholder
      expectedProtocol: ASTM
      identifierPattern: "(?i)(maglumi|snibe)"
      codeToLoinc:
        TSH: "3016-3"
        FT4: "14920-3"
      unitToUcum:
        "[uIU/mL]": "u[IU]/mL"
        "[pmol/L]": "pmol/L"
        "[ng/dL]": "ng/dL"
```

Three bench-driven cautions:

1. **`name` is cosmetic — do not rely on it.** AC6 proved the X3 enforces *no* identity
   matching: with `Host ID` set to `NOTLIS`, it stamped `NOTLIS` into the H-record
   **receiver-ID field (H-10)** and delivered the batch anyway, LIS green throughout
   (`evidence/bench/maglumi-x3/20260717-ac6-hostid-mismatch/`, capture 006; sender
   H-5 stayed `Maglumi X3`). Both `Analyzer ID` (sender name, **H-5**) and `Host ID`
   (receiver ID, **H-10**) are operator-editable free text with zero validation. Never
   route or validate on them.
2. **The bench wire codes are `FT3` (bare), `FT4 II`, `TSH II`** — note the inconsistent
   ` II` suffix, and that the UI shows `FT3 II` while the wire says `FT3`. The `codeToLoinc`
   keys above are **synthetic seeds** and will not match. The real dictionary is LIS-38.
3. **Units seen on the bench: `pmol/L`, `ng/dL`, `uIU/mL`.** Unit keys need the
   bracket-indexed escape (`"[ng/dL]"`) — `/` is outside Spring's valid unindexed
   property-name charset, and an unbracketed key **silently fails to bind** with no error.

### ⚠️ Source-IP keying vs. port-forwarding

If the bridge sits behind a port-forward (e.g. the WSL bench setup), **it sees the
proxy's IP, not the analyzer's.** Our captures show connections from `172.21.208.1`
(the WSL gateway), never from `192.168.1.100`. Registry lookup keyed on
`"[192.168.1.100]"` would never match.

Options, best first:

1. Run the bridge on a host **directly on the bench LAN** (no proxy) — the honest topology.
2. Key the registry on the **proxy's** IP — works, but records a fiction.
3. Use `identifierPattern` against the H-record sender as a fallback — diagnostic only,
   and per AC6 that string is operator-editable.

## Step 4 — Expose the port (`edge/drivers/docker-compose.yml`)

Uncomment alongside the config block:

```yaml
    ports:
      - "12020:12021"   # ASTM SNIBE simplified-envelope listener
```

Host `12020` → container `12021`, following the existing `12000/12001`, `12010/12011`
pattern. **The analyzer points at `12020`** (the host port).

## Step 5 — Point the bridge at OpenELIS

```yaml
      forward-http-server:
        uri: http://<openelis-host>:8080/api/OpenELIS-Global/analyzer
        username: <user>
        password: <pass>
        connect-timeout-seconds: 30
        read-timeout-seconds: 30
        max-attempts: 3
        backoff-ms: 1000
```

Base path only — `HttpForwardingRouter` appends `/astm`, `/hl7`, `/csv`, `/raw` per
protocol. X3 traffic lands on **`/analyzer/astm`**.

## Step 6 — Start and verify the listener

```bash
cd edge/drivers
docker compose up -d
docker compose logs -f openelis-analyzer-bridge
```

Confirm the port is actually open before touching the analyzer:

```bash
ss -ltn | grep 12020        # expect LISTEN
```

> A closed port is indistinguishable, from the analyzer's UI, from a protocol failure —
> both surface as *"Communication timeout"*. **Always confirm the listener is up before
> concluding anything about the analyzer.** This cost us a bench cycle on 2026-07-17.

## Step 7 — Point the analyzer at the bridge

On the operation PC: **`Set` → `System Setting` → `Online`**

| Field | Value |
|---|---|
| Online Setting | `TCP/IP` |
| IP Address | bridge host IP |
| Port | `12020` |
| Host Comm. Protocol | `ASTM` |
| Analyzer ID | `Maglumi X3` |
| Host ID | `Lis` (cosmetic — see AC6) |
| Enable Checksum | **unchecked** (must match `checksum: false`) |
| Auto Upload Test Result | checked |
| Auto Upload QC Data | checked only for a QC run (LIS-33) |

Click **`Save`** → the **`LIS`** indicator should go **green**.

> **Green means TCP connect only.** It proves a socket opened — nothing about ASTM,
> identity, or the bridge parsing anything. `PLC` / `TCP-IP` red is expected while the
> chassis is disconnected. Do not read green as success.

## Step 8 — End-to-end verification

Trigger an upload — either a live run, or `Result` → tick a row → **`→LIS Online`** to
replay a stored result over the genuine ASTM stack.

**No bench handy?** Every archived evidence `.bin` is wire-replayable — the capture
tool plays the analyzer side byte-for-byte with the X3's per-token ACK pacing:

```bash
python3 scripts/x3_astm_capture.py \
    --replay evidence/bench/maglumi-x3/20260717-ac6-hostid-mismatch/raw-20260717-151920-002.bin \
    --to <bridge-host>:12020 --gap 15
```

`--gap` holds the connection idle between envelopes; a gap above the bridge's
`so-timeout-seconds` reproduces the LIS-265 idle teardown on demand.

Verify each hop in order; stop at the first that fails:

1. **Wire** — bridge log shows `ENQ` → `ACK` → `STX` → records → `ETX`/`EOT`.
2. **Parse** — records resolve to H/P/O/R/L; `R` value, units, range extracted.
3. **Registry** — analyzer resolved by source IP (watch for the proxy-IP trap, Step 3).
4. **Forward** — HTTP POST to `/analyzer/astm` returns 2xx.
5. **OpenELIS** — result lands against the accession.

Expected wire shape (bench-verified, redacted):

```
<ENQ><STX>H|\^&||PSWD|Maglumi X3|||||Lis||P|E1394-97|20260717<CR>
P|1<CR>
O|1|<sample-id>||^^^FT4 II<CR>
R|1|^^^FT4 II|1.58|ng/dL|0.9 - 1.75|N||||||20250320152944<CR>
L|1|N<CR>
<ETX><EOT>
```

## Bench-verified facts the bridge must honour

| Fact | Consequence |
|---|---|
| Simplified framing: per-token ACK, **no checksum, no frame#, no LF** | `checksum: false` |
| **One long-lived connection reused across transactions when healthy; fresh concurrent connections also observed** | Never close on `<EOT>`; never close on idle (Step 2); accept concurrently |
| Message boundaries **do not align with TCP reads** — `<ETX>`/`<EOT>` split three different ways across three captures | Parser must be a byte-stream state machine, never read-boundary keyed |
| **R-record timestamp is field 13** (not 11/12) | Resolves the documented off-by-one; KB fixtures using 12 are wrong |
| Reference range is **free text**: `3.08 - 6.468` (space-hyphen-space) | Do not parse as a number pair without tolerance |
| **`O-3` (sample id) carries free text**, not a barcode grammar | Treat as untrusted: spaces, commas, mixed case. Assume real PHI in production |
| **No identity enforcement** (AC6) | Bridge needs no name config to receive |

## Known gaps

- **`direction: upload-only`.** Order download (`Q` → host `O`) is LIS-177, not
  implemented. `Auto Download Test Assay` on the Online screen has nothing to answer it.
- **QC upload uncaptured** (LIS-33). QC is captured and classified only, never
  auto-accepted — engineer sign-off.
- **`codeToLoinc` seeds are synthetic** and do not match the bench codes. LIS-38.
- **Auto-upload framing unconfirmed.** Every capture to date is a manual `LIS Online`
  replay with the chassis disconnected. A live auto-upload from a real run is expected
  to be identical but has **not been observed**.

## Troubleshooting

| Symptom | First check |
|---|---|
| *"Communication timeout between software and LIS"* | **Is the listener actually up?** (`ss -ltn \| grep 12020`). Then Step 2 — idle teardown. Retry once before concluding anything. |
| LIS green, no data in bridge log | Green = TCP only. Check `Auto Upload Test Result`, or use `→LIS Online` to force. |
| Bridge parses, registry misses | Source-IP vs proxy IP (Step 3). |
| Unit never maps | Missing bracket escape — binds silently as absent, no error. |
| Garbled records / framing errors | `Enable Checksum` vs `checksum:` mismatch. |
