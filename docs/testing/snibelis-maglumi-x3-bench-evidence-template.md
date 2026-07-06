# MAGLUMI X3 Bench Evidence Template (native `Online` ASTM → our bridge)

> Slice: LIS-108 / S3.0a — **re-framed 2026-07-06 by LIS-178**: the SnibeLis middleware is
> dropped from the topology; the interface under test is the X3's **native built-in LIS
> interface** speaking directly to our bridge. Use this when **LIS-75** runs the bench
> capture and LIS-38 needs live bench evidence. Keep raw captures with the issue/PR
> artifact bundle; do not paste patient-identifying data into tracker comments.
> *(The filename keeps its legacy `snibelis-` prefix for link stability only — there is no
> SnibeLis on the wire.)*

## Scope

- Analyzer: SNIBE MAGLUMI X3, using its native LIS interface (`Set → System Setting → Online`).
- Interface under test: the X3's native `Online` **ASTM E1394-97** over TCP (serial COM
  fallback 9600/8/N/1) direct to the LabSolution edge bridge. HL7 v2.5 (proprietary SNIBE
  dialect) is the documented fallback lever — LIS-176.
- Our role: **the host** — the bridge is the TCP listener; the analyzer is the TCP client.
  Present receiver / Host ID = `Lis`. Port is site-chosen (no fixed vendor port).
- No middleware: SnibeLis / SnibeLinker is **not** on the wire. The export/DB route exists
  only as the LIS-34 last-resort contingency and is not part of this capture.

## Required Environment Evidence

| Item | Value |
|---|---|
| Bench date/time | |
| Engineer(s) | |
| MAGLUMI X3 serial / software version | |
| `Online` screen: Online Setting (TCP/IP vs COM Port) | |
| `Online` screen: Analyzer ID / Host ID | |
| `Online` screen: Host Comm. Protocol (ASTM / HL7) | |
| `Online` screen: `Enable Checksum` toggle | on / off |
| Bridge host / IP / listen port (site-chosen) | |
| Query/order download enabled | yes / no |
| Upload QC Data enabled | yes / no |

## Capture Set

Collect raw bytes before parser normalization.

| Capture | Required? | File / digest | Notes |
|---|---:|---|---|
| Patient result upload: H/P/O/R/L | yes | | Include ACK transcript. |
| Query request: Q | yes, if enabled | | Q-3 must preserve the sample ID form. |
| Host order response: H/P/O/L | yes, if enabled | | Confirm O-5 assay repetition with `\`. |
| QC upload | yes, if available | | Requires engineer sign-off before interpreting QC. No documented ASTM wire discriminator — record whatever distinguishes the QC run (LIS-33). |
| Checksummed variant | yes, if `Enable Checksum` was toggled on | | Re-capture at least the result upload with the toggle inverted, so both framing variants are pinned (LIS-174). |

## Framing Classification

Select exactly one based on wire bytes (capture both if the `Enable Checksum` toggle was
exercised).

| Mode | Evidence |
|---|---|
| Full E1381 | Frames are `STX frame-number text ETX checksum CR LF`; ACK after each frame. |
| X3 simplified (documented default) | One `ENQ`, `STX`, payload records, `ETX`, `EOT` envelope per message; ACK after each control token; **no NAK, no checksum, no frame numbers, no LF**. A missing ACK = link declared dead (reconnect, not retransmit). |
| X3 simplified + checksum | As above but with checksums present (`Enable Checksum` on). |
| Raw/non-compliant | Payload starts at `H|` without control-code establishment. |
| Other | Describe and attach bytes. |

ACK transcript:

```text
X3 -> bridge: ENQ
bridge -> X3: ACK
...
```

## Field Assertions

| Assertion | Observed |
|---|---|
| `H-5` transmitter name matches configured analyzer identity | |
| `H` receiver field carries the configured Host ID (`Lis`) | |
| `Q-3` sample ID keeps leading component marker (`^<id>`) on the wire | |
| `O-3` sample ID matches the queried sample | |
| `O-5` assay identifiers use `^^^<assay>` (site-configured "Lis ID", no vendor table) | |
| Multiple assays repeat with `\` | |
| `R-3` assay identifiers use `^^^<assay>` | |
| `R-5` raw unit preserved | |
| `R-6` raw reference range preserved | |
| `R-7` abnormal flag preserved (`L`, `H`, `N` only) | |
| Completion timestamp: record the **observed field index** (the manual's numbering has a documented off-by-one — use a tolerant scan, do not hard-index) | |
| QC marker / discriminator location identified (host-side classification, LIS-33) | |

## Fixture Promotion

After capture:

1. Copy the application payload into `edge/sim/fixtures/snibelis-maglumi-x3-*/message.astm`
   *(legacy fixture-directory name kept for stability; renaming is out of scope — LIS-174/LIS-38
   if ever)*.
2. Set `synthetic` to `false`.
3. Replace `source.reference` with the capture ID and artifact digest.
4. Keep the framing mode in `message.framing` aligned to the live classification.
5. If live framing is full E1381, validate through `AstmTransport`; if live framing is
   simplified, validate through the simplified-envelope session simulator (`edge/sim`'s
   `snibelis.py` module — legacy name; framing key `snibelis-astm`).
6. If query/download is disabled, keep a result-upload fixture and record
   `query/order download disabled by site config` in the channel evidence.

## Safety Sign-Offs

| Area | Required sign-off |
|---|---|
| QC interpretation / patient-stream exclusion | |
| Firmware or analyzer software change | |
| Production mapping table activation | |
