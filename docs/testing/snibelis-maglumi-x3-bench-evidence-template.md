# SnibeLis / MAGLUMI X3 Bench Evidence Template

> **⚠ SUPERSEDED (2026-07-06, LIS-75).** The SnibeLis middleware premise is dropped
> (owner directive): the X3 now attaches its native `Online` ASTM E1394-97
> interface **directly** to our host, with **no** SnibeLis PC / license / DB on the
> wire. The current bench instrument is **`docs/runbooks/snibe-maglumi-x3-bench.md`**
> (no-SnibeLis), whose embedded evidence packet replaces the tables below. This file
> is kept only for historical reference and is formally retired by **LIS-178**
> (Stage-3 doc re-baseline). Do not fill this in for a native-ASTM bench.

> Slice: LIS-108 / S3.0a (historical). Originally: use this when LIS-75 unblocks the
> SnibeLis PC/license and LIS-38 needs live bench evidence. Keep raw captures with
> the issue/PR artifact bundle; do not paste patient-identifying data into tracker
> comments.

## Scope

- Analyzer: SNIBE MAGLUMI X3.
- Middleware: SnibeLis / SnibeLinker Windows PC.
- Interface under test: SnibeLis northbound ASTM E1394 to the LabSolution edge.
- Our role: host/LIS.

## Required Environment Evidence

| Item | Value |
|---|---|
| Bench date/time | |
| Engineer(s) | |
| SnibeLis PC hostname / OS | |
| SnibeLis version / installer | |
| SnibeLis registration status | |
| MAGLUMI X3 serial / software version | |
| Analyzer ID / SnibeLis Instrument Name | |
| Edge host/IP/port | |
| Relay mode confirmed with SNIBE | emit socket / export file / DB export |
| Query/order download enabled | yes / no |
| Upload QC Data enabled | yes / no |

## Capture Set

Collect raw bytes before parser normalization.

| Capture | Required? | File / digest | Notes |
|---|---:|---|---|
| Patient result upload: H/P/O/R/L | yes | | Include ACK transcript. |
| Query request: Q | yes, if enabled | | Q-3 must preserve the sample ID form. |
| Host order response: H/P/O/L | yes, if enabled | | Confirm O-5 assay repetition with `\`. |
| QC upload | yes, if available | | Requires engineer sign-off before interpreting QC. |
| Export/DB fallback row | if socket emit unavailable | | Capture raw export plus SnibeLis config proving fallback mode. |

## Framing Classification

Select exactly one based on wire bytes.

| Mode | Evidence |
|---|---|
| Full E1381 | Frames are `STX frame-number text ETX checksum CR LF`; ACK after each frame. |
| SnibeLis simplified | `ENQ`, `STX`, payload records, `ETX`, `EOT`; ACK after ENQ/STX/ETX/EOT; no frame numbers/checksums. |
| Raw/non-compliant | Payload starts at `H|` without control-code establishment. |
| Other | Describe and attach bytes. |

ACK transcript:

```text
SnibeLis -> host: ENQ
host -> SnibeLis: ACK
...
```

## Field Assertions

| Assertion | Observed |
|---|---|
| `H-5` transmitter name matches configured analyzer identity | |
| `Q-3` sample ID keeps leading component marker (`^<id>`) on the wire | |
| `O-3` sample ID matches the queried sample | |
| `O-5` assay identifiers use `^^^<assay>` | |
| Multiple assays repeat with `\` | |
| `R-3` assay identifiers use `^^^<assay>` | |
| `R-5` raw unit preserved | |
| `R-6` raw reference range preserved | |
| `R-7` abnormal flag preserved (`L`, `H`, `N`) | |
| `R-13` completion timestamp format observed | |
| QC marker location identified | |

## Fixture Promotion

After capture:

1. Copy the application payload into `edge/sim/fixtures/snibelis-maglumi-x3-*/message.astm`.
2. Set `synthetic` to `false`.
3. Replace `source.reference` with the capture ID and artifact digest.
4. Keep the framing mode in `message.framing` aligned to the live classification.
5. If live framing is full E1381, validate through `AstmTransport`; if live framing is
   simplified, validate through the SnibeLis session simulator.
6. If query/download is disabled, keep a result-upload fixture and record
   `query/order download disabled by site config` in the channel evidence.

## Safety Sign-Offs

| Area | Required sign-off |
|---|---|
| QC interpretation / patient-stream exclusion | |
| Firmware or analyzer software change | |
| Production mapping table activation | |
