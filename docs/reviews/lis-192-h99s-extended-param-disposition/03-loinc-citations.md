# LIS-192 — LOINC/UCUM citation verification (factual backbone)

> Web-verified LOINC/UCUM lookup pass. Every asserted LOINC is cited. Negative results ("no standard LOINC") are deliberate and important. Traps flagged inline. A prior LIS-183 pass caught 3 errors (NRBC swap, PCT=EKG code) — this pass caught more (LUC≠LIC, Macro%-ordinal-only, PDW/PDW-SD single-code collision, IME unverified).

| Wire code | Standard LOINC | Property | UCUM | Confidence | Source / trap |
|---|---|---|---|---|---|
| PDW | **32207-3** Platelet distribution width [Entitic volume], Automated | EntVol | fL | High | loinc.org/32207-3 · wire 9.0–17.0 ≈ Sysmex XN fL RI 9.3–17.3 (PMC6517618) ⇒ fL not ratio |
| PDW-SD | **32207-3** (same code — no separate SD split) | EntVol | fL | High | LOINC defines 32207-3 as the SD-analogous form; only 32207-3 (fL) & 51631-0 (ratio) exist ⇒ PDW & PDW-SD collide, needs local disambiguation |
| P-LCR | **48386-7** Platelets Large/Platelets, Automated | NFr | % | High | loinc.org/48386-7 · exact def (large platelets >12fL / total) |
| P-LCC | **none** (no absolute-count analog of 48386-7) | — | (10*9/L) | Med-high (neg) | local/non-LOINC code if wanted |
| PLT-I | **777-3** Platelets, Automated (impedance = default, not method-named) | NCnc | 10*9/L | Med | no explicit "impedance" LOINC; 777-3 collides with generic PLT |
| PLT-A | **97995-5** Platelets, Automated.optical | NCnc | 10*9/L | High | loinc.org/97995-5 · explicit optical method |
| Macro# | **none** | — | — | Med-high (neg) | no count code |
| Macro% | **none numeric**; closest 15198-5 Macrocytes [Presence] (PrThr/Ord) — NOT equivalent | — | — | Med-high (neg) | **TRAP**: 15198-5 is ordinal presence, not a numeric fraction |
| Micro# | **none** | — | — | Med-high (neg) | no count code |
| Micro% | **74761-8** Microcytes/Erythrocytes | NFr | % | High | loinc.org/74761-8 · real numeric % (asymmetry vs macro) |
| IPF-D | **71693-6** Platelets reticulated/Platelets, Automated (also 51633-6) | NFr | % | Med | "reticulated" vs "immature" terminology gap |
| IRF-D | **33516-6** Immature reticulocytes/Reticulocytes.total | NFr | % | High | "-D" = decorated wire form, same analyte |
| HFR-D | **51642-7** Reticulocytes.high light scatter/Retic.total | NFr | % | High | loinc.org/51642-7 |
| MFR-D | **82592-7** Reticulocytes.mid light scatter/Retic.total, Automated | NFr | % | High | loinc.org/82592-7 |
| LFR-D | **82591-9** Reticulocytes.low light scatter/Retic.total, Automated | NFr | % | High | loinc.org/82591-9 |
| RET#-D | **60474-4** (same as plain RET# — already mapped) | NCnc | 10*9/L | High | "-D" wire decoration only ⇒ normalize (LIS-190) |
| RET%-D | **17849-1** (same as plain RET% — already mapped) | NFr | % | High | same as RET#-D |
| InR# | **51636-9** Immature reticulocytes [#/volume] | NCnc | 10*9/L | Med | "InR#" not vendor-verified; inferred; check EDAN spec |
| ALY# | **43743-4** Variant lymphocytes [#/volume], Automated | NCnc | 10*9/L | High | LOINC uses "variant" not "atypical" — same analyte |
| ALY% | **42250-1** Variant lymphocytes/Leukocytes, Automated | NFr | % | High | loinc.org/42250-1 |
| LIC# | **none** | — | — | Med-high (neg) | **TRAP**: 17789-9 LUC ≠ LIC (distinct Coulter peroxidase-neg concept) |
| LIC% | **none** | — | — | Med-high (neg) | same LUC trap |
| IME# | **unresolved** — likely = IMG# **53115-2** (already mapped) | NCnc | 10*9/L | Low-med | **DO NOT GUESS** — one source claimed "immature eosinophil"; conflicts w/ LIS-190 IMG. Verify vs EDAN spec |
| IME% | **unresolved** — likely = IMG% **38518-7** (already mapped) | NFr | % | Low-med | same caveat |
| HFC# | **none** (analogous to Sysmex HFLC, itself uncoded) | — | — | Med-high (neg) | — |
| HFC% | **none** | — | — | Med-high (neg) | — |
| TNC | **50774-9** Nucleated cells [#/volume] in Blood | NCnc | 10*9/L | High | use blood code, NOT body-fluid codes |
| TNC-D / TNC-N | **50774-9** (same; -D/-N = channel decoration) | NCnc | 10*9/L | Med | no channel-specific LOINC |
| WBC-D / WBC-N | **6690-2** (same as reported WBC — method-dup) | NCnc | 10*9/L | Med | no channel-qualified WBC LOINC |
| H-NR% / L-NR% | **none**; definition unverified | — | — | Low | pull EDAN service manual |
| NLR / MLR / PLR | **none** (no LOINC for computed ratios) | — | {ratio}/1 | Med-high (neg) | universally computed downstream in EHR/LIS |
| LYM/MON/NEU-X/Y/Z(+W) | **none** (raw scatter coords) | — | — | High (neg) | not analytes |
| *_PNG_BASE64 | n/a (image) | — | — | — | attachment |

## Traps (must not be violated in the seed)
1. **LUC (17789-9) ≠ LIC** — do not map LIC to it.
2. **Macro% has only an ordinal presence code (15198-5)** — not a numeric fraction; do not map as %.
3. **PDW & PDW-SD both resolve to 32207-3** — cannot both own it 1:1; map PDW, disambiguate/drop PDW-SD locally.
4. **IME unverified** — likely IMG but one source says "immature eosinophil"; verify vs EDAN spec before ANY mapping/normalization.
5. **PLT-I → 777-3 collides with generic PLT** — method-dup.
6. **NLR/MLR/PLR have no LOINC** — derive downstream, don't invent a code.
