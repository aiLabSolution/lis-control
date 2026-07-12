#!/usr/bin/env python3
"""Claude Code PostToolUse shift-left hook — run the relevant CI check locally, now.

Why this exists
---------------
Two umbrella CI checks are cheap to run locally: the stdlib-only scripts/ unittest
suite (.github/workflows/scripts-tests.yml) and the edge/sim pytest harness
(.github/workflows/edge-sim.yml) — each costs a full push→CI→read-logs round trip
when caught remotely. The third dispatch, prettier in the edge/drivers submodule,
mirrors no CI (nothing runs prettier anywhere); it applies the bridge repo's own
formatting convention (.prettierrc.yml, npm prettier) at edit time so diffs land
formatted. NOTE it runs `prettier --write`, i.e. it MUTATES the just-edited file:
when formatting changed anything, the next Edit of that file sees it as modified
since read and must re-read first. Wired as a PostToolUse hook on
Edit|Write|MultiEdit, dispatching on the edited file's repo-relative path and
feeding genuine failures straight back to the model (exit 2, message on stderr)
while the context is still hot.

Contract (per docs/agents conventions for editing-session hooks)
----------------------------------------------------------------
* exit 0  — check passed, path not covered, or infrastructure problem (malformed
  stdin, tool missing, node_modules absent, subprocess timeout). A broken hook must
  never brick an editing session, so infrastructure problems FAIL OPEN.
* exit 2  — genuine check failure only (failing tests, prettier syntax error);
  stderr carries the tail of the failing output back to the model.

Repo root: parent of the directory holding this script, overridable via
LIS_HOOK_REPO_ROOT (used by tests to point at throwaway trees — running the
scripts/ suite against the real root from inside a test would recurse).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# .prettierrc.yml in edge/drivers covers these; other suffixes (e.g. .py) are not
# prettier-formatted there.
PRETTIER_SUFFIXES = {".java", ".xml", ".yml", ".yaml", ".json", ".md"}
TAIL_LINES = 30


def _repo_root() -> Path:
    override = os.environ.get("LIS_HOOK_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-TAIL_LINES:])


def _run(cmd, cwd, timeout):
    """Run a check; None means infrastructure problem (fail open)."""
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"shift-left: {cmd[0]} timed out after {timeout}s; skipping", file=sys.stderr)
        return None
    except OSError:
        return None


def _fail(header: str, output: str) -> int:
    print(header, file=sys.stderr)
    print(_tail(output), file=sys.stderr)
    return 2


def _run_scripts_suite(root: Path) -> int:
    # Exact CI command (scripts-tests.yml); sys.executable is the python3 that
    # launched this hook, so the interpreter matches even off-PATH.
    cmd = [sys.executable or "python3", "-m", "unittest",
           "discover", "-s", "scripts", "-p", "test_*.py"]
    proc = _run(cmd, cwd=root, timeout=90)
    if proc is None or proc.returncode == 0:
        return 0
    return _fail("shift-left: scripts/ unittest suite FAILED"
                 " (mirrors .github/workflows/scripts-tests.yml):",
                 proc.stdout + "\n" + proc.stderr)


def _run_edge_sim(root: Path) -> int:
    sim_dir = root / "edge" / "sim"
    if shutil.which("uv") is None or not sim_dir.is_dir():
        return 0
    # Exact CI command (edge-sim.yml), cwd edge/sim as in the workflow.
    proc = _run(["uv", "run", "--frozen", "--python", "3.12", "pytest", "-q"],
                cwd=sim_dir, timeout=110)
    if proc is None or proc.returncode == 0:
        return 0
    return _fail("shift-left: edge/sim pytest FAILED"
                 " (mirrors .github/workflows/edge-sim.yml):",
                 proc.stdout + "\n" + proc.stderr)


def _run_prettier(root: Path, abs_file: Path) -> int:
    drivers = root / "edge" / "drivers"
    prettier = drivers / "node_modules" / ".bin" / "prettier"
    # node_modules appears only after `npm ci` in the submodule (see its README);
    # until then formatting is CI's problem, not a hook failure.
    if not (prettier.is_file() and os.access(prettier, os.X_OK)):
        return 0
    # cwd = edge/drivers so its .prettierrc.yml applies.
    proc = _run([str(prettier), "--write", str(abs_file)], cwd=drivers, timeout=60)
    if proc is None or proc.returncode == 0:
        return 0
    return _fail(f"shift-left: prettier FAILED on {abs_file}:", proc.stderr)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return 0

    root = _repo_root()
    try:
        abs_file = Path(file_path).resolve()
        rel = abs_file.relative_to(root)
    except (ValueError, OSError):
        return 0  # outside the repo — not ours to check

    parts = rel.parts
    if len(parts) == 2 and parts[0] == "scripts" and rel.suffix == ".py":
        return _run_scripts_suite(root)
    if len(parts) >= 3 and parts[:2] == ("edge", "sim"):
        return _run_edge_sim(root)
    if len(parts) >= 3 and parts[:2] == ("edge", "drivers") and rel.suffix in PRETTIER_SUFFIXES:
        return _run_prettier(root, abs_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
