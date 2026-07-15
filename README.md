# lis-control

Control plane and umbrella for the LabSolution LIS programme. This repo holds the
**planning, architecture, diagrams, and agent/issue-tracker configuration**, and
pins each implementation component as a **git submodule** so one revision of
`lis-control` reproduces the whole system at known versions — the spine of the
ISO 15189 / IQ-OQ-PQ traceability story in `LIS_IMPLEMENTATION_PLAN.md`.

## Layout

| Path | What | Repo |
|---|---|---|
| `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` | Research / architecture report | this repo |
| `LIS_IMPLEMENTATION_PLAN.md` | Phased, verifiable delivery plan | this repo |
| `diagrams/` | Excalidraw reference architecture + roadmap views | this repo |
| `docs/agents/` | Agent skills: issue tracker, triage, domain docs | this repo |
| `core/openelis/` | OpenELIS Global 2 — clinical core (submodule) | `aiLabSolution/OpenELIS-Global-2` |
| `edge/drivers/` | Analyzer bridge / interface engine (submodule) | `aiLabSolution/openelis-analyzer-bridge` |
| `deploy/kit/` | On-prem deploy kit + authoritative deployed config (submodule) | `aiLabSolution/lis-deploy-kit` |

Future components (per `LIS_IMPLEMENTATION_PLAN.md` §5) will be added as further
submodules under their own org repos — e.g. `plugins/` (analyzer plugins) and
`infra/` (IaC).

## Cloning

```bash
git clone --recurse-submodules https://github.com/aiLabSolution/lis-control.git
# already cloned without --recurse-submodules:
git submodule update --init --recursive
```

## Component repositories and original sources

Every submodule clone URL uses an `aiLabSolution` repository as `origin`. The
original project URLs are retained here for attribution and deliberate source
review only; clones do not configure standing `upstream` remotes. In particular,
OpenELIS core follows the standalone `aiLabSolution/main` model from ADR-0003.

| Mount | `origin` | Original source |
|---|---|---|
| `core/openelis/` | [`aiLabSolution/OpenELIS-Global-2`](https://github.com/aiLabSolution/OpenELIS-Global-2) | [`DIGI-UW/OpenELIS-Global-2`](https://github.com/DIGI-UW/OpenELIS-Global-2) |
| `edge/drivers/` and `core/openelis/tools/openelis-analyzer-bridge/` | [`aiLabSolution/openelis-analyzer-bridge`](https://github.com/aiLabSolution/openelis-analyzer-bridge) | [`DIGI-UW/openelis-analyzer-bridge`](https://github.com/DIGI-UW/openelis-analyzer-bridge) |
| `deploy/kit/` | [`aiLabSolution/lis-deploy-kit`](https://github.com/aiLabSolution/lis-deploy-kit) | LabSolution-owned; no external source |
| `core/openelis/plugins/` | [`aiLabSolution/openelisglobal-plugins`](https://github.com/aiLabSolution/openelisglobal-plugins) | [`DIGI-UW/openelisglobal-plugins`](https://github.com/DIGI-UW/openelisglobal-plugins) |
| `core/openelis/dataexport/` | [`aiLabSolution/dataexport`](https://github.com/aiLabSolution/dataexport) | [`DIGI-UW/dataexport`](https://github.com/DIGI-UW/dataexport) |
| `core/openelis/projects/catalyst/` | [`aiLabSolution/openelis-catalyst`](https://github.com/aiLabSolution/openelis-catalyst) | [`DIGI-UW/openelis-catalyst`](https://github.com/DIGI-UW/openelis-catalyst) |
| `core/openelis/tools/Liquibase-Outdated/` | [`aiLabSolution/Liquibase-Outdated`](https://github.com/aiLabSolution/Liquibase-Outdated) | [`DIGI-UW/Liquibase-Outdated`](https://github.com/DIGI-UW/Liquibase-Outdated) |
| `core/openelis/tools/Password-Migrator/` | [`aiLabSolution/Password-Migrator`](https://github.com/aiLabSolution/Password-Migrator) | [`DIGI-UW/Password-Migrator`](https://github.com/DIGI-UW/Password-Migrator) |
| `core/openelis/tools/analyzer-mock-server/` | [`aiLabSolution/analyzer-mock-server`](https://github.com/aiLabSolution/analyzer-mock-server) | [`DIGI-UW/analyzer-mock-server`](https://github.com/DIGI-UW/analyzer-mock-server) |
| `core/openelis/Consolidated-Server/` (declared, not currently pinned) | [`aiLabSolution/Consolidated-Server`](https://github.com/aiLabSolution/Consolidated-Server) | [`DIGI-UW/Consolidated-Server`](https://github.com/DIGI-UW/Consolidated-Server) |
| `core/openelis/hapi-fhir-jpaserver-starter/` (declared, not currently pinned) | [`aiLabSolution/hapi-fhir-jpaserver-starter`](https://github.com/aiLabSolution/hapi-fhir-jpaserver-starter) | [`DIGI-UW/hapi-fhir-jpaserver-starter`](https://github.com/DIGI-UW/hapi-fhir-jpaserver-starter) |

Existing recursive clones can adopt versioned URL changes with:

```bash
git submodule sync --recursive
```

After updating a submodule, record the new pin in this repo:

```bash
git add core/openelis && git commit -m "core: bump openelis to <sha>"
```
