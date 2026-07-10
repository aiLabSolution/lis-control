# AC1 evidence — H99S CD-mode DEV012 capture (real wire, 2026-07-08)

Snapshot of `clinlims.analyzer_results` (analyzer_id=5) immediately after the operator sent a **CD-mode** DEV01260000000000012 run through the physical H99S (192.168.50.50), **before Save** (status_id=1). Units are the OE-stored OBX-6 values (HL7-escaped: `\S\`=`^`, so `10\S\9/L`=10⁹/L, `10\S\12/L`=10¹²/L; `\T\`=`&`). This is the authoritative unit source the prior analysis lacked.

## Extended params — captured units + values (confirms/corrects the matrix)

| Wire code | Value | Units (raw → UCUM) | Disposition confirmation |
|---|---|---|---|
| **PDW** | 13.66 | *(empty)* | **unit-less on wire; value in manual RI 10.0–17.4 fL** → 32207-3 fL ✓ (055 seed) |
| **PDW-SD** | 12.2 | `fL` | fL-scale, distinct value from PDW → collides on 32207-3 → local/drop ✓ |
| **P-LCR** | 35.7 | `%` | in manual RI 19.3–47.1 ✓ (48386-7) |
| **P-LCC** | 88 | `10\S\9/L`→10⁹/L | in manual RI 39–101 ✓ (no LOINC) |
| **PLT-I** | 248 | 10⁹/L | **= PLT 248 → method-dup CONFIRMED → drop** |
| **PLT-A** | 248 | 10⁹/L | **= PLT 248 → method-dup CONFIRMED → drop** |
| **Macro#** | 0.51 | `10\S\12/L`→10¹²/L | RBC-scale count; no LOINC |
| **Macro%** | 9.5 | `%` | no numeric LOINC (only ordinal 15198-5) |
| **Micro#** | 0.04 | 10¹²/L | no LOINC |
| **Micro%** | 0.7 | `%` | 74761-8 (unvalidated on EDAN) |
| **IPF-D** | 0 | `10\S\9/L`→**10⁹/L (count!)** | **wire IPF-D is a COUNT, not the % fraction 71693-6** — see ⚠ below |
| **IRF-D** | 0.00 | `%` | research DIFF variant |
| **HFR-D / MFR-D / LFR-D** | 0.00 | `%` each | research retic-maturity |
| **RET#-D** | 0.0000 | 10¹²/L | = mapped RET# → normalize (LIS-190) |
| **RET%-D** | 0.00 | `%` | = mapped RET% → normalize (LIS-190) |
| **IME#** | 0.00 | 10⁹/L | **Immature Eosinophil (research) ≠ IMG → drop** |
| **IME%** | 0.0 | `%` | ≠ IMG% → drop |
| **HFC# / HFC%** | 0 / 0.5 | 10⁹/L / % | research high-fluorescence → drop |
| **ALY# / ALY%** | 0.03 / 0.50 | 10⁹/L / % | **research atypical-lymph → drop (don't map 43743-4)** |
| **InR#** | 0.00 | 10⁹/L | **Infected RBC count (manual) — not immature retic** |
| **InR‰** | 0.00 | `‰` (permille) | **Infected RBC permillage — confirms manual; 51636-9 refuted** |
| **NLR / PLR / MLR** | 1.5 / 104.7 / 0.15 | *(none)* | ratios, unit-less → derive downstream ✓ |
| **TNC / TNC-D / TNC-N** | 6.55 / 6.40 / 6.55 | 10⁹/L | **= WBC 6.55 → double-count → drop** |
| **WBC-D / WBC-N** | 6.40 / 6.55 | 10⁹/L | **= WBC 6.55 → method-dup → drop** |
| **H-NR% / L-NR%** | 0.00 / 0.00 | `%` | research NRBC-region → drop |
| **NEU/LYM/MON-X,Y,Z** | e.g. NEU-X 79.85, NEU-Y 139.32, NEU-Z 61.76 | *(none)* | scatter coords → drop |
| **NEU/LYM/MON-XW,YW,ZW** | e.g. NEU-XW 52, NEU-YW 48 | *(none)* | scatter widths → drop |

## Two wire quirks confirmed (both = other slices, not this one)

1. **`\T\`-decorated diff codes stage unmapped** — the base 5-part diff arrived as **`NEU#\T\` (3.53, 10⁹/L), `NEU%\T\` (53.8 %), `LYM#\T\` (2.33, 10⁹/L), `LYM%\T\` (35.6 %)** — i.e. the mapped codes NEU#/NEU%/LYM#/LYM% with a trailing `&` (`\T\`) the bridge is not un-escaping → **LIS-190** (bridge OBX code normalization). This is why the full 5-part diff doesn't persist in CD mode.
2. **i18n key leaks as the code** — several *mapped* analytes (test_id 507/515/512/514/517/516/511/510/508/509 = NEU%/PCT/NRBC#/RDW-SD/IMG%/IMG#/EOS%/EOS#) show `test_name = "ts:btn:284:name"` (an i18n key leaking into the OBX-3/code slot). Cosmetic display bug (they mapped via test_id); separate from this slice.

## ⚠ Finding that changes bucket ② (IRF/IPF)

The manual lists **base IRF/IPF** as reportable — but this CD-mode run emitted **only the `-D` forms** (`IRF-D` %, `IPF-D` **10⁹/L count**), no plain `IRF`/`IPF`. So:
- We cannot map "base IRF/IPF" from this wire — the base codes did not appear (may be a different analyzer mode, or CD mode only emits the -D forms).
- `IPF-D` arrives as a **count (10⁹/L)**, not the fraction the % LOINC 71693-6 expects.
→ **Bucket ② (map IRF/IPF) is blocked pending clarification** of which code the reportable value rides on (owner/EDAN-spec/other-mode capture). Do not map the -D forms as-is (research + wrong property).

## Net: AC1 satisfied
Real units + code strings captured for every genuinely-new param. PDW(fL)/P-LCR(%)/P-LCC(10⁹/L) confirmed; all bucket-⑥ method-dups confirmed equal to their reported measurand; InR=Infected RBC ‰ confirmed; IRF/IPF base absent (only -D). CSV/structured copy retained from the same snapshot.
