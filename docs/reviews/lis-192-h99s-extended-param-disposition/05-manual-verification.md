# LIS-192 — Manual verification of the disposition matrix (EDAN H99S manuals)

> **Authoritative pass.** The disposition matrix (`04-DISPOSITION-MATRIX.md`) was built from real wire units + web-verified LOINCs + clinical inference. This pass checks it against the **EDAN H90-series manuals**. Where the manual and the inference disagree, **the manual wins** — corrections are folded into `04` and this file records the evidence.

## Sources
- **LIS protocol** — `manuals-and-lis-protocol/EDAN/H99S/H90_Series_LIS_protocol.pdf` v1.0 (2025-09-03), covers H90/H90S/H95/H95S/H96/H96S/H98S/**H99S**. OBX field table at PDF p.31–32.
- **User manual** — `manuals-and-lis-protocol/EDAN/H99S/H90_Series_User_manual.pdf` (214 pp). §2.2 Parameters (abbreviation dictionary) PDF p.38–45; Appendix 3.7 Reference Ranges PDF p.204–205.
- H99S = top model of the H90 Series.

## ✅ Confirmed by manual
- **OBX field map:** OBX-4 = parameter name (analyte code), OBX-6 = Units, OBX-7 = Reference Range. **OBX-3 = suspect-result mark**, not the code. (Matches `00-wire-inventory.md`.)
- **Histograms** → `XXX_PNG_BASE64` in OBX-4, PNG bitmap in OBX-5 → bucket ⑦ attachment (→ LIS-112). Confirmed.
- **PDW unit = fL** — stated directly in the manual, no inference. ⇒ `055` seed → LOINC **32207-3** (fL/EntVol) is **correct**.
- **P-LCR = %** (RI 19.3–47.1). Confirmed reportable.
- **"-D" codes are DIFF-channel variants** of a base measurand (e.g. RET#-D = "Reticulocyte Count-DIFF") ⇒ normalize-to-base (bucket ③) is sound *for genuine same-measurand duplicates*.
- **Bucket ⑥ safety headline holds** and widens: PLT-I = Impedance, **PLT-A = "calculated by AI Algorithm"**, **PLT-O = Optical** (alternate PLT counts); **WBC-D/WBC-N/WBC-O** (alternate WBC); TNC/-D/-N. All double-count a reported measurand → **drop**.
- **OBX-9 = Parameter Type: `0` = Result, `1` = Research.** §2.2 NOTE: *"Research parameters are for research use only, which cannot be used for diagnosis purpose."* ⇒ **authoritative do-not-map filter: never map an OBX-9==1 (Research) parameter to a diagnostic LOINC.**

## ❌ Refuted — the important correction
- **IME ≠ IMG (BLOCKING for LIS-190).** Matrix ③ (and prior memory) assumed IME#/IME% are a CD-mode decorated form of IMG. **Manual: IMG = Immature *Granulocyte*** (reportable, RI 0.01–0.07 ×10⁹/L, already mapped 53115-2/38518-7); **IME = Immature *Eosinophil*** (research-only). **Different measurands.** Normalizing IME→IMG would merge two cell populations = data-integrity error. **IME must NOT be normalized to IMG** — it is a research param → **drop**. → flagged on **LIS-190** (which currently plans this normalization).

## ⚠️ Corrections folded into `04`
- **PDW reference range** = **10.0–17.4 fL** (Appendix 3.7, H99S default). The matrix's "9.0–17.0" was an H60S site-config value. Unit (fL) and LOINC (32207-3) unchanged; only the cited RI is corrected (in `04` and the `055` changeset comment).
- **Map the BASE IRF/IPF, not the `-D` forms.** Manual: **IRF** (RI 2.7–13.8%) and **IPF** (RI 1.2–8.9%) are **reportable Result params** with RIs; the `-D` forms are **research-only** DIFF variants. So: bucket ② maps base **IRF → 33516-6** and **IPF → 71693-6**; the `-D` variants normalize-to-base (③) or drop as research. (`04` ② previously said IRF-D/IPF-D — corrected.)

## Resolved — manual defines the bucket-⑧ "defer" items (§2.2)
- **InR# = Infected Red Blood Cell Count**; **InR‰ = Infected RBC Permillage (‰, not %).** ⇒ the earlier candidate LOINC **51636-9 (immature reticulocytes) is WRONG** — InR is a malaria/parasite param, not a reticulocyte. Research/specialized → do not map to 51636-9; drop or local-code per owner.
- **ALY#/ALY% = Atypical Lymphocyte — research-only** ⇒ keep as flags, do **not** map to the variant-lymphocyte LOINCs (43743-4/42250-1). (Confirms the clinical pass's caution; overrides "LOINC exists → mappable".)
- **H-NR%/L-NR% = High/Low Forward-Scattered-Light NRBC %** (`#` = WNB-channel-only) → research/gating → drop.
- **NLR/PLR/MLR = research-only** → derive-downstream defensible; do not ingest instrument values (bucket ⑤ holds).

## Reference ranges captured (Appendix 3.7) — for eventual UCUM/RI work (LIS-191)
PDW **10.0–17.4 fL** · P-LCR **19.3–47.1 %** · P-LCC **39–101 ×10⁹/L** · IPF **1.2–8.9 %** · IRF **2.7–13.8 %** · IMG# **0.01–0.07 ×10⁹/L** · IMG% **0.0–0.8 %** · MPV **9.3–12.7 fL**.

## Not verifiable from the manual (external)
- **LOINC code correctness** — external terminology (loinc.org). The manual **corroborates the Sysmex-XN cross-reference method** (Appendix 3.7 refs 1,2,4 = Sysmex XN; ref 3 = Mindray BC-6800Plus for platelet params), which is exactly the analog-mapping basis the LOINC pass used → methodologically sound, but each code still rests on the `03-loinc-citations.md` web verification.
- **OBX-6 HL7 escaping** (`\S\`=`^`): the protocol labels OBX-6 "Units"; the escaping is undocumented there → our decode remains a (consistent) inference.

## Net effect on the plan
- **PDW → 32207-3 (fL): CONFIRMED. `055` seed is good to land** (ref-range citation corrected).
- **Newly manual-confirmed reportable (RI-backed) map candidates:** IRF → 33516-6, IPF → 71693-6, P-LCR → 48386-7 (all base codes, OBX-9==0). Recommend adding to the seed **after** a fresh H99S CD capture confirms the exact wire code strings + OBX-9 Result/Research flag per code.
- **IME → drop (research eosinophil), NOT normalize** → correct LIS-190 scope.
- **ALY, InR#, H-NR%/L-NR%, NLR/MLR/PLR → research-only** → do not map; the OBX-9==1 filter formalizes this.
