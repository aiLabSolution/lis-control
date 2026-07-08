# LIS-192 AC1 — H99S CD-mode wire capture (operator guide)

Goal: capture the real OBX-4 code / OBX-5 value / **OBX-6 unit** / OBX-7 ref-range for every param the H99S emits in **CD (cell-differentiation / research) mode** — especially the B2 research/morphology/scatter params and the true PDW unit (see `00-wire-inventory.md`).

## Why a fresh scan is needed
The H60S extended-panel capture already gives real units for the 9 B1 params. The B2 params only appear on an **H99S CD-mode** run (the 83-obs mode). The DEV…012 CD-run staging was already consumed, so we need one fresh run. Manual entry hangs the H99S → **scan the barcode**; do NOT replay a synthetic ORU (pollutes OE staging).

## Primary capture path — `analyzer_results` snapshot (no sudo, structured, includes units)
When the H99S sends the CD ORU, the bridge forwards all observations to OE, which writes them to `clinlims.analyzer_results` (analyzer_id=5) with `test_name`, `result`, `units` — **including the unmapped research params** (test_id NULL). These unmapped rows also **linger after Save**, so timing is forgiving.

Operator steps:
1. Ensure H99S is at `192.168.50.50` and set to **CD mode** (5-part diff + research channels, the ~83-obs run).
2. **Scan** a whole-blood sample barcode (a real CD run). Watch the bridge answer the host query and route ~83 observations.
3. Tell the agent "sent" — the agent snapshots `analyzer_results` for analyzer 5 immediately (before you click Save in the OE Analyzer Results screen). Saving is fine either way (unmapped rows persist), but snapshot-before-Save is cleanest.

Snapshot query the agent runs (read-only):
```sql
SELECT test_name, result, units, test_id, status_id, last_updated
FROM clinlims.analyzer_results
WHERE analyzer_id = 5
ORDER BY last_updated DESC, test_name;
```

## Secondary/forensic path — pcap (needs sudo; operator-run)
For the exact raw OBX-3-vs-OBX-4 code strings + escapes (`\T\`, `\S\`) and ref-ranges. Host is on the analyzer subnet (`enp3s0` = 192.168.50.1/24). Run in a session shell with `! <cmd>` (needs sudo password):
```
sudo tcpdump -i enp3s0 -U -s0 -w docs/reviews/lis-192-h99s-extended-param-disposition/evidence/h99s-cd-mode.pcap tcp port 2575
```
Start it BEFORE the scan; Ctrl-C after the run completes. De-frame later with `tshark -r … -T fields`.
