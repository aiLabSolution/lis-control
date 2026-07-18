# Runbook — SNIBE MAGLUMI X3 native-ASTM bench capture (LIS-75)

Drafted 2026-07-06 for the physical MAGLUMI X3 bench run. This is the
critical-path bench capture that turns the X3 integration from **synthetic** into
**bench-verified**: prove that the X3's built-in `Online` LIS interface speaks
ASTM E1394-97 to **our** host (no SNIBE middleware on the wire), that our host
ACKs it correctly so the analyzer's LIS indicator goes green, and that the raw
wire bytes are captured and the five open unknowns are pinned.

> **Owner directive (2026-07-06):** the SnibeLis middleware is dropped. The X3
> attaches its native `Online` interface (ASTM E1394-97, HL7 v2.5 fallback)
> **directly** to our bridge, which presents as the host the X3 already knows how
> to talk to (`Host ID = Lis`). This runbook is the no-SnibeLis bench.

Unlike the EDAN H99S/H60S benches (whose production bridge parse profile was
already shipped and merged before the bench), the X3's dedicated receive path
(**LIS-174**) and analyzer channel (**LIS-175**) are **not built yet** — by
design. Every bridge fixture for the X3 is flagged `synthetic: true`. This
capture is the single source of ground truth that unblocks them, so it uses a
**standalone capture tool** rather than the bridge, and **getting real bytes on
disk is the deliverable**. A live bridge→OpenELIS parse is out of scope here.

## References

- **Protocol ground truth:** the SNIBE MAGLUMI X3 driver knowledgebase — a local
  working note (`thoughts/references/SNIBE_MAGLUMI_X3_LIS_driver_knowledgebase.md`
  on the bench box; not repo-tracked, mirroring the H99S KB convention). Esp. §3
  (transport + the `Online` screen fields), §4 (framing + the `Enable Checksum`
  ambiguity, the documented 4-point ACK handshake), §5 (record and field layer),
  §6 (verbatim wire fixtures + the field off-by-one hazard), §13 (bench checklist),
  §14 (open questions). Its durable citations point to the vendor manuals in
  `~/projects/manuals-and-lis-protocol/manuals-and-lis-protocol/SNIBE/MAGLUMI-X3/`
  (SnibeLis LIS User Manual v1.1 App. A; MAGLUMI X3 User Manual App. B) — those
  PDFs are the authoritative source, not this runbook or the KB note.
- **Capture tool:** `scripts/x3_astm_capture.py` (this repo) — a stdlib-only TCP
  listener that plays the host side of the handshake and archives raw bytes. Its
  analysis layer (framing classification, R-timestamp field detection anchored on
  a 14-digit scan, code/unit extraction) is unit-tested against the KB §6 fixtures
  and their off-by-one variants (`scripts/test_x3_astm_capture.py`). Treat its live
  CAPTURE SUMMARY as a decode aid, not the record of truth: confirm framing against
  the `Enable Checksum` toggle state and read the pinned values off the archived
  raw bytes.
- **Architecture:** `docs/adr/0009-astm-e1381-codec-and-session.md`,
  `docs/adr/0010-astm-e1394-record-parser.md`,
  `docs/adr/0012-raw-message-archive-and-deterministic-replay.md`,
  `docs/adr/0014-bidirectional-host-query-qrd-qrf.md`,
  `docs/adr/0015-edge-transport-substrate-and-channel-attachment.md`.
- **Precedent (bench-evidence conventions):** the EDAN H99S
  (`docs/runbooks/edan-h99s-bench-conformance.md`, LIS-149) and H60S
  (`docs/runbooks/edan-h60s-bench-conformance.md`, LIS-20, PR #91) bench captures —
  graduated fixtures, wire-fact write-ups, raw archives.
- **Downstream consumers of this capture:** LIS-174 (framing receive-path spec),
  LIS-175 (port/IP/identity/codes for the analyzer channel), LIS-38 (Lis-ID →
  LOINC/UCUM dictionary + fixture graduation), LIS-269 (QC sample-ID pattern;
  supersedes LIS-33 on the native path),
  LIS-173 (calibration-ID convention). LIS-34 (SnibeLis export/DB fallback) closes
  Won't-Do if the native connect succeeds (the expected outcome).

## Scope

Bench evidence target for this run:

- MAGLUMI X3 over TCP/IP, **analyzer as TCP client**, our capture host as TCP
  **server/listener** (KB §3.2).
- Native `Online` **ASTM E1394-97** result upload (`H/P/O/R/L`), simplified
  envelope (`ENQ STX … ETX EOT`, ACK per control token — KB §4).
- Correct host ACK cadence so the analyzer's LIS indicator turns **green**.
- Raw wire capture archived, plus the analyzer PC's `logs/date/online`.
- The five open unknowns (below) pinned against real firmware bytes.

Out of scope for this slice (capture-only, tracked elsewhere):

- Live bridge → OpenELIS ingest / LOINC normalization (LIS-174 / LIS-175 / LIS-32).
- Order-download (`Q` → host-initiated `O`) round-trip (LIS-177 / ADR-0014). The
  capture tool **detects and logs** a `Q` query but does not answer it.
- Fixture graduation to `edge/sim` / bridge (LIS-38). Capture the bytes here;
  graduate them there.
- QC acceptance. QC is **captured and classified only**, never auto-accepted —
  engineer sign-off territory.

## The five unknowns to pin (ordered by risk — KB §14)

1. **Does the X3 firmware connect to a non-SNIBE host at all?** Strongly implied
   by the protocol-generic `Online` screen and the `Lis` receiver name, but never
   proven. **Test this FIRST.** If it refuses, go to §8 (HL7 lever, then the
   LIS-34 contingency).
2. **Framing:** simplified `ENQ/STX/…/ETX/EOT` (ACK per control token, no
   NAK/checksum/frame#/LF) vs a checksummed E1381 variant. Record the
   `Enable Checksum` toggle state.
3. **R-record completion-timestamp field position** (11 vs 12 vs 13 — the
   documented vendor off-by-one, KB §6.6).
4. **The site's real Lis-ID → assay strings, units, and reference-range string
   format** (`"low to high"` vs hyphen forms) — feeds the LIS-38 dictionary.
5. **Peer identity:** do the `Analyzer ID` / `Host ID` names have to match (as
   SnibeLis required an exact case-sensitive match)? Record the actual
   `Analyzer ID` / `Host ID` / ASTM delimiter defaults.

## Bench Roles

| Role | Responsibility |
|---|---|
| Bench operator | Analyzer UI, `Online`-screen config, sample/QC handling, screenshots, nameplate/firmware photo, archiving `logs/date/online` from the analyzer PC. |
| LIS edge engineer | Capture host + `x3_astm_capture.py` listener, packet capture, live-decode watch, evidence extraction. |
| Validation owner | Pass/fail call, evidence packet review, signed conformance report (LIS-38). |

Use bench/test identifiers only. Do not use real patient PHI for this run.

## Prerequisites

- Physical MAGLUMI X3 is powered on and ready. Nameplate, serial, software/firmware
  build, and the LIS protocol document version are recorded.
- The X3's **operation-unit PC** rear-panel Ethernet and the capture host are on
  the same routable bench network and can ping each other. **Connect to the
  operation-PC, not the analyzer chassis** — the chassis↔PC link is a separate
  private net (KB §3.2).
- Capture host has `python3` (stdlib only — no extra deps) and, ideally, `tcpdump`
  and/or `socat` for a redundant packet-level backstop.
- **No SnibeLis PC, license, or DB is on the wire.** If §8 forces the LIS-34
  fallback, that is a documented escalation, not the plan.

## Evidence Packet

A fill-in-the-blanks companion form — environment table, capture set, framing
classification, and field-assertion rows — lives at
`docs/testing/snibelis-maglumi-x3-bench-evidence-template.md` (re-framed to this
no-SnibeLis topology by LIS-178; the legacy `snibelis-` filename is kept for link
stability only). Use this runbook for the procedure and that template for the
per-run record.

Create one run directory before starting, named with date and serial number:

```text
evidence/bench/maglumi-x3/<YYYYMMDD>-<serial>/
```

Collect at minimum:

| Artifact | Required content |
|---|---|
| `identity.md` | Model, serial, firmware/software build, KB/protocol version, operator names, date/time. |
| `nameplate.jpg` | Physical nameplate or device identity screen. |
| `online-screen.png` | The analyzer `Online` screen showing Online Setting / IP / Port / Host Comm. Protocol / Analyzer ID / Host ID / **Enable Checksum state** / delimiters. |
| `lis-indicator-green.png` | Device UI proof that the LIS status indicator turned green on connect (AC1). |
| `x3-astm.pcap` | Full `tcpdump` packet capture of the connect test + at least one result-upload session (backstop for the tool's archive). |
| `raw-*.bin` | The `x3_astm_capture.py` raw byte archive for ≥1 result-upload session (AC2). |
| `annotated-*.log` | The tool's annotated/decoded log incl. the CAPTURE SUMMARY block. |
| `analyzer-pc-online-logs/` | Copy of the analyzer PC's `logs/date/online` for the session (second capture source, KB §3.1). |
| `framing.md` | Framing classification (simplified vs checksummed) + the `Enable Checksum` toggle state (AC3). |
| `field-map.md` | R-timestamp field index (AC4); real Lis-ID codes/units/reference-range format (AC5); observed `Analyzer ID`/`Host ID`, delimiters, and the peer-identity finding (AC6). |
| `signed-conformance-report.pdf` | Final validation sign-off (LIS-38). |

If any artifact contains PHI, do not commit it to the repo. Redact before sharing
outside the validation evidence store.

## Test Plan

### 1. Physical identity and protocol confirmation

1. Photograph the nameplate; record serial and software/firmware build.
2. Confirm the unit is a MAGLUMI X3 (not a sibling SNIBE analyzer mislabeled in
   inventory).
3. Record the LIS protocol document version the site's firmware claims to
   implement (ASTM E1394-97 / HL7 v2.5).

Pass criteria: `identity.md` and `nameplate.jpg` are captured; the unit is
confirmed to be an X3.

### 2. Stand up the capture host

1. Pick a TCP port (site-configurable; there is **no** standard port — vendor
   screenshots show `2020`, `2019`, `17`). Record the chosen port.
2. Start the capture listener (simplified mode is the documented default):

   ```bash
   python3 scripts/x3_astm_capture.py --port <PORT> --outdir evidence/bench/maglumi-x3/<run>/
   ```

3. Start the redundant packet capture as a backstop:

   ```bash
   sudo tcpdump -i <bench-interface> -s0 -w evidence/bench/maglumi-x3/<run>/x3-astm.pcap tcp port <PORT>
   # or, as a byte-level tee: socat -x -v TCP-LISTEN:<PORT>,reuseaddr,fork STDOUT
   ```

   Use `tcpdump`/`socat` **only as a backstop** — the capture tool is the primary
   archive and also plays the required ACK handshake. Do not run `socat` on the
   **same** port as the listener; use it on a separate probe port or the pcap.

Pass criteria: the listener prints "listening on … ACK mode=simplified" and the
pcap is running.

### 3. Configure the analyzer `Online` screen and connect (AC1 — highest risk)

On the analyzer: **`Set → System Setting → Online`** (KB §3.1):

- `Online Setting = TCP/IP`; `IP Address` / `Port` → the capture host + chosen port.
- `Host Comm. Protocol = ASTM`.
- `Analyzer ID` = a recorded value (e.g. `Maglumi User`); `Host ID = Lis`.
- Enable `Auto-Upload Test Report`.
- **Record the `Enable Checksum` state** and the ASTM delimiter defaults (Field /
  Repeat / Component / Escape).
- Save → **expect the analyzer LIS status indicator to turn green.**

Pass criteria:

- The analyzer LIS indicator is **green** (`lis-indicator-green.png`), **or** the
  refusal is documented and you proceed to §8.
- The capture host's listener logs an inbound connection from the analyzer.
- Packet capture confirms the analyzer is the TCP **client** and the host is the
  **server**.

> If the indicator does not go green but the listener logged bytes: check the
> annotated log's CAPTURE SUMMARY. If it reports **checksummed** framing, the
> simplified ACK cadence may have desynced — go to §4 and restart the listener
> with `--mode framed`.

### 4. Capture a result-upload session and classify framing (AC2, AC3)

1. Run one patient **immunoassay** result on the X3 under bench-operator control
   (bench-only sample ID, e.g. `SNB-BENCH-001`).
2. Send it via auto-upload. Watch the listener: it ACKs `ENQ/STX/ETX/EOT` and, at
   `EOT`, prints a CAPTURE SUMMARY.
3. Confirm the raw archive (`raw-*.bin`) and annotated log were written, and copy
   the analyzer PC's `logs/date/online` for the session.
4. Read the framing off the summary and **cross-check against the `Enable Checksum`
   toggle state** you recorded in §3.

Framing decision (record exactly one in `framing.md`):

| Mode | Wire evidence |
|---|---|
| Simplified (expected) | `ENQ STX <records> ETX EOT`; ACK after each of ENQ/STX/ETX/EOT; no frame numbers, no checksum, no LF. |
| Checksummed E1381 | `STX <frame#> <records> ETX <cc> CR LF`; ACK per frame. If observed, restart the listener `--mode framed` and re-capture. |
| Raw/non-compliant | Payload starts at `H|` with no `ENQ/STX` establishment. Attach bytes. |

Pass criteria: ≥1 result-upload session is archived raw; framing is classified and
the `Enable Checksum` state is recorded; the tool's classification agrees with the
toggle state (or the disagreement is written up).

### 5. Pin the R-record timestamp field position (AC4)

The vendor byte examples drift (field 11 vs 12 vs 13, KB §6.6). The capture tool
reports the observed index per R record and a de-duplicated set for the session
(`R-timestamp field position(s) observed: […]`). Record it in `field-map.md`.

Pass criteria: the completion-timestamp field index is pinned from real bytes (not
assumed), and any deviation from the KB fixtures (which land at field 12) is noted.

### 6. Record the real Lis-ID codes, units, and reference-range format (AC5)

From the same capture's `O`/`R` records (the tool extracts these into the summary):

- The site's real **assay codes** (the `^^^<code>` strings in `O-5`/`R-3`).
- Raw **units** (`R-5`) and **reference-range** string format (`R-6` — e.g.
  `"0.27 to 4.20"` vs a hyphen form).
- Abnormal **flags** (`R-7`: `L`/`H`/`N`).

Record these in `field-map.md`. They feed the LIS-38 Lis-ID → LOINC/UCUM
dictionary. **Do not** graduate a fixture here — that is LIS-38.

Pass criteria: real codes, units, and the reference-range format are captured
verbatim for the LIS-38 dictionary.

### 7. Determine the peer-identity requirement (AC6)

From the `H` record and a small experiment:

1. Record the observed `H-5` (transmitter / `Analyzer ID`) and `H-10` (receiver /
   `Host ID`, expected `Lis`) and the ASTM delimiter defaults.
2. If bench time allows, change the capture host's advertised identity (or the
   analyzer's `Analyzer ID`) and observe whether the analyzer still connects and
   uploads, or refuses — SnibeLis required an exact case-sensitive match. Record
   whether the X3 firmware enforces the same.

Pass criteria: the peer-identity requirement (must the host name match?) is
determined and written to `field-map.md`.

### 8. If the X3 refuses our host (documented escalation, unknown #1)

Only if §3 fails to go green **and** no result bytes are captured:

1. Try `Host Comm. Protocol = HL7` on the `Online` screen (native MLLP path,
   KB §7 / LIS-176) and re-attempt with an MLLP-capable listener. Capture and
   classify whatever bytes appear.
2. Only if **both** ASTM and HL7 native attach fail, record the LIS-34 SnibeLis
   export/DB fallback as the escalation (requires a SnibeLis PC — not on the bench
   today).

Pass criteria: the refusal and the escalation path taken are documented in
`identity.md` / `framing.md`. A documented refusal + escalation **satisfies AC1's
alternative** and is a valid slice outcome.

### 9. QC upload characterization (capture-only)

Run only after the sample-result path is stable, and only if the operator can send
QC without disrupting routine controls. This is the LIS-266 chassis-attached
session's QC leg; classification/provisioning is tracked by LIS-269 (LIS-33 is
retained-Done, superseded by LIS-269 for the native path).

1. Enable `Upload QC Data`, send one QC result, capture the bytes.
2. Classify the QC message and note any wire discriminator (KB §9.2 warns there may
   be **no** wire discriminator between QC and patient results — flag this for
   LIS-269). Specifically record: does the O-record carry an action code (`O.12=Q`)?
   What is the QC sample-ID convention? Are Q-segments (lot / control level)
   emitted?
3. **Never auto-accept QC.** Capture and classify only; QC acceptance is engineer
   sign-off territory.

Pass criteria: the QC message is archived and labeled as characterization
evidence; if there is no wire discriminator, a QC-routing note is filed for LIS-269.

### 9a. QC replay proof (LIS-269 — after the §9 capture exists)

OE now provisions the X3 with a **provisional** `O.12=Q` QC rule via the
`snibe-maglumi-x3` analyzer profile (`astm/snibe-maglumi-x3.json`, authoritative
copy in `deploy/kit/configs/analyzer-profiles/`) — provisional means *assumed,
not bench-verified*; the guarded go-live posture and required operator SOP are in
`docs/runbooks/x3-qc-guarded-go-live.md`.
Once §9 has produced a real QC bin, close the loop:

1. Derive the actual discriminator from the captured bytes and amend the OE-side
   rules if it differs from `O.12=Q` (profile `configDefaults.qcRules` and the
   analyzer's `analyzer_qc_rule` rows; add a sample-ID rule if that is the real
   convention, and activate the inactive `CALIBRATION_*` placeholder only with a
   confirmed operand).
   In OE, the X3 analyzer's transport IP must be set (operator config) so push-sync
   provisions the bridge registry keyed at the real source IP — verify with
   `GET <bridge>/api/analyzers` that the X3 entry carries the expected `qcRules`.
2. Replay the captured QC bin through the deployed stack:

   ```
   python3 scripts/x3_astm_capture.py --replay <archived raw-*.bin> --to <bridge-host>:12020
   ```

3. Verify staging: the QC row must land in `analyzer_results` with
   `is_control = true` and `read_only = true` (QC meta-tag path), and must **never**
   be acceptable into the patient stream. A patient-shaped replay from the same
   session must still stage as a patient result (no over-classification).
4. Archive the replay evidence next to the capture and note the verdict on LIS-269;
   on a confirmed discriminator, retire the heightened daily review per
   `x3-qc-guarded-go-live.md` §SOP step 6.

Pass criteria: captured QC bin replays to a QC-tagged, read-only staging row; the
provisional rule is either confirmed or amended from the capture; evidence archived.

## Exit Criteria

The X3 native-ASTM capture (LIS-75) is complete when:

- The X3 connects to our non-SNIBE host with the LIS indicator **green**, **or**
  the refusal is documented with the escalation path taken (§8).
- A raw wire capture + the analyzer PC's `logs/date/online` are archived for ≥1
  result-upload session.
- Framing is classified (simplified vs checksummed) with the `Enable Checksum`
  state recorded.
- The R-record timestamp field position is pinned from real bytes.
- Real Lis-ID codes, units, and reference-range format are recorded.
- The peer-identity requirement is determined.
- The validation owner signs the evidence packet.

## Follow-Up Slices to File / Feed

- **LIS-174** — the dedicated X3 framing receive path (simplified 4-point ACK,
  and a checksummed profile if the bench proved `Enable Checksum` in use). This
  capture **specifies** it.
- **LIS-175** — register the X3 analyzer channel with the bench-proven port, IP,
  identity, and codes.
- **LIS-38** — graduate the captured bytes into an `edge/sim` fixture
  (`synthetic: false`) and build the Lis-ID → LOINC/UCUM conformance dictionary.
- **LIS-269** — QC sample-ID pattern / routing if §9 shows no wire discriminator
  (supersedes LIS-33 for the native path; run §9a replay proof after capture).
- **LIS-173** — calibration-ID convention if calibration uploads are observed.
- **LIS-177 / ADR-0014** — order-download (`Q` → host-initiated `O`) round-trip,
  out of scope for this capture.
- **LIS-34** — close Won't-Do if the native connect succeeds (expected).
