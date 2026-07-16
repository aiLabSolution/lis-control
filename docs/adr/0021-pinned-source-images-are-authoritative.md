# ADR-0021 — Pinned source images are authoritative

- **Status:** Accepted
- **Date:** 2026-07-16
- **Issue:** LIS-141
- **Supersedes:** ADR-0002 Decisions 2 and 4
- **Relates to:** ADR-0001 (umbrella reproducibility spine), ADR-0016
  (deploy-kit authority), ADR-0020 (clean-box smoke gate)

## Context

The umbrella pins an exact LabSolution OpenELIS commit, but the original Stage 0
bootstrap selected published upstream images by digest. A digest reproduces the
same image bytes; it does not prove that those bytes contain the source commit
the umbrella pins. The upstream image can lag or diverge while every checksum
continues to pass.

The pinned core's `build.docker-compose.yml` now provides the required source
build model. Its one explicit nested build dependency, `dataexport`, can be
resolved from the gitlink in the pinned core and checked out independently in
CI. The deploy-kit wrapper also owns enough operation-aware guardrails to make
the source selection mandatory and to force recreation from freshly built
images.

One compatibility constraint remains: older deploy-kit `up` runs recorded the
retired digest overlay's exact path. A later plain `down` must be able to replay
that compose model to remove the old stack safely.

## Decision

1. The exact `core/openelis` source commit pinned by `lis-control` is the
   authoritative source of OpenELIS deployment images.
2. The Stage 0 bootstrap workflow composes the core base file with the pinned
   core's `build.docker-compose.yml`, checks out the core's pinned `dataexport`
   gitlink, and runs `up --build` before the health assertion.
3. Deploy-kit runtime operations use the wrapper's pinned-source default. The
   wrapper rejects image-selection opt-outs and Compose options that could reuse
   a stale image or preserve a container created from an older image.
4. `deploy/ci/compose.bootstrap.yml` is retained unchanged in its image model at
   its historical path for recorded legacy `down` replay only. It is not a
   supported input to `up`, `config`, live instructions, or CI rendering.

## Consequences

- One umbrella commit now identifies both the deployed core source and the
  dependency source used to build it; upstream image publication cannot alter
  that provenance.
- Cold CI and operator installs are slower and require the OpenELIS source build
  toolchain and the pinned `dataexport` checkout.
- The Stage 0 health check and deploy-kit clean-box smoke test the implementation
  the umbrella actually pins, while retaining their distinct health-only and
  packaging/FHIR scopes.
- Existing stacks created with the retired digest mode remain safely removable;
  the legacy overlay is compatibility data, not a deployment alternative.
