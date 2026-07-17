# MAGLUMI X3 — pre-connection config baseline (2026-07-17)

Captured while the analyzer was temporarily off the bench (operation PC only,
not yet re-cabled to the chassis). This is **config-screen evidence only** — no
wire capture exists yet. Do not treat any item below as satisfying an LIS-75
acceptance criterion; it is the input needed to configure the live connect
attempt once the analyzer is back on the table.

## Identity (from nameplate.jpg, taken separately)

| Field | Value |
|---|---|
| Model | MAGLUMI X3 |
| REF | 010101003301 |
| SN | 0101010034012301113 |
| Manufacture date | 2023-09-18 |

## `Set > System Setting > Online` screen (online-screen.jpeg)

| Field | Value |
|---|---|
| Online Setting | **None** (not yet enabled — neither COM Port nor TCP/IP selected) |
| COM Port (if COM mode used) | COM4, 9600 baud, 8 data bits, 1 stop bit, parity None |
| TCP/IP Setting on file | IP `10.1.52.78`, Port `2003` — **unconfirmed**, may be a leftover target from a prior (possibly SnibeLis) setup. Needs to be repointed at our capture host/bridge before the live attempt. |
| Analyzer ID | `Maglumi X3` |
| Host ID | `Lis` |
| Host Comm. Protocol | ASTM (selected, not HL7) |
| Communicate Timeout(s) | 3 |
| Resend Times | 3 |
| Field Delimiter | `\|` |
| Repeat Delimiter | `\` |
| Component Delimiter | `^` |
| Escape/"Bounce" Delimiter | `&` |
| Enable Checksum | **off** (unchecked) — simplified framing expected once connected |
| Enable Dilution Ratio | off (unchecked) |
| Auto Download Test Assay | on |
| Auto Upload QC Data | off |
| Auto Upload Test Result | on |
| Automatic Upload Result Type | "Results without SampleArm Error" |

Status lights at capture time: **PLC 🔴 / TCP-IP 🔴 / LIS 🔴** — all red, i.e.
no connection has ever been established from this screen.

## `Result` tab (result-tab-precapture.jpeg)

One row present: Sample ID `sdfdsfbdszfb`, Assay `FT3 II`, Normal Range
`3.08 - 6.468`, Status `Failed`. This has the appearance of a manually
keyed-in test entry (non-conforming sample ID), not a genuine analyzer
measurement, and was never uploaded anywhere (LIS status is red). Recorded
here only because the FT3 II normal range is a real configured value, useful
input for the LIS-38 dictionary later — not evidence of a wire transaction.

## What's still needed (unblocks AC1/AC2/AC4/AC5, firms up AC6)

1. Reconnect the analyzer chassis to this operation PC (private link).
2. Flip `Online Setting` from `None` to `TCP/IP`, point `IP Address`/`Port` at
   the capture host (`scripts/x3_astm_capture.py`) or the bridge's `snibe`
   listener (port 12021, LIS-174), `Save`.
3. Watch the `LIS` status light — green (or a documented refusal) satisfies
   AC1.
4. Run a real result and capture the raw bytes — satisfies AC2/AC3/AC4/AC5.
5. Optionally vary `Analyzer ID` to test whether an exact-name match is
   enforced — settles AC6 fully (currently only the *values*, not the
   *matching requirement*, are pinned).
