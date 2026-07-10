# LIS-192 — Clinical disposition analysis (hematology-informatics expert pass)

> Expert reasoning pass (Opus; Fable was unavailable — session limit). Recommends & justifies; the owner (Pinote, DEC-01) decides. LOINC candidates other than PDW are deferred to the LOINC-citation pass (`03-loinc-citations.md`). Every "map" LOINC must be verified before catalog sign-off.

## Disposition table

| Param | What it is | Clinical status | Method-dup risk | Recommended disposition | Rationale |
|---|---|---|---|---|---|
| **PDW** | Platelet distribution width (spread of platelet-volume histogram) | Routinely reportable platelet index | Low | **map** (unit fL) — cand. LOINC **32207-3** *(verify)* | Standard platelet index; only blocker was the unit — ref 9.0–17.0 ⇒ fL form |
| **PDW-SD** | SD form of platelet-volume width | RUO / method-variant of PDW | Med (dup of PDW) | **local-code** or defer | No clean standard LOINC; risks two "PDW" columns |
| **P-LCR** | Platelet large-cell ratio (% platelets >~12 fL) | Reportable but niche | Low | **local-code** *(verify LOINC)* | Real ratio; LOINC uncertain |
| **P-LCC** | Platelet large-cell count = PLT×P-LCR | RUO / derived | Med | **local-code** or **drop** | Redundant derived count |
| **PLT-I** | Platelet count by **impedance** channel | Internal method channel | **HIGH** (= reported PLT) | **drop** | Double-counts platelets |
| **PLT-A** | Platelet count by **optical** channel | Internal method channel | **HIGH** (= reported PLT) | **drop** | Analyzer reconciles into one final PLT |
| **Macro#/%** | Macrocytes (large-volume RBCs) | RUO / morphology screen | Low | **defer** → else drop | Screening morphology, not validated |
| **Micro#/%** | Microcytes (small-volume RBCs, "MicroR") | Emerging (Fe-def/thal screen), unvalidated here | Low | **defer** → else local-code | Micro% has more evidence than Macro% |
| **IPF-D** | Immature platelet fraction (reticulated platelets, %) | Clinically useful | Low; `-D` decorated | **defer** (gated: LIS-190 code-norm + LOINC) | Worth reporting; resolve code decoration first |
| **IRF-D** | Immature reticulocyte fraction (HFR+MFR, %) | Clinically useful (marrow response) | Low; `-D` decorated | **defer** (gated: LIS-190 + LOINC) | Mappable, gated on code-norm |
| **HFR-D/MFR-D/LFR-D** | Retic maturity sub-fractions | RUO (IRF is the used composite) | Med (sum to IRF) | **local-code** (if wanted) → else drop | Avoid reporting parts + IRF both |
| **RET#-D/RET%-D** | Reticulocyte count/%, **decorated** code | Reportable; plain RET already mapped | **HIGH** (= mapped RET) | **drop → normalize (LIS-190)** | Same measurand under CD-mode code |
| **InR#** | Ambiguous (likely immature retic abs count) | Unknown | Unknown | **defer** (identify vs spec/capture) | Cannot disposition without confirming measurand |
| **ALY#/%** | Atypical/reactive lymphocytes (flag) | Screening flag, not validated count | Overlaps LYM | **defer** (flag only) → else drop | Smear-review trigger; unsafe as a number |
| **LIC#/%** | Large immature cells (screen) | Screening flag, RUO | Overlaps WBC | **drop** (or defer as flag) | Blast/abnormal-cell screen |
| **IME#/%** | Immature-cell channel — **almost certainly immature granulocytes** | Reportable as IG, but IMG already mapped | **HIGH** (= mapped IMG) | **drop → normalize (LIS-190)**; verify vs spec | CD-mode `IME` vs seeded `IMG` = code mismatch |
| **HFC#/%** | High-fluorescence cells | RUO screening flag | Overlaps WBC | **drop** (or defer as flag) | Abnormal-cell screen |
| **TNC/TNC-D/TNC-N** | Total nucleated cells (=WBC+NRBC) + channel variants | Internal count (niche for fluids/apheresis) | **HIGH** (= WBC+NRBC) | **drop** | Double-counts for whole-blood CBC |
| **WBC-D/WBC-N** | WBC from diff / nucleated channel | Internal method channels | **HIGH** (= reported WBC) | **drop** | Analyzer reconciles into final WBC |
| **H-NR%/L-NR%** | Ambiguous (likely region/gating ratios) | Internal / QC | n/a | **drop** (blocked on ID) | Reads as instrument gating |
| **NLR** | Neutrophil-lymphocyte ratio (NEU#/LYM#) | Widely used inflammatory index | Fully derived | **defer** — compute downstream (else local-code) | Don't ingest a value that can diverge from components |
| **MLR** | Monocyte-lymphocyte ratio | Prognostic (niche) | Fully derived | **defer** — compute downstream | Same divergence risk as NLR |
| **PLR** | Platelet-lymphocyte ratio | Prognostic (niche) | Fully derived | **defer** — compute downstream | Same divergence risk as NLR |
| **LYM/MON/NEU-X/Y/Z(+W)** | Raw scatter-cluster coords + widths | **Not analytes** (engineering data) | n/a | **drop** | No clinical scalar meaning |
| ***_PNG_BASE64** | Base64 histograms/scattergrams | Image, not scalar | n/a | **attachment (→ LIS-112)** | Attach as report image, never a result field |

## Key judgment calls & open questions for the owner

- **PDW = fL (not %/ratio).** Unit-less on the wire, ref **9.0–17.0** ⇒ classic absolute-fL platelet-distribution-width. A CV/ratio form would sit in a different band (~15–20%). Map as fL; confirm the analyzer isn't sending PDW-CV under the same tag. If both PDW & PDW-SD present, only one is the clinician's "distribution width" — pick the primary.
- **IME almost certainly = IMG (immature granulocytes)** → belongs to **LIS-190 code normalization**, not a new mapping. Confirm vs EDAN CD-mode spec (small chance IME is a broader "immature cells" bucket = un-mappable flag).
- **Same-measurand double-counting hazards (top safety priority):** PLT-I/PLT-A vs PLT; WBC-D/WBC-N vs WBC; TNC vs WBC+NRBC; RET#-D/RET%-D vs mapped RET; IME vs mapped IMG. Each would surface the same physical quantity twice under two codes → drop-or-normalize, never a parallel mapping.
- **NLR/MLR/PLR — derive downstream, don't ingest.** Pure ratios of already-reported analytes; ingesting the analyzer's own value can silently disagree with reported components. Compute in LIS, or defer; if ingested as-is use a local code + document analyzer-sourced.
- **Screening flags vs quantitative results:** ALY#/%, LIC#/%, HFC#/% are analyzer screening flags needing smear confirmation → surface as flags only, or drop; do **not** map as first-class numeric analytes.
- **IPF-D / IRF-D are the most clinically valuable "extras"** (immature platelet fraction; immature reticulocyte fraction) → worth the menu, but gated on LIS-190 `-D` normalization + LOINC verify → defer-to-map, not drop.
- **Retic maturity granularity:** HFR/MFR/LFR sum to IRF → report IRF, sub-fractions local-code-only or dropped.
- **Genuinely unidentified — need vendor spec / fresh capture before any disposition:** InR#, H-NR%/L-NR%.

*Caveat: EDAN CD-mode naming isn't fully standardized across firmware; IME=IMG, InR#, H-NR%/L-NR%, and the PDW unit rest on inference → confirm vs vendor spec / annotated wire capture before catalog sign-off.*
