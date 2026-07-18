#!/usr/bin/env python3
"""Docker-backed local ports of the umbrella compose-stack gates.

These checks intentionally use the exact umbrella-pinned component checkouts.
They isolate proof resources from the development stacks, install the nested
dataexport gitlink locally, and register teardown before any compose ``up``.

Stage 0 follows accepted ADR-0021 and the current hosted workflow: images are
built from pinned source.  The retired digest overlay is teardown-compatibility
data and is never an input to a live local-CI operation.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


STAGE0_PROJECT = "lis-local-ci-stage0"
STAGE4_PROJECT = "lis-local-ci-stage4"
SITE_OE_PROJECT = "lis-local-ci-site-oe"
SITE_BRIDGE_PROJECT = "lis-local-ci-site-bridge"
SITE_NETWORK = "lis-local-ci-site"
SITE_BRIDGE_CONTAINER = "lis-local-ci-site-bridge"
SITE_BRIDGE_VOLUME = "lis-local-ci-site-bridge-data"
SITE_X3_PORT = "22021"
TIMEOUT_CLEANUP_RESERVE_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = {
    "stage0-bootstrap": 3600,
    "stage4-smoke": 3600,
    "site-stack-smoke": 7200,
}

PROOF_CONTAINERS = (
    "lis-proof-oe-certs",
    "lis-proof-openelisglobal-database",
    "lis-proof-openelisglobal-webapp",
    "lis-proof-external-fhir-api",
    "lis-proof-openelisglobal-front-end",
    "lis-proof-openelisglobal-proxy",
)
PROOF_VOLUMES = (
    "lis-proof-openelis-db-data",
    "lis-proof-openelis-key-trust-store",
    "lis-proof-openelis-certs",
    "lis-proof-openelis-keys",
    "lis-proof-openelis-lucene",
    "lis-proof-openelis-oe-logs",
    "lis-proof-openelis-tomcat-logs",
    "lis-proof-openelis-branding",
    "lis-proof-openelis-analyzer-imports",
    "lis-local-ci-openelis-programs",
)
PROOF_NETWORK = "lis-proof-openelis-default"

HISTORICAL_STAGE4_RED_SHA = "3ef18a894a93b619628ab6f75e870f8afcf7733b"
HISTORICAL_STAGE4_GREEN_SHA = "18ff1b6e2247754ef65fd798128af844d79ddb50"


class StackCheckError(RuntimeError):
    """An actionable local stack-check failure."""


@dataclass(frozen=True)
class Layout:
    root: Path
    core: Path
    kit: Path
    bridge: Path

    @classmethod
    def from_root(cls, root: Path, core_override: Path | None = None) -> "Layout":
        resolved = root.resolve()
        return cls(
            resolved,
            (core_override or resolved / "core/openelis").resolve(),
            resolved / "deploy/kit",
            resolved / "edge/drivers",
        )


def merged_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    if overrides:
        environment.update(overrides)
    return environment


def run_logged(
    argv: Sequence[str],
    cwd: Path,
    *,
    environment: Mapping[str, str] | None = None,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print(f"+ ({cwd}) {shlex.join(tuple(argv))}")
    try:
        result = subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=merged_environment(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise StackCheckError(f"could not run {argv[0]!r}: {exc}") from exc
    if result.stdout and not quiet:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    return result


def require_success(
    result: subprocess.CompletedProcess[str], label: str
) -> subprocess.CompletedProcess[str]:
    if result.returncode:
        tail = (result.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit {result.returncode} with no output"
        raise StackCheckError(f"{label} failed: {detail}")
    return result


def output(
    argv: Sequence[str], cwd: Path, environment: Mapping[str, str] | None = None
) -> str:
    return require_success(
        run_logged(argv, cwd, environment=environment, quiet=True),
        shlex.join(tuple(argv)),
    ).stdout.strip()


def require_docker() -> str:
    real_docker = shutil.which("docker")
    if not real_docker:
        raise StackCheckError(
            "Docker CLI with Compose v2 is required for stack heavy checks; "
            "no host-service fallback is supported"
        )
    version = run_logged(("docker", "compose", "version"), Path.cwd())
    require_success(version, "Docker Compose v2 preflight")
    return str(Path(real_docker).resolve())


def git_head(root: Path) -> str:
    return output(("git", "rev-parse", "HEAD"), root)


def verify_component_pin(root: Path, path: str, checkout: Path) -> None:
    expected = output(("git", "rev-parse", f"HEAD:{path}"), root)
    actual = git_head(checkout)
    if actual != expected:
        raise StackCheckError(
            f"{path} checkout is {actual[:12]}, not umbrella pin {expected[:12]}"
        )


def verify_exact_override(checkout: Path, expected_sha: str) -> None:
    if git_head(checkout) != expected_sha:
        raise StackCheckError(
            f"override core checkout must be exact {expected_sha}, got "
            f"{git_head(checkout)}"
        )
    status = output(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"), checkout
    )
    if status:
        raise StackCheckError("override core checkout must be clean")


def initialize_pins(
    layout: Layout,
    component_paths: Sequence[str],
    *,
    core_override_sha: str | None = None,
) -> None:
    umbrella_paths = [path for path in component_paths if path != "core/openelis"]
    if core_override_sha is None and "core/openelis" in component_paths:
        umbrella_paths.insert(0, "core/openelis")
    if umbrella_paths:
        require_success(
            run_logged(
                ("git", "submodule", "update", "--init", *umbrella_paths),
                layout.root,
            ),
            "pinned component initialization",
        )
    if "core/openelis" in component_paths:
        if core_override_sha is None:
            verify_component_pin(layout.root, "core/openelis", layout.core)
        else:
            verify_exact_override(layout.core, core_override_sha)
        require_success(
            run_logged(
                ("git", "submodule", "update", "--init", "dataexport"),
                layout.core,
            ),
            "pinned dataexport initialization",
        )
        verify_component_pin(layout.core, "dataexport", layout.core / "dataexport")
    for path in umbrella_paths:
        checkout = layout.root / path
        verify_component_pin(layout.root, path, checkout)


def root_owned_entries(root: Path) -> frozenset[str]:
    found: set[str] = set()
    for current, directories, files in os.walk(root):
        current_path = Path(current)
        for name in (*directories, *files):
            path = current_path / name
            try:
                if path.stat(follow_symlinks=False).st_uid == 0:
                    found.add(path.relative_to(root).as_posix())
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise StackCheckError(f"cannot inspect ownership of {path}: {exc}") from exc
    return frozenset(found)


@contextlib.contextmanager
def ownership_guard(root: Path):
    before = root_owned_entries(root)
    try:
        yield
    finally:
        after = root_owned_entries(root)
        introduced = sorted(after - before)
        if introduced:
            sample = ", ".join(introduced[:10])
            raise StackCheckError(
                f"stack check left root-owned paths in {root}: {sample}"
            )


class TeardownTrap:
    """LIFO cleanup trap that also runs for SIGINT/SIGTERM exceptions."""

    def __init__(self) -> None:
        self._callbacks: list[tuple[str, Callable[[], None]]] = []
        self._handlers: dict[int, object] = {}

    def add(self, label: str, callback: Callable[[], None]) -> None:
        self._callbacks.append((label, callback))

    def __enter__(self) -> "TeardownTrap":
        def interrupted(signum, _frame):
            raise KeyboardInterrupt(f"received signal {signum}")

        for signum in (signal.SIGINT, signal.SIGTERM):
            self._handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, interrupted)
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        failures: list[str] = []
        for label, callback in reversed(self._callbacks):
            try:
                print(f"local_ci stack teardown trap: {label}")
                callback()
            except Exception as cleanup_exc:  # cleanup must continue through all callbacks
                failures.append(f"{label}: {cleanup_exc}")
        for signum, handler in self._handlers.items():
            signal.signal(signum, handler)
        if failures:
            message = "; ".join(failures)
            if exc_type is None:
                raise StackCheckError(f"teardown failed: {message}")
            print(f"WARNING: teardown also failed: {message}", file=sys.stderr)
        return False


@contextlib.contextmanager
def graceful_deadline(timeout_seconds: int):
    """Raise before the engine hard timeout so teardown retains a grace window."""
    deadline = timeout_seconds - TIMEOUT_CLEANUP_RESERVE_SECONDS
    if deadline <= 0:
        raise StackCheckError(
            f"hard timeout {timeout_seconds}s is too short for the required "
            f"{TIMEOUT_CLEANUP_RESERVE_SECONDS}s cleanup reserve"
        )
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise StackCheckError(
            f"stack execution exceeded {deadline}s; beginning teardown with "
            f"{TIMEOUT_CLEANUP_RESERVE_SECONDS}s before the engine hard timeout"
        )

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(deadline)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@contextlib.contextmanager
def docker_isolation_environment(layout: Layout, real_docker: str):
    """Put the checked-in Docker pass-through shim first on PATH temporarily."""
    source = layout.root / "scripts/local_ci_docker_shim.py"
    if not source.is_file():
        raise StackCheckError(f"local-CI Docker shim is missing: {source}")
    with tempfile.TemporaryDirectory(prefix="lis-local-ci-docker-shim-") as temporary:
        executable = Path(temporary) / "docker"
        shutil.copy2(source, executable)
        executable.chmod(0o755)
        yield {
            "PATH": temporary + os.pathsep + os.environ.get("PATH", ""),
            "LIS_LOCAL_CI_REAL_DOCKER": real_docker,
            "LIS_LOCAL_CI_OPENELIS_ROOT": str(layout.core),
            "LIS_LOCAL_CI_OPENELIS_OVERLAY": str(
                layout.root / "deploy/ci/compose.local-ci-openelis.yml"
            ),
            "LIS_LOCAL_CI_BRIDGE_ROOT": str(layout.bridge),
            "LIS_LOCAL_CI_BRIDGE_OVERLAY": str(
                layout.root / "deploy/ci/compose.local-ci-bridge.yml"
            ),
        }


def compose_command(
    project: str,
    project_directory: Path,
    files: Iterable[Path],
    args: Sequence[str],
) -> tuple[str, ...]:
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(project_directory),
        "--project-name",
        project,
    ]
    for path in files:
        command.extend(("-f", str(path)))
    command.extend(args)
    return tuple(command)


def openelis_files(layout: Layout) -> tuple[Path, ...]:
    return (
        layout.core / "docker-compose.yml",
        layout.core / "build.docker-compose.yml",
        layout.core / ".github/ci/ci.memory-limits.yml",
        layout.kit / "compose/openelis-local-proof.yml",
        layout.root / "deploy/ci/compose.local-ci-openelis.yml",
    )


def image_list_sanity(text: str) -> None:
    images = [line.strip() for line in text.splitlines() if line.strip()]
    if len(images) < 3:
        raise StackCheckError(
            f"compose image-list sanity expected at least 3 images, got {images!r}"
        )
    floating = [image for image in images if image.endswith(":develop")]
    if floating:
        raise StackCheckError(
            "pinned-source compose unexpectedly selected retired floating images: "
            + ", ".join(floating)
        )
    print("image-list sanity: " + ", ".join(images))


def assert_project_empty(root: Path, project: str) -> None:
    containers = output(
        (
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ),
        root,
    )
    if containers:
        raise StackCheckError(
            f"Docker state is not clean; compose project {project} still has "
            f"containers: {containers}"
        )


def assert_objects_missing(root: Path, kind: str, names: Iterable[str]) -> None:
    leftovers = []
    for name in names:
        result = run_logged(("docker", kind, "inspect", name), root, quiet=True)
        if result.returncode == 0:
            leftovers.append(name)
    if leftovers:
        raise StackCheckError(
            f"Docker state is not clean; {kind} object(s) remain: "
            + ", ".join(leftovers)
        )


def assert_openelis_proof_clean(root: Path, project: str) -> None:
    assert_project_empty(root, project)
    assert_objects_missing(root, "container", PROOF_CONTAINERS)
    assert_objects_missing(root, "volume", PROOF_VOLUMES)
    assert_objects_missing(root, "network", (PROOF_NETWORK,))


def direct_openelis_down(layout: Layout, project: str) -> None:
    command = compose_command(
        project,
        layout.core,
        openelis_files(layout),
        ("down", "-v", "--remove-orphans"),
    )
    require_success(run_logged(command, layout.root), f"{project} teardown")
    assert_openelis_proof_clean(layout.root, project)


def wrapper_environment(layout: Layout, project: str) -> dict[str, str]:
    return {
        "LIS_CONTROL_ROOT": str(layout.root),
        "OPENELIS_ROOT": str(layout.core),
        "LIS_DEPLOY_USE_LOCAL_PROOF": "true",
        "COMPOSE_PROJECT_NAME": project,
    }


def openelis_wrapper(layout: Layout) -> Path:
    return layout.kit / "scripts/compose-openelis.sh"


def wrapper_openelis_down(layout: Layout, project: str, environment: Mapping[str, str]) -> None:
    result = run_logged(
        (str(openelis_wrapper(layout)), "down", "-v"),
        layout.root,
        environment=environment,
    )
    require_success(result, f"{project} wrapper teardown")
    assert_openelis_proof_clean(layout.root, project)


def healthcheck(layout: Layout, environment: Mapping[str, str]) -> None:
    require_success(
        run_logged(
            ("bash", str(layout.root / "deploy/ci/healthcheck.sh")),
            layout.root,
            environment=environment,
        ),
        "OpenELIS health check",
    )


def diagnose_openelis(layout: Layout, project: str, environment: Mapping[str, str] | None = None) -> None:
    command = compose_command(
        project, layout.core, openelis_files(layout), ("ps",)
    )
    run_logged(command, layout.root, environment=environment)
    for container in PROOF_CONTAINERS:
        run_logged(("docker", "logs", "--tail", "150", container), layout.root)


def stage0_bootstrap(layout: Layout) -> None:
    initialize_pins(layout, ("core/openelis", "deploy/kit"))
    require_docker()
    files = openelis_files(layout)
    with ownership_guard(layout.core), TeardownTrap() as trap:
        trap.add(
            "Stage-0 isolated source-build stack",
            lambda: direct_openelis_down(layout, STAGE0_PROJECT),
        )
        try:
            images = require_success(
                run_logged(
                    compose_command(
                        STAGE0_PROJECT, layout.core, files, ("config", "--images")
                    ),
                    layout.root,
                ),
                "Stage-0 compose image render",
            )
            image_list_sanity(images.stdout)
            require_success(
                run_logged(
                    compose_command(
                        STAGE0_PROJECT,
                        layout.core,
                        files,
                        ("up", "-d", "--build"),
                    ),
                    layout.root,
                ),
                "Stage-0 pinned-source compose up",
            )
            healthcheck(
                layout,
                {
                    "BASE_URL": "https://localhost:10443",
                    "DB_CONTAINER": "lis-proof-openelisglobal-database",
                    "WEBAPP_CONTAINER": "lis-proof-openelisglobal-webapp",
                    "TIMEOUT": "600",
                },
            )
        except Exception:
            diagnose_openelis(layout, STAGE0_PROJECT)
            raise
    print("OK stage0-bootstrap")


def stage4_smoke(layout: Layout, core_override_sha: str | None = None) -> None:
    initialize_pins(
        layout,
        ("core/openelis", "deploy/kit"),
        core_override_sha=core_override_sha,
    )
    real_docker = require_docker()
    wrapper = openelis_wrapper(layout)
    with docker_isolation_environment(layout, real_docker) as isolation:
        environment = {**wrapper_environment(layout, STAGE4_PROJECT), **isolation}
        with ownership_guard(layout.core), TeardownTrap() as trap:
            trap.add(
                "Stage-4 deploy-kit proof stack",
                lambda: wrapper_openelis_down(
                    layout, STAGE4_PROJECT, environment
                ),
            )
            try:
                require_success(
                    run_logged(
                        (str(wrapper), "config", "-q"),
                        layout.root,
                        environment=environment,
                    ),
                    "Stage-4 deploy-kit plan validation",
                )
                images = require_success(
                    run_logged(
                        (str(wrapper), "config", "--images"),
                        layout.root,
                        environment=environment,
                    ),
                    "Stage-4 deploy-kit image render",
                )
                image_list_sanity(images.stdout)
                require_success(
                    run_logged(
                        (
                            str(wrapper),
                            "up",
                            "-d",
                            "certs",
                            "db.openelis.org",
                            "oe.openelis.org",
                        ),
                        layout.root,
                        environment=environment,
                    ),
                    "Stage-4 deploy-kit source-build install",
                )
                proof_environment = {
                    **environment,
                    "HEALTH_URL": "https://localhost:18443/api/OpenELIS-Global/health",
                    "DB_CONTAINER": "lis-proof-openelisglobal-database",
                    "WEBAPP_CONTAINER": "lis-proof-openelisglobal-webapp",
                    "TIMEOUT": "600",
                }
                healthcheck(layout, proof_environment)
                require_success(
                    run_logged(
                        (
                            "bash",
                            str(layout.root / "deploy/ci/smoke-diagnostic-report.sh"),
                        ),
                        layout.root,
                        environment={
                            **proof_environment,
                            "BASE_URL": "https://localhost:18443/api/OpenELIS-Global",
                        },
                    ),
                    "finalized FHIR DiagnosticReport read",
                )
            except Exception:
                run_logged(
                    (str(wrapper), "ps"),
                    layout.root,
                    environment=environment,
                )
                for container in (
                    "lis-proof-openelisglobal-webapp",
                    "lis-proof-openelisglobal-database",
                ):
                    run_logged(
                        ("docker", "logs", "--tail", "200", container),
                        layout.root,
                        environment=environment,
                    )
                raise
    print("OK stage4-smoke")


def site_environment(layout: Layout, password: str) -> dict[str, str]:
    extra_properties = layout.kit / ".state/local-ci-site/extra.properties"
    return {
        # compose-site.sh rejects an ambient project name because it manages
        # the independently named OpenELIS and bridge projects below.
        "COMPOSE_PROJECT_NAME": "",
        "LIS_CONTROL_ROOT": str(layout.root),
        "OPENELIS_ROOT": str(layout.core),
        "BRIDGE_ROOT": str(layout.bridge),
        "LIS_DEPLOY_KIT_ROOT": str(layout.kit),
        "LIS_DEPLOY_BRIDGE_ROOT": str(layout.bridge),
        "LIS_DEPLOY_USE_LOCAL_PROOF": "true",
        "LIS_DEPLOY_SITE": "true",
        "LIS_SITE_NETWORK": SITE_NETWORK,
        "LIS_SITE_X3_BIND": SITE_X3_PORT,
        "LIS_SITE_OE_PROJECT": SITE_OE_PROJECT,
        "LIS_SITE_BRIDGE_PROJECT": SITE_BRIDGE_PROJECT,
        "LIS_SITE_OE_TRUST_VOLUME": "lis-proof-openelis-key-trust-store",
        "LIS_SITE_EXTRA_PROPERTIES": str(extra_properties),
        "LIS_SITE_OE_USER": "admin",
        "LIS_SITE_OE_PASSWORD": "adminADMIN!",
        "LIS_SITE_OE_SERVICES": "certs db.openelis.org oe.openelis.org",
        "BRIDGE_AUTH_PASSWORD": password,
        "OE_PROJECT": SITE_OE_PROJECT,
        "BRIDGE_PROJECT": SITE_BRIDGE_PROJECT,
        "OE_BASE_URL": "https://localhost:18443/api/OpenELIS-Global",
        "X3_PORT": SITE_X3_PORT,
        "X3_FIXTURE_FILE": str(
            layout.root
            / "edge/sim/fixtures/snibelis-maglumi-x3-result-upload/message.astm"
        ),
        "CLEAN": "true",
    }


def site_wrapper(layout: Layout) -> Path:
    return layout.kit / "scripts/compose-site.sh"


def site_down(layout: Layout, environment: Mapping[str, str]) -> None:
    cleanup_environment = {
        **environment,
        "LIS_DEPLOY_CONFIRM_DESTROY": "true",
    }
    failures: list[str] = []

    def attempt(label: str, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:
            failures.append(f"{label}: {exc}")

    def wrapper_down() -> None:
        result = run_logged(
            (str(site_wrapper(layout)), "down", "-v"),
            layout.root,
            environment=cleanup_environment,
        )
        require_success(result, "site wrapper teardown")

    attempt("canonical site wrapper down", wrapper_down)
    attempt(
        "OpenELIS proof-state assertion",
        lambda: assert_openelis_proof_clean(layout.root, SITE_OE_PROJECT),
    )
    attempt(
        "bridge project assertion",
        lambda: assert_project_empty(layout.root, SITE_BRIDGE_PROJECT),
    )
    attempt(
        "bridge container assertion",
        lambda: assert_objects_missing(
            layout.root, "container", (SITE_BRIDGE_CONTAINER,)
        ),
    )
    attempt(
        "bridge volume assertion",
        lambda: assert_objects_missing(layout.root, "volume", (SITE_BRIDGE_VOLUME,)),
    )
    attempt(
        "site network assertion",
        lambda: assert_objects_missing(layout.root, "network", (SITE_NETWORK,)),
    )
    attempt(
        "rendered site-secret removal",
        lambda: Path(environment["LIS_SITE_EXTRA_PROPERTIES"]).unlink(missing_ok=True),
    )
    if failures:
        raise StackCheckError("; ".join(failures))


def diagnose_site(layout: Layout, environment: Mapping[str, str]) -> None:
    run_logged((str(site_wrapper(layout)), "ps"), layout.root, environment=environment)
    for container in (
        SITE_BRIDGE_CONTAINER,
        "lis-proof-openelisglobal-webapp",
        "lis-proof-openelisglobal-database",
    ):
        run_logged(("docker", "logs", "--tail", "200", container), layout.root)


def site_stack_smoke(layout: Layout) -> None:
    initialize_pins(layout, ("core/openelis", "deploy/kit", "edge/drivers"))
    real_docker = require_docker()
    password = secrets.token_hex(24)
    with docker_isolation_environment(layout, real_docker) as isolation:
        environment = {**site_environment(layout, password), **isolation}
        with ownership_guard(layout.core), ownership_guard(
            layout.bridge
        ), TeardownTrap() as trap:
            trap.add(
                "isolated site stack",
                lambda: site_down(layout, environment),
            )
            try:
                require_success(
                    run_logged(
                        ("bash", str(layout.kit / "tests/compose-site.sh")),
                        layout.root,
                        environment=environment,
                    ),
                    "deploy-kit site wrapper regression tests",
                )
                require_success(
                    run_logged(
                        (str(site_wrapper(layout)), "config", "-q"),
                        layout.root,
                        environment=environment,
                    ),
                    "canonical site install-plan render",
                )
                require_success(
                    run_logged(
                        (str(site_wrapper(layout)), "up"),
                        layout.root,
                        environment=environment,
                    ),
                    "canonical site stack up/readiness gate",
                )
                require_success(
                    run_logged(
                        (
                            "bash",
                            str(layout.kit / "scripts/prove-site-x3-e2e.sh"),
                        ),
                        layout.root,
                        environment=environment,
                    ),
                    "synthetic X3 ASTM end-to-end proof",
                )
                require_success(
                    run_logged(
                        (
                            "bash",
                            str(layout.kit / "scripts/prove-site-failure-modes.sh"),
                        ),
                        layout.root,
                        environment=environment,
                    ),
                    "canonical site failure-mode proofs",
                )
                require_success(
                    run_logged(
                        (str(site_wrapper(layout)), "ready"),
                        layout.root,
                        environment=environment,
                    ),
                    "final site readiness re-assertion",
                )
            except Exception:
                diagnose_site(layout, environment)
                raise
    print("OK site-stack-smoke")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a LIS local-CI compose-stack check")
    parser.add_argument(
        "check", choices=("stage0-bootstrap", "stage4-smoke", "site-stack-smoke")
    )
    parser.add_argument(
        "--root",
        help="exact umbrella checkout (defaults to LIS_LOCAL_CI_CHECKOUT)",
    )
    parser.add_argument(
        "--core-checkout",
        help="explicit clean core checkout for the Stage-4 historical acid test",
    )
    parser.add_argument(
        "--expected-core-sha",
        help=(
            "exact SHA for --core-checkout; historical red "
            f"{HISTORICAL_STAGE4_RED_SHA}, fixed green {HISTORICAL_STAGE4_GREEN_SHA}"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root_value = args.root or os.environ.get("LIS_LOCAL_CI_CHECKOUT")
    if not root_value:
        print("ERROR: --root or LIS_LOCAL_CI_CHECKOUT is required", file=sys.stderr)
        return 2
    if bool(args.core_checkout) != bool(args.expected_core_sha):
        print(
            "ERROR: --core-checkout and --expected-core-sha must be provided together",
            file=sys.stderr,
        )
        return 2
    if args.core_checkout and args.check != "stage4-smoke":
        print("ERROR: the core override is only valid for stage4-smoke", file=sys.stderr)
        return 2
    layout = Layout.from_root(
        Path(root_value), Path(args.core_checkout) if args.core_checkout else None
    )
    timeout_value = os.environ.get(
        "LIS_LOCAL_CI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS[args.check])
    )
    try:
        try:
            timeout_seconds = int(timeout_value)
        except ValueError as exc:
            raise StackCheckError(
                f"LIS_LOCAL_CI_TIMEOUT_SECONDS must be an integer, got {timeout_value!r}"
            ) from exc
        with graceful_deadline(timeout_seconds):
            if args.check == "stage0-bootstrap":
                stage0_bootstrap(layout)
            elif args.check == "stage4-smoke":
                stage4_smoke(layout, args.expected_core_sha)
            else:
                site_stack_smoke(layout)
    except StackCheckError as exc:
        print(f"ERROR {args.check}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
