# Field map — MAGLUMI X3, 2026-07-23 client-lab bench (AC4, AC5, AC6)

Source: `raw-20260723-203124-023.bin` (the only result-bearing session tonight), confirmed
against the analyzer's own `online_ASTM.log`. One patient-shaped result, manually re-sent
from the Result screen (**not** an auto-upload at run completion — see `identity.md`).

## AC4 — R-record completion-timestamp field position

**Field 13.**

```
R|1|^^^T4|119|nmol/L|52 - 127|N||||||20260422111529
 1  2      3   4      5         6 7 8 9 10 11 12  ^-- 13
```

Tool output: `R-timestamp field position(s) observed: [13]`.

This **diverges from the vendor KB §6.6 fixtures (field 12)** and **matches the 2026-07-17
bench** on a different physical X3. Two independent units now agree on 13; treat 13 as the
real firmware behaviour and the KB fixtures as the documentation error. A parser must scan
for the 14-digit timestamp rather than index a fixed field.

## AC5 — Lis-ID codes, units, reference-range format (feeds LIS-38)

| Wire code (`O-5` / `R-3`) | UI menu name | Value | Unit (`R-5`) | Reference range (`R-6`) | Flag (`R-7`) |
|---|---|---|---|---|---|
| `^^^T4` | T4 | 119 | `nmol/L` | `52 - 127` | `N` |

- **Reference-range format is the hyphen form `low - high` with spaces** (`52 - 127`), NOT
  the `"low to high"` form. Confirms the hyphen variant for this site/firmware.
- Unit string is `nmol/L` — note the slash: bracket-escaped map keys (`"[nmol/L]"`) are
  required in the bridge mapping config, per the 2026-07-17 finding.
- Flag vocabulary observed: `N`. (`L`/`H` not exercised — this result is in range.)
- Only ONE assay captured tonight. The site's full menu (34 assays, from the 2026-07-22
  launcher log) remains uncaptured on the wire; the ` II` suffix question (UI `FT4 II` vs
  wire `^^^FT4`) is still open for every assay except T4, which has no suffix either way.

## AC6 — Peer identity

`H` record as transmitted:

```
H|\^&||PSWD|Maglumi X3|||||Lis||P|E1394-97|20260723
```

| Field | Value | Note |
|---|---|---|
| H-2 delimiters | `\^&` | ASTM defaults |
| H-4 | `PSWD` | literal string, not a configured value — appears to be a fixed password/placeholder slot |
| H-5 sender / Analyzer ID | `Maglumi X3` | matches the Online screen's `Analyzer ID` field |
| H-10 receiver / Host ID | `Lis` | matches the Online screen's `Host ID` field |
| H-12 | `P` | processing ID (production) |
| H-13 | `E1394-97` | version |
| H-14 | `20260723` | date stamp (date only, no time) |

**Finding: the host does NOT have to identify itself.** Our capture host advertises no name
at all — it only ACKs — and the analyzer connected, went green, and uploaded without
complaint. So the SnibeLis-era exact case-sensitive `Host ID` match requirement does **not**
apply to the native `Online` interface talking to a generic host. The `Host ID` value is
transmitted in H-10 for the host's benefit; nothing is verified in return.

Not tested: whether the analyzer would reject a host that actively sends a *wrong* identity
(we never send one), and whether changing `Analyzer ID` changes anything downstream.

## P-record / patient identity

```
P|1
```

**Bare `P|1` — no patient ID, no name, no DOB, no sex.** Third independent confirmation
(KB, 2026-07-17 bench, tonight). Consequences unchanged: every X3 result stages with a blank
patient hint, and the LIS-239 same-day patient-mismatch guard cannot fire on this channel.
The compensating operator procedure (`docs/runbooks/x3-patient-identity-verification-sop.md`,
LIS-270) remains a required go-live gate.

## O-record sample ID — PHI finding, now confirmed at a real site

```
O|1|PATIENT-REDACTED-1||^^^T4
```

`O-3 = 'PATIENT-REDACTED-1'` — a **person-shaped name in the sample-ID field**, entered by this
lab's own operators in their normal workflow. (Site staff state this record is
dummy/training data, not a real patient; the *workflow pattern* is what matters here.)

Because OpenELIS consumes `O-3` as the accession number (2026-07-17 finding), this site's
current practice would put patient names into the OE accession field: a correctness problem
and a PHI surface. This is no longer theoretical — it is observed site behaviour on real
firmware, and it is the concrete justification for requiring a **barcode scanner** so that
`O-3` carries a real accession. Feeds the head-lab recommendation and LIS-38 go-live gating.
