# LIS-192 — H99S extended/CD-mode params: disposition matrix (for owner sign-off)

**Owner:** Pinote (test-catalog owner, DEC-01). **Prepared:** 2026-07-08.
**Inputs:** real wire units (`00-wire-inventory.md`), clinical/hematology-informatics reasoning (`02-…`), web-verified LOINC/UCUM with citations (`03-…`). Every "map" LOINC is cited; nothing guessed.
**Scope:** params the H99S emits that have **no current OE test** (the "genuinely-new" bucket). The 28 core CBC+diff analytes are already mapped (LIS-183). CD-mode *decorated* codes of already-mapped analytes belong to **LIS-190**, not here.

## Recommendation at a glance — 8 buckets

| Bucket | Params | Action |
|---|---|---|
| **① MAP NOW** | **PDW** (32207-3, fL); *optional:* **P-LCR** (48386-7, %) | New OE test + LOINC + `analyzer_test_map`, mirroring LIS-183 `052` |
| **② MAP after LIS-190** | **IRF-D** (33516-6), **IPF-D** (71693-6) | Clinically valuable; blocked on `-D` code normalization (LIS-190) + retic ordering |
| **③ NORMALIZE (→ LIS-190)** | **RET#-D/RET%-D** (=60474-4/17849-1); **IME#/IME%** (likely =IMG 53115-2/38518-7) | Same measurand as already-mapped codes → bridge code-norm, **never a 2nd mapping**. IME **must be spec-verified** first |
| **④ LOCAL-CODE (owner opt-in)** | **Micro%** (74761-8*), **HFR/MFR/LFR-D** (51642-7/82592-7/82591-9), **P-LCC**, **PDW-SD**, **LIC#/%**, **HFC#/%**, **Macro#/%**, **Micro#** | Reportable-ish but niche/redundant/no-clean-LOINC → only if the lab wants them |
| **⑤ DERIVE DOWNSTREAM** | **NLR, MLR, PLR** | Compute in LIS from mapped components; **do not ingest** the analyzer value (divergence risk); no LOINC exists |
| **⑥ DROP (method-dup / internal)** | **PLT-I, PLT-A, WBC-D, WBC-N, TNC/TNC-D/TNC-N**, scatter **LYM/MON/NEU-X/Y/Z(+W)** | Double-counts an already-reported measurand or is raw engineering data → never surface |
| **⑦ ATTACHMENT (→ LIS-112)** | **\*_PNG_BASE64** histograms/scattergrams | Ride along as report images, not result fields |
| **⑧ DEFER (need vendor spec)** | **InR#** (cand. 51636-9), **H-NR%/L-NR%**, **ALY#/%** | Measurand/clinical-use unconfirmed — hold until EDAN spec / capture clarifies |

## Full per-param table

| Param | Unit (captured/inferred) | Std LOINC (cited) | Clinical status | Method-dup? | **Disposition** | Why |
|---|---|---|---|---|---|---|
| **PDW** | fL (wire unit-less, ref 9–17) | **32207-3** | Reportable platelet index | No | **① MAP (fL)** | Distinct measurand, verified LOINC, unit resolved (9–17 ⇒ fL). Closes LIS-183 item-3 PDW. |
| **P-LCR** | % | **48386-7** | Reportable, niche | No | **① MAP (opt)** | Clean LOINC + captured %; map if lab wants platelet-index on menu |
| **IRF-D** | % | **33516-6** | Reportable (marrow response) | No | **② MAP after LIS-190** | Valuable; gated on `-D` norm + retic order |
| **IPF-D** | % | **71693-6** (med conf) | Reportable (thrombopoiesis) | No | **② MAP after LIS-190** | Valuable; "reticulated"≈"immature" terminology gap → verify |
| **RET#-D** | 10⁹/L | 60474-4 (=plain RET#) | Reportable (already mapped) | **HIGH** | **③ NORMALIZE (LIS-190)** | `-D` = wire decoration of mapped RET# |
| **RET%-D** | % | 17849-1 (=plain RET%) | " | **HIGH** | **③ NORMALIZE (LIS-190)** | same |
| **IME#** | 10⁹/L | likely 53115-2 (IMG#) | likely = immature granulocytes | **HIGH** | **③ NORMALIZE (LIS-190) — VERIFY SPEC** | one source says "immature eosinophil" (conflict) → confirm before norm |
| **IME%** | % | likely 38518-7 (IMG%) | " | **HIGH** | **③ NORMALIZE (LIS-190) — VERIFY SPEC** | same |
| **Micro%** | % | **74761-8** | Emerging (Fe-def/thal), unvalidated on EDAN | No | **④ LOCAL/defer** | LOINC exists but EDAN clinical validity unproven |
| **HFR-D** | % | **51642-7** | RUO (retic maturity) | Sum→IRF | **④ LOCAL (opt)** | Redundant with IRF; granularity only if wanted |
| **MFR-D** | % | **82592-7** | RUO | Sum→IRF | **④ LOCAL (opt)** | same |
| **LFR-D** | % | **82591-9** | RUO | Sum→IRF | **④ LOCAL (opt)** | same |
| **P-LCC** | 10⁹/L | **none** (LUC≠) | RUO/derived (=PLT×P-LCR) | Med | **④ LOCAL or DROP** | No LOINC; redundant derived count |
| **PDW-SD** | fL | **32207-3** (collides w/ PDW) | RUO/method-variant | Med | **④ LOCAL or DROP** | Can't co-own 32207-3; pick PDW as primary |
| **LIC#/%** | 10⁹/L / % | **none** (**LUC 17789-9 ≠ LIC**) | Screening flag | Overlaps WBC | **④ LOCAL(flag) or DROP** | No LOINC; smear-confirmation flag |
| **HFC#/%** | 10⁹/L / % | **none** | RUO screening flag | Overlaps WBC | **④ LOCAL(flag) or DROP** | No LOINC (like Sysmex HFLC) |
| **Macro#/%** | 10⁹/L / % | **none** (15198-5 = ordinal, not numeric) | RUO morphology | No | **④ LOCAL or DROP** | No numeric LOINC; screen only |
| **Micro#** | 10⁹/L | **none** | see Micro% | No | **④ LOCAL or DROP** | No count LOINC |
| **NLR** | ratio | **none** | Widely-used inflammatory index | Derived | **⑤ DERIVE DOWNSTREAM** | Compute from NEU#/LYM#; ingesting risks divergence |
| **MLR** | ratio | **none** | Prognostic (niche) | Derived | **⑤ DERIVE DOWNSTREAM** | Compute from MON#/LYM# |
| **PLR** | ratio | **none** | Prognostic (niche) | Derived | **⑤ DERIVE DOWNSTREAM** | Compute from PLT/LYM# |
| **PLT-I** | 10⁹/L | 777-3 (=PLT) | Internal impedance channel | **HIGH** | **⑥ DROP** | Double-counts reported PLT |
| **PLT-A** | 10⁹/L | 97995-5 (optical) | Internal optical channel | **HIGH** | **⑥ DROP** | Analyzer reconciles into one final PLT; opt-in reflex only |
| **WBC-D / WBC-N** | 10⁹/L | 6690-2 (=WBC) | Internal channels | **HIGH** | **⑥ DROP** | Double-counts reported WBC |
| **TNC / TNC-D / TNC-N** | 10⁹/L | 50774-9 | =WBC+NRBC (internal) | **HIGH** | **⑥ DROP** | Double-counts in whole-blood CBC |
| **LYM/MON/NEU-X/Y/Z(+W)** | — | **none** | Not analytes (scatter coords) | n/a | **⑥ DROP** | Raw engineering data |
| **\*_PNG_BASE64** | — | n/a (image) | Plot image | n/a | **⑦ ATTACHMENT (LIS-112)** | Report image, not a result field |
| **InR#** | 10⁹/L? | 51636-9 (unverified) | Unknown (immature retic?) | Unknown | **⑧ DEFER (spec)** | Measurand unconfirmed |
| **H-NR% / L-NR%** | %? | **none** | Internal/gating (unconfirmed) | n/a | **⑧ DEFER (spec)** | No def, no LOINC |
| **ALY#** | 10⁹/L | **43743-4** (variant lymphs) | Screening flag (LOINC exists) | Overlaps LYM | **⑧ DEFER (owner)** | LOINC exists BUT clinically needs smear confirm → owner decides map-vs-flag |
| **ALY%** | % | **42250-1** | " | Overlaps LYM | **⑧ DEFER (owner)** | same |

\* Micro% 74761-8 is a valid LOINC; the "defer" is a clinical-validity-on-EDAN call, not a coding gap.

## The safety headline (please read)

**Do NOT map any bucket-⑥ param.** PLT-I/PLT-A, WBC-D/WBC-N, TNC, and the RET-D/IME decorated codes all report the **same physical quantity that is already reported under another code**. Mapping them would surface the same measurand twice under two LOINCs — a genuine patient-safety/result-integrity hazard. These are drop-or-normalize, never a parallel mapping.

## Proposed minimal first landing (owner: approve / adjust)

1. **Seed PDW** → 32207-3 fL (new `(Whole Blood)` test + `analyzer_test_map` for analyzer 5), mirroring LIS-183 `052`. Closes the LIS-183 item-3 PDW deferral.
2. **Optionally seed P-LCR** → 48386-7 % in the same changeset if the lab wants it on the menu.
3. Everything in ②/③ routes to **LIS-190**; ⑦ routes to **LIS-112**; ④/⑤/⑧ documented as decided-not-to-map with the rationale above.

## Open questions needing you (or a fresh capture)
- **PDW unit** = fL — confirm against the EDAN manual (wire is unit-less; evidence strongly favors fL).
- **IME = IMG?** — must be spec-verified before LIS-190 normalizes it (one source dissents).
- **ALY#/%** — map to variant-lymphocyte LOINCs, or keep as smear-review flags? (clinical policy call)
- **NLR/MLR/PLR** — derive downstream (recommended) or not report at all?
- **InR#, H-NR%/L-NR%** — need the EDAN CD-mode parameter manual to identify the measurand.
