# LIS

## Repository structure

`lis-control` is the **umbrella** repo (`aiLabSolution/lis-control`). Code components
are **git submodules** pinned at known SHAs — OpenELIS core at `core/openelis`, more
to come (`edge/drivers`, `plugins`, `deploy/kit`, `infra`). Clone with
`--recurse-submodules`. Topology and rationale: `docs/adr/0001-repository-topology-submodule-umbrella.md`.
Context index: `CONTEXT-MAP.md`.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in Plane.so, driven via the bundled `plane` CLI (the `/plane` skill). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, mapped onto Plane workflow states. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context layout — `CONTEXT-MAP.md` at the root points to per-context `CONTEXT.md` files. See `docs/agents/domain.md`.
