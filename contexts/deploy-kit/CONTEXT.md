# Context — Deploy kit

## What this is

The on-prem/offline deploy kit for LabSolution LIS. It owns deployed
configuration, deployment packaging, and site-local operational assets that are
outside the OpenELIS clinical core and the edge analyzer bridge.

## Repo & versioning

- **Mount:** `deploy/kit/` (git submodule, pinned in `lis-control`).
- **origin:** `https://github.com/aiLabSolution/lis-deploy-kit.git`.
- **Authoritative analyzer profiles:** `deploy/kit/configs/analyzer-profiles/`.
- **Runtime mount contract:** the deploy stack exposes that directory to
  OpenELIS as `/data/analyzer-profiles`, read-only.

## Ownership boundaries

- Deploy kit owns deployed configuration and packaging.
- OpenELIS core owns profile consumers, analyzer creation, test mapping seed, QC
  rule seed, and result processing.
- Edge/drivers owns analyzer transport listeners and message parsing/runtime
  routing.
- A site stack may carry a complete analyzer source binding marked
  `LOCAL_BOOTSTRAP` as a narrow startup/liveness exception. OpenELIS remains
  authoritative for ordinary registry entries and wins the same source key;
  deploy kit owns the explicitly marked bootstrap document until that handoff.

## Component decisions

- **ADR-0016 — Deploy kit as authoritative deployed configuration component:**
  `docs/adr/0016-deploy-kit-authoritative-config.md`.
- **ADR-0020 — Deploy-kit clean-box smoke gate for the M1 pilot:**
  `docs/adr/0020-deploy-kit-clean-box-smoke-gate.md`.

## Glossary

- **Authoritative deployed configuration** — files read by deployed
  environments at runtime. For analyzer profiles, this is
  `configs/analyzer-profiles/` in the deploy kit, mounted into OpenELIS as
  `/data/analyzer-profiles`.
- **Core mirror** — OpenELIS `projects/analyzer-profiles/`, kept for local
  development, unit tests, and profile authoring. If it drifts from the deploy
  kit, the deploy kit wins for deployed environments.
