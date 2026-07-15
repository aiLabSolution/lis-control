#!/usr/bin/env bash
# LIS Stage 0 (LIS-4 / S0.2) — core bootstrap health gate.
#
# Asserts that a reproducible `compose up` reaches a healthy, DB-backed core, with
# NO manual database or migration steps:
#   (1) the database container's healthcheck reports `healthy` (pg_isready);
#   (2) the OpenELIS webapp container is `running` — Liquibase migrations run on
#       startup, so a fatal migration would exit the container;
#   (3) the proxied UI returns HTTP 200.
# All three must hold within TIMEOUT. On success it also prints the webapp's
# "Server startup" line as evidence that the WAR deployed.
#
# Env (all optional):
#   BASE_URL          default https://localhost   (the nginx proxy)
#   HEALTH_URL        default $BASE_URL/; set this for a direct backend probe
#   DB_CONTAINER      default openelisglobal-database
#   WEBAPP_CONTAINER  default openelisglobal-webapp
#   TIMEOUT           default 420  (seconds to wait for app deploy after `up`)
set -euo pipefail

BASE_URL="${BASE_URL:-https://localhost}"
HEALTH_URL="${HEALTH_URL:-${BASE_URL%/}/}"
DB_CONTAINER="${DB_CONTAINER:-openelisglobal-database}"
WEBAPP_CONTAINER="${WEBAPP_CONTAINER:-openelisglobal-webapp}"
TIMEOUT="${TIMEOUT:-420}"

deadline=$(( $(date +%s) + TIMEOUT ))
health=missing state=missing code=000
while [ "$(date +%s)" -lt "$deadline" ]; do
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$DB_CONTAINER" 2>/dev/null || echo missing)
  state=$(docker inspect --format '{{.State.Status}}' "$WEBAPP_CONTAINER" 2>/dev/null || echo missing)
  code=$(curl -sk -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || echo 000)
  if [ "$health" = healthy ] && [ "$state" = running ] && [ "$code" = 200 ]; then
    echo "HEALTHY  db=$health  webapp=$state  ui=$code"
    docker logs "$WEBAPP_CONTAINER" 2>&1 | grep -m1 "Server startup in" || true
    exit 0
  fi
  echo "waiting…  db=$health  webapp=$state  ui=$code"
  sleep 5
done

echo "UNHEALTHY after ${TIMEOUT}s  db=$health  webapp=$state  ui=$code" >&2
exit 1
