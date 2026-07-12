#!/usr/bin/env python3
"""Deterministic ADR lint — catch number collisions before they land, nothing more.

Why this exists
---------------
ADR numbers here have collided during concurrent merges before (ADR-0011 is a
renumbered 0006; see the "ADR number collision resolution" protocol). The number
namespace is also *deliberately* overloaded: the umbrella `docs/adr/` and each
`contexts/<name>/docs/adr/` carry their own independent 0001..N sequence, so
"ADR-0003" legitimately names two different documents. A generic ADR linter
flags that; this one knows better.

Rules
-----
ERROR (exit 1)
  * duplicate 4-digit number within one namespace.
WARN (stderr, exit 0)
  * filename not matching `NNNN-<kebab-slug>.md`;
  * ADR missing a recognizable Status (this repo's form is a
    `- **Status:** <value>` header bullet; a `## Status` heading is also read);
  * Status value outside the set this repo actually uses.
Deliberately NOT flagged: numbering gaps (renumbering is forbidden — gaps are
the natural residue of collision resolution) and cross-namespace number reuse.

Usage
-----
  python3 scripts/adr_lint.py [--repo-root PATH]
Clean run prints nothing and exits 0.
"""

import argparse
import re
import sys
from pathlib import Path

FILENAME_RE = re.compile(r"^\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
NUMBER_RE = re.compile(r"^(\d{4})\D")
# Strip markdown emphasis/list decoration so `- **Status:** **Accepted**`,
# `Status: Accepted` and `> **Status**: Accepted` all reduce to the same text.
DECOR_RE = re.compile(r"[*_`]+")
STATUS_LINE_RE = re.compile(r"^[-+>\s]*Status\s*:\s*(\S.*)$", re.IGNORECASE)
STATUS_HEADING_RE = re.compile(r"^#{1,6}\s*Status\s*$", re.IGNORECASE)

# Lifecycle values in actual use across docs/adr/ and contexts/*/docs/adr/
# (surveyed 2026-07-12: Accepted ×18, Proposed ×7). Superseded is allowed
# because every ADR header carries a "Supersedes / Superseded by" field, so
# it is the anticipated third state even though no ADR holds it yet.
ALLOWED_STATUSES = {"Proposed", "Accepted", "Superseded"}


def find_namespaces(root):
    """Independent number namespaces: umbrella docs/adr + each context's docs/adr."""
    candidates = [root / "docs" / "adr"]
    contexts = root / "contexts"
    if contexts.is_dir():
        candidates.extend(sorted(p / "docs" / "adr" for p in contexts.iterdir() if p.is_dir()))
    return [p for p in candidates if p.is_dir()]


def extract_status(text):
    """Return the raw Status value, or None if the ADR has no recognizable one."""
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = DECOR_RE.sub("", raw).strip()
        m = STATUS_LINE_RE.match(line)
        if m:
            return m.group(1).strip()
        if STATUS_HEADING_RE.match(line):
            for follow in lines[i + 1 :]:
                value = DECOR_RE.sub("", follow).strip()
                if value:
                    return value
    return None


def lint_file(path, rel, warnings):
    if not FILENAME_RE.match(path.name):
        warnings.append("WARN %s: filename does not match NNNN-<kebab-slug>.md" % rel)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return  # fail open: an unreadable file is an infrastructure problem, not a lint finding
    status = extract_status(text)
    if status is None:
        warnings.append("WARN %s: no recognizable Status (expected a '- **Status:** <value>' header bullet)" % rel)
        return
    # Values carry annotations ("Accepted (signed off ...)"), so gate on the leading word.
    leading = status.split(None, 1)[0].rstrip(".,;:—-")
    if leading not in ALLOWED_STATUSES:
        warnings.append(
            "WARN %s: Status %r not in the set used by this repo (%s)"
            % (rel, leading, "/".join(sorted(ALLOWED_STATUSES)))
        )


def lint_repo(root):
    """Lint every ADR namespace under root; return (error_lines, warning_lines)."""
    root = Path(root)
    errors, warnings = [], []
    for ns in find_namespaces(root):
        ns_rel = ns.relative_to(root).as_posix()
        by_number = {}
        for path in sorted(ns.glob("*.md")):
            lint_file(path, "%s/%s" % (ns_rel, path.name), warnings)
            m = NUMBER_RE.match(path.name)
            if m:
                by_number.setdefault(m.group(1), []).append(path.name)
        for number, names in sorted(by_number.items()):
            if len(names) > 1:
                errors.append("ERROR %s: duplicate ADR number %s: %s" % (ns_rel, number, ", ".join(names)))
    return errors, warnings


def main(argv=None):
    default_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Lint ADR numbering and Status headers.")
    parser.add_argument("--repo-root", type=Path, default=default_root, help="repo root (default: %(default)s)")
    args = parser.parse_args(argv)

    errors, warnings = lint_repo(args.repo_root)
    for line in errors:
        print(line)
    for line in warnings:
        print(line, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
