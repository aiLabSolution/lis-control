# ADR-0017 — Fork openelisglobal-plugins to persist plugin build fixes

- **Status:** Accepted
- **Date:** 2026-07-02
- **Deciders:** Marloe Uy (aiLabSolution)
- **Issue:** LIS-106 (follow-up to LIS-94)

## Context

The SD1 bench needs OpenELIS's GenericHL7 analyzer plugin, which lives in the
`plugins` submodule of core/openelis — until now the **unforked**
`DIGI-UW/openelisglobal-plugins`. The plugin does not compile from the pinned
source: its Java imports `org.apache.commons.lang3.StringUtils`, but the plugin
pom never declares `commons-lang3` (`cannot find symbol: StringUtils`).

LIS-94 ([lis-control#63](https://github.com/aiLabSolution/lis-control/pull/63))
shipped a reproducible workaround: `deploy/ci/install-generichl7-plugin.sh`
applied a carried patch (`deploy/ci/patches/generichl7-commons-lang3.patch`) at
build time and reverted it after. LIS-94's AC #1 requires the fix to be
persisted in the plugin/component repo, which is impossible without controlling
that repo.

ADR-0001's topology (see `CONTEXT-MAP.md`) already anticipated an aiLabSolution
fork of `openelisglobal-plugins` as the plugins component source ("TBD"). The
technical owner ruled on 2026-07-02 (LIS-106): create the fork now, over
vendoring GenericHL7 locally or keeping the carried patch permanently.

## Decision

Fork `DIGI-UW/openelisglobal-plugins` → **`aiLabSolution/openelisglobal-plugins`**.

- The fork was cut at DIGI-UW `develop` head `8faf0056` — exactly core's
  previous submodule pin, so the re-point introduces **zero upstream drift**
  beyond our fixes.
- Plugin fixes land as reviewed PRs on the fork's `develop`
  (first: [openelisglobal-plugins#1](https://github.com/aiLabSolution/openelisglobal-plugins/pull/1),
  the GenericHL7 `commons-lang3` dependency at `provided`/`3.18.0`, matching the
  host webapp).
- Core's nested `plugins` submodule re-points to the fork (`.gitmodules` URL +
  pin bump, [OpenELIS-Global-2#16](https://github.com/aiLabSolution/OpenELIS-Global-2/pull/16)).
- The carried patch and its apply/revert machinery are removed from
  `install-generichl7-plugin.sh`; the script now builds from pinned source and
  runs `git submodule sync plugins` first so pre-fork clones pick up the new URL.
- The fork stays **public** (MPL-2.0). Proprietary analyzer drivers do **not**
  go into this fork — they remain in aiLabSolution-private components per the
  proprietary-drivers ruling; the fork carries only build/compat fixes to the
  upstream plugin set. Upstreaming individual fixes to DIGI-UW is permitted but
  not required.

## Consequences

- Plugin changes are now **three-level**: fork PR → core submodule pin bump PR →
  umbrella core pin bump PR. This extends the two-level submodule flow in the
  slice-loop protocol by one hop, but only for `plugins/` changes.
- Reproducibility: the GenericHL7 jar builds from pinned source with no carried
  patch, restoring the "pin fully describes the build input" property for the
  IQ/OQ story (ADR-0001).
- Existing clones of core need a one-time `git submodule sync plugins` (the
  install script does this automatically).
- Tracking upstream: DIGI-UW `develop` moves on; periodic fork refreshes are a
  deliberate rebase/merge + pin-bump chore, not automatic. The fork's delta
  should stay minimal to keep refreshes cheap.
- `CONTEXT-MAP.md`'s Plugins context row now names the fork; the planned
  top-level `plugins/` umbrella mount remains future work (today the fork is
  reached as core's nested submodule).
