#!/usr/bin/env python3
"""Run registered local CI checks against an exact, clean GitHub revision.

The runner is intentionally stdlib-only.  GitHub access goes through the
already-authenticated ``gh`` CLI; check commands are argv arrays from the
strict JSON registry and are never interpreted by a shell.

Local CI is additive while ``local_ci.json`` is in ``hosted`` mode.  The mode
is registry metadata for the merge gate; it does not stop an operator from
collecting local evidence while hosted CI remains authoritative.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import fnmatch
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse


STATUS_PREFIX = "local-ci/"
SUMMARY_CONTEXT = STATUS_PREFIX + "summary"
DEFAULT_LOCK_PATH = "/tmp/lis-local-ci.lock"
DEFAULT_REGISTRY = "local_ci.json"
GITHUB_DESCRIPTION_LIMIT = 140
GH_TIMEOUT_SECONDS = 60
STATUS_DETAIL_ENV = "LIS_LOCAL_CI_STATUS_DETAIL_FILE"
MAX_STATUS_DETAIL_LENGTH = 100

_TOP_LEVEL_FIELDS = {"version", "mode", "repositories", "checks"}
_REPOSITORY_FIELDS = {"gate_required"}
_CHECK_FIELDS = {
    "name",
    "repository",
    "paths",
    "additional_triggers",
    "command",
    "class",
    "timeout_seconds",
    "min_memory_mib",
}
_CHECK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


class LocalCIError(RuntimeError):
    """An actionable refusal or infrastructure error."""


class RegistryError(LocalCIError):
    """The declarative registry is invalid."""


@dataclasses.dataclass(frozen=True)
class RepositoryConfig:
    name: str
    gate_required: bool = False


@dataclasses.dataclass(frozen=True)
class CheckConfig:
    name: str
    repository: str
    paths: tuple[str, ...]
    command: tuple[str, ...]
    check_class: str
    timeout_seconds: int
    min_memory_mib: int | None = None
    additional_triggers: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def paths_for_repository(self, repository: str) -> tuple[str, ...] | None:
        repository_lower = repository.lower()
        if self.repository.lower() == repository_lower:
            return self.paths
        for name, paths in self.additional_triggers:
            if name.lower() == repository_lower:
                return paths
        return None


@dataclasses.dataclass(frozen=True)
class Registry:
    version: int
    mode: str
    repositories: dict[str, RepositoryConfig]
    checks: tuple[CheckConfig, ...]


@dataclasses.dataclass(frozen=True)
class PullRequest:
    sha: str
    url: str
    repository: str
    changed_paths: tuple[str, ...]
    base_sha: str = ""
    head_branch: str = ""


@dataclasses.dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    duration_seconds: float
    detail: str
    log_url: str | None


def _unknown_fields(value: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RegistryError(f"{where}: unknown field(s): {', '.join(unknown)}")


def _require_string_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise RegistryError(f"{where} must be a non-empty array of strings")
    return tuple(value)


def load_registry(path: Path) -> Registry:
    """Parse and strictly validate a version-1 JSON check registry."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"cannot parse registry {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError("registry root must be an object")
    _unknown_fields(raw, _TOP_LEVEL_FIELDS, "registry")

    version = raw.get("version")
    if type(version) is not int or version != 1:
        raise RegistryError("registry.version must be the integer 1")
    mode = raw.get("mode", "hosted")
    if mode not in {"hosted", "local"}:
        raise RegistryError("registry.mode must be 'hosted' or 'local'")

    repositories_raw = raw.get("repositories")
    if not isinstance(repositories_raw, dict) or not repositories_raw:
        raise RegistryError("registry.repositories must be a non-empty object")
    repositories: dict[str, RepositoryConfig] = {}
    for name, value in repositories_raw.items():
        if not isinstance(name, str) or not _REPOSITORY_RE.fullmatch(name):
            raise RegistryError(f"invalid repository name: {name!r}")
        if not isinstance(value, dict):
            raise RegistryError(f"repository {name!r} must be an object")
        _unknown_fields(value, _REPOSITORY_FIELDS, f"repository {name!r}")
        gate_required = value.get("gate_required", False)
        if type(gate_required) is not bool:
            raise RegistryError(
                f"repository {name!r}.gate_required must be a boolean"
            )
        repositories[name.lower()] = RepositoryConfig(name, gate_required)

    checks_raw = raw.get("checks")
    if not isinstance(checks_raw, list) or not checks_raw:
        raise RegistryError("registry.checks must be a non-empty array")
    checks: list[CheckConfig] = []
    names: set[str] = set()
    for index, value in enumerate(checks_raw):
        where = f"check[{index}]"
        if not isinstance(value, dict):
            raise RegistryError(f"{where} must be an object")
        _unknown_fields(value, _CHECK_FIELDS, where)
        name = value.get("name")
        if not isinstance(name, str) or not _CHECK_NAME_RE.fullmatch(name):
            raise RegistryError(
                f"{where}.name must match {_CHECK_NAME_RE.pattern!r}"
            )
        if name in names:
            raise RegistryError(f"duplicate check name: {name}")
        names.add(name)
        repository = value.get("repository")
        if not isinstance(repository, str) or repository.lower() not in repositories:
            raise RegistryError(
                f"{where}.repository must name an entry in registry.repositories"
            )
        paths = _require_string_list(value.get("paths"), f"{where}.paths")
        if any(path.startswith("/") or "\\" in path for path in paths):
            raise RegistryError(
                f"{where}.paths must contain repository-relative POSIX patterns"
            )
        additional_raw = value.get("additional_triggers", {})
        if not isinstance(additional_raw, dict):
            raise RegistryError(f"{where}.additional_triggers must be an object")
        additional_triggers: list[tuple[str, tuple[str, ...]]] = []
        for trigger_repository, trigger_paths_raw in additional_raw.items():
            trigger_repository_lower = (
                trigger_repository.lower()
                if isinstance(trigger_repository, str)
                else ""
            )
            if trigger_repository_lower not in repositories:
                raise RegistryError(
                    f"{where}.additional_triggers repository {trigger_repository!r} "
                    "must name an entry in registry.repositories"
                )
            if trigger_repository_lower == repository.lower():
                raise RegistryError(
                    f"{where}.additional_triggers repeats primary repository "
                    f"{trigger_repository!r}"
                )
            trigger_paths = _require_string_list(
                trigger_paths_raw,
                f"{where}.additional_triggers[{trigger_repository!r}]",
            )
            if any(path.startswith("/") or "\\" in path for path in trigger_paths):
                raise RegistryError(
                    f"{where}.additional_triggers paths must be repository-relative "
                    "POSIX patterns"
                )
            additional_triggers.append(
                (repositories[trigger_repository_lower].name, trigger_paths)
            )
        command = _require_string_list(value.get("command"), f"{where}.command")
        check_class = value.get("class", "fast")
        if check_class not in {"fast", "heavy"}:
            raise RegistryError(f"{where}.class must be 'fast' or 'heavy'")
        timeout_seconds = value.get("timeout_seconds")
        if type(timeout_seconds) is not int or timeout_seconds <= 0:
            raise RegistryError(f"{where}.timeout_seconds must be a positive integer")
        min_memory_mib = value.get("min_memory_mib")
        if min_memory_mib is not None and (
            type(min_memory_mib) is not int or min_memory_mib <= 0
        ):
            raise RegistryError(f"{where}.min_memory_mib must be a positive integer")
        if check_class == "heavy" and min_memory_mib is None:
            raise RegistryError(f"{where}: heavy checks require min_memory_mib")
        if check_class != "heavy" and min_memory_mib is not None:
            raise RegistryError(f"{where}: min_memory_mib is only valid for heavy checks")
        checks.append(
            CheckConfig(
                name=name,
                repository=repository,
                paths=paths,
                command=command,
                check_class=check_class,
                timeout_seconds=timeout_seconds,
                min_memory_mib=min_memory_mib,
                additional_triggers=tuple(additional_triggers),
            )
        )
    return Registry(version, mode, repositories, tuple(checks))


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=str(cwd),
            input=input_text,
            stdin=subprocess.DEVNULL if input_text is None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except OSError as exc:
        raise LocalCIError(f"could not run {argv[0]!r}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalCIError(
            f"{' '.join(argv)} timed out after {timeout}s"
        ) from exc


def _failure_tail(proc: subprocess.CompletedProcess[str]) -> str:
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    return lines[-1] if lines else f"exit {proc.returncode} with no output"


def _repository_from_pr_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] != "pull":
        raise LocalCIError(f"gh returned an unexpected PR URL: {url!r}")
    return f"{parts[0]}/{parts[1]}"


def resolve_pr(selector: str, repo: str | None, root: Path) -> PullRequest:
    argv = [
        "gh",
        "pr",
        "view",
        selector,
        "--json",
        "baseRefOid,headRefName,headRefOid,url,files",
    ]
    if repo:
        argv += ["--repo", repo]
    proc = _run(argv, cwd=root, timeout=GH_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise LocalCIError(f"gh could not resolve PR {selector!r}: {_failure_tail(proc)}")
    try:
        data = json.loads(proc.stdout)
        base_sha = data["baseRefOid"]
        head_branch = data["headRefName"]
        sha = data["headRefOid"]
        url = data["url"]
        file_items = data["files"]
        changed_paths = tuple(item["path"] for item in file_items)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise LocalCIError("gh returned malformed PR metadata") from exc
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise LocalCIError("gh returned an invalid PR head SHA")
    if not isinstance(base_sha, str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}", base_sha
    ):
        raise LocalCIError("gh returned an invalid PR base SHA")
    if not isinstance(head_branch, str) or not head_branch:
        raise LocalCIError("gh returned an invalid PR head branch")
    if not isinstance(url, str) or not isinstance(file_items, list):
        raise LocalCIError("gh returned malformed PR metadata")
    if any(not isinstance(path, str) or not path for path in changed_paths):
        raise LocalCIError("gh returned an invalid changed-file path")
    return PullRequest(
        sha=sha.lower(),
        url=url,
        repository=_repository_from_pr_url(url),
        changed_paths=changed_paths,
        base_sha=base_sha.lower(),
        head_branch=head_branch,
    )


def verify_checkout(root: Path, expected_sha: str) -> None:
    """Refuse unless HEAD and the full worktree, including gitlinks, are exact."""
    head = _run(["git", "rev-parse", "HEAD"], cwd=root, timeout=15)
    if head.returncode != 0:
        raise LocalCIError(f"cannot read local HEAD: {_failure_tail(head)}")
    actual_sha = head.stdout.strip().lower()
    if actual_sha != expected_sha.lower():
        raise LocalCIError(
            "local HEAD does not equal the PR head "
            f"(local {actual_sha[:12]}, PR {expected_sha[:12]}); fetch and check out "
            "the exact PR head before retrying"
        )
    status = _run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
        cwd=root,
        timeout=30,
    )
    if status.returncode != 0:
        raise LocalCIError(f"cannot inspect worktree cleanliness: {_failure_tail(status)}")
    if status.stdout.strip():
        sample = ", ".join(line[3:] for line in status.stdout.splitlines()[:5])
        raise LocalCIError(
            "worktree is dirty (including submodule gitlinks); commit, stash, or "
            f"remove local changes before retrying: {sample}"
        )


def path_matches(pattern: str, path: str) -> bool:
    """Match POSIX registry globs, including a bare gitlink for ``dir/**``."""
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.endswith("/**") and path == pattern[:-3].rstrip("/"):
        return True
    return False


def select_checks(
    registry: Registry,
    repository: str,
    changed_paths: Iterable[str],
    requested: Iterable[str] = (),
) -> tuple[CheckConfig, ...]:
    repository_lower = repository.lower()
    paths = tuple(changed_paths)
    requested_set = set(requested)
    known = {check.name for check in registry.checks}
    missing = sorted(requested_set - known)
    if missing:
        raise LocalCIError(f"unknown requested check(s): {', '.join(missing)}")
    if requested_set:
        applicable = {
            check.name
            for check in registry.checks
            if check.paths_for_repository(repository_lower) is not None
        }
        inapplicable = sorted(requested_set - applicable)
        if inapplicable:
            raise LocalCIError(
                f"requested check(s) not applicable to repository {repository}: "
                f"{', '.join(inapplicable)}"
            )
    selected = []
    for check in registry.checks:
        trigger_paths = check.paths_for_repository(repository_lower)
        if trigger_paths is None:
            continue
        if requested_set:
            if check.name in requested_set:
                selected.append(check)
            continue
        if any(path_matches(pattern, path) for pattern in trigger_paths for path in paths):
            selected.append(check)
    return tuple(selected)


def available_memory_mib(meminfo: Path = Path("/proc/meminfo")) -> int:
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                fields = line.split()
                if len(fields) >= 2:
                    return int(fields[1]) // 1024
    except (OSError, ValueError) as exc:
        raise LocalCIError(f"cannot read available memory from {meminfo}: {exc}") from exc
    raise LocalCIError(f"{meminfo} does not contain MemAvailable")


def running_container_names() -> tuple[str, ...]:
    """Return visible running containers without mutating Docker state."""
    try:
        result = _run(
            ("docker", "ps", "--format", "{{.Names}}"),
            cwd=Path.cwd(),
            timeout=15,
        )
    except LocalCIError:
        return ()
    if result.returncode:
        return ()
    return tuple(sorted(line.strip() for line in result.stdout.splitlines() if line.strip()))


def preflight_memory(
    checks: Iterable[CheckConfig],
    available_mib: int | None = None,
    running_containers: Iterable[str] | None = None,
) -> None:
    heavy = [check for check in checks if check.check_class == "heavy"]
    if not heavy:
        return
    threshold = max(check.min_memory_mib or 0 for check in heavy)
    available = available_memory_mib() if available_mib is None else available_mib
    if available < threshold:
        names = ", ".join(check.name for check in heavy)
        containers = tuple(
            running_container_names()
            if running_containers is None
            else running_containers
        )
        container_detail = (
            " Running containers (left untouched): " + ", ".join(containers) + "."
            if containers
            else " No running container names were visible."
        )
        raise LocalCIError(
            f"heavy check(s) {names} require {threshold} MiB available RAM; only "
            f"{available} MiB is available.{container_detail} Stop or move co-resident OpenELIS "
            "dev/site/proof stacks yourself, then retry. local_ci never stops "
            "containers."
        )


@contextlib.contextmanager
def global_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("a+", encoding="utf-8")
    except OSError as exc:
        raise LocalCIError(f"cannot open global lock {path}: {exc}") from exc
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()} host={socket.gethostname()}\n")
        handle.flush()
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _description(host: str, duration_seconds: float, detail: str) -> str:
    value = f"host={host} duration={duration_seconds:.1f}s {detail}"
    return value[:GITHUB_DESCRIPTION_LIMIT]


def post_status(
    root: Path,
    repository: str,
    sha: str,
    context: str,
    state: str,
    host: str,
    duration_seconds: float,
    detail: str,
    target_url: str | None = None,
) -> None:
    argv = [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repository}/statuses/{sha}",
        "-f",
        f"state={state}",
        "-f",
        f"context={context}",
        "-f",
        f"description={_description(host, duration_seconds, detail)}",
    ]
    if target_url:
        argv += ["-f", f"target_url={target_url}"]
    proc = _run(argv, cwd=root, timeout=GH_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise LocalCIError(
            f"could not post {context} status to {sha[:12]}: {_failure_tail(proc)}"
        )


def publish_gist(
    root: Path, name: str, sha: str, log: str
) -> str | None:
    filename = f"local-ci-{name}-{sha[:12]}.log"
    argv = [
        "gh",
        "gist",
        "create",
        "-",
        "--filename",
        filename,
        "--desc",
        f"local_ci {name} evidence for {sha}",
    ]
    try:
        proc = _run(argv, cwd=root, timeout=GH_TIMEOUT_SECONDS, input_text=log)
    except LocalCIError as exc:
        print(f"local_ci: warning: gist publication failed: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            "local_ci: warning: gist publication failed; posting status without "
            f"a link: {_failure_tail(proc)}",
            file=sys.stderr,
        )
        return None
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if not url.startswith(("https://", "http://")):
        print(
            "local_ci: warning: gist publication returned no URL; posting status "
            "without a link",
            file=sys.stderr,
        )
        return None
    return url


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    output = exc.stdout or ""
    stderr = exc.stderr or ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return str(output) + str(stderr)


def read_command_status_detail(path: Path) -> str | None:
    """Read the optional one-line detail emitted by a trusted check command."""
    if not path.exists():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise LocalCIError(f"cannot read command status detail: {exc}") from exc
    if not value or "\n" in value or "\r" in value:
        raise LocalCIError("command status detail must be one non-empty line")
    if len(value) > MAX_STATUS_DETAIL_LENGTH:
        raise LocalCIError(
            f"command status detail exceeds {MAX_STATUS_DETAIL_LENGTH} characters"
        )
    return value


def run_check(
    root: Path,
    check: CheckConfig,
    pr: PullRequest,
    host: str,
    control_root: Path | None = None,
) -> CheckResult:
    control_root = (control_root or root).resolve()
    checkout = root.resolve()
    context = STATUS_PREFIX + check.name
    post_status(
        control_root,
        pr.repository,
        pr.sha,
        context,
        "pending",
        host,
        0.0,
        "running",
    )
    start = time.monotonic()
    timed_out = False
    environment = os.environ.copy()
    detail_directory = tempfile.TemporaryDirectory(prefix="lis-local-ci-detail-")
    detail_path = Path(detail_directory.name) / "status.txt"
    environment.update(
        {
            "LIS_LOCAL_CI_BASE_SHA": pr.base_sha,
            "LIS_LOCAL_CI_HEAD_SHA": pr.sha,
            "LIS_LOCAL_CI_HEAD_BRANCH": pr.head_branch,
            "LIS_LOCAL_CI_CHANGED_PATHS_JSON": json.dumps(list(pr.changed_paths)),
            "LIS_LOCAL_CI_REPOSITORY": pr.repository,
            "LIS_LOCAL_CI_CONTROL_ROOT": str(control_root),
            "LIS_LOCAL_CI_CHECKOUT": str(checkout),
            # Stack checks reserve cleanup time before this hard engine limit.
            "LIS_LOCAL_CI_TIMEOUT_SECONDS": str(check.timeout_seconds),
            STATUS_DETAIL_ENV: str(detail_path),
        }
    )
    try:
        proc = subprocess.run(
            list(check.command),
            # Registry commands live in the umbrella. Component checks receive
            # their exact checkout through LIS_LOCAL_CI_CHECKOUT and must use
            # it explicitly rather than assuming the process working directory.
            cwd=str(control_root),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=check.timeout_seconds,
        )
        returncode = proc.returncode
        output = proc.stdout or ""
    except OSError as exc:
        returncode = 127
        output = f"could not run {check.command[0]!r}: {exc}\n"
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        output = _timeout_output(exc)
        output += f"\nTIMED OUT after {check.timeout_seconds}s\n"
    command_detail: str | None = None
    try:
        command_detail = read_command_status_detail(detail_path)
    except LocalCIError as exc:
        returncode = 2
        output += f"\nINVALID STATUS DETAIL: {exc}\n"
    finally:
        detail_directory.cleanup()
    duration = time.monotonic() - start
    passed = returncode == 0
    if passed:
        detail = command_detail or "passed"
    elif timed_out:
        detail = f"timed out after {check.timeout_seconds}s"
    else:
        detail = f"failed (exit {returncode})"
    log = (
        f"local_ci check: {check.name}\n"
        f"repository: {pr.repository}\n"
        f"PR: {pr.url}\n"
        f"base: {pr.base_sha}\n"
        f"head: {pr.sha}\n"
        f"head_branch: {pr.head_branch}\n"
        f"changed_paths: {json.dumps(pr.changed_paths)}\n"
        f"control_root: {control_root}\n"
        f"checkout: {checkout}\n"
        f"host: {host}\n"
        f"duration_seconds: {duration:.3f}\n"
        f"command: {json.dumps(check.command)}\n"
        f"result: {detail}\n\n{output}"
    )
    log_url = publish_gist(control_root, check.name, pr.sha, log)
    post_status(
        control_root,
        pr.repository,
        pr.sha,
        context,
        "success" if passed else "failure",
        host,
        duration,
        detail,
        log_url,
    )
    return CheckResult(check.name, passed, duration, detail, log_url)


def run_engine(
    root: Path,
    registry: Registry,
    selector: str | None,
    repo: str | None,
    lock_path: Path,
    requested_checks: Iterable[str] = (),
    checkout: Path | None = None,
    commit_sha: str | None = None,
    head_branch: str | None = None,
) -> int:
    root = root.resolve()
    checkout = (checkout or root).resolve()
    requested_checks = tuple(requested_checks)
    commit_mode = commit_sha is not None
    if commit_mode:
        if selector is not None:
            raise LocalCIError("provide a PR selector or --commit, not both")
        if not repo:
            raise LocalCIError("--commit requires --repo OWNER/REPO")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
            raise LocalCIError("--commit must be an exact 40-character Git SHA")
        if not head_branch:
            raise LocalCIError("--commit requires --head-branch")
        if not requested_checks:
            raise LocalCIError(
                "--commit requires at least one explicit --check because no PR "
                "changed-file list is available"
            )
        exact_sha = commit_sha.lower()
        pr = PullRequest(
            sha=exact_sha,
            url=f"https://github.com/{repo}/commit/{exact_sha}",
            repository=repo,
            changed_paths=(),
            base_sha=exact_sha,
            head_branch=head_branch,
        )
    else:
        if selector is None:
            raise LocalCIError("provide a PR selector or --commit")
        pr = resolve_pr(selector, repo, root)
    repository_key = pr.repository.lower()
    if repository_key not in registry.repositories:
        raise LocalCIError(
            f"PR repository {pr.repository} is not registered in {DEFAULT_REGISTRY}"
        )
    # This validation deliberately precedes every status/gist call.
    verify_checkout(checkout, pr.sha)
    checks = select_checks(registry, pr.repository, pr.changed_paths, requested_checks)
    normal_checks = (
        ()
        if commit_mode
        else select_checks(registry, pr.repository, pr.changed_paths)
    )
    summary_eligible = not commit_mode and (
        not requested_checks
        or {check.name for check in checks}
        == {check.name for check in normal_checks}
    )
    preflight_memory(checks)
    if commit_mode:
        requested_names = ", ".join(check.name for check in checks) or "(none)"
        print(
            "local_ci: EXACT-COMMIT EVIDENCE ONLY: running explicitly requested "
            f"checks [{requested_names}]. Individual check evidence will be "
            f"published, but {SUMMARY_CONTEXT} and its summary gist will not. "
            "This run cannot satisfy the merge gate because no PR changed-file "
            "selection was verified."
        )
    elif not summary_eligible:
        requested_names = ", ".join(check.name for check in checks) or "(none)"
        normal_names = ", ".join(check.name for check in normal_checks) or "(none)"
        print(
            "local_ci: PARTIAL EVIDENCE ONLY: explicit --check set "
            f"[{requested_names}] does not exactly match the normal path-selected "
            f"set [{normal_names}]. Individual check evidence will be published, "
            f"but {SUMMARY_CONTEXT} and its summary gist will not. This run cannot "
            "satisfy the merge gate."
        )
    host = socket.gethostname()
    run_start = time.monotonic()
    results: list[CheckResult] = []
    with global_lock(lock_path):
        if summary_eligible:
            post_status(
                root,
                pr.repository,
                pr.sha,
                SUMMARY_CONTEXT,
                "pending",
                host,
                0.0,
                f"running {len(checks)} check(s)",
            )
        for check in checks:
            print(f"local_ci: running {check.name}: {' '.join(check.command)}")
            results.append(run_check(checkout, check, pr, host, root))
        duration = time.monotonic() - run_start
        passed = all(result.passed for result in results)
        summary_detail = (
            f"{sum(result.passed for result in results)}/{len(results)} checks passed"
        )
        if summary_eligible:
            summary_log = (
                f"local_ci summary\nrepository: {pr.repository}\nPR: {pr.url}\n"
                f"head: {pr.sha}\nhost: {host}\nduration_seconds: {duration:.3f}\n"
                f"registry_mode: {registry.mode}\nselected_checks: "
                f"{', '.join(check.name for check in checks) or '(none)'}\nresult: "
                f"{summary_detail}\n"
                + "".join(
                    f"\n{result.name}: {result.detail} ({result.duration_seconds:.3f}s)"
                    f" log={result.log_url or '(gist unavailable)'}"
                    for result in results
                )
                + "\n"
            )
            summary_url = publish_gist(root, "summary", pr.sha, summary_log)
            post_status(
                root,
                pr.repository,
                pr.sha,
                SUMMARY_CONTEXT,
                "success" if passed else "failure",
                host,
                duration,
                summary_detail,
                summary_url,
            )
    return 0 if passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run registered local CI checks against an exact, clean PR head"
    )
    parser.add_argument(
        "pr",
        nargs="?",
        help="PR number, URL, or branch understood by `gh pr view`",
    )
    parser.add_argument("--repo", help="GitHub OWNER/REPO when the PR is not inferred here")
    parser.add_argument(
        "--commit",
        help="exact 40-character default-branch SHA for immutable current-main proof",
    )
    parser.add_argument(
        "--head-branch",
        help="branch name recorded in exact-commit evidence (required with --commit)",
    )
    parser.add_argument(
        "--checkout",
        help=(
            "exact clean checkout of the PR repository (default: the lis-control "
            "checkout containing this runner)"
        ),
    )
    parser.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY,
        help=f"registry path relative to the checkout (default: {DEFAULT_REGISTRY})",
    )
    parser.add_argument(
        "--lock-file",
        default=os.environ.get("LIS_LOCAL_CI_LOCK", DEFAULT_LOCK_PATH),
        help=f"machine-global serialisation lock (default: {DEFAULT_LOCK_PATH})",
    )
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        help=(
            "run a named applicable check regardless of paths (repeatable); a PR "
            "run publishes merge-gate summary evidence only when the explicit set "
            "equals normal path selection"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    registry_path = Path(args.registry)
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    try:
        registry = load_registry(registry_path)
        return run_engine(
            root,
            registry,
            args.pr,
            args.repo,
            Path(args.lock_file),
            args.check,
            Path(args.checkout) if args.checkout else None,
            args.commit,
            args.head_branch,
        )
    except LocalCIError as exc:
        print(f"local_ci: REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
