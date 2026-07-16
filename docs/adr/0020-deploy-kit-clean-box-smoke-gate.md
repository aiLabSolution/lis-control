# ADR-0020 — Deploy-kit clean-box smoke gate for the M1 pilot

- **Status:** Accepted
- **Date:** 2026-07-15
- **Issue:** LIS-50 (S4.9)
- **Relates to:** ADR-0002 (bootstrap health), ADR-0006 (M1 pilot topology),
  ADR-0016 (deploy kit owns deployed packaging/configuration)

## Context

LIS-50 requires an automated, from-scratch install proof that reaches an HTTP
200 health response and serves a FHIR R4 `DiagnosticReport` read. The original
ticket text also names a sync service, but ADR-0006 subsequently fixed the pilot
topology as M1: fully onsite, single site, and no sync. The M3 central-sync spoke
is post-pilot work and cannot become an implicit dependency of this gate.

At the time of this decision, the Stage 0 bootstrap gate proved that an older
digest-pinned OpenELIS snapshot booted. It did not exercise the deploy-kit
wrapper, and its pinned webapp image predated the OpenELIS-backed
`DiagnosticReport` read provider from LIS-41. Reusing that image would have made
the new FHIR assertion a false proof of a different API surface. ADR-0021 later
moved Stage 0 to the pinned source build as well; this clean-box gate remains the
distinct proof of the deploy-kit wrapper and public FHIR read.

## Decision

Add an umbrella CI gate that checks out the exact `core/openelis` and
`deploy/kit` SHAs pinned by the umbrella commit and then:

1. renders the deploy-kit compose plan;
2. uses the deploy-kit wrapper's source-build + local-proof modes to install a
   disposable, single-site OpenELIS stack from the pinned core source;
3. waits for the database and webapp and requires HTTP 200 from the OpenELIS
   backend health endpoint;
4. inserts one namespaced, finalized-result fixture into the disposable proof
   database; and
5. reads that result through the public
   `/api/OpenELIS-Global/fhir/DiagnosticReport/{id}` endpoint, asserting the
   resource type, id, final status, and Observation reference.

Fixture SQL is setup only. The acceptance assertion goes through the public
FHIR interface rather than inspecting persistence state. Fixed LIS-50 UUIDs
make reruns deterministic, and the workflow always deletes the proof volumes.

## Consequences

- A pull request that changes the core pin, deploy-kit pin, or deploy CI assets
  must prove the deployable pinned pair rather than either component in
  isolation.
- The gate builds the pinned OpenELIS webapp from source and tests the API
  implementation the umbrella actually pins. Unlike the Stage 0 health gate, it
  also proves deploy-kit composition and the public FHIR read.
- The deploy-kit overlay requires the final PostgreSQL server process—not the
  temporary initialization server—to become healthy before Tomcat starts. This
  prevents first-install Liquibase failures that leave the container running
  without a deployed OpenELIS application.
- No sync or central node is installed or asserted. Adding the M3 spoke later
  requires its own change-controlled deployment and validation delta under
  ADR-0006.
- The smoke fixture depends on the stable OpenELIS clinical schema for setup;
  schema changes that invalidate the fixture fail the deployment gate and must
  update the fixture in the same traceable change.
