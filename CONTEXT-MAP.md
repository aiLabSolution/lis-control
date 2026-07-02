# CONTEXT-MAP

Index of contexts for the LIS programme. `lis-control` is the **umbrella** repo
(see `README.md`); each code component is a **git submodule** pinned at a known
SHA (see `docs/adr/0001-repository-topology-submodule-umbrella.md`).

Read the `CONTEXT.md` for any context relevant to your task before exploring it.
These files are created lazily — some may not exist yet (see `docs/agents/domain.md`).

## Contexts

| Context | Mount (submodule) | Component repo | Context doc |
|---|---|---|---|
| **OpenELIS core** — clinical core: orders/results/QC/reporting, RBAC, audit, data model | `core/openelis/` | `aiLabSolution/OpenELIS-Global-2` (`upstream`: `DIGI-UW/OpenELIS-Global-2`) | [`contexts/core-openelis/CONTEXT.md`](contexts/core-openelis/CONTEXT.md) |
| **Edge / drivers** — analyzer interface engine (`openelis-analyzer-bridge`): per-transport listeners (MLLP/serial/ASTM/file), parse + LOINC/UCUM normalization, FHIR northbound (ADR-0015) | `edge/drivers/` (submodule, pin `fe391a7` = release `3.0.7` w/ LIS-28 registry-backed unit→UCUM, LIS-26 EC90 ASTM, EDAN H90 profile, LIS-95 QC/cal gate, branch `develop`) | `aiLabSolution/openelis-analyzer-bridge` (standalone export, not a fork) | [`contexts/edge-drivers/CONTEXT.md`](contexts/edge-drivers/CONTEXT.md) |
| **Plugins** — analyzer plugins; generic ones contributed upstream | `plugins/` _(planned)_ | _aiLabSolution fork of `DIGI-UW/openelisglobal-plugins` (TBD)_ | _(lazy)_ |
| **Deploy kit** — on-prem/offline deploy kit, authoritative deployed configuration, single-site store-and-forward (pilot); **site↔central sync = post-pilot M3 spoke** (ADR-0006) | `deploy/kit/` | `aiLabSolution/lis-deploy-kit` | [`contexts/deploy-kit/CONTEXT.md`](contexts/deploy-kit/CONTEXT.md) |
| **Infra** — IaC, CI/CD, environments | `infra/` _(planned)_ | _aiLabSolution (TBD)_ | _(lazy)_ |

## Layered context

Context is layered, root → component:

- **Umbrella (this repo)** — system-wide context lives here: this map, the phased
  plan (`LIS_IMPLEMENTATION_PLAN.md`), the research report
  (`LIS_BUILD_AND_INTEGRATION_RESEARCH.md`), and system-wide decisions in `docs/adr/`.
- **Per component** — each submodule has a `CONTEXT.md` under
  `contexts/<mount>/CONTEXT.md` (hosted in the umbrella so the forks' tracked
  branches stay a clean mirror of upstream — ADR-0001 §5). Component-scoped
  decisions go in `contexts/<mount>/docs/adr/`.

When a context names a domain concept, use the term as defined in its `CONTEXT.md`
glossary. If your output contradicts an ADR, flag it rather than silently overriding
(see `docs/agents/domain.md`).
