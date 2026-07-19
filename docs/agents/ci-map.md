# CI map and merge-evidence modes

This is the operational map for hosted GitHub Actions and `scripts/local_ci.py`.
It is the authority for deciding which checks are expected on an exact pull-request
head. The registry itself remains authoritative for local-check selection.

Snapshot date: **2026-07-19**. Source issues: LIS-280 through LIS-286. Source decisions:
[ADR-0001](../adr/0001-repository-topology-submodule-umbrella.md),
[ADR-0020](../adr/0020-deploy-kit-clean-box-smoke-gate.md), and
[ADR-0021](../adr/0021-pinned-source-images-are-authoritative.md).

## Expected checks: the mode-aware definition

Read `local_ci.json` from the exact checkout under review before deciding what is
expected.

- In **hosted mode**, every hosted workflow/check selected by the repository, event,
  target branch, and path filters is expected on the exact PR head. A selected workflow
  that never ran is red, as are pending, failed, errored, cancelled, timed-out, or stale
  results. `local-ci/summary` is not required.
- In **local mode**, every registry repository with `gate_required: true` requires a
  successful `local-ci/summary` commit status on the exact PR head. It must come from the
  engine's normal path selection; partial, subset, superset, and exact-commit evidence do
  not mint the summary and cannot satisfy the gate. Any hosted workflow intentionally
  retained and selected for that PR is expected as well. An absent local summary is an
  **unrun expected check**, therefore red.
- A workflow documented below as dormant-by-design is not expected merely because its
  YAML exists. Conversely, an empty check rollup is never proof for a repository/mode
  that has an expected check.
- CI evidence is repository-local. An umbrella success does not prove a component PR,
  and component success does not prove the pinned umbrella composition.

The merge-gate hook fails open only for its additive local-summary test when the registry
is missing or invalid. That safety behavior prevents a broken control checkout from
bricking every shell; it is not permission for an operator or reviewer to ignore an
unreadable registry.

## Current estate

| Repository | Default branch | Visibility | Protection / expected-check source | Local gate status |
|---|---|---|---|---|
| `aiLabSolution/lis-control` | `main` | **Public temporarily** | Active `main` ruleset; hook + this map still define expected checks | `gate_required`; 3 landed fast checks; 3 stack checks pending PR #168 |
| `aiLabSolution/OpenELIS-Global-2` | `main` | **Public temporarily** | No branch protection returned by the API; hook + this map | `gate_required`; i18n landed; backend/frontend pending PR #164 |
| `aiLabSolution/openelis-analyzer-bridge` | `develop` | **Public temporarily** | No branch protection returned by the API; `Run Tests` is live | `gate_required`; `bridge-tests` landed |
| `aiLabSolution/lis-deploy-kit` | `main` | Private | Current plan does not expose private-repo branch protection; hook + review | `gate_required`; `kit-lint` landed |

Public visibility currently avoids the exhausted private-repository Actions allowance and
makes repository rulesets available. It does **not** itself configure protection: at this
snapshot only the umbrella reports an active ruleset. Before relying on protection, query
both branch protection and repository rulesets rather than inferring from visibility.

Never register a self-hosted Actions runner while any repository is public. An untrusted
fork pull request must never gain a route to the LIS host, its network, credentials, caches,
or sibling worktrees. Public repositories also make committed content world-readable:
real analyzer captures and raw messages can contain the PHI assets identified in
[`docs/compliance/threat-model.md` A1/A2](../compliance/threat-model.md#assets).
Use synthetic/de-identified fixtures only; follow the production raw-archive boundary in
[ADR-0022](../adr/0022-production-inbound-raw-archive.md).

## Hosted merge workflows and local equivalents

Times are observed execution times, not timeout budgets. Hosted Stage-0/Stage-4 values are
from PR #167's successful exact head `75baf574...`; local fast values are the live
LIS-282 status evidence. A dash means the workflow is not the matching local proof.

### Umbrella (`lis-control`)

| Hosted workflow / job | Hosted trigger paths | Observed hosted | Local check | Class | Local trigger paths | Observed local | Status |
|---|---|---:|---|---|---|---:|---|
| `scripts-tests.yml` / `python -m unittest (scripts/)` | `scripts/**`, workflow | 14s (PR #163) | `scripts-tests` | fast | hosted paths plus `.githooks/**`, `local_ci.json` | 5.8s | Landed |
| `edge-sim.yml` / harness pytest | `edge/sim/**`, workflow | 10s | `edge-sim` | fast | same | 1.4s | Landed |
| `deploy-kit-config.yml` / `kit-config` | core pin, kit pin, `deploy/ci/**`, workflow | 12s | `deploy-kit-config` | fast | same | 16.4s | Landed |
| `core-bootstrap-health.yml` / source bootstrap | core pin, `deploy/ci/**`, workflow | 5m45s | `stage0-bootstrap` | heavy | core + kit pins, `deploy/ci/**`, stack runner/shim, workflow | **not measured** | Draft PR #168; do not flip modes |
| `deploy-kit-smoke.yml` / clean-box FHIR read | core + kit pins, `deploy/ci/**`, smoke test, workflow | 6m31s | `stage4-smoke` | heavy | hosted paths plus stack runner/shim | **not measured** | Draft PR #168; do not flip modes |
| `site-stack-smoke.yml` / X3 site E2E | core + kit + bridge pins, workflow | 12m05s | `site-stack-smoke` | heavy | hosted pins plus X3 fixture, local overlays, stack runner/shim | **not measured** | Draft PR #168; do not flip modes |

### Component repositories

| Repository | Hosted workflow / check | Hosted selection | Local check | Class | Local trigger paths | Observed local | Status |
|---|---|---|---|---|---|---:|---|
| Core | `backend.yml` / terminal `01 Checkpoint - Backend` | every PR; `Build + Test` is selected only for backend paths (`src/**`, Maven/dataexport/plugins/FHIR/build and compose inputs, workflow) | `core-backend` | heavy | same backend source/build/compose set | **not measured** | Hosted live; local draft PR #164 |
| Core | `frontend.yml` / terminal `02 Checkpoint - Frontend` | every PR; static/image sub-jobs are selected only for `frontend/**`, compose/build/analyzer-harness inputs, workflow | `core-frontend` | heavy | same frontend/build/compose set | **not measured** | Hosted live; local draft PR #164 |
| Core | `i18n-check.yml` / duplicate keys + source ownership | PR changes under `frontend/src/languages/**` | `core-i18n` | fast | `frontend/src/languages/**` | 0.1s | Landed |
| Bridge | `test.yml` / `Run Tests` | PRs to `master`/`develop`; pushes to `master`, `develop`, and feature branches | `bridge-tests` | fast | all component paths; umbrella `edge/drivers` pin | 91.2s | Landed |
| Deploy kit | none | no hosted component workflow | `kit-lint` | fast | `scripts/**`, `tests/**`, analyzer/plugin configs; umbrella `deploy/kit` pin | 0.8s | Landed; umbrella composition remains separate |

Umbrella pin changes additionally select the component-aware local checks via
`additional_triggers`: `edge/drivers` selects `bridge-tests`, and `deploy/kit` selects
`kit-lint`. The umbrella Stage-4 checks still prove the pinned composition separately.

For core hosted review, the two terminal checkpoint contexts—not an individual conditional
sub-job—are the expected contracts on every PR. Each checkpoint must conclude `success`.
Its build/static/image sub-job may be `skipped` only when the workflow's change detector
concluded `success` and reported that path family false; a skipped terminal checkpoint or a
skipped sub-job on a selected path is red. When `i18n-check.yml` is selected, the
`Duplicate key check` must succeed and `Translation source-of-truth check` must succeed except on the
documented `chore/update-transifex` branch, where that second job is expected to skip.

## Timing ledger and the open evidence gate

| Local check | Cold | Warm | Evidence state |
|---|---:|---:|---|
| `scripts-tests` | not separately recorded | 5.8s | Full 342-test suite in the LIS-286 worktree |
| `edge-sim` | not separately recorded | 1.4s | LIS-282 live exact-head status |
| `deploy-kit-config` | not separately recorded | 16.4s | LIS-282 live exact-head status |
| `kit-lint` | not separately recorded | 0.8s | LIS-282 live exact-head status |
| `core-i18n` | not separately recorded | 0.1s | LIS-282 live exact-head status |
| `bridge-tests` | not separately recorded | 91.2s | LIS-282 live exact-head status; 966 tests |
| `core-backend` | **not measured** | **not measured** | LIS-283 / draft PR #164 requires a real Docker host |
| `core-frontend` | **not measured** | **not measured** | LIS-283 / draft PR #164 requires a real Docker host |
| `stage0-bootstrap` | **not measured** | **not measured** | LIS-284 / draft PR #168 requires a real Docker host |
| `stage4-smoke` | **not measured** | **not measured** | LIS-284 / draft PR #168 requires a real Docker host |
| `site-stack-smoke` | **not measured** | **not measured** | LIS-284 / draft PR #168 requires a real Docker host |

This table deliberately does not turn hosted timings into local timings. The current host
has neither Docker CLI nor socket. LIS-283 and LIS-284 require cold/warm runs of their
actual local entrypoints, including isolation and cleanup evidence, before these rows can
be completed and before LIS-286's measured-wall-clock criterion is met.

## Designated integration gate

The **Stage-4 family** is the system integration gate:

- `stage4-smoke` proves a clean install of the exact core + deploy-kit pins through the
  public health and FHIR `DiagnosticReport` surfaces (ADR-0020/0021).
- `site-stack-smoke` extends that proof across the exact bridge pin, X3 listener, core
  ingest, registry sync, and fail-closed readiness behavior.

This is not ceremonial coverage. It has caught two merge-blocking P0s that component
tests missed:

1. LIS-226 pinned a core that passed component tests but could not boot its production
   Spring context because of a circular dependency; the clean-box gate forced LIS-242.
2. LIS-251's site stack was healthy while a host-owned `0600` properties file was
   unreadable by Tomcat and silently ignored; the site E2E caught the broken
   core-to-bridge leg and added an in-container readability gate.

Never waive the Stage-4 family for a change whose paths select it.

## Hosted automation that is not a current merge gate

| Repository | Workflows | Why not an expected main-PR check / action in local mode |
|---|---|---|
| Core | `e2e-tests.yml`, `publish-images.yml`, `deploy-testing.yml`, `label-merge-conflict.yml`, `publish-dev-backend-images.yml`, `publish-dev-frontend-images.yml`, `tx-pull.yml`, `tx-push.yml`, `e2e-cache-cleanup.yml` | Jobs are gated to `github.repository == 'DIGI-UW/OpenELIS-Global-2'`; on the LabSolution standalone repo they are dormant-by-design. Disable the two scheduled files during the private flip so no daily/weekly no-op run is mistaken for coverage. |
| Core | `e2e-playwright.yml` | PR target filter is `develop` (plus one named fix branch), not the LabSolution `main` model; manual/release uses remain operational automation, not a current main-PR gate. |
| Core | `build-installer.yml`, `e2e-authoritative-reusable.yml`, `e2e-playwright-reusable.yml`, `e2e-cypress-deprecated.yml` | Reusable/manual workflows with no automatic main-PR trigger. They are invoked only by an explicit caller/operator and are not current merge evidence. |
| Core | `spec-pages.yml`, `speckit-validate.yml` | Documentation/tooling automation. They are not represented by `local_ci`; decide explicitly whether to retain or disable them when private rather than calling them product merge evidence. |
| Bridge | `docker-build-dev.yml`, `docker-build-master.yml` | Push/release image publication, not PR merge evidence. Keep or suspend deliberately; `bridge-tests` replaces only `test.yml`. |
| Deploy kit | none | No hosted workflows are configured. |

The ordered operational procedure is
[`docs/runbooks/flip-back-private-ci.md`](../runbooks/flip-back-private-ci.md).
