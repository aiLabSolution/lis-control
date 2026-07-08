# LIS-192 — H99S extended/CD-mode params: disposition matrix (for owner sign-off)

**Owner:** Pinote (test-catalog owner, DEC-01). **Prepared:** 2026-07-08.
**Inputs:** real wire units (`00-wire-inventory.md`), clinical/hematology-informatics reasoning (`02-…`), web-verified LOINC/UCUM with citations (`03-…`), **and EDAN H99S manual verification (`05-manual-verification.md`) — authoritative, overrides inference.**
**Scope:** params the H99S emits that have **no current OE test** (the "genuinely-new" bucket). The 28 core CBC+diff analytes are already mapped (LIS-183). CD-mode *decorated* codes of already-mapped analytes belong to **LIS-190**, not here.

> **⛑ Manual-verification corrections applied (see `05`):** (1) **IME ≠ IMG** — IME = Immature *Eosinophil* (research), IMG = Immature *Granulocyte* (reportable) → **IME drops, is NOT normalized to IMG** (corrects ③; flagged on LIS-190). (2) Map **base IRF/IPF**, not the `-D` research variants. (3) **InR# = Infected RBC Count** (not immature retic) → LOINC 51636-9 was wrong. (4) **ALY = research-only** → don't map to variant-lymph LOINCs. (5) **PDW RI = 10.0–17.4 fL** (manual). (6) **OBX-9==1 = Research** is the authoritative do-not-map filter. (7) Bucket ⑥ widens: also **PLT-O** (optical), **WBC-O**.

## Recommendation at a glance — 8 buckets

| Bucket | Params | Action |
|---|---|---|
| **① MAP NOW** | **PDW** (32207-3, fL); *optional:* **P-LCR** (48386-7, %) | New OE test + LOINC + `analyzer_test_map`, mirroring LIS-183 `052` |
| **② MAP after CD capture** | **IRF** (33516-6), **IPF** (71693-6) *(base codes — manual-confirmed reportable, RI 2.7–13.8% / 1.2–8.9%)* | Map the **base** codes (OBX-9==0); the `-D` forms are research DIFF variants → ③/drop. Confirm exact wire code string via a CD capture first |
| **③ NORMALIZE (→ LIS-190)** | **RET#-D/RET%-D** (=60474-4/17849-1) *(same measurand, DIFF-channel variant)* | Same measurand as already-mapped codes → bridge code-norm, **never a 2nd mapping**. **IME removed — it is NOT IMG (see ⑥/manual).** |
| **④ LOCAL-CODE (owner opt-in)** | **InR#/InR‰** *(owner-approved 2026-07-08 — Infected RBC, malaria)*, **Micro%** (74761-8*), **HFR/MFR/LFR-D** (51642-7/82592-7/82591-9), **P-LCC** (RI 39–101), **PDW-SD**, **LIC#/%**, **HFC#/%**, **Macro#/%**, **Micro#** | Reportable-ish but niche/redundant/no-clean-LOINC → only if the lab wants them |
| **⑤ DERIVE DOWNSTREAM** | **NLR, MLR, PLR** *(manual: research-only)* | Compute in LIS from mapped components; **do not ingest** the analyzer value (divergence risk); no LOINC exists |
| **⑥ DROP (method-dup / research / internal)** | **PLT-I, PLT-A, PLT-O, WBC-D, WBC-N, WBC-O, TNC/TNC-D/TNC-N**, scatter **LYM/MON/NEU-X/Y/Z(+W)**, **IME#/IME%** (research immature-eosinophil), **ALY#/%** (research atypical-lymph), **HFC#/%**, **H-NR%/L-NR%** | Double-counts an already-reported measurand, is flagged Research (OBX-9==1), or is raw engineering data → never surface |
| **⑦ ATTACHMENT (→ LIS-112)** | **\*_PNG_BASE64** histograms/scattergrams | Ride along as report images, not result fields |
| **⑧ DEFER (open)** | **IRF/IPF base codes** (reportable per manual but absent on the CD wire — only `-D` research forms seen) | Need a non-CD capture / EDAN spec to confirm the reportable code before mapping (bucket ②) |

## Full per-param table

| Param | Unit (captured/inferred) | Std LOINC (cited) | Clinical status | Method-dup? | **Disposition** | Why |
|---|---|---|---|---|---|---|
| **PDW** | fL (wire unit-less; manual RI **10.0–17.4 fL**) | **32207-3** | Reportable platelet index | No | **① MAP (fL)** | Distinct measurand; **manual states unit = fL directly** (32207-3). Closes LIS-183 item-3 PDW. |
| **P-LCR** | % | **48386-7** | Reportable, niche | No | **① MAP (opt)** | Clean LOINC + captured %; map if lab wants platelet-index on menu |
| **IRF** (base) | % (RI 2.7–13.8) | **33516-6** | **Reportable (manual)** | No | **② MAP after CD capture** | Map the base code; `-D` form is research → drop/normalize |
| **IPF** (base) | % (RI 1.2–8.9) | **71693-6** | **Reportable (manual)** | No | **② MAP after CD capture** | Map the base code; `-D` form is research → drop/normalize |
| **IRF-D / IPF-D** | % | (=base) | Research DIFF variant (OBX-9==1) | vs base | **③/DROP** | Research variant of the base IRF/IPF — do not map as its own result |
| **RET#-D** | 10⁹/L | 60474-4 (=plain RET#) | Reportable (already mapped) | **HIGH** | **③ NORMALIZE (LIS-190)** | `-D` = wire decoration of mapped RET# |
| **RET%-D** | % | 17849-1 (=plain RET%) | " | **HIGH** | **③ NORMALIZE (LIS-190)** | same |
| **IME#** | 10⁹/L | **≠ IMG** (no map) | **Immature *Eosinophil* — research (manual)** | Distinct from IMG | **⑥ DROP** | **Manual-refuted: IME ≠ IMG.** IMG=immature *granulocyte* (mapped); IME=immature *eosinophil* (research). Normalizing would merge populations → data-integrity error. Flag LIS-190 |
| **IME%** | % | **≠ IMG** (no map) | Immature Eosinophil — research | Distinct from IMG | **⑥ DROP** | same — do NOT normalize to IMG% 38518-7 |
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
| **InR# / InR‰** | 10⁹/L / ‰ | **none** (~~51636-9~~ was wrong) | **Infected RBC count/permillage (manual)** — malaria/parasite | n/a | **④ LOCAL-CODE (owner-approved)** | **Manual: InR = Infected RBC, NOT immature retic** (51636-9 refuted). Owner (2026-07-08): surface via a local/non-LOINC code (lab does malaria work). Separate follow-up seed — not part of the PDW landing |
| **H-NR% / L-NR%** | % | **none** | **High/Low FSC NRBC % (manual) — research** | n/a | **⑥ DROP** | Gating/region ratio, research |
| **ALY#** | 10⁹/L | ~~43743-4~~ (don't map) | **Atypical lymph — research-only (manual)** | Overlaps LYM | **⑥ DROP** | **Manual: research-only** → keep as flag, do NOT map to diagnostic LOINC |
| **ALY%** | % | ~~42250-1~~ (don't map) | Atypical lymph — research-only | Overlaps LYM | **⑥ DROP** | same |

\* Micro% 74761-8 is a valid LOINC; the "defer" is a clinical-validity-on-EDAN call, not a coding gap.

## The safety headline (please read)

**Do NOT map any bucket-⑥ param.** The 2026-07-08 CD capture proved these equal an already-reported measurand: **PLT-I = PLT-A = PLT (248)**, **WBC-D/WBC-N/TNC = WBC (6.55)**, **RET#-D/RET%-D = mapped RET**. Mapping any would surface the same measurand twice under two codes — a patient-safety/result-integrity hazard. **IME# /IME% are NOT in this class** — they are a *distinct* research analyte (immature eosinophil), so they are dropped as research, **not** normalized to IMG. Drop-or-normalize; never a parallel mapping.

## Proposed minimal first landing (owner: approve / adjust)

1. **Seed PDW** → 32207-3 fL (new `(Whole Blood)` test + `analyzer_test_map` for analyzer 5), mirroring LIS-183 `052`. Closes the LIS-183 item-3 PDW deferral. **Confirmed by manual (unit fL) + capture (value 13.66 in RI 10.0–17.4).** → built as core `055-edan-pdw-loinc-seed.xml`.
2. **Optionally seed P-LCR** → 48386-7 % (capture 35.7 %, in RI 19.3–47.1) if the lab wants it on the menu.
3. ③/⑥ decorated & method-dup codes route to **LIS-190** (incl. the `\T\`-escaped NEU/LYM diff codes seen on the wire); ⑦ histograms → **LIS-112**; ④/⑤/⑧ documented as decided-not-to-map.

## Open questions (updated post manual + capture)
- ✅ **PDW unit = fL** — resolved (manual states directly; capture value in fL RI). No longer open.
- ✅ **IME ≠ IMG** — resolved (manual: immature *eosinophil* vs *granulocyte*). IME drops; do **not** normalize to IMG in LIS-190.
- ✅ **ALY** — resolved (manual: research-only) → don't map; keep as flag.
- ✅ **NLR/MLR/PLR** — research-only (manual) → derive downstream, don't ingest.
- ✅ **InR# / InR‰** — resolved (manual: Infected RBC count/permillage) → owner decides local-code vs drop.
- ⚠ **IRF/IPF (bucket ②) — NEW open item:** the manual says base IRF/IPF are reportable, but the CD capture emitted **only the `-D` research forms** (and `IPF-D` as a **count**, not the % fraction). Need to confirm which code the reportable IRF/IPF value rides on (a non-CD mode? EDAN spec?) before mapping. Do not map the `-D` forms as-is.
