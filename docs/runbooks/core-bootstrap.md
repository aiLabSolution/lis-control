# Runbook — reproducible core bootstrap (Stage 0 / LIS-4)

Boot the forked OpenELIS clinical core from a clean checkout to a healthy state with
**no manual database or migration steps**. This is the canonical Stage 0 bootstrap and
the contract the CI gate (`.github/workflows/core-bootstrap-health.yml`) enforces.

## Prerequisites

- Docker Engine + Compose v2 (`docker compose version`).
- A clean checkout of `lis-control` with the `core/openelis` submodule initialised:
  ```bash
  git clone --recurse-submodules git@github.com:aiLabSolution/lis-control.git
  # or, in an existing checkout:
  git submodule update --init core/openelis
  ```
  `core/openelis` is the **private** `aiLabSolution/OpenELIS-Global-2` repo — you need
  read access. (First-level only; the nested submodules are not needed for the
  prebuilt-image bootstrap — see the ADR.)

## Boot

The bootstrap pulls **prebuilt images** (no source build) and applies the umbrella
overlay that pins them by digest for reproducibility:

```bash
docker compose --project-directory core/openelis \
  -f core/openelis/docker-compose.yml \
  -f core/openelis/.github/ci/ci.memory-limits.yml \
  -f deploy/ci/compose.bootstrap.yml \
  up -d
```

Then assert health:

```bash
bash deploy/ci/healthcheck.sh   # waits for: db healthy + webapp running + UI 200
```

The webapp (Tomcat) needs ~60s after `up` to deploy the WAR and run Liquibase
migrations; `healthcheck.sh` polls until ready (default 420s).

## What "healthy" means

| Signal | How it's checked | Proves |
|---|---|---|
| DB ready | `openelisglobal-database` healthcheck = `healthy` (pg_isready) | Postgres up |
| App + migrations | `openelisglobal-webapp` container `running` | WAR deployed; Liquibase migrations applied (a fatal migration exits the container) |
| System serves | `GET https://localhost/` → **200** | proxy + frontend serving |

Default admin credentials (dev only): `admin` / `adminADMIN!`.

> **Note on the login health contract.** The project's stricter readiness check
> (`core/openelis/scripts/e2e/wait-for-openelis-login.sh` → `verify-login.sh`, expecting
> JSON `"authenticated": true`) only holds against the **from-source** build
> (`build.docker-compose.yml`) used by the fork's e2e. With the prebuilt `:develop`
> image the login API 302-redirects to the SPA, because the published image lags the
> pinned source SHA. See the ADR for the reproducibility implications.

## Local port / subnet collisions

The base compose hardcodes host ports `8080`/`8081` and subnet `172.20.1.0/24` (+ a
static webapp IP). If those collide on your machine, add a **local-only** override
(do NOT commit it to the fork — ADR-0001 §5 keeps the fork a clean mirror) remapping
the conflicting ports and the network subnet, e.g.:

```yaml
# local.override.yml
services:
  oe.openelis.org:
    ports: !override ["18080:8080", "8443:8443"]
    networks: { default: { ipv4_address: 172.28.5.121 } }
  fhir.openelis.org:
    ports: !override ["18081:8080", "8444:8443"]
networks:
  default: { driver: bridge, ipam: { config: !override [{ subnet: 172.28.5.0/24 }] } }
```

## Teardown

```bash
docker compose --project-directory core/openelis \
  -f core/openelis/docker-compose.yml \
  -f core/openelis/.github/ci/ci.memory-limits.yml \
  -f deploy/ci/compose.bootstrap.yml down -v
```
