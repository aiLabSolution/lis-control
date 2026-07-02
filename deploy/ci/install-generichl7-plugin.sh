#!/usr/bin/env bash
# LIS-94 (SD1 bench) — reproducibly build + install the GenericHL7 analyzer plugin
# into the OpenELIS plugin volume, with NO manual jar copying.
#
# Why this script exists
# ----------------------
# The SD1 live bench needs OpenELIS's GenericHL7 plugin (MSH-3/4 pattern-matched,
# Dashboard-configured HL7 v2 analyzers). It ships in the DIGI-UW `plugins`
# submodule of core/openelis, but it does NOT build from the pinned source: its
# Java imports `org.apache.commons.lang3.StringUtils`, yet the plugin pom never
# declares commons-lang3 (the `openelisglobal:classes` parent dep does not export
# it to the plugin compile classpath). A build therefore fails with
# `cannot find symbol: StringUtils` and the jar is missing from the volume, so
# OpenELIS registers zero analyzer types.
#
# Until the fix is persisted upstream (a fork of DIGI-UW/openelisglobal-plugins —
# see the LIS-94 follow-up), this script carries the one-line pom fix as a patch
# (deploy/ci/patches/generichl7-commons-lang3.patch, `commons-lang3` at `provided`
# scope, version pinned to the host's 3.18.0), applies it, builds the jar from the
# pinned submodule in a pinned Maven image, installs it, then reverts the patch so
# the submodule working tree stays clean.
#
# Usage:
#   deploy/ci/install-generichl7-plugin.sh            # build + install
#   deploy/ci/install-generichl7-plugin.sh --offline  # build with a warm ~/.m2 only
#   deploy/ci/install-generichl7-plugin.sh --verify    # after a webapp restart,
#                                                       # assert the plugin loaded
#   deploy/ci/install-generichl7-plugin.sh --help
#
# After install you must recreate/restart the webapp so it re-scans the volume:
#   C="-f core/openelis/docker-compose.yml -f core/openelis/.github/ci/ci.memory-limits.yml -f deploy/ci/compose.bootstrap.yml"
#   docker compose --project-directory core/openelis $C up -d oe.openelis.org
# then re-run with --verify.
set -euo pipefail

MAVEN_IMAGE="${MAVEN_IMAGE:-maven:3.9-eclipse-temurin-21}"
DB_CONTAINER="${DB_CONTAINER:-openelisglobal-database}"
WEBAPP_CONTAINER="${WEBAPP_CONTAINER:-openelisglobal-webapp}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORE="$REPO_ROOT/core/openelis"
PLUGIN_DIR="plugins/analyzers/GenericHL7"          # relative to $CORE
PATCH="$SCRIPT_DIR/patches/generichl7-commons-lang3.patch"
JAR_NAME="GenericHL7-1.0.jar"
DEST="$CORE/volume/plugins"

OFFLINE=false
DO_BUILD=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) OFFLINE=true ;;
    --verify)  DO_BUILD=false ;;
    --help)    sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
red()   { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }

verify() {
  local ok=0
  local types
  types="$(docker exec "$DB_CONTAINER" psql -U clinlims -d clinlims -tAc \
    "SELECT name FROM clinlims.analyzer_type ORDER BY name;" 2>/dev/null || true)"
  if grep -qx 'Generic HL7' <<<"$types"; then
    green "✓ analyzer_type contains 'Generic HL7'"
  else
    red   "✗ analyzer_type has no 'Generic HL7' row (got: ${types:-<none>})"; ok=1
  fi
  # Capture first (a piped `grep -q` short-circuits the pipe, and pipefail would
  # then mis-read docker's SIGPIPE exit as "no match").
  local logs
  logs="$(docker logs "$WEBAPP_CONTAINER" 2>&1 || true)"
  if grep -q 'PluginLoader.*Plugins loaded' <<<"$logs"; then
    green "✓ webapp log shows PluginLoader 'Plugins loaded'"
    grep 'PluginRegistryService.*Plugin registry complete' <<<"$logs" | tail -1 || true
  else
    red   "✗ webapp log has no PluginLoader 'Plugins loaded' line"; ok=1
  fi
  return $ok
}

if [ "$DO_BUILD" = false ]; then
  verify; exit $?
fi

[ -f "$PATCH" ] || { red "patch not found: $PATCH"; exit 1; }

echo "→ Initializing core plugins submodule…"
git -C "$CORE" submodule update --init plugins >/dev/null

# Apply the carried pom fix; always revert on exit so the submodule stays clean.
cleanup() { git -C "$CORE/plugins" checkout -- "analyzers/GenericHL7/pom.xml" 2>/dev/null || true; }
trap cleanup EXIT
if git -C "$CORE/plugins" apply --check "$PATCH" 2>/dev/null; then
  git -C "$CORE/plugins" apply "$PATCH"
  echo "→ Applied commons-lang3 pom fix (transient)."
else
  echo "→ pom fix already present or not applicable; building as-is."
fi

echo "→ Building $JAR_NAME from the pinned submodule ($MAVEN_IMAGE)…"
mvn_flags=(-Duser.home=/var/maven -Dmaven.test.skip=true -Dspotless.check.skip=true package)
$OFFLINE && mvn_flags=(-o "${mvn_flags[@]}")
docker run --rm \
  -u "$(id -u):$(id -g)" \
  -v "$CORE":/work -w "/work/$PLUGIN_DIR" \
  -v "$HOME/.m2":/var/maven/.m2 \
  -e MAVEN_CONFIG=/var/maven/.m2 \
  "$MAVEN_IMAGE" \
  mvn "${mvn_flags[@]}"

SRC="$CORE/$PLUGIN_DIR/target/$JAR_NAME"
[ -f "$SRC" ] || { red "build did not produce $SRC"; exit 1; }

mkdir -p "$DEST"
install -m 0644 "$SRC" "$DEST/$JAR_NAME"
green "✓ Installed $JAR_NAME → $DEST/"
echo
echo "Next: recreate the webapp so it re-scans the volume, then run:"
echo "  $0 --verify"
