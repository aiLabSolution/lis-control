# LIS-192 — H99S extended/CD-mode param disposition · wire inventory & evidence

**Analyzer:** EDAN H99S (OE analyzer id 5, ip 192.168.50.50) / H60S (id 7, .50.51) — shared EDAN H90-series wire.
**Bench:** OE `…:b9e23490` (LIS-183 seed live), bridge healthy. Captured 2026-07-08.

## Wire format facts (established)

- EDAN H90-series puts the **analyte code in OBX-4** (OBX-3 = suspect flag `0`/`1`), sample in OBR-2, patient in PID-2 (memory `edan-h90-series-field-repurposing`).
- **Units are in OBX-6, HL7-escaped:** `\S\` = `^` (superscript delimiter). So `10\S\9/L` = **10⁹/L** (UCUM `10*9/L`), `10\S\12/L` = **10¹²/L** (`10*12/L`), `g/L`, `%`, `fL`, `pg` verbatim.
- **Reference range in OBX-7.** Value repeated in the last OBX field.
- **PDW arrives with an EMPTY OBX-6 unit** (confirmed on H60S capture; ref range 9.0–17.0) → unit must be resolved from vendor spec / LOINC, not the wire.
- **Ratios (PLR, NLR) arrive unit-less** (dimensionless).
- CD-mode decorates some diff codes (`IME`≠seeded `IMG`, `NEU%\T\` [`\T\`=`&`], `RET#-D`) → **that's LIS-190's scope, not this slice.**

## A. Already mapped (LIS-183 30-code map on analyzer 5) — OUT of scope

`WBC 6690-2 · RBC 789-8 · HGB 718-7 · HCT 4544-3 · MCV 787-2 · MCH 785-6 · MCHC 786-4 · PLT 777-3 · MPV 32623-1 · PCT 51637-7 · RDW-CV 788-0 · RDW-SD 21000-5 · NEU# 751-8 · NEU% 770-8 · LYM# 731-0 · LYM% 736-9 · MON# 742-7 · MON% 5905-5 · EOS# 711-2 · EOS% 713-8 · BAS# 704-7 · BAS% 706-2 · NRBC# 771-6 · NRBC% 58413-6 · IMG# 53115-2 · IMG% 38518-7 · RET# 60474-4 · RET% 17849-1`

## B. Genuinely-new params needing disposition (this slice)

### B1 — Captured with real units (H60S extended-panel ORU, 34 obs, `evidence/h60s-extended-panel-34obs.hl7`)

| Wire code | OBX-6 unit (raw → UCUM) | OBX-7 ref range | Family |
|---|---|---|---|
| PDW    | *(empty)*            | 9.0–17.0   | Platelet distribution width |
| P_LCR  | `%`                 | 11.0–45.0  | Platelet-large-cell ratio |
| P_LCC  | `10\S\9/L` → 10⁹/L   | 30–90      | Platelet-large-cell count |
| ALY#   | `10\S\9/L` → 10⁹/L   | *(none)*   | Atypical lymphocytes (abs) |
| ALY%   | `%`                 | *(none)*   | Atypical lymphocytes (%) |
| LIC#   | `10\S\9/L` → 10⁹/L   | *(none)*   | Large immature cells (abs) |
| LIC%   | `%`                 | *(none)*   | Large immature cells (%) |
| PLR    | *(empty)*           | *(none)*   | Platelet-lymphocyte ratio |
| NLR    | *(empty)*           | *(none)*   | Neutrophil-lymphocyte ratio |

### B2 — Seen on H99S CD-mode 83-obs run; units to CONFIRM by capture (inferred in parens)

- **Platelet indices:** `PDW-SD` (fL?), `PLT-I` (impedance PLT, 10⁹/L — likely method-dup of PLT 777-3), `PLT-A` (aperture/optical PLT, 10⁹/L?)
- **RBC morphology:** `Macro#` (10⁹/L?), `Macro%` (%), `Micro#`, `Micro%`
- **Immature platelet / reticulocyte fractions:** `IPF-D` (%?), `IRF-D` (%), `RET#-D` (10⁹/L?)/`RET%-D` (%) [CD-decorated RET → LIS-190 overlap?], `HFR-D`/`MFR-D`/`LFR-D` (% retic maturity fractions), `InR#`
- **Atypical / other cells:** `IME#`/`IME%` (**check vs LIS-190 IMG**), `HFC#`/`HFC%` (high-fluorescence cells), `TNC`/`TNC-D`/`TNC-N` (total nucleated cells), `WBC-D`/`WBC-N` (WBC by diff channel / nuclear channel — method-dup of WBC 6690-2?), `H-NR%`/`L-NR%`
- **Ratios:** `MLR` (monocyte-lymphocyte ratio, unit-less)
- **Flow-cytometry scatter raw channels (NOT reportable analytes → LIS-112):** `LYM-X/Y/Z(+W)`, `MON-X/Y/Z(+W)`, `NEU-X/Y/Z(+W)` (scatterplot coordinates/widths)
- **Histograms (→ LIS-112 attachment):** `*_PNG_BASE64` (WBC/RBC/PLT/BASO/DIFF plots)

## Capture status

- **AC1 partial:** B1 units are real (H60S wire). B2 units + exact CD-mode code strings pending a fresh H99S CD-mode scan (operator-gated; snapshot `analyzer_results` WHERE analyzer_id=5 before Save — unmapped rows also linger per analyzer-7 behavior).
