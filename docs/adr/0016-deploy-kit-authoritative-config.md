# ADR-0016 — Deploy kit as authoritative deployed configuration component

- **Status:** Accepted
- **Date:** 2026-07-02
- **Deciders:** Marloe Uy (aiLabSolution)
- **Issue:** LIS-100

## Context

OpenELIS exposes analyzer profile templates from `/data/analyzer-profiles`.
The core repository also carries a mirror under `projects/analyzer-profiles/`
for local development, unit tests, and profile authoring. That mirror explicitly
states that deployed environments use the out-of-tree distro
`configs/analyzer-profiles/` as the source of truth.

LIS-95 added the Seamaty SD1 HL7 profile to the OpenELIS mirror. Without an
authoritative deployed configuration component, deployed LabSolution
environments cannot consume that profile even though the core mirror is correct.

ADR-0001 already reserves `deploy/kit/` as the future deploy-kit component
submodule. LIS-100 promotes that planned component into the authoritative home
for deployed configuration.

## Decision

Create `aiLabSolution/lis-deploy-kit` and mount it in the umbrella at
`deploy/kit/`.

`deploy/kit/configs/analyzer-profiles/` is the authoritative LabSolution source
for analyzer profile JSON used by deployed environments. The deploy stack must
mount this directory read-only into OpenELIS as `/data/analyzer-profiles`.

OpenELIS `projects/analyzer-profiles/` remains a development/test mirror. When
the two copies drift, the deploy-kit copy wins for deployed environments.

## Consequences

- A single `lis-control` commit now pins the deploy-kit revision alongside core
  and edge revisions, preserving the reproducible IQ/OQ/PQ snapshot.
- Analyzer profile delivery is a deploy/configuration change when OpenELIS
  consumers already understand the profile schema.
- Profile additions that also require core behavior changes still use the
  two-level flow: component PR first, then umbrella pin bump.
- Deploy-kit verification must prove both file presence at
  `/data/analyzer-profiles` and runtime consumption through the OpenELIS
  profile/defaultConfig path.
