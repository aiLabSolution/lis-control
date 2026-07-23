# Redactions and exclusions — 2026-07-23 client-lab packet

This packet is a **curated, redacted subset** of the bench session. The complete
capture stays in the validation evidence store outside git. Convention follows the
2026-07-17 packet (`../20260717-0101010034012301113/`), which redacted its O-3 name
the same way.

## Redacted in place

`PATIENT-REDACTED-1` replaces the O-3 sample id, a **patient-shaped name typed by
site staff** (site staff state this particular record is dummy/training data; it is
redacted regardless, because the value's *shape* is the finding and the claim is not
independently verifiable). Applied to:

- `raw-20260723-203124-023.bin` — the redacted field is longer than the original, so
  this file is **no longer byte-exact**. Harmless for the SIMPLIFIED, checksum-off
  envelope (ASTM fields are not fixed-width), and it replays fine, but **do not cite
  it as a byte-fidelity fixture**.
- `annotated-20260723-203124-023.log` — redacted in both the decode line and the hex
  dump. Its `RECV <n>B` counts are original-wire values and no longer match its own
  hex; see the header note in the file.
- `analyzer-pc-online-logs/20260723/online_ASTM.log`
- `field-map.md`, `framing.md`

## Excluded from git entirely

| Excluded | Why |
|---|---|
| `analyzer-pc-online-logs/20260422/` (`user.log` 2.9 MB, `app.log`) | Contains **three** patient-shaped names from a routine operating day, two of which were never vouched for as test data (the names are deliberately not reproduced here). Not required by the runbook — it is the wrong day's folder, pulled before we had the session folder. No evidentiary value for any AC. |
| `analyzer-pc-online-logs/20260723/user.log`, `Launcher.log` | Not required (the runbook's second capture source is `online_ASTM.log`, which is included) and not reviewed line-by-line, so they cannot be cleared for PHI. |
| `qc-result-screen.jpg` | The photo has a sticky note with the analyzer login credentials legible on the monitor bezel. No crop tooling on the bench host. Every fact from the screen is transcribed in `qc-characterization.md`, so nothing evidentiary is lost. |
| 71 empty `raw-*.bin` + their annotated logs | Idle keep-alive reconnect cycles with zero bytes (the analyzer reconnecting after each 120 s host-side idle close). The behaviour itself is documented in `framing.md` and visible in `online_ASTM.log`. |

## Note for the upcoming per-assay captures

Use a **bench-only sample id** in O-3 (e.g. `SNB-BENCH-<assay>`) rather than a patient
name. O-3 is independent of the assay code under test, so nothing is lost, and the
resulting captures are byte-faithful and need no redaction at all.
