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

## UPDATE 2026-07-17 ~11:50 — first live connect: LIS indicator GREEN (software-only)

Same session, later in the day. Laptop (capture host) direct-cabled to the
operation PC's second Ethernet port; analyzer chassis still NOT connected
(PLC red throughout).

- Network: operation PC `192.168.1.100/24` (pre-existing static on "Ethernet 2");
  capture laptop given `192.168.1.50` (the `10.1.52.78:2003` target found saved
  in the Online screen turned out to be from an older, different-subnet setup —
  target repointed to `192.168.1.50:2003` on the Online screen).
- Windows-side plumbing on the capture laptop: static IP + `netsh portproxy`
  `192.168.1.50:2003 → WSL:2003` + TCP-2003 firewall rule; listener =
  `scripts/x3_astm_capture.py --port 2003` (ACK mode simplified).
- `Online Setting` flipped `None → TCP/IP`, Save → **LIS dot GREEN**
  (`lis-indicator-green.jpeg`, `online-screen-tcpip-configured.jpeg`).
- Listener observed the connect: sessions `raw-20260717-114829-003` (held open)
  and `raw-20260717-115031-004` (opened 11:50:31, closed 11:51:20) — **both
  0 bytes**. The software opens a bare TCP connection and sends nothing until
  it has a message to deliver.

Wire-facts established (software-only, chassis absent):

1. The X3 operation software connects to a **non-SNIBE host** and shows LIS
   green — the slice's highest-risk unknown, answered affirmatively at the
   software level. (Full AC1 sign-off still wants the chassis attached.)
2. LIS-green requires only a successful TCP connect — **no ASTM handshake and
   no host-identity exchange happens at connect time**, so peer-identity
   enforcement (AC6), if any, must occur at message time, not connect time.
3. Vendor PC ships with `192.168.1.100/24` static on its LIS-side NIC —
   registry source-IP for this bench is therefore `192.168.1.100` (or the
   docker-NAT rewrite, per the configuration.yml dev-bench note).

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
