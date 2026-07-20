---
name: core-verify
description: Run OpenELIS core (core/openelis) or analyzer-bridge (edge/drivers) Maven builds, tests, and spotless locally via Docker. Use whenever compiling, testing, or formatting Java in either submodule — this box has NO java/mvn on PATH, needs sg-docker wrapping, and is RAM-tight, so naive invocations fail in four distinct ways documented here.
---

# core-verify — Docker Maven recipe for this box

This box has **no `java`/`mvn` on PATH** (no SDKMAN either). All Maven work runs in the
cached Docker image `maven:3.9-eclipse-temurin-21`. Do not improvise the invocation —
four independent blockers were discovered the hard way and ALL are needed together:

1. **Network (re-verified 2026-07-19 — the IPv6 story has FLIPPED).** IPv6 to Maven
   Central is now broken while IPv4 works: do **NOT** add the old
   `-Djava.net.preferIPv6Addresses=true` flags — they now cause the resolution
   failures they used to fix. Keep `--network host` (bridge-network containers still
   lack working outbound).
2. **The shell is not in the docker group** → wrap every docker invocation in
   `sg docker -c '…'`. The docker socket group is gid **119** (it was 967 before a
   rebuild) → `--group-add 119` when testcontainers needs the socket.
3. With `--user "$(id -u)"` there is no passwd entry in-container, so Maven's `user.home`
   is not `$HOME` and the mounted `.m2` is **silently ignored** (symptom: `dataexport-api`
   "not found" though installed). → pass `-Dmaven.repo.local=/mvnhome/.m2/repository`.
4. Host `~/.m2` accumulates **root-owned files** from earlier root-run containers
   (`AccessDeniedException` on `_remote.repositories`).
   → fix: `docker run --rm -v ~/.m2:/m2 maven:3.9-eclipse-temurin-21 chown -R 1000:1000 /m2`.

## Core tests (targeted subsets — full suite is too RAM-heavy, ~2GB free)

```bash
sg docker -c 'docker run --rm --network host --user "$(id -u):$(id -g)" --group-add 119 \
  -e HOME=/mvnhome -e MAVEN_OPTS="-Xmx700m" \
  -e TESTCONTAINERS_RYUK_DISABLED=true \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v <core-worktree>:/work -v ~/.m2:/mvnhome/.m2 -w /work maven:3.9-eclipse-temurin-21 \
  mvn -B -Dmaven.repo.local=/mvnhome/.m2/repository test -Dtest="<TestClassPattern>" \
    -DfailIfNoTests=false -DargLine=-Xmx1300m'
```

- `--group-add 119` = docker group (for the testcontainers socket); testcontainers
  postgres:14.4 + ryuk images are already cached.
- Prefer CI for the full ~4500-test suite; use local Docker mainly for spotless and
  targeted `-Dtest=` subsets.
- **3 pre-existing flaky full-suite failures on core main** (don't chase; diff against a
  clean-main baseline): `ObservationFacadeTest.createObservation_shouldCreateNewResult`
  plus 2 `OrderEntryLabelRequestServiceAggregationTest` label-ordering tests.

## Core spotless (CI's only fast-fail — always apply before pushing)

Full-project `spotless:check` fails in the maven image (the `**/*.md` prettier step
needs npm) — scope with `-DspotlessFiles`:

```bash
sg docker -c 'docker run --rm --user "$(id -u):$(id -g)" -e HOME=/mvnhome -e MAVEN_OPTS="-Xmx1000m" \
  -v <core-worktree>:/work -v <scratch>/m2:/mvnhome/.m2 -v <scratch>/mvnhome:/mvnhome \
  -w /work maven:3.9-eclipse-temurin-21 \
  mvn -B spotless:apply -DspotlessFiles=".*Foo(Test)?[.]java"'   # regex over changed files
```

- **Scope the regex to EVERY changed file, not just `.java`** — spotless also formats
  XML (test fixtures, liquibase) and a hand-wrapped XML comment fails CI's
  `spotless:check` exactly like Java would (burned PR #39: `testdata/*.xml` comment
  wrapping). Build the regex from `git diff --name-only`, e.g.
  `-DspotlessFiles='.*(autoverification.*[.]java|testdata/autoverification-gate[.]xml)'`.
- Formatter config: `tools/OpenELIS_java_formatter.xml` (Eclipse JDT). Hand-formatting
  to match it is error-prone — always `spotless:apply`.
- **Flaky:** spotless downloads the eclipse-jdt formatter bundle at runtime and often
  times out (`Failed to load eclipse jdt formatter: SocketTimeoutException`). Transient —
  **retry**; once cached in the mounted `.m2`/HOME it succeeds. `apply` succeeding proves
  the file is clean even if a follow-up `check` times out.
- CI signature: a red Build+Test dying in ~90s = spotless; a long run means formatting
  passed and the full suite is executing.

## Bridge (edge/drivers) tests — local runs supplement CI

The bridge repo HAS CI (`.github/workflows/test.yml`: builds `astm-http-lib`, runs
root-module `mvn test`; PRs to master/develop) — that check, green on the exact PR
head, is the gate; local runs are for fast iteration before pushing. Two wrinkles when
reading that gate (both hit on `openelis-analyzer-bridge#50`):

- The workflow triggers on **`push` and `pull_request`**, so one SHA carries **two
  check-runs both named `test`**. `gh pr checks` shows two rows and **both** must be
  green — it is easy to read the passing one and miss the failing one.
- **Known socket flake:** `SnibeChecksumDelegationTest.checksumFalseRejectsE1381Framing`
  fails with `SocketException: Broken pipe` in CI while the identical tree passes
  locally and on the other trigger event. Re-run the failed job; don't hunt it in
  your diff.

The repo has **no aggregator pom**: `org.itech:astm-http-lib` is a sibling module not on Central,
so a bare `mvn test` at the root fails resolution. One Docker invocation:

```bash
sg docker -c 'docker run --rm --network host --user "$(id -u):$(id -g)" \
  -e HOME=/mvnhome -e MAVEN_OPTS="-Xmx700m" \
  -v <bridge-worktree>:/work -v ~/.m2:/mvnhome/.m2 -w /work maven:3.9-eclipse-temurin-21 \
  bash -c "mvn -B -Dmaven.repo.local=/mvnhome/.m2/repository -f astm-http-lib/pom.xml install -DskipTests && \
           mvn -B -Dmaven.repo.local=/mvnhome/.m2/repository test -DargLine=-Xmx1300m"'
```

(~1041 tests at the LIS-232 pin, ~2 min from a warm `.m2`. Prefer targeted `-Dtest=` —
the full suite has crashed a surefire fork on this RAM-tight box and passed on retry.)

## Cleanup gotcha

Never run the container as root: root-owned `target/` dirs make `git worktree remove`
and `rm -rf` fail with Permission denied. If it already happened:
`docker run --rm -v <worktree>:/w maven:3.9-eclipse-temurin-21 rm -rf /w/<module>/target`
then `git worktree prune`.

## Notes

- `~/.m2/settings.xml` already mirrors everything to Central except
  jaspersoft/shibboleth (packages.uwdigi.org is unreachable).
- The box co-hosts ERPNext stacks (own :8080/:8081 + a 172.20.x network) — stop them
  first if bringing up the full OpenELIS stack; RAM is the binding constraint.
