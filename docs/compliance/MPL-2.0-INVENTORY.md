# MPL-2.0 inventory & obligations

> **Relocated to the umbrella (2026-06-29).** Originally authored on `core/openelis`
> `develop` (S0.1 / LIS-3) but never merged to core `main`; the umbrella pins
> `core/openelis` on `main`, so an auditor reproducing the pinned IQ baseline (ADR-0001 /
> REQ-VAL-02) could not find this file. Relocated here so the **MPL-2.0 inventory travels
> with the reproducible umbrella snapshot**. It describes the **`core/openelis` fork** at
> the pin; `core/openelis/LICENSE.md` / `core/openelis/UPSTREAM.md` are the core repo root.

Tracks every Mozilla Public License 2.0 component in (or planned for) this system and the
obligations they carry. MPL-2.0 is **file-level copyleft**: obligations attach to the
individual MPL-licensed files, not to the whole repository.

## Obligations (summary — see `core/openelis/LICENSE.md` for authoritative text)

- **§3.1 Distribute source of MPL files.** When you *distribute* the software (source or
  binaries) to a third party, you must make the **source of the MPL-covered files** (with
  your modifications) available to recipients under MPL-2.0.
- **§3.2 / §3.3 Larger Work.** MPL files may be combined with proprietary/other-licensed
  code in a "Larger Work"; only the MPL files stay MPL. Our net-new code may carry its own
  license, provided MPL files keep their notices and remain available as source.
- **Notices.** Preserve existing MPL headers and `core/openelis/LICENSE.md`; do not strip
  attribution.

> **Distribution trigger.** Keeping this repository private is fully MPL-compliant — no
> obligation activates until we distribute binaries/source to a third party (e.g. deploying
> to a customer site). At that point we must offer the MPL source to that recipient. Track
> each external deployment as a distribution event.

## Component inventory

| Component | Upstream | License | Status | Notes |
|-----------|----------|---------|--------|-------|
| OpenELIS-Global-2 (core) | DIGI-UW/OpenELIS-Global-2 | **MPL-2.0** | In repo (pinned 3.2.1.10) | The forked core; see `core/openelis/UPSTREAM.md`. |
| openelisglobal-plugins | DIGI-UW/openelisglobal-plugins | **MPL-2.0** | Planned (driver home) | Per-analyzer plugin pattern. |
| Open Integration Engine | OpenIntegrationEngine/engine | **MPL-2.0** | Optional | HL7/ASTM channel engine (Mirth 4.5.2 fork). |
| openelis-analyzer-bridge | aiLabSolution/openelis-analyzer-bridge (private mirror of DIGI-UW) | **MPL-2.0** — modified warranty clauses (`NOASSERTION`) | **In use** | §2 grant is intact MPL-2.0 → reuse permitted; bound by file-level copyleft + the custom warranty terms. Upstream code, not LabSolution IP. See `docs/compliance/THIRD-PARTY-HOLDS.md` HOLD-001 (cleared). |
| LabSolution analyzer bridges / site code | aiLabSolution (this org) | TBD (our choice) | Net-new | Keep separable from MPL files to preserve license flexibility. |

Update this table whenever a component is added, upgraded, or its license status changes.
