# Third-party reuse holds

> **Relocated to the umbrella (2026-06-29).** Originally authored on `core/openelis`
> `develop` (S0.1 / LIS-71) but never merged to core `main`; the umbrella pins
> `core/openelis` on `main`, so an auditor reproducing the pinned IQ baseline (ADR-0001 /
> REQ-VAL-02) could not find this HOLD-001 clearance record. Relocated here so it travels
> with the reproducible umbrella snapshot. Bare `LICENSE.md` below refers to the
> **openelis-analyzer-bridge** repo's own license file (an external repo), not this tree.

Components blocked from **direct reuse** pending a licensing or compliance resolution.
A hold means: do not copy, vendor, embed, statically/dynamically link, or derive from the
component until the hold is cleared and this file is updated. Cleared holds are kept for the
audit trail.

## HOLD-001 — openelis-analyzer-bridge — ✅ CLEARED (reuse permitted under MPL-2.0)

| Field | Value |
|-------|-------|
| Component | openelis-analyzer-bridge |
| In-use repo | https://github.com/aiLabSolution/openelis-analyzer-bridge (private mirror) |
| Upstream | https://github.com/DIGI-UW/openelis-analyzer-bridge |
| License | **MPL-2.0** with custom (non-grant) warranty/liability clauses — GitHub `NOASSERTION` |
| Raised | 2026-06-22 (Stage 0 / S0.1) |
| Cleared | 2026-06-22 |
| Status | **CLEARED — direct reuse permitted; bound by the modified MPL-2.0** |
| Tracking | Plane **LIS-71** (Done) |

**The mirror is the same code.** `aiLabSolution/openelis-analyzer-bridge` is a private export of
DIGI-UW's repo — `develop @ 53b6acbf`, **byte-identical `LICENSE.md`**, commit history authored
entirely by upstream OpenELIS contributors. It is **upstream code, not LabSolution IP**;
relocating it into our org did not by itself change any rights.

**Why the hold is cleared.** Reviewing the actual `LICENSE.md`, the **§2 grant is intact, standard
MPL-2.0** — "a world-wide, royalty-free, non-exclusive license … to use, reproduce, make available,
modify, display, perform, distribute" plus the §2.1(b) patent grant. The customisations are confined
to the warranty/liability sections (added healthcare-specific disclaimers), which is why GitHub
reports `NOASSERTION`; they do **not** restrict the grant of use. **Direct reuse is therefore
permitted** under those terms.

**What we accept by using it**
- **MPL-2.0 file-level copyleft.** Modify the bridge's MPL files and distribute ⇒ make the source of
  those files available under MPL-2.0 and keep license notices. (Private use triggers nothing — see
  `MPL-2.0-INVENTORY.md`.)
- **Modified warranty/liability.** Contributors expressly disclaim fitness for clinical-care
  standards, privacy-law compliance, and provider judgement. Our ISO 15189 / NPC validation
  (Stage 5) is what establishes fitness regardless.
- Track it as a **consumed third-party dependency**, not original work.

**Optional de-risk (not blocking).** Upstream's README still says "License: TBD," contradicting
`LICENSE.md`, and file headers are patchy. A one-line confirmation from DIGI-UW that `LICENSE.md`
governs would erase the last ambiguity — low value given the §2 grant is explicit; pursue only if a
compliance reviewer asks.
