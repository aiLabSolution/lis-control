#!/usr/bin/env python3
"""Pass through Docker, adding final local-CI Compose isolation overlays.

Deploy-kit wrappers own the authoritative compose-file sequence.  This shim is
put first on PATH only for a local stack check; it preserves every wrapper and
proof entrypoint while appending the umbrella-owned isolation overlay just
before the Compose subcommand for the exact pinned core or bridge directory.
All non-Compose Docker commands pass through byte-for-byte.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Sequence


COMPOSE_SUBCOMMANDS = frozenset(
    {
        "build",
        "config",
        "create",
        "down",
        "events",
        "exec",
        "images",
        "kill",
        "logs",
        "ls",
        "pause",
        "port",
        "ps",
        "pull",
        "push",
        "restart",
        "rm",
        "run",
        "start",
        "stop",
        "top",
        "unpause",
        "up",
        "version",
        "wait",
        "watch",
    }
)


class ShimError(RuntimeError):
    """The requested Compose command cannot be isolated safely."""


def _project_directory(argv: Sequence[str]) -> str | None:
    for index, value in enumerate(argv):
        if value == "--project-directory" and index + 1 < len(argv):
            return argv[index + 1]
        if value.startswith("--project-directory="):
            return value.split("=", 1)[1]
    return None


def _subcommand_index(argv: Sequence[str]) -> int | None:
    for index, value in enumerate(argv):
        if value in COMPOSE_SUBCOMMANDS:
            return index
    return None


def augment_argv(
    argv: Sequence[str], environment: Mapping[str, str]
) -> tuple[str, ...]:
    values = tuple(argv)
    if not values or values[0] != "compose":
        return values
    project_value = _project_directory(values)
    if project_value is None:
        return values
    project = Path(project_value).resolve()
    mappings = (
        (
            environment.get("LIS_LOCAL_CI_OPENELIS_ROOT"),
            environment.get("LIS_LOCAL_CI_OPENELIS_OVERLAY"),
        ),
        (
            environment.get("LIS_LOCAL_CI_BRIDGE_ROOT"),
            environment.get("LIS_LOCAL_CI_BRIDGE_OVERLAY"),
        ),
    )
    overlay = next(
        (
            candidate
            for root, candidate in mappings
            if root and candidate and project == Path(root).resolve()
        ),
        None,
    )
    if overlay is None:
        return values
    overlay_path = Path(overlay)
    if not overlay_path.is_file():
        raise ShimError(f"local-CI Compose overlay is missing: {overlay_path}")
    if str(overlay_path) in values:
        return values
    subcommand = _subcommand_index(values[1:])
    if subcommand is None:
        raise ShimError(
            f"cannot identify Compose subcommand for isolated project {project}"
        )
    insertion = subcommand + 1
    return (*values[:insertion], "-f", str(overlay_path), *values[insertion:])


def main() -> int:
    real_docker = os.environ.get("LIS_LOCAL_CI_REAL_DOCKER")
    if not real_docker or not Path(real_docker).is_file():
        print("local_ci docker shim: real Docker CLI is missing", file=sys.stderr)
        return 127
    try:
        argv = augment_argv(sys.argv[1:], os.environ)
    except ShimError as exc:
        print(f"local_ci docker shim: {exc}", file=sys.stderr)
        return 2
    os.execv(real_docker, (real_docker, *argv))
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
