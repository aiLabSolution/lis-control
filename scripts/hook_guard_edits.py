#!/usr/bin/env python3
"""Claude Code PreToolUse guard for append-only / immutable files.

Why this exists
---------------
Two classes of file in this repo must never be edited in place, and each has
bitten a real session:

  * Liquibase changesets under core/openelis/src/main/resources/liquibase/ —
    once a changeset is committed in the core/openelis submodule it is (or is
    about to be) applied and checksummed on deployed databases; editing it in
    place breaks `liquibase update` on every existing install. The base
    changelogs (base-changelog.xml, any base.xml) are the append-only spine:
    existing <include> entries may never be removed or reordered, only new
    ones appended — the keep-both-blocks / never-renumber rule from the
    upstream-sync postmortem.
  * core/openelis/tools/OpenELIS_java_formatter.xml — the single formatting
    source for the whole core repo; an edit silently reformats every Java
    file on the next spotless run.

Wired in .claude/settings.json as a PreToolUse hook on Edit|Write|MultiEdit.
Contract: hook payload JSON on stdin; exit 0 allows, exit 2 blocks (stderr is
fed back to the model). Anything unexpected — malformed stdin, missing git,
uninitialized submodule — FAILS OPEN (exit 0): a broken hook must never brick
an editing session. Deliberate escape hatch: LIS_EDIT_GUARD_OVERRIDE=1.

Repo root defaults to the parent of this scripts/ dir; LIS_HOOK_REPO_ROOT
overrides it (tests, cross-checkout smoke runs). Stdlib only.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_LIQUIBASE = ("core", "openelis", "src", "main", "resources", "liquibase")
_FORMATTER = ("core", "openelis", "tools", "OpenELIS_java_formatter.xml")
_BASE_NAMES = ("base-changelog.xml", "base.xml")
_OVERRIDE = "LIS_EDIT_GUARD_OVERRIDE"
_HATCH = f"If this is a deliberate, reviewed exception: re-run with {_OVERRIDE}=1."

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# Real shapes vary: <include file="..." /> and <include relativeToChangelogFile="true" file="..."/>
_INCLUDE_RE = re.compile(r"<include\b[^>]*>")


def _repo_root():
    return Path(
        os.environ.get("LIS_HOOK_REPO_ROOT") or Path(__file__).resolve().parent.parent
    ).resolve()


def _in_submodule_head(submodule, rel_posix):
    """True/False = tracked/untracked in submodule HEAD; None = no usable answer (fail open)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(submodule), "ls-tree", "HEAD", "--", rel_posix],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:  # no git dir / unborn HEAD (uninitialized worktree)
        return None
    return bool(proc.stdout.strip())


def _simulate(tool_name, tool_input, on_disk):
    """Post-edit content, or None when the tool call would fail on its own anyway."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    edits = [tool_input] if tool_name == "Edit" else list(tool_input.get("edits") or [])
    text = on_disk
    for edit in edits:
        old = edit.get("old_string", "")
        if not old or old not in text:
            return None
        new = edit.get("new_string", "")
        text = text.replace(old, new) if edit.get("replace_all") else text.replace(old, new, 1)
    return text


def _includes(xml_text):
    # Whole normalized tags, not just file= values: rewriting an existing entry's
    # attributes (e.g. adding relativeToChangelogFile) changes which file the chain
    # resolves to — that is mutation, and must break the prefix compare.
    return [
        re.sub(r"\s+", " ", tag).strip()
        for tag in _INCLUDE_RE.findall(_COMMENT_RE.sub("", xml_text))
    ]


def _check_base_changelog(tool_name, tool_input, target, rel):
    try:
        before_text = target.read_text(encoding="utf-8")
    except OSError:
        return None
    after_text = _simulate(tool_name, tool_input, before_text)
    if after_text is None:
        return None
    before = _includes(before_text)
    if _includes(after_text)[: len(before)] == before:
        return None
    return (
        f"BLOCKED: this edit removes, reorders, or rewrites existing <include> entries in {rel}.\n"
        "Base changelogs are append-only (keep-both-blocks / never-renumber): the included "
        "changesets are already checksummed on deployed databases, so the existing chain must "
        "survive verbatim.\n"
        f"Remedy: keep every current <include> in place and in order; only APPEND new entries. {_HATCH}"
    )


def check(payload):
    """None = allow; str = block message (goes to stderr, exit 2)."""
    if os.environ.get(_OVERRIDE) == "1":
        return None
    tool_name = payload.get("tool_name")
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return None
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path or not isinstance(file_path, str):
        return None
    root = _repo_root()
    target = Path(file_path)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        rel = target.relative_to(root)
    except ValueError:
        return None  # outside the repo — not ours to police

    if rel.parts == _FORMATTER:
        if _in_submodule_head(root / "core" / "openelis", "tools/OpenELIS_java_formatter.xml"):
            return (
                f"BLOCKED: {rel} is the single formatting source for the whole core repo — any "
                "change here silently reformats every Java file on the next spotless run.\n"
                "Remedy: leave it untouched; a deliberate formatting-rule change must go through "
                f"its own reviewed core/openelis PR. {_HATCH}"
            )
        return None

    if rel.parts[: len(_LIQUIBASE)] != _LIQUIBASE or len(rel.parts) == len(_LIQUIBASE):
        return None
    # core/openelis is a submodule: "already committed?" must be asked of ITS git dir.
    committed = _in_submodule_head(root / "core" / "openelis", "/".join(rel.parts[2:]))
    if not committed:
        return None  # brand-new changeset (or unusable submodule): stays editable until committed
    if rel.name in _BASE_NAMES:
        return _check_base_changelog(tool_name, tool_input, target, rel)
    return (
        f"BLOCKED: {rel} is an already-committed liquibase changeset; applied changesets are "
        "checksummed on every deployed database, so editing one in place breaks `liquibase "
        "update` on upgrade.\n"
        "Remedy: put the correction in a NEW numbered changeset file and <include> it from the "
        f"matching base changelog. {_HATCH}"
    )


def main():
    try:
        message = check(json.load(sys.stdin))
    except Exception:
        return 0  # fail open: a broken hook must never brick an editing session
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
