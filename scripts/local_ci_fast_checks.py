#!/usr/bin/env python3
"""Standalone implementations of the cheap component-aware local CI checks.

The module has no Python dependencies outside the standard library. External
tools are invoked as argv arrays; versioned tools that are absent from the host
PATH are supplied by ``mise x``.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


SHELLCHECK_TOOL = "shellcheck@0.10.0"
COMPOSE_TOOL = "docker-compose@2.27.1"
JAVA_TOOL = "java@temurin-21"
MAVEN_TOOL = "maven@3.9.9"
MAVEN_IMAGE = "maven:3.9-eclipse-temurin-21"
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64}) [ *](.+)$")
SCRIPT_CONTROL_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DRIFT_SCOPES = frozenset(("notes-only", "full-file"))


class FastCheckError(RuntimeError):
    """A check failed with an actionable explanation."""


def _display(argv: Sequence[str]) -> str:
    return " ".join(repr(item) if any(char.isspace() for char in item) else item for item in argv)


def run_checked(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> str:
    """Run one command, echo its output, and turn failures into check failures."""
    print(f"+ ({cwd}) {_display(argv)}")
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise FastCheckError(f"could not run {argv[0]!r}: {exc}") from exc
    output = proc.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if proc.returncode != 0:
        raise FastCheckError(
            f"command failed with exit {proc.returncode}: {_display(argv)}"
        )
    return output


def mise_command(tools: Sequence[str], command: Sequence[str]) -> tuple[str, ...]:
    return ("mise", "x", *tools, "--", *command)


def git_output(checkout: Path, *arguments: str) -> str:
    return run_checked(("git", *arguments), cwd=checkout).strip()


def assert_gitlink(control_root: Path, relative: str) -> Path:
    component = control_root / relative
    if not component.is_dir():
        raise FastCheckError(
            f"{relative} is not initialized; initialize the pinned submodule before retrying"
        )
    try:
        expected = git_output(control_root, "rev-parse", f"HEAD:{relative}")
        actual = git_output(component, "rev-parse", "HEAD")
    except FastCheckError as exc:
        raise FastCheckError(
            f"cannot verify initialized {relative} checkout against its umbrella gitlink: {exc}"
        ) from exc
    if not SHA_RE.fullmatch(expected) or not SHA_RE.fullmatch(actual):
        raise FastCheckError(f"git returned malformed pin metadata for {relative}")
    if actual.lower() != expected.lower():
        raise FastCheckError(
            f"{relative} checkout is {actual}, but umbrella HEAD pins {expected}; "
            "check out the exact gitlink before retrying"
        )
    print(f"OK gitlink: {relative} = {expected}")
    return component


def read_allowlist(path: Path) -> dict[str, tuple[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FastCheckError(f"cannot read profile drift allowlist {path}: {exc}") from exc
    entries: dict[str, tuple[str, str]] = {}
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=2)
        relative = fields[0]
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts or "\\" in relative:
            raise FastCheckError(
                f"{path}:{number}: allowlist path must be a relative POSIX path"
            )
        if len(fields) < 2 or fields[1] not in PROFILE_DRIFT_SCOPES:
            scopes = " or ".join(sorted(PROFILE_DRIFT_SCOPES))
            raise FastCheckError(
                f"{path}:{number}: allowlist scope must be {scopes}"
            )
        if len(fields) < 3:
            raise FastCheckError(f"{path}:{number}: allowlist reason is required")
        scope, reason = fields[1:]
        if relative in entries:
            raise FastCheckError(f"{path}:{number}: duplicate allowlist path {relative}")
        entries[relative] = (scope, reason)
    return entries


def _relative_files(root: Path) -> tuple[str, ...]:
    if not root.is_dir():
        raise FastCheckError(f"required directory is missing: {root}")
    return tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    )


def check_profile_drift(control_root: Path, core: Path, kit: Path) -> None:
    core_profiles = core / "projects/analyzer-profiles"
    kit_profiles = kit / "configs/analyzer-profiles"
    allowlist_path = control_root / "deploy/ci/profile-drift-allowlist.txt"
    allowlist = read_allowlist(allowlist_path)
    failures: list[str] = []

    kit_files = _relative_files(kit_profiles)
    for relative in kit_files:
        kit_file = kit_profiles / relative
        core_file = core_profiles / relative
        allowed = allowlist.get(relative)
        if not core_file.is_file():
            if allowed and allowed[0] == "full-file":
                scope, reason = allowed
                print(f"ALLOWED kit-only profile: {relative} ({scope}: {reason})")
            elif allowed:
                failures.append(
                    f"kit-only profile outside notes-only scope: {relative}"
                )
            else:
                failures.append(f"kit-only profile not present in core mirror: {relative}")
            continue
        if kit_file.read_bytes() == core_file.read_bytes():
            print(f"OK profile in-sync: {relative}")
            continue
        if allowed and allowed[0] == "full-file":
            scope, reason = allowed
            print(f"ALLOWED profile divergence: {relative} ({scope}: {reason})")
            continue
        if allowed:
            _scope, reason = allowed
            try:
                core_profile = json.loads(core_file.read_text(encoding="utf-8"))
                kit_profile = json.loads(kit_file.read_text(encoding="utf-8"))
                if not isinstance(core_profile, dict) or not isinstance(kit_profile, dict):
                    raise ValueError("profile root must be a JSON object")
                core_profile.pop("notes", None)
                kit_profile.pop("notes", None)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                failures.append(
                    f"cannot verify notes-only profile drift for {relative}: {exc}"
                )
            else:
                if core_profile == kit_profile:
                    print(
                        f"ALLOWED notes-only profile divergence: {relative} "
                        f"(notes-only: {reason})"
                    )
                    continue
                failures.append(f"profile drift outside notes-only scope: {relative}")
        else:
            failures.append(f"profile drift (kit != core at umbrella pins): {relative}")
        try:
            before = core_file.read_text(encoding="utf-8").splitlines()
            after = kit_file.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line in list(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"core/{relative}",
                tofile=f"kit/{relative}",
            )
        )[:40]:
            print(line)

    kit_set = set(kit_files)
    for relative in _relative_files(core_profiles):
        if (
            relative.endswith(".json")
            and not relative.startswith("schema/")
            and relative not in kit_set
        ):
            print(f"NOTE core-only profile (not adopted by kit): {relative}")

    unused = sorted(set(allowlist) - set(kit_files))
    for relative in unused:
        print(f"NOTE unused profile drift allowlist entry: {relative}")
    if failures:
        raise FastCheckError("profile drift check failed:\n  - " + "\n  - ".join(failures))


def shell_scripts(kit: Path) -> tuple[Path, ...]:
    scripts = tuple(
        sorted(
            path
            for directory in (kit / "scripts", kit / "tests")
            for path in directory.rglob("*.sh")
            if path.is_file()
        )
    )
    if not scripts:
        raise FastCheckError(f"no shell scripts found under {kit}/scripts or {kit}/tests")
    return scripts


def shellcheck(paths: Sequence[Path], cwd: Path) -> None:
    relative = [str(path.relative_to(cwd)) for path in paths]
    run_checked(
        mise_command((SHELLCHECK_TOOL,), ("shellcheck", *relative)),
        cwd=cwd,
    )


def bash_syntax(paths: Sequence[Path], cwd: Path) -> None:
    for path in paths:
        run_checked(("bash", "-n", str(path.relative_to(cwd))), cwd=cwd)


def run_wrapper_harnesses(kit: Path) -> None:
    tests = tuple(sorted(path for path in (kit / "tests").glob("*.sh") if path.is_file()))
    if not tests:
        raise FastCheckError(f"no wrapper regression harnesses found under {kit}/tests")
    for test in tests:
        run_checked(("bash", str(test.relative_to(kit))), cwd=kit)


def _docker_shim(directory: Path) -> Path:
    shim = directory / "docker"
    shim.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" != compose ]; then\n"
        "  echo 'local_ci docker shim supports only: docker compose' >&2\n"
        "  exit 2\n"
        "fi\n"
        "shift\n"
        "exec docker-cli-plugin-docker-compose \"$@\"\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def render_compose_models(
    control_root: Path, core: Path, kit: Path, bridge: Path
) -> None:
    with tempfile.TemporaryDirectory(prefix="local-ci-compose-shim-") as tmp:
        shim_dir = Path(tmp)
        _docker_shim(shim_dir)
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{shim_dir}{os.pathsep}{environment.get('PATH', '')}",
                "LIS_CONTROL_ROOT": str(control_root),
                "OPENELIS_ROOT": str(core),
                "BRIDGE_ROOT": str(bridge),
            }
        )
        wrapper = kit / "scripts/compose-openelis.sh"
        site_wrapper = kit / "scripts/compose-site.sh"
        command_prefix = ("mise", "x", COMPOSE_TOOL, "--")
        run_checked(
            (*command_prefix, "bash", str(wrapper), "config", "-q"),
            cwd=control_root,
            env=environment,
        )
        proof_environment = dict(environment)
        proof_environment["LIS_DEPLOY_USE_LOCAL_PROOF"] = "true"
        run_checked(
            (*command_prefix, "bash", str(wrapper), "config", "-q"),
            cwd=control_root,
            env=proof_environment,
        )
        run_checked(
            (*command_prefix, "bash", str(site_wrapper), "config", "-q"),
            cwd=control_root,
            env=environment,
        )


def deploy_kit_config(control_root: Path) -> None:
    core = assert_gitlink(control_root, "core/openelis")
    kit = assert_gitlink(control_root, "deploy/kit")
    bridge = assert_gitlink(control_root, "edge/drivers")
    check_profile_drift(control_root, core, kit)
    scripts = shell_scripts(kit)
    shellcheck(scripts, kit)
    run_wrapper_harnesses(kit)
    render_compose_models(control_root, core, kit, bridge)
    print("OK deploy-kit-config")


def validate_json_files(root: Path) -> None:
    files = tuple(sorted(root.rglob("*.json"))) if root.is_dir() else ()
    if not files:
        raise FastCheckError(f"no JSON files found under {root}")
    failures: list[str] = []
    for path in files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            failures.append(f"{path.relative_to(root)}: {exc}")
    if failures:
        raise FastCheckError("invalid analyzer profile JSON:\n  - " + "\n  - ".join(failures))
    print(f"OK analyzer profile JSON: {len(files)} file(s)")


def verify_plugin_checksums(plugin_dir: Path) -> None:
    checksum_files = tuple(sorted(plugin_dir.glob("*.sha256"))) if plugin_dir.is_dir() else ()
    if not checksum_files:
        raise FastCheckError(f"no plugin .sha256 files found under {plugin_dir}")
    failures: list[str] = []
    jars = tuple(sorted(plugin_dir.glob("*.jar")))
    sidecar_targets: dict[Path, set[str]] = {}
    for jar in jars:
        sidecar = plugin_dir / f"{jar.name}.sha256"
        if not sidecar.is_file():
            failures.append(
                f"{jar.name}: missing required checksum sidecar {sidecar.name}"
            )
    for checksum_file in checksum_files:
        try:
            lines = checksum_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            failures.append(f"{checksum_file.name}: cannot read: {exc}")
            continue
        if not lines:
            failures.append(f"{checksum_file.name}: empty checksum file")
            continue
        for number, line in enumerate(lines, 1):
            match = CHECKSUM_RE.fullmatch(line)
            if not match:
                failures.append(f"{checksum_file.name}:{number}: malformed sha256 entry")
                continue
            expected, filename = match.groups()
            relative = Path(filename)
            if relative.is_absolute() or ".." in relative.parts:
                failures.append(f"{checksum_file.name}:{number}: unsafe filename {filename!r}")
                continue
            sidecar_targets.setdefault(checksum_file, set()).add(filename)
            artifact = plugin_dir / relative
            try:
                actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
            except OSError as exc:
                failures.append(f"{checksum_file.name}:{number}: cannot read {filename}: {exc}")
                continue
            if actual.lower() != expected.lower():
                failures.append(
                    f"{checksum_file.name}:{number}: {filename} sha256 mismatch "
                    f"(expected {expected.lower()}, got {actual})"
                )
            else:
                print(f"OK plugin sha256: {filename}")
    for jar in jars:
        sidecar = plugin_dir / f"{jar.name}.sha256"
        if sidecar.is_file() and jar.name not in sidecar_targets.get(sidecar, set()):
            failures.append(
                f"{sidecar.name}: must contain a sha256 entry for its own artifact "
                f"{jar.name}"
            )
    if failures:
        raise FastCheckError(
            "plugin checksum verification failed:\n  - " + "\n  - ".join(failures)
        )


def kit_lint(checkout: Path) -> None:
    scripts = shell_scripts(checkout)
    shellcheck(scripts, checkout)
    bash_syntax(scripts, checkout)
    validate_json_files(checkout / "configs/analyzer-profiles")
    verify_plugin_checksums(checkout / "configs/plugins")
    print("OK kit-lint")


def _no_duplicate_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate key {key!r}")
        value[key] = item
    return value


def check_language_json(language_dir: Path) -> None:
    files = tuple(sorted(language_dir.glob("*.json"))) if language_dir.is_dir() else ()
    if not files:
        raise FastCheckError(f"no language JSON files found under {language_dir}")
    failures: list[str] = []
    for path in files:
        try:
            json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_no_duplicate_object_pairs,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            failures.append(f"{path.name}: {exc}")
    if failures:
        raise FastCheckError("i18n JSON validation failed:\n  - " + "\n  - ".join(failures))
    print(f"OK i18n duplicate-key check: {len(files)} file(s)")


def validate_exact_sha(value: str, label: str) -> str:
    if not SHA_RE.fullmatch(value):
        raise FastCheckError(f"{label} must be an exact 40-character Git SHA")
    return value.lower()


def core_i18n(checkout: Path, base_sha: str, head_sha: str, head_branch: str) -> None:
    base_sha = validate_exact_sha(base_sha, "base SHA")
    head_sha = validate_exact_sha(head_sha, "head SHA")
    if not head_branch:
        raise FastCheckError("head branch metadata is required")
    actual_head = git_output(checkout, "rev-parse", "HEAD").lower()
    if actual_head != head_sha:
        raise FastCheckError(
            f"core-i18n checkout HEAD is {actual_head}, expected exact PR head {head_sha}"
        )
    language_dir = checkout / "frontend/src/languages"
    check_language_json(language_dir)
    if head_branch == "chore/update-transifex":
        print("OK i18n source-of-truth: Transifex sync branch exemption")
        return
    changed_output = git_output(
        checkout,
        "diff",
        "--name-only",
        f"{base_sha}...{head_sha}",
        "--",
        "frontend/src/languages/",
    )
    changed = tuple(path for path in changed_output.splitlines() if path)
    non_english = tuple(
        path for path in changed if path.endswith(".json") and not path.endswith("/en.json")
    )
    if non_english:
        raise FastCheckError(
            "non-English translation files changed relative to exact PR base "
            f"{base_sha}; translations belong on Transifex and only en.json may be "
            "edited outside chore/update-transifex:\n  - "
            + "\n  - ".join(non_english)
        )
    print("OK i18n source-of-truth: only en.json changed")


def bridge_tests(checkout: Path) -> None:
    maven_home = Path.home() / ".m2"
    if not maven_home.is_dir():
        raise FastCheckError(
            f"Maven cache is missing at {maven_home}; create it before running bridge-tests"
        )
    if shutil.which("docker"):
        # The core-verify recipe is load-bearing on Docker workers: host
        # networking, IPv6 preference, a non-root uid, and the explicit local
        # repository mount must travel together.
        run_checked(
            (
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-e",
                "HOME=/mvnhome",
                "-e",
                "MAVEN_OPTS=-Xmx700m -Djava.net.preferIPv6Addresses=true",
                "-v",
                f"{checkout}:/work",
                "-v",
                f"{maven_home}:/mvnhome/.m2",
                "-w",
                "/work",
                MAVEN_IMAGE,
                "bash",
                "-c",
                "mvn -B -Dmaven.repo.local=/mvnhome/.m2/repository "
                "-f astm-http-lib/pom.xml clean install -DskipTests && "
                "mvn -B -Dmaven.repo.local=/mvnhome/.m2/repository test "
                "-DargLine=\"-Xmx1300m -Djava.net.preferIPv6Addresses=true\"",
            ),
            cwd=checkout,
        )
    else:
        # Local-CI workers may intentionally provide mise without a Docker
        # daemon. Preserve the pinned Java/Maven versions and JVM limits so the
        # hosted two-step recipe remains reproducible on those workers.
        print("NOTE bridge-tests: Docker unavailable; using pinned mise toolchain")
        environment = os.environ.copy()
        environment["MAVEN_OPTS"] = "-Xmx700m -Djava.net.preferIPv6Addresses=true"
        maven_prefix = mise_command((JAVA_TOOL, MAVEN_TOOL), ("mvn", "-B"))
        repository = f"-Dmaven.repo.local={maven_home / 'repository'}"
        run_checked(
            (
                *maven_prefix,
                repository,
                "-f",
                "astm-http-lib/pom.xml",
                "clean",
                "install",
                "-DskipTests",
            ),
            cwd=checkout,
            env=environment,
        )
        run_checked(
            (
                *maven_prefix,
                repository,
                "test",
                "-DargLine=-Xmx1300m -Djava.net.preferIPv6Addresses=true",
            ),
            cwd=checkout,
            env=environment,
        )
    # SerialIntegrationTest remains off unless its PTY environment gate is
    # deliberately provided through a separate serial-test workflow.
    print("OK bridge-tests")


def _env_or(value: str | None, name: str, default: str = "") -> str:
    return value if value is not None else os.environ.get(name, default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a standalone LIS local-CI fast check")
    parser.add_argument(
        "check",
        choices=(
            "edge-sim",
            "profile-drift",
            "deploy-kit-config",
            "kit-lint",
            "core-i18n",
            "bridge-tests",
        ),
    )
    parser.add_argument(
        "--checkout", help="component checkout (defaults to runner metadata or cwd)"
    )
    parser.add_argument("--control-root", help="lis-control checkout containing the registry")
    parser.add_argument("--base-sha", help="exact PR base SHA (core-i18n)")
    parser.add_argument("--head-sha", help="exact PR head SHA (core-i18n)")
    parser.add_argument("--head-branch", help="exact PR head branch (core-i18n)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checkout = Path(
        _env_or(args.checkout, "LIS_LOCAL_CI_CHECKOUT", str(Path.cwd()))
    ).resolve()
    control_root = Path(
        _env_or(args.control_root, "LIS_LOCAL_CI_CONTROL_ROOT", str(SCRIPT_CONTROL_ROOT))
    ).resolve()
    is_umbrella = (
        os.environ.get("LIS_LOCAL_CI_REPOSITORY", "").lower()
        == "ailabsolution/lis-control"
    )
    try:
        if args.check == "edge-sim":
            run_checked(
                ("uv", "run", "--frozen", "--python", "3.12", "pytest", "-q"),
                cwd=checkout / "edge/sim",
            )
            print("OK edge-sim")
        elif args.check == "profile-drift":
            check_profile_drift(
                checkout, checkout / "core/openelis", checkout / "deploy/kit"
            )
        elif args.check == "deploy-kit-config":
            deploy_kit_config(checkout)
        elif args.check == "kit-lint":
            if is_umbrella:
                checkout = assert_gitlink(checkout, "deploy/kit")
            kit_lint(checkout)
        elif args.check == "core-i18n":
            core_i18n(
                checkout,
                _env_or(args.base_sha, "LIS_LOCAL_CI_BASE_SHA"),
                _env_or(args.head_sha, "LIS_LOCAL_CI_HEAD_SHA"),
                _env_or(args.head_branch, "LIS_LOCAL_CI_HEAD_BRANCH"),
            )
        elif args.check == "bridge-tests":
            if is_umbrella:
                checkout = assert_gitlink(checkout, "edge/drivers")
            bridge_tests(checkout)
    except FastCheckError as exc:
        print(f"local_ci_fast_checks: FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
