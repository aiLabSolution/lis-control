# QC characterization — MAGLUMI X3, 2026-07-23 client-lab bench (LIS-269 leg)

**Status: SCREEN-ONLY. No QC bytes captured yet.** Everything below is read off the
analyzer UI (`qc-result-screen.jpg`), not off the wire. Nothing here is wire-verified.

## What the QC Result screen shows (2026-07-23 21:07)

- **109 stored QC records** — QC history is available for replay without reagents.
- Tabs: `QC Result` / `QC Analysis`. Actions on the QC screen:
  `Today Result | Search | Delete | Details | →LIS Online | Recalc. | Export | Print`.
  **`→LIS Online` is a QC-specific send-to-LIS control** — the QC upload path does not
  require enabling `Auto Upload QC Data` on the Online screen, so a QC capture costs no
  analyzer config change.
- Columns: `Sample ID | QC Lot-No. | Assay | RLU | CV(%) | Conc. | Unit | Status | Flag |
  Level | Finished Time | No…`

### Rows visible in the photo

| Sample ID | QC Lot-No. | Assay | RLU | Conc. | Unit | Status | Flag | Level | Finished |
|---|---|---|---|---|---|---|---|---|---|
| `#49324031Q2#` | 49324031Q2 | hs-cTnI II | | | | Failed | | Q2 | |
| `#49324031Q2#` | 49324031Q2 | hs-cTnI II | | | | Failed | | Q2 | |
| `#49324031Q2#` | 49324031Q2 | hs-cTnI II | 7905 | 18.9 ng/L | ng/L | Finish | | Q2 | 2025-10-13 14:31:19 |
| `#49324031Q3#` | 49324031Q3 | hs-cTnI II | 33940 | 165 ng/L | ng/L | Finish | | Q3 | 2025-10-13 14:31:36 |
| `#02624011Q2#` | 02624011Q2 | AFP | | | | Failed | | Q2 | |
| `#02624011Q2#` | 02624011Q2 | AFP | 209513 | 57.1 ng/mL | ng/mL | Finish | E | Q2 | 2025-10-22 04:24:13 |
| `#24725021Q1#` | 24725021Q1 | Anti-Tg II | 18192 | 71.2 IU/mL | IU/mL | Finish | | Q1 | 2025-10-30 12:25:25 |
| `#24725021Q2#` | 24725021Q2 | Anti-Tg II | 177670 | 269 IU/mL | IU/mL | Finish | | Q2 | 2025-10-30 12:25:43 |
| `#24725021Q1#` | 24725021Q1 | Anti-Tg II | 19520 | 73.4 IU/mL | IU/mL | Finish | | Q1 | 2025-10-30 14:04:47 |
| `#24725021Q2#` | 24725021Q2 | Anti-Tg II | 173617 | 263 IU/mL | IU/mL | Finish | | Q2 | 2025-10-30 14:05:05 |

## Findings and hypotheses (UNVERIFIED — need a wire capture to confirm)

1. **QC sample-ID convention appears to be `#<lot><level>#`** — hash-delimited, e.g.
   `#49324031Q2#` = lot `49324031`, level `Q2`. If that string reaches `O-3` on the wire it
   is a strong, machine-shaped discriminator — and a much better one than the
   **provisional, assumed** `O.12=Q` rule currently shipped in
   `astm/snibe-maglumi-x3.json` (`configDefaults.qcRules`). **Confirm before amending.**
2. **Levels are Q1/Q2/Q3** and are also embedded in the lot column. Whether level rides the
   wire separately (a Q-segment, or a component of O-3) is unknown.
3. Stored QC dates are 2025-10-xx while the newest patient result is 2026-04-22 — QC has not
   been run recently at this site. Relevant to the go-live QC posture
   (`docs/runbooks/x3-qc-guarded-go-live.md`), independent of the wire question.
4. `Failed` rows carry no RLU/Conc. Do not select them for a send test — nothing to transmit.
5. QC assays seen here (hs-cTnI II, AFP, Anti-Tg II) are **not** the `LC_LRN/LC_RRN/LC_SMP`
   materials seen in the 2026-07-22 launcher-log assay menu. `LC_*` may be a different
   control family (or a menu entry never run). Note for the LIS-38 dictionary.

## Next step when QC is resumed

Tick ONE `Finish` row → press `→LIS Online` → capture. Then repeat with a different **level**
of the same assay (the Anti-Tg II Q1/Q2 pair) to see whether level is encoded on the wire.
Per runbook §9: capture and classify ONLY, never auto-accept QC.
