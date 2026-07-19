#!/usr/bin/env python3
"""Docker-backed OpenELIS heavy checks for the local-CI registry.

The host intentionally supplies neither Java nor Maven.  Backend verification
therefore follows the repository's core-verify contract exactly: the pinned
Maven/Temurin-21 image, host networking on this IPv6-only machine, explicit
IPv6 JVM selection, a non-root container user, and the Docker socket for
Testcontainers.  A named volume preserves Maven artifacts between runs.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence


MAVEN_IMAGE = "maven:3.9-eclipse-temurin-21"
MAVEN_CACHE_VOLUME = "lis-local-ci-maven-repository-v1"
DOCKER_SOCKET = Path("/var/run/docker.sock")
STATUS_DETAIL_ENV = "LIS_LOCAL_CI_STATUS_DETAIL_FILE"
MAVEN_REPOSITORY = "/mvnhome/.m2/repository"
MAVEN_OPTS = "-Xmx700m -Djava.net.preferIPv6Addresses=true"
SUREFIRE_ARGLINE = "-Xmx1300m -Djava.net.preferIPv6Addresses=true"
# Deliberate, visible parity gaps — hosted spotless remains the authority:
# 1. The pinned Maven image ships no npm, so the pom's `**/*.md` prettier
#    format cannot run locally (proved on core main 670644335: spotless dies
#    on src/test/resources/FIXTURE_LOADER_README.md).  The leading lookahead
#    removes the Markdown files from scope.
# 2. The alternation scopes to backend-trigger-shaped paths, so hosted-checked
#    files outside them (root *.sh, .gitignore, tools/** xml) are locally
#    unchecked as well.
SPOTLESS_BACKEND_FILES_REGEX = (
    "(?!.*[.]md$)"
    ".*(pom[.]xml|src/.*|fhir/.*|Dockerfile|build[.]docker-compose[.]yml|"
    "docker-compose[.]yml|dev[.]docker-compose[.]yml|"
    "docker-compose[.]letsencrypt[.]yml|"
    "[.]github/ci/ci[.]analyzer-harness[.]yml|"
    "[.]github/workflows/backend[.]yml)"
)

# These failures are pre-existing on a clean core-main full-suite baseline and
# are order-dependent.  Matching is deliberately exact (package-qualified
# class + method, parameter suffix stripped) and fail-closed: any other
# failure leaves the check red.
#
# Admission criterion — every entry must have all three proofs, recorded in the
# slice evidence before it is added here:
#   1. fails in a full-suite run on a clean core-main checkout,
#   2. passes in isolation (targeted -Dtest= run) on the same checkout+image,
#   3. hosted backend CI is green at that same SHA.
# First three: baseline established pre-LIS-283.  Last three: full-suite run on
# core main 670644335 (2026-07-19) failed exactly these and both classes passed
# 6/6 and 12/12 in isolation on the identical checkout.
BASELINE_FLAKES = frozenset(
    {
        "org.openelisglobal.fhir.ObservationFacadeTest."
        "createObservation_shouldCreateNewResult",
        "org.openelisglobal.labelpreset.service."
        "OrderEntryLabelRequestServiceAggregationTest."
        "ac13_columnOrdering_systemFirstThenCustomAlphabetical",
        "org.openelisglobal.labelpreset.service."
        "OrderEntryLabelRequestServiceAggregationTest."
        "determinism_sameInputsProduceSameOutput",
        "org.openelisglobal.labelpreset.service."
        "OrderEntryLabelRequestServiceAggregationTest."
        "fr014a_seededSpecimenLabel_isSampleColumn_onNoLinkOrder",
        "org.openelisglobal.analyzerresults.service."
        "AnalyzerResultsAcceptUnmatchedGateTest."
        "acceptNoSampleGroup_withConfirmation_persistsUnderUnknownPatientWithAuditNote",
        "org.openelisglobal.analyzerresults.service."
        "AnalyzerResultsAcceptUnmatchedGateTest."
        "secondArrivalOnAnalyzerCreatedSample_stillRequiresConfirmation",
    }
)

# Recursive so a future modularized core (nested */target report dirs) cannot
# silently fall out of scope; today only the root module exists.
REPORT_PATTERNS = (
    "**/target/surefire-reports/TEST-*.xml",
    "**/target/failsafe-reports/TEST-*.xml",
)

# When surefire's forked VM dies (OOM kill, crash), per-test XML is truncated
# or missing entirely and per-testcase parsing cannot be trusted.
FORK_CRASH_MARKERS = (
    "The forked VM terminated",
    "Crashed tests",
)


class HeavyCheckError(RuntimeError):
    """An actionable heavy-check failure."""


def run_logged(
    argv: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    print(f"+ ({cwd}) {shlex.join(tuple(argv))}")
    try:
        result = subprocess.run(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise HeavyCheckError(f"could not run {argv[0]!r}: {exc}") from exc
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    return result


def require_docker(*, require_socket: bool) -> None:
    if not shutil.which("docker"):
        raise HeavyCheckError(
            "Docker CLI is required for OpenELIS heavy checks; install/expose "
            "Docker and retry (Java/Maven host fallbacks are intentionally forbidden)"
        )
    if require_socket and not DOCKER_SOCKET.exists():
        raise HeavyCheckError(
            f"Docker socket {DOCKER_SOCKET} is required for the full core "
            "Testcontainers suite"
        )


def _settings_file() -> Path | None:
    candidate = Path.home() / ".m2/settings.xml"
    return candidate if candidate.is_file() else None


def maven_docker_command(
    checkout: Path,
    workdir: str,
    maven_args: Sequence[str],
    *,
    uid: int,
    gid: int,
    docker_gid: int,
    include_socket: bool,
    settings_file: Path | None,
) -> tuple[str, ...]:
    container_workdir = "/work" + (f"/{workdir.strip('/')}" if workdir else "")
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--user",
        f"{uid}:{gid}",
        "-e",
        "HOME=/mvnhome",
        "-e",
        f"MAVEN_OPTS={MAVEN_OPTS}",
    ]
    if include_socket:
        argv.extend(
            [
                "--group-add",
                str(docker_gid),
                "-e",
                "TESTCONTAINERS_RYUK_DISABLED=true",
                "-v",
                f"{DOCKER_SOCKET}:{DOCKER_SOCKET}",
            ]
        )
    argv.extend(["-v", f"{MAVEN_CACHE_VOLUME}:{MAVEN_REPOSITORY}"])
    if settings_file is not None:
        argv.extend(
            ["-v", f"{settings_file}:/mvnhome/.m2/settings.xml:ro"]
        )
    argv.extend(
        [
            "-v",
            f"{checkout.resolve()}:/work",
            "-w",
            container_workdir,
            MAVEN_IMAGE,
            "mvn",
            "-B",
        ]
    )
    if settings_file is not None:
        # The arbitrary numeric container user has no passwd entry, so Maven's
        # inferred user.home is unreliable. Select the mounted settings file
        # explicitly for the same reason the repository path is explicit.
        argv.extend(("--settings", "/mvnhome/.m2/settings.xml"))
    argv.extend((f"-Dmaven.repo.local={MAVEN_REPOSITORY}", *maven_args))
    return tuple(argv)


def frontend_docker_command(checkout: Path, sha: str) -> tuple[str, ...]:
    suffix = sha[:12].lower() if re.fullmatch(r"[0-9a-fA-F]{40}", sha) else "standalone"
    frontend = checkout.resolve() / "frontend"
    return (
        "docker",
        "build",
        "--network",
        "host",
        "--progress",
        "plain",
        "--file",
        str(frontend / "Dockerfile"),
        "--tag",
        f"lis-local-ci/openelis-frontend:{suffix}",
        str(frontend),
    )


def ensure_maven_cache(cwd: Path, uid: int, gid: int) -> None:
    created = run_logged(("docker", "volume", "create", MAVEN_CACHE_VOLUME), cwd)
    if created.returncode:
        raise HeavyCheckError("could not create the persistent local-CI Maven volume")
    # Docker creates named-volume roots as root.  This narrowly scoped init
    # container touches only the cache volume; every source-mounted build runs
    # as the invoking non-root user.
    ownership = run_logged(
        (
            "docker",
            "run",
            "--rm",
            "-v",
            f"{MAVEN_CACHE_VOLUME}:/repository",
            MAVEN_IMAGE,
            "chown",
            "-R",
            f"{uid}:{gid}",
            "/repository",
        ),
        cwd,
    )
    if ownership.returncode:
        raise HeavyCheckError("could not make the persistent Maven volume writable")


def _formatter_download_flake(output: str) -> bool:
    return (
        "Failed to load eclipse jdt formatter" in output
        and "SocketTimeoutException" in output
    )


def run_spotless_with_retry(
    command: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    result = run_logged(command, cwd)
    if result.returncode and _formatter_download_flake(result.stdout or ""):
        print(
            "RETRY: known eclipse-jdt formatter download timeout; retrying once "
            "against the persistent Maven cache"
        )
        return run_logged(command, cwd)
    return result


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _report_roots(checkout: Path):
    for pattern in REPORT_PATTERNS:
        for report in sorted(checkout.glob(pattern)):
            try:
                yield report, ET.parse(report).getroot()
            except (OSError, ET.ParseError) as exc:
                raise HeavyCheckError(f"cannot parse Maven test report {report}: {exc}") from exc


def failed_test_ids(checkout: Path) -> frozenset[str]:
    failures: set[str] = set()
    for _report, root in _report_roots(checkout):
        for case in root.iter():
            if _local_tag(case) != "testcase":
                continue
            if not any(
                _local_tag(child) in {"failure", "error"} for child in case
            ):
                continue
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "").split("[", 1)[0]
            if classname and name:
                failures.add(f"{classname}.{name}")
    return frozenset(failures)


def reported_failure_total(checkout: Path) -> int:
    """Sum the testsuite-level failure+error counters across all reports.

    Surefire counts suite-level errors (crashed setup, unnameable testcases)
    in these attributes even when no parseable <testcase> child carries the
    failure, so this is the reconciliation anchor for absorption.
    """
    total = 0
    for report, root in _report_roots(checkout):
        for element in root.iter():
            if _local_tag(element) != "testsuite":
                continue
            try:
                total += int(element.attrib.get("failures") or 0)
                total += int(element.attrib.get("errors") or 0)
            except ValueError as exc:
                raise HeavyCheckError(
                    f"unparseable failure counters in {report}: {exc}"
                ) from exc
    return total


def fork_crash_detected(output: str) -> bool:
    return any(marker in output for marker in FORK_CRASH_MARKERS)


def can_absorb(failures: frozenset[str]) -> bool:
    return bool(failures) and failures.issubset(BASELINE_FLAKES)


def report_absorption(failures: frozenset[str], detail_path: Path | None) -> None:
    print("!" * 78)
    print("BASELINE FLAKE ALLOWLIST ABSORBED — CHECK IS GREEN WITH EXPLICIT DEBT")
    for test_id in sorted(failures):
        print(f"ALLOWLISTED EXACT TEST: {test_id}")
    print("No unlisted test failure was absorbed.")
    print("!" * 78)
    if detail_path is not None:
        try:
            detail_path.write_text(
                f"passed; absorbed {len(failures)} baseline flakes\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise HeavyCheckError(f"cannot write status-detail evidence: {exc}") from exc


def _require_file(path: Path, message: str) -> None:
    if not path.is_file():
        raise HeavyCheckError(f"{message}: missing {path}")


def _require_success(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode:
        raise HeavyCheckError(f"{label} failed with exit {result.returncode}")


def core_backend(checkout: Path) -> None:
    checkout = checkout.resolve()
    require_docker(require_socket=True)
    _require_file(checkout / "pom.xml", "not an OpenELIS core checkout")
    _require_file(
        checkout / "dataexport/pom.xml",
        "dataexport submodule is not initialized; run git submodule update --init dataexport",
    )

    uid, gid = os.getuid(), os.getgid()
    docker_gid = DOCKER_SOCKET.stat().st_gid
    settings = _settings_file()
    ensure_maven_cache(checkout, uid, gid)

    def maven(
        workdir: str, args: Sequence[str], *, socket: bool = False
    ) -> tuple[str, ...]:
        return maven_docker_command(
            checkout,
            workdir,
            args,
            uid=uid,
            gid=gid,
            docker_gid=docker_gid,
            include_socket=socket,
            settings_file=settings,
        )

    spotless = run_spotless_with_retry(
        maven(
            "",
            (
                "spotless:check",
                f"-DspotlessFiles={SPOTLESS_BACKEND_FILES_REGEX}",
            ),
        ),
        checkout,
    )
    _require_success(spotless, "core formatting check")

    dataexport = run_logged(maven("dataexport", ("clean", "install")), checkout)
    _require_success(dataexport, "dataexport build")

    full_build = run_logged(
        maven(
            "",
            (
                "clean",
                "install",
                "-Dspotless.check.skip=true",
                f"-DargLine={SUREFIRE_ARGLINE}",
            ),
            socket=True,
        ),
        checkout,
    )
    if full_build.returncode == 0:
        print("OK core-backend")
        return

    # Absorption guards, all fail-closed.  1: a crashed surefire fork leaves
    # truncated/absent XML, so per-testcase parsing cannot be trusted.  2: the
    # testsuite counters must reconcile exactly with the parsed testcases, or
    # some failure (suite-level error, unnameable testcase) is not attributable
    # to an exact allowlisted test.  3: only the exact baseline set absorbs.
    if fork_crash_detected(full_build.stdout or ""):
        raise HeavyCheckError(
            f"full core build failed with exit {full_build.returncode} and the "
            "output carries a surefire fork-crash marker; absorption refused "
            "because per-test reports cannot be trusted after a crashed fork"
        )
    failures = failed_test_ids(checkout)
    reported = reported_failure_total(checkout)
    if reported != len(failures):
        raise HeavyCheckError(
            f"full core build failed with exit {full_build.returncode}; test "
            f"reports count {reported} failure(s)/error(s) but only "
            f"{len(failures)} exact failing testcase(s) were parsed — "
            "absorption refused because not every failure is attributable to "
            "an exact test"
        )
    if not can_absorb(failures):
        unlisted = sorted(failures - BASELINE_FLAKES)
        rendered = ", ".join(unlisted) or "no failing test reports found"
        allowlisted_note = (
            f" ({len(failures) - len(unlisted)} allowlisted baseline flake(s) "
            "also failed)"
            if failures and unlisted and len(unlisted) != len(failures)
            else ""
        )
        raise HeavyCheckError(
            f"full core build failed with exit {full_build.returncode}; "
            f"unabsorbed failures: {rendered}{allowlisted_note}"
        )

    # A test-phase failure stops Maven before packaging/install.  Complete that
    # phase without rerunning tests, then publish the explicit absorption.
    package = run_logged(
        maven(
            "",
            (
                "install",
                "-DskipTests",
                "-Dmaven.test.skip=true",
                "-DskipITs=true",
                "-Dspotless.check.skip=true",
            ),
        ),
        checkout,
    )
    _require_success(package, "post-allowlist core packaging")
    detail_value = os.environ.get(STATUS_DETAIL_ENV)
    report_absorption(failures, Path(detail_value) if detail_value else None)
    print("OK core-backend (allowlisted baseline flakes absorbed visibly)")


def core_frontend(checkout: Path) -> None:
    # Covers the hosted frontend workflow's Image job only.  Its blocking
    # static-checks job (prettier --check + ESLint) is a known, documented
    # local gap: local core-frontend green must never be read as hosted
    # frontend-workflow green.
    checkout = checkout.resolve()
    require_docker(require_socket=False)
    _require_file(checkout / "frontend/Dockerfile", "not an OpenELIS core checkout")
    sha = os.environ.get("LIS_LOCAL_CI_HEAD_SHA", "")
    result = run_logged(frontend_docker_command(checkout, sha), checkout)
    _require_success(result, "production frontend image build")
    print("OK core-frontend")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a LIS local-CI core heavy check")
    parser.add_argument("check", choices=("core-backend", "core-frontend"))
    parser.add_argument(
        "--checkout",
        help="exact OpenELIS component checkout (defaults to LIS_LOCAL_CI_CHECKOUT)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    checkout_value = args.checkout or os.environ.get("LIS_LOCAL_CI_CHECKOUT")
    if not checkout_value:
        print(
            "ERROR: --checkout or LIS_LOCAL_CI_CHECKOUT is required",
            file=sys.stderr,
        )
        return 2
    try:
        if args.check == "core-backend":
            core_backend(Path(checkout_value))
        else:
            core_frontend(Path(checkout_value))
    except HeavyCheckError as exc:
        print(f"ERROR {args.check}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
