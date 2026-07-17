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

## UPDATE 2026-07-17 ~13:35 — FIRST REAL WIRE CAPTURE (all 5 unknowns pinned)

Re-sent a stored historical result via the `Result` tab's `→LIS Online`
button (the manual-upload path; the analyzer chassis is still disconnected, so
this is a software-driven replay of a completed record, not a fresh run). First
genuine X3 firmware ASTM message captured — raw bytes in
`raw-20260717-133451-004.bin`, decoded in `annotated-20260717-133451-004.log`.

Redacted wire (O-record sample-id was real PHI, replaced with a bench
placeholder — see PHI note below):

```
<ENQ><STX>H|\^&||PSWD|Maglumi X3|||||Lis||P|E1394-97|20260717<CR>
P|1<CR>
O|1|BENCH-SAMPLE-001||^^^FT3<CR>
R|1|^^^FT3|5.43|pmol/L|3.08 - 6.468|N||||||20250320153245<CR>
L|1|N<CR>
<ETX><EOT>
```

Handshake: per-token ACK on `ENQ`, `STX`, `ETX`, `EOT` (the whole H/P/O/R/L
body arrives in two `recv`s between the STX-ACK and the ETX, un-ACKed
individually). No NAK, no checksum, no frame number, no LF.

**Five unknowns — all answered from real bytes:**

1. **AC1 — non-SNIBE host:** ✅ the software both *connects* (LIS green) and
   *delivers a message* to our stdlib listener. No SnibeLis anywhere.
2. **AC3 — framing:** ✅ **SIMPLIFIED** — `ENQ/STX/…/ETX/EOT`, per-token ACK,
   **no checksum** (matches `Enable Checksum` = off), no frame#, no LF.
3. **AC4 — R-record completion-timestamp field:** ✅ **field 13**
   (`20250320153245`), resolving the documented 11/12/13 vendor off-by-one
   against real firmware bytes. (KB fixtures land at 12; this real X3 is 13.)
4. **AC5 — Lis-ID / units / range:** ✅ assay `^^^FT3` (bare `FT3`, note: **not**
   the `FT3 II` shown in the assay-selection UI), unit `pmol/L`, reference-range
   string `"3.08 - 6.468"` (space-hyphen-space form), abnormal flag `N`.
5. **AC6 — peer identity:** ✅ H-record sender/Analyzer-ID `Maglumi X3`,
   receiver/Host-ID `Lis`, version `E1394-97`, delimiters `\^&`. Field 4 carries
   a literal `PSWD` token. (Whether an exact host-name *match* is enforced is
   still only inferable — the connect succeeded with our arbitrary host; a
   deliberate mismatch test was not run.)

**Concurrent-connection behavior (new wire-fact, feeds LIS-174):** the software
does NOT reuse the idle status connection to deliver. It opens a fresh TCP
connection per upload attempt (observed ports 58973/58974/63906…) while the
green-LIS status connection stays open in parallel. A serve-one-at-a-time host
leaves the delivery connection queued until the software's ~3s timeout fires
(that was the "Communication timeout between software and LIS!" error seen
before the fix). `scripts/x3_astm_capture.py` was patched to accept each
connection on its own thread (24 self-tests still green); the receive path
LIS-174 must be concurrent for the same reason.

**PHI note:** the O-record sample-id field carried a real personal name. Per the
runbook, the pristine capture is kept ONLY in the offline validation evidence
store (not committed); the in-repo `raw-*.bin` / `annotated-*.log` have that one
field replaced with `BENCH-SAMPLE-001`. Every other byte is verbatim. The
measurement itself (FT3 5.43) is a real historical patient result — treat the
values as illustrative of *format*, not as a bench control.

## AC status after the 13:35 capture

| AC | Status | Evidence |
|---|---|---|
| AC1 connect / LIS green | **MET** (software level) | `lis-indicator-green.jpeg` + delivered message |
| AC2 raw wire capture archived | **MET** | `raw-20260717-133451-004.bin` (+ pristine offline) |
| AC3 framing classified + checksum state | **MET** | SIMPLIFIED, checksum off |
| AC4 R-timestamp field position | **MET** | field 13 |
| AC5 real Lis-ID / units / range | **MET** | `^^^FT3`, `pmol/L`, `3.08 - 6.468` |
| AC6 peer identity | **PARTIAL** | H-record values pinned; name-match enforcement not tested |

## Residual / nice-to-have (not blocking)

1. **Confirm with the live chassis attached.** Today's capture is a software
   replay of a stored result over the real ASTM stack — genuine firmware bytes,
   but the analyzer chassis was disconnected (PLC red). A fresh run with the
   chassis on the table would upgrade AC1 from "software-level" to full and
   confirm auto-upload (vs. manual `→LIS Online`) frames identically.
2. **Settle AC6's match question** by deliberately varying `Analyzer ID` /
   `Host ID` and observing whether the software still uploads or refuses.
3. **QC path (runbook §9):** capture a QC upload and check for a wire
   discriminator (feeds LIS-33).
4. **Fixture graduation (LIS-38):** the redacted payload can seed a
   `synthetic: false` `edge/sim` fixture — but note `^^^FT3` here vs. the
   existing `FT3 II` synthetic seeds; reconcile the assay-code strings there.
