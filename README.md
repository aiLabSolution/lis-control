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

Future components (per `LIS_IMPLEMENTATION_PLAN.md` §5) will be added as further
submodules under their own org repos — e.g. `edge/drivers/` (instrument
driver/interface layer), `plugins/` (analyzer plugins), `deploy/kit/` (on-prem
deploy kit), `infra/` (IaC).

## Cloning

```bash
git clone --recurse-submodules https://github.com/aiLabSolution/lis-control.git
# already cloned without --recurse-submodules:
git submodule update --init --recursive
```

## Component repos are independent

Each submodule is a standalone repo with its own remotes. The OpenELIS core
tracks the canonical project as `upstream` so releases can be pulled and generic
plugins contributed back (plan §0/§6):

```bash
cd core/openelis
git remote -v
#   origin    https://github.com/aiLabSolution/OpenELIS-Global-2.git   (the fork/mirror)
#   upstream  https://github.com/DIGI-UW/OpenELIS-Global-2.git         (canonical OpenELIS Global)

# pull upstream changes onto the fork:
git fetch upstream && git merge upstream/develop   # or rebase
```

After updating a submodule, record the new pin in this repo:

```bash
git add core/openelis && git commit -m "core: bump openelis to <sha>"
```
