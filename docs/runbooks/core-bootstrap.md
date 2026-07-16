# Runbook — reproducible core bootstrap (Stage 0 / LIS-4)

Boot the forked OpenELIS clinical core from a clean checkout to a healthy state with
**no manual database or migration steps**. This is the canonical Stage 0 bootstrap and
the contract the CI gate (`.github/workflows/core-bootstrap-health.yml`) enforces.

## Prerequisites

- Docker Engine + Compose v2 (`docker compose version`).
- A clean checkout of `lis-control` with the `core/openelis` submodule initialised:
  ```bash
  git clone git@github.com:aiLabSolution/lis-control.git
  cd lis-control
  git submodule update --init core/openelis
  git -C core/openelis submodule update --init dataexport
  ```
  `core/openelis` is the **private** `aiLabSolution/OpenELIS-Global-2` repo — you need
  read access. The pinned `dataexport` nested repository is the source build's
  required Maven dependency; the other nested repositories are not needed for
  this bootstrap.

## Boot

The bootstrap builds images from the exact OpenELIS and `dataexport` SHAs pinned
by the umbrella checkout:

```bash
docker compose --project-directory core/openelis \
  -f core/openelis/docker-compose.yml \
  -f core/openelis/build.docker-compose.yml \
  -f core/openelis/.github/ci/ci.memory-limits.yml \
  up -d --build
```

Then assert health:

```bash
bash deploy/ci/healthcheck.sh   # waits for: db healthy + webapp running + UI 200
```

Allow 15-30 minutes for an uncached build on a small machine. After the image is
built, the webapp (Tomcat) needs roughly 60s to deploy the WAR and run Liquibase
migrations; `healthcheck.sh` polls until ready (default 420s).

## What "healthy" means

| Signal | How it's checked | Proves |
|---|---|---|
| DB ready | `openelisglobal-database` healthcheck = `healthy` (pg_isready) | Postgres up |
| App + migrations | `openelisglobal-webapp` container `running` | WAR deployed; Liquibase migrations applied (a fatal migration exits the container) |
| System serves | `GET https://localhost/` → **200** | proxy + frontend serving |

Default admin credentials (dev only): `admin` / `adminADMIN!`.

The source build also keeps runtime behavior aligned with the pinned core. In
particular, it avoids the login-contract drift previously observed in published
upstream images.

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
  -f core/openelis/build.docker-compose.yml \
  -f core/openelis/.github/ci/ci.memory-limits.yml \
  down -v
```
