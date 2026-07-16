---
name: bench-capture
description: Route physical analyzer bench-capture sessions to the right capture tool, port, and runbook. Use for any bench capture session, analyzer wire capture, or Lifotronic H9 / SNIBE MAGLUMI X3 / EDAN H60S / EDAN H99S bench work — the tools, default ports, and desync gotchas are easy to fumble under bench time pressure.
---

# bench-capture — analyzer wire-capture router

Thin router: which tool, which port, which runbook. The runbooks own the full
procedure (evidence packet, analyzer-screen setup, pass/fail gates) — do not
duplicate them, open them.

## Router

| Analyzer | Capture tool | Default port | Transport | Runbook |
|---|---|---|---|---|
| Lifotronic H9 | `scripts/h9_capture.py` | `/dev/serial/by-id/<adapter>` | Proprietary upload-only RS-232, 115200 8N1, no flow control | `docs/runbooks/lifotronic-h9-bench.md` |
| SNIBE MAGLUMI X3 | `scripts/x3_astm_capture.py` | 12010 (site-configurable; no vendor standard) | ASTM E1394-97 over TCP | `docs/runbooks/snibe-maglumi-x3-bench.md` |
| EDAN H60S | `scripts/h60s_mllp_capture.py` | 7999 (ADR-0015) | HL7 v2 MLLP | `docs/runbooks/edan-h60s-host-query-bench.md` |
| EDAN H99S | no standalone tool — attaches via the production bridge (shared EDAN H90-family wire) | 7999 | HL7 v2 MLLP | `docs/runbooks/edan-h99s-bench-conformance.md` |

```bash
python3 scripts/h9_capture.py --port /dev/serial/by-id/<adapter> \
  --outdir /path/to/controlled-evidence/lifotronic-h9/<run>/archive --frames 1
python3 scripts/x3_astm_capture.py --port 12010 --outdir ./x3-capture
python3 scripts/h60s_mllp_capture.py --port 7999 --outdir ./h60s-capture
```

## Gotchas (the ones that bite at the bench)

- **H9**: passive capture only. Connect the capture adapter's RX + signal ground;
  leave TX and handshake conductors disconnected. The tool opens the port read-only
  and never ACKs. Confirm analyzer DB-9 pinout and straight-vs-null-modem topology at
  the bench instead of assuming DTE/DCE from connector gender. Live capture requires
  an explicit controlled output directory outside the repository checkout.
- **X3**: start in `simplified` mode (the default). If the link desyncs after the
  first frame and the summary reports checksummed framing, restart with
  `--mode framed` (classic E1381 checksummed-frame ACK cadence).
- **H60S**: `--ack` sends a minimal HL7 `MSA|AA` keep-alive ONLY — it is never an
  ORF^R04 worklist answer (that is LIS-149 scope). Default is capture-only.
- **Both**: the analyzer is the TCP **client**; the same port must also be set on
  the analyzer's own config screen (X3 `Online` screen / H60S manual Annex 2), or
  nothing ever connects.
- Two analyzers sharing one link need **distinct source IPs** — the bridge routes
  by source IP (precedent: H99S `192.168.50.50` / H60S `192.168.50.51`).
- `--replay RAWFILE` re-parses an archived raw capture offline after the bench
  session — no socket, no analyzer needed.
- `--once` exits after a single connection (useful for scripted one-shot captures).

Captures feed fixtures for **both** edge/drivers and edge/sim (two-level mirror —
sim-only is incomplete).
