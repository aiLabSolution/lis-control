# ADR-0002 — Stage 0 reproducible bootstrap + where the health-check CI lives

- **Status:** Superseded
- **Date:** 2026-06-22
- **Deciders:** Marloe Uy (aiLabSolution)
- **Relates to:** ADR-0001 (repository topology); LIS-2 (Stage 0 PRD); LIS-3 (fork/pin); LIS-4 (S0.2)
- **Superseded by:** ADR-0021 (LIS-141), which replaces Decisions 2 and 4
  with builds from the exact umbrella-pinned source. This document remains the
  historical record of the original Stage 0 gate.

## Context

LIS-4 (S0.2) requires that a clean checkout + `compose up` brings the forked OpenELIS
core to a **200 health check with no manual database/migration steps**, gated **green in
CI on every merge**, and that unit/component suites run on every merge. Several facts
discovered while implementing this shape the decision:

1. **The fork's tracked branch is a clean mirror of upstream** (ADR-0001 §5). LabSolution
   does not push CI/overlays onto `core/openelis`'s `develop`.
2. **The fork's e2e workflow is repo-gated.** `core/openelis/.github/workflows/e2e-tests.yml`
   runs only `if: github.repository == 'DIGI-UW/OpenELIS-Global-2'` — it does **not** run on
   `aiLabSolution/OpenELIS-Global-2`. The unit/component gate (`backend.yml`) *does* run on
   the fork (push-to-develop + PRs).
3. **The bootstrap can use prebuilt images.** `core/openelis/docker-compose.yml` pulls
   `itechuw/openelis-global-2*:develop` from Docker Hub — it does not build from source, so
   it boots without OpenELIS's nested submodules (incl. the SSH-only `Consolidated-Server`
   and the **license-blocked** `tools/openelis-analyzer-bridge`, HOLD-001).
4. **Prebuilt `:develop` is a rolling tag** — not reproducible, and it can lag/diverge from
   the pinned *source* SHA. (Observed: the prebuilt webapp 302-redirects the `ValidateLogin`
   API to the SPA, whereas the from-source build returns the expected JSON; the e2e uses
   `build.docker-compose.yml`.)

## Decision

1. **The compose→health gate lives in the umbrella `lis-control`**, not the fork — consistent
   with ADR-0001 (umbrella = reproducibility spine). Workflow:
   `.github/workflows/core-bootstrap-health.yml`. It checks out `core/openelis` at the pinned
   SHA (first-level submodule only), runs `compose up`, and asserts health. Unit/component
   testing stays on the fork's inherited `backend.yml`.

2. **Bootstrap = prebuilt images, pinned by digest.** `deploy/ci/compose.bootstrap.yml`
   overrides the base compose's rolling `:develop` tags with content digests, making
   `compose up` byte-for-byte reproducible. Digests are refreshed deliberately (recorded in
   a commit/ADR), never silently.

3. **Health contract = DB healthy + webapp running + proxied UI 200** (`deploy/ci/healthcheck.sh`).
   This proves Postgres is up, Liquibase migrations applied (a fatal migration exits the
   webapp), and the system serves — all with no manual steps. The stricter login-JSON
   readiness contract is deferred to the from-source path (see below).

4. **Full source-level reproducibility is deferred.** Building the core from the pinned SHA
   (which would also make the login health contract hold) requires resolving the nested
   submodules + the analyzer-bridge license (HOLD-001). Tracked as an open item in
   `contexts/core-openelis/CONTEXT.md`; revisit before Stage 1 needs a source build.

## Consequences

**Positive**
- A single `lis-control` commit's bootstrap is reproducible (digest-pinned) and CI-gated —
  the IQ/OQ/PQ traceability spine.
- The fork stays a clean upstream mirror; no LabSolution CI pushed onto it.
- No dependency on the uninitialised / license-blocked nested submodules.

**Negative / costs / open items**
- **Image vs source drift:** prebuilt `:develop` images can diverge from the pinned source
  SHA. Digest-pinning fixes *reproducibility* but not *fidelity to the source*; closed only
  when we build from source (deferred, see Decision 4).
- **CI needs a cross-repo token.** `core/openelis` is in the **private**
  `aiLabSolution/OpenELIS-Global-2` repo; the default `GITHUB_TOKEN` can't read it. CI
  requires an `OPENELIS_SUBMODULE_TOKEN` secret (fine-grained PAT or GitHub App installation
  token, read-only on that repo). **Setup action required before CI can pass.**
- Weaker health contract than login-readiness (mitigated by Decision 4's deferral).

## LIS-3 follow-up (related)

LIS-3's acceptance says "pinned upstream release tag recorded in-repo," but the fork is
SHA-pinned to `develop` and has **no git tags** (a memory note referenced "3.2.1.10"; no such
tag exists). Recommend recording the intended upstream release pin here or in a dedicated ADR
so the Stage 0 reproducibility/traceability story is explicit. Pending decision (raised on
LIS-4).

## Alternatives considered

- **CI on the fork** — rejected: violates ADR-0001 clean-mirror; the fork's e2e is repo-gated
  to DIGI-UW anyway.
- **Build from source in the bootstrap gate** — rejected for Stage 0: blocked on nested
  submodules + analyzer-bridge license; heavy. Revisit later (Decision 4).
- **Leave `:develop` rolling tags** — rejected: not reproducible, fails the ISO 15189 story.
