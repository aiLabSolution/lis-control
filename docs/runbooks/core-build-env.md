# Runbook — local OpenELIS core build/test env (for LIS-5/6/7/8 deltas)

How to build the OpenELIS core (`core/openelis`, branch `main`) **from source** and run its
tests locally, so LabSolution deltas (RBAC denial recording, audit-immutability triggers,
Result-table shape, LOINC/UCUM seed) can be developed test-first.

Distinct from the *bootstrap* gate (ADR-0002 / `docs/runbooks/core-bootstrap.md`), which boots
prebuilt images. This is the *from-source* path needed to compile + test code changes.

## Toolchain (user-space, no root)

OpenELIS `3.2.1.10` builds with **JDK 21 + Maven 3.9** and runs its integration tests via
**Testcontainers** (spins an ephemeral Postgres — needs Docker, no manual DB).

```bash
# One-time: JDK 21 + Maven into a user dir (example layout used on this box)
TOOLS=~/.local/share/openelis-build
mkdir -p "$TOOLS" && cd "$TOOLS"
curl -sL -o jdk21.tar.gz 'https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse?project=jdk'
curl -sL -o maven.tar.gz 'https://archive.apache.org/dist/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.tar.gz'
tar xzf jdk21.tar.gz && tar xzf maven.tar.gz
cat > env.sh <<'EOF'
export JAVA_HOME="$HOME/.local/share/openelis-build/jdk-21.0.11+10"
export PATH="$JAVA_HOME/bin:$HOME/.local/share/openelis-build/apache-maven-3.9.9/bin:$PATH"
EOF
```

`source ~/.local/share/openelis-build/env.sh` before any `mvn` command.

## Get the source

Develop in a checkout of the core repo on `main` (separate from the umbrella's pinned
submodule, to keep the umbrella clean):

```bash
git clone --branch main https://github.com/aiLabSolution/OpenELIS-Global-2.git openelis-dev
cd openelis-dev
git submodule update --init dataexport     # the build's one explicit submodule dependency
```

Do **not** init `tools/openelis-analyzer-bridge` (license-blocked, HOLD-001). The backend
build/test does not need it, nor the frontend, nor the other nested submodules.

## Build + test

```bash
source ~/.local/share/openelis-build/env.sh
# 1) build the dataexport dependency into the local ~/.m2
( cd dataexport && mvn clean install -DskipTests -Dspotless.check.skip=true )
# 2) compile main + tests
mvn clean test-compile -Dspotless.check.skip=true
# 3) run a single test (Testcontainers pulls a postgres image on first run)
mvn test -Dtest=<TestClassName> -Dspotless.check.skip=true
# full backend gate (what CI runs): mvn clean install -Dspotless.check.skip=true
```

The CI equivalent is the fork's `.github/workflows/backend.yml` (JDK 21 + Maven), which runs
on PRs to `main`. Keep `mvn spotless:check` clean (or run `mvn spotless:apply`) before pushing.

## Notes

- First `mvn` run downloads a large dependency tree (several minutes) across central +
  jaspersoft + shibboleth repos.
- Testcontainers needs a running Docker daemon; the test user must be able to talk to it.
