"""Capture-sanitize tooling -- LIS-319 (Phase 0.5 of the MAGLUMI X3 dev-simulator
plan).

Bench captures of the SNIBE MAGLUMI X3 carry PHI: the ASTM O-record field 3
(specimen/sample-id position) has carried a real patient name (see
``evidence/bench/maglumi-x3/20260717-0101010034012301113/``, and the
``PATIENT-REDACTED-1``/``BENCH-SAMPLE-001`` tokens already hand-applied to two
prior bench sessions). This module makes that redaction a deterministic,
structure-verified tool instead of an ad-hoc hand edit:

* :func:`sanitize_capture` redacts one addressed ASTM field (``--record``/
  ``--field``, 1-based, ``fields[0]`` is the record-type letter itself) across
  every envelope of a raw capture -- the byte stream a bench session leaves on
  disk (``scripts/x3_astm_capture.py``'s ``raw-*.bin``): ASCII with control
  bytes ``ENQ``/``STX``/``ETX``/``EOT``, CR-separated records between
  ``STX``/``ETX``, one or more ``ENQ..EOT`` envelopes per session (one per
  assay, in the X3's simplified envelope -- see :mod:`edge_sim.snibelis`).
* It rewrites the matching annotated log (the ``annotated-*.log`` companion
  file) line-for-line in the *exact* format ``x3_astm_capture.py`` emits:
  ``RECV <n>B  hex=...`` / ``decode=...`` line pairs and the plain-text
  ``CAPTURE SUMMARY`` block.
* It writes a ``sanitization.json`` transformation ledger recording *that* a
  redaction happened, deliberately never recording the original value, its
  length, or an absolute path (see "DELIBERATE OMISSIONS" on
  :func:`sanitize_capture`).
* It refuses (writes nothing) unless the sanitized capture is verified,
  in-memory, to have the identical structural shape as the original -- see
  ``_verify_structure``.
* It refuses to run against an input capture that lives inside this
  repository's working tree at all: quarantine-first intake means a raw
  capture never lands in git or a PR before it has been sanitized and
  reviewed. There is no override flag; that posture is deliberate.

Output contract (fd-pinned staging, single atomic publish)
------------------------------------------------------------
``--out`` must name a directory that does NOT yet exist, whose PARENT
already does. The tool never creates ``--out``'s parent (no more
``mkdir(parents=True)``); the caller creates it once, deliberately. The
three output files (sanitized bin, sanitized log, ``sanitization.json``)
are written into a sibling staging directory, ``<out>.staging``, and the
whole staging directory is published as ``--out`` in ONE atomic
``os.rename`` at the very end -- so a fault at any point before that single
rename leaves neither a partial ``--out`` nor any final-named file behind,
only (at worst) a ``<out>.staging`` directory that a subsequent run refuses
to reuse (crashed-prior-run posture: inspect/delete it by hand).

This closes two defects an external adversarial review (Codex round 3)
found in the prior per-file ``<name>.tmp`` + sequential-``os.replace``
design: (1) a parent-directory swap performed AFTER the original up-front
path checks but before writing could redirect every subsequent write
through a re-traversed pathname -- fixed by resolving ``--out``'s parent
ONCE, early (before any of the slower parsing/redaction/ledger work below),
and opening it with ``os.open(..., O_NOFOLLOW)`` to obtain a directory file
descriptor; every later filesystem operation for output goes through that
fd (or the staging-directory fd derived from it) via the ``dir_fd=``-taking
``os.*`` calls, never through ``out_dir``'s pathname again, so a rename-
and-symlink swap of ``out_dir``'s parent after the pin cannot retarget the
write. (2) three independent sequential ``os.replace`` calls could leave a
partial final set (e.g. a final bin with no ledger) if a fault struck
between them -- fixed by publishing all three files as one directory via a
single ``os.rename``, which is atomic: either the whole set appears at
``--out`` or none of it does.

Canonical token vocabulary
---------------------------
``TOKEN_CLASSES`` maps a redaction class to its token prefix; the caller
supplies ``--ordinal`` (default 1) to get e.g. ``PATIENT-REDACTED-1``, or an
explicit ``--token`` to control the value directly (required whenever
``--no-length-preserving`` is not used and the class-derived token's length
does not happen to match the original field). ``BENCH-SAMPLE-001`` is
grandfathered from the 2026-07-17 session 004 evidence: it is *recognized* (a
legacy value already in the evidence tree) but this tool never emits it for a
new redaction.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .astm import ACK, CR, ENQ, EOT, ETB, ETX, NAK, STX

__all__ = [
    "TOKEN_CLASSES",
    "LEGACY_TOKENS",
    "SanitizeError",
    "SanitizeResult",
    "sanitize_capture",
]

# --- canonical token vocabulary ---------------------------------------------
TOKEN_CLASSES = {
    "patient-name": "PATIENT-REDACTED-",
    "operator-id": "OPERATOR-REDACTED-",
    "specimen-id": "SPECIMEN-REDACTED-",
}

# Grandfathered in the 2026-07-17 session 004 evidence
# (evidence/bench/maglumi-x3/20260717-0101010034012301113/) -- recognized as a
# legacy value already committed to the evidence tree, never emitted by this
# tool for a new redaction.
LEGACY_TOKENS = {"BENCH-SAMPLE-001"}

# A token must never contain an ASTM delimiter -- it would corrupt the
# field/record structure it is substituted into. (CR, every other C0 control,
# and DEL are rejected separately below by the printable-ASCII range check --
# not listed here since they are not ASTM delimiters per se.)
_FORBIDDEN_TOKEN_CHARS = frozenset("|\\^&")

# A token must consist solely of printable ASCII -- 0x20 (space) through 0x7E
# (``~``) inclusive. This rejects every C0 control byte (0x00-0x1F, which
# includes CR, LF, NUL, and TAB) and DEL (0x7F), matching the project's
# established escape-all-C0 wire posture: a length-matched token containing
# e.g. LF or NUL would otherwise pass both this validator and structure
# verification (records split on CR; no field/delimiter count changes), so a
# malformed field would get certified ``structure_verified: true``.
_PRINTABLE_ASCII_MIN = 0x20
_PRINTABLE_ASCII_MAX = 0x7E

# Control bytes whose exact order (and, in length-preserving mode, exact byte
# offset) must survive redaction unchanged -- ENQ/STX/ETX/EOT per the plan,
# plus ETB/ACK/NAK for robustness against a framed or bidirectional capture.
_CONTROL_BYTES = frozenset({ENQ, ACK, STX, ETX, ETB, EOT, NAK})

# The ASTM E1394 delimiter characters (default ``|\^&`` -- see
# edge_sim.e1394.Delimiters) -- used to build a delimiter-only "skeleton" of a
# record line for the structure-verification delimiter-bytes check.
_DELIMITER_CHARS = frozenset("|\\^&")

_PIPE = ord("|")

try:
    # edge_sim's package __init__ does not currently define __version__; fall
    # back per the LIS-319 spec if/when it does.
    from . import __version__ as _SANITIZER_VERSION  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised whenever __init__ lacks it
    _SANITIZER_VERSION = "0.1"

# Mirror of scripts/x3_astm_capture.py's ``_CTRL_NAME`` -- reproduced (not
# imported; that script is a standalone bench tool, not a package dependency
# of edge_sim) so a redacted RECV chunk's expected decode= rendering can be
# recomputed and checked for consistency before any output is written.
_CTRL_NAME_FOR_LOG = {
    ENQ: "ENQ",
    ACK: "ACK",
    STX: "STX",
    ETX: "ETX",
    ETB: "ETB",
    EOT: "EOT",
    CR: "CR",
    0x0A: "LF",
    NAK: "NAK",
}


class SanitizeError(Exception):
    """Raised whenever a capture cannot be sanitized safely. No partial output
    is ever produced when this is raised -- callers (the CLI) map it to a
    clean exit 1, never a traceback."""


@dataclass(frozen=True)
class SanitizeResult:
    """Outcome of a successful :func:`sanitize_capture` call."""

    bin_path: Path
    log_path: Path | None
    ledger_path: Path
    token: str
    occurrences: int


# --- byte-stream structural parsing (no sockets, no records tree needed) ---
@dataclass(frozen=True)
class _Field:
    start: int  # absolute byte offset in the raw capture
    end: int  # exclusive
    text: str


@dataclass(frozen=True)
class _RecordSpan:
    start: int
    end: int  # exclusive, before the terminating CR
    type: str
    fields: tuple[_Field, ...]
    raw_text: str


@dataclass(frozen=True)
class _Envelope:
    start: int  # offset of ENQ
    end: int  # exclusive, offset just past EOT (or end of a truncated envelope)
    records: tuple[_RecordSpan, ...]


@dataclass(frozen=True)
class _Structure:
    control_sequence: tuple[int, ...]
    control_offsets: tuple[int, ...]
    envelopes: tuple[_Envelope, ...]
    total_length: int


@dataclass(frozen=True)
class _Occurrence:
    start: int
    end: int
    value: str


def _scan_control_tokens(raw: bytes) -> tuple[tuple[int, int], ...]:
    return tuple((i, b) for i, b in enumerate(raw) if b in _CONTROL_BYTES)


def _build_record(raw: bytes, start: int, end: int) -> _RecordSpan:
    text = raw[start:end].decode("latin-1")
    rtype = text[:1]
    fields: list[_Field] = []
    field_start = start
    for idx in range(start, end):
        if raw[idx] == _PIPE:
            fields.append(_Field(field_start, idx, raw[field_start:idx].decode("latin-1")))
            field_start = idx + 1
    fields.append(_Field(field_start, end, raw[field_start:end].decode("latin-1")))
    return _RecordSpan(start=start, end=end, type=rtype, fields=tuple(fields), raw_text=text)


def _parse_records(raw: bytes, start: int, end: int) -> tuple[_RecordSpan, ...]:
    records: list[_RecordSpan] = []
    rec_start = start
    for i in range(start, end):
        if raw[i] == CR:
            if i > rec_start:
                records.append(_build_record(raw, rec_start, i))
            rec_start = i + 1
    if rec_start < end:
        records.append(_build_record(raw, rec_start, end))
    return tuple(records)


def _parse_structure(raw: bytes) -> _Structure:
    """Parse a raw capture byte stream into envelopes/records/fields.

    Tolerant of only a missing final ``EOT`` (link closed right after ``ETX``)
    so a mid-session link drop right after the last record is still
    sanitizable. Otherwise strict: a missing ``ETX`` -- or any byte sequence
    that does not look like ``ENQ STX ... ETX [EOT]`` -- raises
    :class:`SanitizeError` ("the input capture fails to parse").
    """
    envelopes: list[_Envelope] = []
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] != ENQ:
            raise SanitizeError(
                f"cannot parse capture as an ASTM session: expected ENQ at byte "
                f"offset {i}, found 0x{raw[i]:02x}"
            )
        enq = i
        if i + 1 >= n or raw[i + 1] != STX:
            raise SanitizeError(
                f"cannot parse capture as an ASTM session: expected STX right "
                f"after ENQ at byte offset {i}"
            )
        stx = i + 1
        etx = None
        j = stx + 1
        while j < n:
            if raw[j] == ETX:
                etx = j
                break
            j += 1
        if etx is None:
            # Truncated envelope (link dropped mid-message): keep what we have
            # as one envelope with no records parsed past the truncation point
            # is not attempted -- refuse instead, since a truncated envelope
            # cannot be structurally verified after redaction either.
            raise SanitizeError(
                f"cannot parse capture as an ASTM session: no ETX found for the "
                f"envelope starting at byte offset {enq} (truncated capture?)"
            )
        eot = None
        if etx + 1 < n and raw[etx + 1] == EOT:
            eot = etx + 1
            end = eot + 1
        else:
            end = etx + 1  # tolerate a missing EOT (link closed right after ETX)
        records = _parse_records(raw, stx + 1, etx)
        envelopes.append(_Envelope(start=enq, end=end, records=records))
        i = end
    control_tokens = _scan_control_tokens(raw)
    return _Structure(
        control_sequence=tuple(b for _, b in control_tokens),
        control_offsets=tuple(off for off, _ in control_tokens),
        envelopes=tuple(envelopes),
        total_length=n,
    )


def _delimiter_skeleton(text: str) -> tuple[str, ...]:
    return tuple(c for c in text if c in _DELIMITER_CHARS)


def _verify_structure(original: _Structure, candidate: _Structure, *, length_preserving: bool) -> None:
    """The core guarantee: the sanitized capture has the identical structural
    shape as the original. Raises :class:`SanitizeError` on the first
    mismatch found; callers must call this BEFORE writing any output."""
    if original.control_sequence != candidate.control_sequence:
        raise SanitizeError(
            "structure verification failed: the control-token (ENQ/STX/ETX/EOT/"
            "ACK) sequence changed -- refusing to write a corrupted capture"
        )
    if len(original.envelopes) != len(candidate.envelopes):
        raise SanitizeError(
            "structure verification failed: envelope count changed "
            f"({len(original.envelopes)} -> {len(candidate.envelopes)})"
        )
    for env_idx, (orig_env, cand_env) in enumerate(zip(original.envelopes, candidate.envelopes)):
        if len(orig_env.records) != len(cand_env.records):
            raise SanitizeError(
                f"structure verification failed: record count changed in "
                f"envelope {env_idx}"
            )
        for orig_rec, cand_rec in zip(orig_env.records, cand_env.records):
            if orig_rec.type != cand_rec.type:
                raise SanitizeError(
                    f"structure verification failed: record-type sequence changed "
                    f"in envelope {env_idx}"
                )
            if len(orig_rec.fields) != len(cand_rec.fields):
                raise SanitizeError(
                    f"structure verification failed: field count changed in a "
                    f"{orig_rec.type!r} record in envelope {env_idx}"
                )
            if _delimiter_skeleton(orig_rec.raw_text) != _delimiter_skeleton(cand_rec.raw_text):
                raise SanitizeError(
                    f"structure verification failed: delimiter bytes changed in a "
                    f"{orig_rec.type!r} record in envelope {env_idx}"
                )
    if length_preserving:
        if original.total_length != candidate.total_length:
            raise SanitizeError(
                "structure verification failed: total byte length changed under "
                "length-preserving redaction "
                f"({original.total_length} -> {candidate.total_length})"
            )
        if original.control_offsets != candidate.control_offsets:
            raise SanitizeError(
                "structure verification failed: a control token moved to a "
                "different byte offset under length-preserving redaction"
            )


def _find_occurrences(structure: _Structure, *, record: str, field: int) -> list[_Occurrence]:
    occurrences: list[_Occurrence] = []
    for envelope in structure.envelopes:
        for rec in envelope.records:
            if rec.type != record:
                continue
            if field < 1 or field > len(rec.fields):
                continue
            f = rec.fields[field - 1]
            if f.text == "":
                continue
            occurrences.append(_Occurrence(start=f.start, end=f.end, value=f.text))
    return occurrences


def _find_external_occurrence(
    structure: _Structure, *, record: str, field: int, values: set[str]
) -> tuple[str, int, str] | None:
    """Scan every field of every record (any record type, any field position)
    for a value that also occurs in the addressed ``record``.``field`` -- i.e.
    the same PHI value recurring somewhere a single-field redaction does not
    cover (LIS-319 adversarial review: e.g. the same patient name repeated in
    a P-record field). Returns ``(record_type, field_number, value)`` for the
    first such occurrence found (any envelope), or ``None``.

    Called before any redaction work happens so a recurrence-elsewhere refusal
    names the exact other location up front, rather than surfacing as a
    generic post-write leak-check failure. A single :func:`sanitize_capture`
    invocation only ever addresses one field, so a value recurring elsewhere
    can only be resolved by redacting that field too, in a separate
    invocation -- fail closed rather than emit a capture with a PHI copy left
    behind."""
    for envelope in structure.envelopes:
        for rec in envelope.records:
            for idx, f in enumerate(rec.fields, start=1):
                if rec.type == record and idx == field:
                    continue  # the addressed field itself -- not "external"
                if f.text and f.text in values:
                    return (rec.type, idx, f.text)
    return None


def _apply_redactions(raw: bytes, occurrences: list[_Occurrence], token_bytes: bytes) -> bytes:
    """Splice ``token_bytes`` into every addressed occurrence's byte range.

    Processes offsets highest-first so earlier (lower) offsets stay valid even
    when the token's length differs from the original field's length."""
    new_raw = bytearray(raw)
    for occ in sorted(occurrences, key=lambda o: o.start, reverse=True):
        new_raw[occ.start : occ.end] = token_bytes
    return bytes(new_raw)


# --- token validation ---------------------------------------------------
def _validate_token(token: str) -> None:
    if not token:
        raise SanitizeError("token must not be empty")
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SanitizeError(f"token must be ASCII, got {token!r}") from exc

    bad_delims = _FORBIDDEN_TOKEN_CHARS & set(token)
    if bad_delims:
        raise SanitizeError(
            f"token {token!r} contains a forbidden delimiter character "
            f"{sorted(bad_delims)!r} -- a token must never contain an ASTM "
            "delimiter (| \\ ^ &)"
        )

    non_printable = sorted({b for b in token_bytes if not (_PRINTABLE_ASCII_MIN <= b <= _PRINTABLE_ASCII_MAX)})
    if non_printable:
        raise SanitizeError(
            f"token {token!r} contains non-printable byte(s) "
            f"{[f'0x{b:02x}' for b in non_printable]} -- a token must consist "
            "solely of printable ASCII (0x20-0x7E); every C0 control byte "
            "(including CR, LF, NUL, and TAB) and DEL (0x7f) is rejected"
        )


# --- quarantine-first intake ---------------------------------------------
def _repo_root() -> Path:
    """The umbrella repo's working-tree root, derived from this file's own
    location: edge/sim/src/edge_sim/sanitize.py -> parents[0]=edge_sim,
    [1]=src, [2]=sim, [3]=edge, [4]=the repo root. (edge/sim is a plain
    directory in the umbrella repo, not its own submodule -- only
    core/openelis, edge/drivers and deploy/kit are, per .gitmodules -- so the
    repo root is five levels up from this file, not four.)"""
    return Path(__file__).resolve().parents[4]


def _check_quarantine(path: Path) -> None:
    resolved = path.resolve()
    root = _repo_root()
    try:
        resolved.relative_to(root)
    except ValueError:
        return  # outside the repo tree: fine
    raise SanitizeError(
        f"refusing to sanitize {path}: it lives inside the repository working "
        f"tree ({root}) -- quarantine-first intake requires a raw capture to "
        "live outside the repo until it has been sanitized and privacy-"
        "reviewed; there is no override flag"
    )


# --- output-path safety ------------------------------------------------
def _check_output_paths(
    *, bin_path: Path, log_path: Path | None, out_dir: Path
) -> tuple[Path, Path | None, Path]:
    """Cheap, pathname-level checks on ``out_dir`` -- fast failure with a
    precise message before any parsing, redaction, or fd work is attempted.
    These are NOT the authoritative guarantee (see :func:`sanitize_capture`'s
    fd-pinned checks, which run against ``os.stat(..., dir_fd=parent_fd,
    follow_symlinks=False)`` and are race-free); this function purely
    improves the common, non-adversarial error message and fails fast.

    Refuses whenever:

    (a) ``out_dir`` resolves to the same directory as an input's own parent
        directory (the caller pointed ``--out`` at the quarantine directory
        itself) -- checked first so this specific footgun gets the precise
        pristine-evidence message, mentioning "pristine" explicitly.

    (b) ``out_dir`` already exists as ANY kind of directory entry --
        checked via ``os.lstat`` (symlink-aware: a symlink counts as an
        existing entry, even a dangling one that would otherwise fool a
        followed-symlink ``exists()`` check). This replaces the OLD per-
        final-name existence checks: under the new output contract, ``--out``
        is a single unit that either does not exist yet (may proceed) or
        already exists (refuse) -- there is no longer a notion of some of
        its three files existing and others not.

    (c) ``out_dir``'s PARENT does not already exist. This tool no longer
        creates ``--out``'s parent (no ``mkdir(parents=True)`` any more) --
        the fd-pinning guarantee in :func:`sanitize_capture` requires a real,
        already-existing parent directory to open and hold open (via
        ``os.open(..., O_NOFOLLOW)``) for the duration of the run.

    Returns ``(out_bin_path, out_log_path, ledger_path)`` -- the FINAL
    output paths, for the caller's bookkeeping and for the eventual
    :class:`SanitizeResult`. Only their ``.name`` (basename) is used for the
    actual fd-relative writes; the caller never re-traverses these Path
    objects to perform a write.
    """
    inputs: list[tuple[str, Path]] = [("capture", bin_path.resolve())]
    if log_path is not None:
        inputs.append(("log", log_path.resolve()))

    out_dir_resolved = out_dir.resolve()
    for in_label, resolved_in in inputs:
        if out_dir_resolved == resolved_in.parent:
            raise SanitizeError(
                f"refusing to write: --out ({out_dir}) resolves to the same "
                f"directory as the input {in_label}'s own directory "
                f"({resolved_in.parent}) -- writing there would overwrite "
                f"the pristine quarantined {in_label}; choose a different "
                "--out directory"
            )

    out_bin_path = out_dir / bin_path.name
    out_log_path = out_dir / log_path.name if log_path is not None else None
    ledger_path = out_dir / "sanitization.json"

    try:
        os.lstat(out_dir)
    except FileNotFoundError:
        pass
    else:
        raise SanitizeError(
            f"refusing to write: --out directory {out_dir} already exists -- "
            "under the current output contract the --out directory must NOT "
            "exist (the sanitized bin/log/ledger are published as one new "
            "directory, atomically); choose a fresh --out path"
        )

    parent = out_dir.parent
    if not parent.is_dir():
        raise SanitizeError(
            f"refusing to write: --out's parent directory ({parent}) does "
            "not exist -- this tool creates --out itself but not its "
            "parent; create the parent directory first, then re-run"
        )

    return out_bin_path, out_log_path, ledger_path


def _resolve_parent_strict(out_dir: Path) -> Path:
    """Resolve ``out_dir``'s parent to a canonical, symlink-free path,
    strictly (raising if it does not actually exist right now). This is the
    first half of the fd-pinning guarantee (see :func:`_open_parent_dir_fd`):
    resolving separately from opening leaves a tiny window between the two
    (documented, out-of-scope residual -- see :func:`sanitize_capture`'s
    docstring), but the ``O_NOFOLLOW`` on the subsequent open closes it for
    the specific case of the final path component being swapped for a
    symlink in that window."""
    try:
        return out_dir.parent.resolve(strict=True)
    except OSError as exc:
        raise SanitizeError(
            f"refusing to write: --out's parent directory ({out_dir.parent}) "
            f"could not be resolved ({exc.strerror or exc}) -- create it "
            "first, then re-run"
        ) from exc


def _open_parent_dir_fd(parent_resolved: Path) -> int:
    """Open ``parent_resolved`` ONCE and return a directory file descriptor
    pinned to it. Every subsequent output filesystem operation goes through
    this fd (or the staging-directory fd derived from it) via the
    ``dir_fd=``-taking ``os.*`` calls, never through ``out_dir``'s pathname
    again -- so a rename-and-symlink swap of ``out_dir``'s parent performed
    AFTER this call (e.g. by an attacker who moves the real directory aside
    and plants a symlink at its old name pointing at an input's quarantine
    directory) cannot redirect any later write: the fd stays bound to the
    original directory's inode regardless of what its old pathname now
    refers to. ``O_NOFOLLOW`` refuses to open if the pathname's last
    component is itself a symlink at open time."""
    try:
        return os.open(str(parent_resolved), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SanitizeError(
            f"refusing to write: could not open --out's parent directory "
            f"{parent_resolved} ({exc.strerror or exc})"
        ) from exc


def _assert_absent_fd(parent_fd: int, name: str, *, message: str) -> None:
    """Authoritative, race-free existence check: ``os.stat(name, dir_fd=...,
    follow_symlinks=False)`` is an ``fstatat(..., AT_SYMLINK_NOFOLLOW)`` --
    it inspects the directory entry itself (lstat semantics), so a symlink
    at ``name`` counts as "existing" even when it is dangling (its target
    does not exist). Raises :class:`SanitizeError` with ``message`` whenever
    anything at all is found there; a clean ``FileNotFoundError`` is the
    only success case."""
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise SanitizeError(message)


def _make_staging_dir(parent_fd: int, staging_name: str) -> int:
    """Create the sibling staging directory ``<out>.staging`` and open it,
    both fd-relative to the already-pinned parent directory fd -- the
    staging unit every output file is written into before the single
    atomic publish (see :func:`_publish_staging_dir`).

    ``os.mkdir(..., dir_fd=parent_fd)`` fails closed (``FileExistsError``)
    on ANY pre-existing entry at ``staging_name`` -- regular file, symlink,
    or directory -- atomically, independent of the caller's earlier
    ``_assert_absent_fd`` check (which exists purely for a precise error
    message in the common, non-racing case). A pre-existing staging entry
    most often means a prior run crashed between creating the staging
    directory and completing the final rename; the operator is directed to
    inspect and delete it by hand rather than have this tool guess whether
    it is safe to reuse or remove.

    Isolated as its own small function (rather than inlined) so a test can
    wrap it to plant an entry INSIDE the freshly created, freshly opened
    staging directory -- proving the ``O_EXCL | O_NOFOLLOW`` staged-file
    opens (see :func:`_open_staging_fd`) are a real defense-in-depth layer
    of their own, not merely redundant with this directory-level guard.
    """
    try:
        os.mkdir(staging_name, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise SanitizeError(
            f"refusing to write: a staging entry already exists at "
            f"{staging_name!r} next to the requested --out directory -- a "
            f"prior run may have crashed before completing publish; inspect "
            f"and delete {staging_name} before retrying"
        ) from exc
    except OSError as exc:
        raise SanitizeError(
            f"refusing to write: could not create staging directory "
            f"{staging_name!r} ({exc.strerror or exc})"
        ) from exc

    try:
        return os.open(staging_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as exc:
        try:
            os.rmdir(staging_name, dir_fd=parent_fd)
        except OSError:
            pass  # best effort -- the open failure below is what we report
        raise SanitizeError(
            f"refusing to write: could not open staging directory "
            f"{staging_name!r} after creating it ({exc.strerror or exc})"
        ) from exc


def _publish_staging_dir(parent_fd: int, staging_name: str, final_name: str) -> None:
    """Atomically publish the fully-written staging directory as
    ``final_name`` -- the single rename that makes the whole three-file
    output set appear at ``--out`` at once (or, on failure, not at all).

    Because the rename SOURCE is a directory, ``rename(2)`` constrains what
    an entry planted at ``final_name`` in the tiny window between the
    caller's pre-rename absence re-check and this rename can do -- and
    never dereferences the destination's final path component in any case:

    * a non-directory entry there (regular file, or a symlink -- dangling
      or not) makes the rename fail with ``ENOTDIR``: the symlink is never
      followed, nothing is written anywhere, and the caller's cleanup
      removes the fully-written staging set;
    * an EMPTY directory there is atomically replaced -- the sanitized set
      still lands at ``--out`` inside the pinned parent;
    * a non-empty directory there makes the rename fail
      (``ENOTEMPTY``/``EEXIST``), same fail-closed outcome as above.

    In every case the quarantined input (reachable only through a wholly
    different, already-pinned path) is untouchable through the destination
    name. A rename failure is wrapped as :class:`SanitizeError` so the CLI
    still exits cleanly rather than with a traceback.

    Isolated as its own function -- rather than an inline ``os.rename`` call
    -- so a test can monkeypatch exactly this publish boundary to simulate a
    fault there, without touching any other ``os.rename`` call in the
    process."""
    try:
        os.rename(staging_name, final_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except OSError as exc:
        raise SanitizeError(
            f"refusing to publish: could not rename the staging directory "
            f"{staging_name!r} onto the final --out name ({exc.strerror or exc}) "
            "-- an entry may have appeared at the --out name during the run; "
            "the staged outputs have been cleaned up, re-run with a fresh --out"
        ) from exc


def _open_staging_fd(staging_fd: int, basename: str) -> int:
    """Create ``basename`` exclusively inside the staging directory (fd
    ``staging_fd``, itself fd-relative to the pinned parent -- see
    :func:`_make_staging_dir`) -- the race-free guarantee behind the
    directory-level checks in :func:`_make_staging_dir`.

    ``O_EXCL`` refuses ANY pre-existing directory entry at ``basename``
    inside the staging directory -- a regular file, a symlink, a FIFO,
    anything -- atomically: the kernel either creates a brand-new entry or
    fails, with no window in which a planted entry could be followed or
    clobbered. This holds even when the entry was planted (e.g. by a racing
    process, or a bug) after the staging directory itself was created and
    opened.

    ``O_NOFOLLOW`` is belt-and-braces on top of ``O_EXCL``: if ``basename``
    is itself a symlink, the open fails rather than following it and
    writing through to whatever it points at -- e.g. a symlink planted at
    the sanitized-bin basename pointing back at the pristine quarantined
    input, which a plain ``write_bytes``/``open(..., "wb")`` would follow
    and irreversibly overwrite.

    Raises :class:`SanitizeError` naming ``basename`` whenever the open
    fails for any reason (pre-existing entry of any kind, symlink,
    permission, etc).
    """
    try:
        return os.open(
            basename,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o644,
            dir_fd=staging_fd,
        )
    except OSError as exc:
        raise SanitizeError(
            f"refusing to write: could not create {basename!r} exclusively "
            f"inside the staging directory ({exc.strerror or exc}) -- an "
            "unexpected entry appeared there (possibly planted, or created "
            "by a race) after the staging directory was created; choose a "
            "fresh --out directory"
        ) from exc


def _write_staged_bytes(staging_fd: int, basename: str, data: bytes) -> None:
    """Create ``basename`` exclusively inside the staging directory (see
    :func:`_open_staging_fd`) and write binary ``data`` through the
    resulting file descriptor."""
    fd = _open_staging_fd(staging_fd, basename)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _write_staged_text(staging_fd: int, basename: str, text: str) -> None:
    """Create ``basename`` exclusively inside the staging directory (see
    :func:`_open_staging_fd`) and write text ``text`` (UTF-8) through the
    resulting file descriptor."""
    fd = _open_staging_fd(staging_fd, basename)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


# --- annotated-log rewriting ----------------------------------------------
def _render_decode(chunk: bytes) -> str:
    """Mirror of scripts/x3_astm_capture.py's ``_decode_chunk``: control
    tokens named, printable ASCII shown verbatim, everything else
    ``\\xHH``-escaped. Used to re-render a redacted RECV chunk's decode= line
    from its sanitized bytes (so hex= and decode= are always derived from, and
    therefore always agree with, the same sanitized bytes) -- never imported
    from the bench script itself, which is a standalone tool, not a package
    dependency."""
    out: list[str] = []
    for byte in chunk:
        if byte in _CTRL_NAME_FOR_LOG:
            out.append(f"<{_CTRL_NAME_FOR_LOG[byte]}>")
        elif 0x20 <= byte < 0x7F:
            out.append(chr(byte))
        else:
            out.append(f"\\x{byte:02x}")
    return "".join(out)


def _replace_text(text: str, distinct_values: list[str], token: str) -> str:
    for value in distinct_values:
        text = text.replace(value, token)
    return text


def _is_summary_close_marker(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) == {"="}


@dataclass(frozen=True)
class _LogChunk:
    """One ``RECV <n>B  hex=...`` / ``decode=...`` line pair, located by line
    index, with the byte range in the ORIGINAL capture it was verified to
    tile exactly (see :func:`_parse_log_chunks`)."""

    hex_line_idx: int
    decode_line_idx: int
    bin_start: int  # offset in the ORIGINAL raw capture
    bin_end: int  # exclusive


def _parse_log_chunks(lines: list[str], raw: bytes) -> list[_LogChunk]:
    """Walk an annotated log's lines, assigning each ``RECV ... hex=`` line the
    byte range it occupies in ``raw`` (a running offset -- the capture tool
    writes ``raw_f.write(chunk)`` per recv, so RECV chunks tile the original
    bin exactly, in order, with no gaps or overlaps). Verifies, for every such
    line, that its decoded hex bytes equal ``raw`` at that range, and that the
    declared ``RECV <n>B`` count matches the decoded length; verifies the
    total tiled length equals ``len(raw)``.

    This is the new integrity check (LIS-319 adversarial review P1): it makes
    log/bin divergence structurally impossible, rather than a silent risk a
    substring-based rewrite could leave undetected. Raises
    :class:`SanitizeError` ("annotated log does not correspond to this
    capture") on the first mismatch, naming the line/offset."""
    chunks: list[_LogChunk] = []
    offset = 0
    n_lines = len(lines)
    i = 0
    while i < n_lines:
        line = lines[i]
        recv_idx = line.find(" RECV ")
        hex_idx = line.find("B  hex=") if recv_idx != -1 else -1
        if recv_idx == -1 or hex_idx == -1:
            i += 1
            continue

        count_str = line[recv_idx + len(" RECV ") : hex_idx]
        hexpart = line[hex_idx + len("B  hex=") :]
        try:
            chunk_bytes = bytes.fromhex(hexpart.replace(" ", ""))
        except ValueError as exc:
            raise SanitizeError(
                "annotated log does not correspond to this capture: unparseable "
                f"hex= on line {i + 1}: {exc}"
            ) from exc
        if not count_str.isdigit() or int(count_str) != len(chunk_bytes):
            raise SanitizeError(
                "annotated log does not correspond to this capture: the "
                f"declared RECV count on line {i + 1} ({count_str!r}) does not "
                f"match its hex= byte count ({len(chunk_bytes)})"
            )
        n = len(chunk_bytes)
        if raw[offset : offset + n] != chunk_bytes:
            raise SanitizeError(
                "annotated log does not correspond to this capture: hex= on "
                f"line {i + 1} (byte offset {offset}) does not match the raw "
                "capture at that range"
            )

        decode_idx = i + 1
        if decode_idx >= n_lines or not lines[decode_idx].lstrip(" ").startswith("decode="):
            raise SanitizeError(
                "annotated log does not correspond to this capture: no "
                f"decode= line immediately follows the RECV hex= line at line "
                f"{i + 1}"
            )

        chunks.append(
            _LogChunk(hex_line_idx=i, decode_line_idx=decode_idx, bin_start=offset, bin_end=offset + n)
        )
        offset += n
        i = decode_idx + 1

    if offset != len(raw):
        raise SanitizeError(
            "annotated log does not correspond to this capture: RECV chunks "
            f"tile {offset} byte(s) of logged traffic but the raw capture is "
            f"{len(raw)} byte(s)"
        )
    return chunks


def _chunk_overlaps_occurrence(chunk: _LogChunk, occ: _Occurrence) -> bool:
    return chunk.bin_start < occ.end and occ.start < chunk.bin_end


def _map_offset(offset: int, sorted_occurrences: list[_Occurrence], token_len: int) -> int:
    """Map a byte offset in the ORIGINAL capture to the corresponding offset in
    the SANITIZED capture, by walking the start-sorted, non-overlapping
    redaction splices and accumulating each one's length delta (``token_len -
    occurrence_len``). Identity whenever every occurrence's length equals
    ``token_len`` -- i.e. always, under length-preserving redaction (the
    default, and the only mode a real bench redaction uses)."""
    delta = 0
    for occ in sorted_occurrences:
        occ_len = occ.end - occ.start
        if offset >= occ.end:
            delta += token_len - occ_len
            continue
        if offset > occ.start:
            # A chunk boundary falls strictly inside this occurrence's
            # original span -- nondeterministic bench chunking split a
            # redacted value across two RECV chunks. Under length-preserving
            # redaction occ_len == token_len, so this is simply identity.
            if occ_len == token_len:
                return offset + delta
            # Non-length-preserving: the replacement token has no byte-level
            # anchor to split at exactly, so map proportionally (best effort;
            # a real bench redaction always uses length-preserving mode, so
            # this branch is not exercised by any bench capture).
            frac = (offset - occ.start) / occ_len
            return occ.start + delta + round(frac * token_len)
        break
    return offset + delta


def _rewrite_log(
    text: str,
    *,
    raw: bytes,
    new_raw: bytes,
    occurrences: list[_Occurrence],
    token: str,
    distinct_values: list[str],
) -> str:
    """Rewrite an annotated log's ``RECV ... hex=``/``decode=`` line pairs and
    ``CAPTURE SUMMARY`` block to match ``new_raw`` byte-for-byte.

    Unlike a substring-based rewrite (the LIS-319 adversarial review P1
    defect: a redacted value split across two RECV chunks by nondeterministic
    bench chunking was silently left un-redacted in the log, and/or a value
    recurring outside the addressed field diverged the log from the bin the
    other way), this maps each RECV chunk's byte RANGE through the redaction
    splices and re-renders from the sanitized bin bytes at the mapped range --
    see :func:`_parse_log_chunks` (tiling integrity) and :func:`_map_offset`
    (range mapping). An occurrence spanning a chunk boundary is handled
    naturally: both fragments get re-rendered from their mapped ranges.

    Chunks that do not overlap any redacted occurrence are left byte-identical
    (no re-rendering churn). The ``CAPTURE SUMMARY`` block keeps the previous
    plain-text substring replacement.
    """
    lines = text.split("\n")
    chunks = _parse_log_chunks(lines, raw)

    sorted_occs = sorted(occurrences, key=lambda o: o.start)
    token_len = len(token.encode("ascii"))

    out_lines = list(lines)

    for chunk in chunks:
        if not any(_chunk_overlaps_occurrence(chunk, occ) for occ in sorted_occs):
            continue  # untouched chunk: leave hex=/decode= exactly as captured

        s0 = _map_offset(chunk.bin_start, sorted_occs, token_len)
        s1 = _map_offset(chunk.bin_end, sorted_occs, token_len)
        sanitized_chunk = new_raw[s0:s1]

        hex_line = lines[chunk.hex_line_idx]
        recv_idx = hex_line.find(" RECV ")
        prefix = hex_line[: recv_idx + len(" RECV ")]
        out_lines[chunk.hex_line_idx] = (
            f"{prefix}{len(sanitized_chunk)}B  hex={sanitized_chunk.hex(' ')}"
        )

        decode_line = lines[chunk.decode_line_idx]
        stripped = decode_line.lstrip(" ")
        indent = decode_line[: len(decode_line) - len(stripped)]
        out_lines[chunk.decode_line_idx] = f"{indent}decode={_render_decode(sanitized_chunk)}"

    in_summary = False
    for idx, line in enumerate(lines):
        if "CAPTURE SUMMARY" in line:
            in_summary = True
            continue
        if in_summary and _is_summary_close_marker(line):
            in_summary = False
            continue
        if in_summary:
            out_lines[idx] = _replace_text(line, distinct_values, token)

    return "\n".join(out_lines)


# --- ledger ----------------------------------------------------------------
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_ledger(
    *,
    input_name: str,
    input_bytes: bytes,
    output_name: str,
    output_bytes: bytes,
    record: str,
    field: int,
    cls: str,
    token: str,
    length_preserving: bool,
    occurrences: int,
) -> dict:
    """Build the ``sanitization.json`` transformation ledger.

    DELIBERATE OMISSIONS (do not add these back): no original value anywhere,
    no original field length (a redacted, non-length-preserving field's
    original length is itself a disclosure), no absolute path (only the
    basename travels -- the ledger travels with a graduation PR)."""
    return {
        "sanitizer": {"name": "edge-sim sanitize", "version": _SANITIZER_VERSION},
        "created_at": date.today().isoformat(),
        "input": {"filename": input_name, "sha256": _sha256(input_bytes)},
        "output": {"filename": output_name, "sha256": _sha256(output_bytes)},
        "transformations": [
            {
                "record": record,
                "field": field,
                "class": cls,
                "token": token,
                "token_length": len(token),
                "length_preserving": length_preserving,
                "occurrences": occurrences,
            }
        ],
        "structure_verified": True,
        "review": {"privacy_reviewed_by": None, "reviewed_at": None},
    }


def _assert_no_pristine_leak(
    *,
    distinct_values: list[str],
    resolved_token: str,
    new_raw: bytes,
    new_log_text: str | None,
    ledger: dict,
) -> None:
    """Final fail-closed post-check, run after all rewriting and before any
    write: for every distinct pristine value, assert its text form and its
    hex-pair form appear NOWHERE in the sanitized bin, the sanitized log text,
    or the serialized ledger JSON.

    This is a defense-in-depth safety net (the primary, precise-message
    detection for the most common way this could happen -- the value also
    occurring outside the addressed field -- runs up front, in
    :func:`sanitize_capture` via :func:`_find_external_occurrence`, before any
    redaction work). Fail closed: a PHI gate must refuse rather than emit a
    capture it cannot prove is clean, even when the specific leak location
    cannot be pinpointed here.

    A value equal to ``resolved_token`` is skipped: that is the case of
    re-running sanitize against an already-sanitized capture with the same
    token (bench idempotency), where the "pristine" value being redacted IS
    the already-public token -- its presence in the output is the intended,
    correct result, not a leak."""
    ledger_text = json.dumps(ledger)
    for value in distinct_values:
        if value == resolved_token:
            continue
        value_bytes = value.encode("latin-1")
        hex_form = value_bytes.hex(" ")
        locations: list[str] = []
        if value_bytes in new_raw:
            locations.append("the sanitized bin")
        if new_log_text is not None and (value in new_log_text or hex_form in new_log_text):
            locations.append("the sanitized log")
        if value in ledger_text or hex_form in ledger_text:
            locations.append("the ledger JSON")
        if locations:
            raise SanitizeError(
                f"refusing to write: a redacted value survives in {', '.join(locations)} "
                "after sanitization -- it likely also occurs somewhere the addressed "
                "field redaction does not cover; if it appears in another record/field, "
                "redact that field too, then re-run"
            )


# --- public API --------------------------------------------------------
def sanitize_capture(
    bin_path: str | Path,
    log_path: str | Path | None = None,
    *,
    record: str,
    field: int,
    cls: str,
    token: str | None = None,
    ordinal: int = 1,
    length_preserving: bool = True,
    out_dir: str | Path,
) -> SanitizeResult:
    """Redact one addressed ASTM field across every envelope of a raw bench
    capture (+ its matching annotated log, if given), verify the sanitized
    capture is structurally identical to the original, and write the
    sanitized capture + a transformation ledger into ``out_dir``.

    ``record``/``field`` address an ASTM field the same way
    ``edge_sim.e1394.Record.field`` does: 1-based, ``field(1)`` is the
    record-type letter itself (so ``O.3`` -- the specimen/sample-id position
    -- is ``field=3``). The addressed field may recur (the same value) across
    several envelopes in one session -- every occurrence gets the same token.

    Token resolution: an explicit ``token`` wins; otherwise the token is
    ``TOKEN_CLASSES[cls] + str(ordinal)``. Under ``length_preserving=True``
    (the default) the token's byte length must equal the original field's
    byte length in EVERY occurrence, or this refuses with a message telling
    the caller to supply an exact-length ``--token``.

    Refuses (raising :class:`SanitizeError`, writing nothing) when:

    * ``bin_path`` (or ``log_path``) lives inside this repository's working
      tree (quarantine-first intake -- no override).
    * the capture cannot be parsed as an ASTM E1394 session at all.
    * the addressed field is absent/empty in every envelope.
    * the addressed field's value also occurs in a field OUTSIDE the
      addressed ``record``.``field`` (any other record type/field position,
      any envelope) -- a single invocation only redacts one addressed field,
      so this refuses with the other location named, rather than emit a
      capture with a PHI copy left behind.
    * the token contains a forbidden delimiter character (``| \\ ^ &``), a
      non-ASCII character, or any non-printable byte -- a token must consist
      solely of printable ASCII (0x20-0x7E); every C0 control byte (including
      CR, LF, NUL, and TAB) and DEL (0x7f) is rejected.
    * length-preserving redaction is requested but the token's length does
      not match the original field's length.
    * ``out_dir`` (``--out``) resolves to an input's own parent directory
      (this would overwrite the pristine quarantined capture/log).
    * ``out_dir`` already exists as ANY kind of directory entry -- file,
      directory, or symlink (even a dangling one) -- under the current
      output contract ``--out`` must NOT already exist; the sanitized bin,
      log, and ledger are published as one new directory, atomically.
      Choose a fresh ``--out`` path.
    * ``out_dir``'s PARENT does not already exist -- this tool creates
      ``--out`` itself but never its parent (no more
      ``mkdir(parents=True)``); create the parent first.
    * a sibling staging directory, ``<out>.staging``, already exists (any
      kind of entry) -- most often because a prior run crashed before
      completing its single publish rename; inspect and delete it by hand
      before retrying.

      These are the up-front, precise-message checks; the AUTHORITATIVE
      guarantee is fd-relative and race-free: ``--out``'s parent is resolved
      and opened (``O_NOFOLLOW``) exactly ONCE, early, into a pinned
      directory file descriptor, and every later filesystem operation for
      output -- the existence checks above, staging-directory creation, the
      three staged file creations (``O_EXCL | O_NOFOLLOW``), and the final
      publish -- goes through that fd (or the staging-directory fd derived
      from it), never through ``out_dir``'s pathname again. This defeats a
      parent-directory swap performed by an attacker AFTER these checks:
      renaming ``out_dir``'s parent aside and symlinking a new one in its
      place cannot redirect any later write, because the pin already holds
      the original directory open by inode, not by name.
    * the sanitized capture's structure (envelope count, control-token
      sequence -- and, under length-preserving redaction, control-token byte
      offsets and total length -- record-type sequence, per-record field
      count, delimiter bytes) would differ from the original's.
    * the annotated log's ``RECV`` chunks do not tile the raw capture exactly
      (a decoded hex= line's bytes disagree with the original bin at its
      offset, or the tiled length doesn't equal the bin's length) --
      "annotated log does not correspond to this capture".
    * (post-check, defense in depth) any pristine value or its hex form
      somehow still appears in the sanitized bin, log, or ledger after all
      rewriting.

    Deterministic: identical inputs produce byte-identical sanitized bin/log
    output (no timestamps are written into either); the ledger's
    ``created_at`` is a date, not a timestamp, so same-day reruns are also
    byte-identical.

    Residual, documented honestly (not fixed, because it cannot cause
    input-overwrite or a partial output): an entry planted at the final
    ``--out`` name in the tiny window between the pre-rename best-effort
    re-check and the rename itself changes only WHETHER the publish
    succeeds, never WHERE anything is written. Because the rename source is
    a directory, ``rename(2)`` fails ``ENOTDIR`` on a non-directory entry
    there (a symlink -- dangling or not -- is never dereferenced, and the
    run refuses with the staging set cleaned up), fails ``ENOTEMPTY``/
    ``EEXIST`` on a non-empty directory, and atomically replaces only an
    EMPTY directory (in which case the set still lands as a real directory
    inside the pinned parent). No input is ever reachable through the
    destination name in any of these cases. Separately, the window
    between ``out_dir.parent.resolve()`` and the subsequent ``os.open`` pin
    is itself before validation completes; it is closed for the *final*
    path component by ``O_NOFOLLOW``, but a swap of an *intermediate*
    directory component earlier in the path, timed to land inside that
    specific window, is out of scope (pre-validation; no fd is pinned yet
    to defend with).
    """
    bin_path = Path(bin_path)
    log_path = Path(log_path) if log_path is not None else None
    out_dir = Path(out_dir)

    _check_quarantine(bin_path)
    if log_path is not None:
        _check_quarantine(log_path)

    # Output-path safety checks run early (right after out_dir is known) for
    # fast failure -- before any file is read or parsed, let alone written.
    out_bin_path, out_log_path, ledger_path = _check_output_paths(
        bin_path=bin_path, log_path=log_path, out_dir=out_dir
    )

    # Pin out_dir's parent EARLY -- before any of the slower parsing,
    # redaction, or ledger-building work below -- specifically so that a
    # parent-directory swap performed by an attacker (or a buggy caller)
    # AFTER this point cannot redirect the eventual write: every subsequent
    # filesystem operation for output goes through this fd (or the staging
    # fd derived from it), never through out_dir's pathname again. See the
    # module and function docstrings for the full threat model and the
    # documented residual.
    parent_resolved = _resolve_parent_strict(out_dir)
    parent_fd = _open_parent_dir_fd(parent_resolved)
    staging_name = out_dir.name + ".staging"
    staging_fd: int | None = None
    published = False
    try:
        _assert_absent_fd(
            parent_fd,
            out_dir.name,
            message=(
                f"refusing to write: --out directory {out_dir} already "
                "exists (fd-relative check) -- the --out directory must not "
                "exist; choose a fresh --out path"
            ),
        )
        _assert_absent_fd(
            parent_fd,
            staging_name,
            message=(
                f"refusing to write: a staging entry already exists at "
                f"{staging_name!r} next to the requested --out directory -- "
                f"a prior run may have crashed before completing publish; "
                f"inspect and delete {staging_name} before retrying"
            ),
        )
        staging_fd = _make_staging_dir(parent_fd, staging_name)

        if cls not in TOKEN_CLASSES:
            raise SanitizeError(
                f"unknown token class {cls!r}; choose one of {sorted(TOKEN_CLASSES)}"
            )
        if field < 1:
            raise SanitizeError("field must be a 1-based ASTM field number (>= 1)")

        if not bin_path.is_file():
            raise SanitizeError(f"capture file not found: {bin_path}")
        raw = bin_path.read_bytes()

        original_structure = _parse_structure(raw)
        if not original_structure.envelopes:
            raise SanitizeError(
                f"{bin_path.name} contains no ASTM envelopes (no ENQ..EOT session found)"
            )

        occurrences = _find_occurrences(original_structure, record=record, field=field)
        if not occurrences:
            raise SanitizeError(
                f"{record}.{field} is absent or empty in every envelope of "
                f"{bin_path.name} -- nothing to redact"
            )

        occ_values = {occ.value for occ in occurrences}
        external = _find_external_occurrence(original_structure, record=record, field=field, values=occ_values)
        if external is not None:
            ext_record, ext_field, ext_value = external
            raise SanitizeError(
                f"refusing to sanitize: the addressed {record}.{field} value also "
                f"appears at {ext_record}.{ext_field}; redact that field too -- the "
                "capture cannot be emitted safely from a single addressed-field "
                "redaction"
            )

        resolved_token = token if token is not None else f"{TOKEN_CLASSES[cls]}{ordinal}"
        _validate_token(resolved_token)
        token_bytes = resolved_token.encode("ascii")

        if length_preserving:
            for occ in occurrences:
                original_len = occ.end - occ.start
                if original_len != len(token_bytes):
                    raise SanitizeError(
                        "length-preserving redaction requires a token of exactly "
                        f"{original_len} byte(s) to match the original {record}.{field} "
                        f"value (got token length {len(token_bytes)}); supply an "
                        "exact-length --token"
                    )

        new_raw = _apply_redactions(raw, occurrences, token_bytes)

        candidate_structure = _parse_structure(new_raw)
        _verify_structure(original_structure, candidate_structure, length_preserving=length_preserving)

        distinct_values = sorted({occ.value for occ in occurrences})

        new_log_text: str | None = None
        if log_path is not None:
            if not log_path.is_file():
                raise SanitizeError(f"annotated log file not found: {log_path}")
            log_text = log_path.read_text(encoding="utf-8")
            new_log_text = _rewrite_log(
                log_text,
                raw=raw,
                new_raw=new_raw,
                occurrences=occurrences,
                token=resolved_token,
                distinct_values=distinct_values,
            )

        ledger = _build_ledger(
            input_name=bin_path.name,
            input_bytes=raw,
            output_name=bin_path.name,
            output_bytes=new_raw,
            record=record,
            field=field,
            cls=cls,
            token=resolved_token,
            length_preserving=length_preserving,
            occurrences=len(occurrences),
        )

        _assert_no_pristine_leak(
            distinct_values=distinct_values,
            resolved_token=resolved_token,
            new_raw=new_raw,
            new_log_text=new_log_text,
            ledger=ledger,
        )

        # All verification passed -- now, and only now, write outputs, all
        # inside the staging directory pinned above. Every file is created
        # via _write_staged_bytes/_write_staged_text, which open it with
        # O_EXCL | O_NOFOLLOW (see _open_staging_fd): this refuses, race-
        # free, ANY pre-existing entry at that basename inside staging.
        _write_staged_bytes(staging_fd, out_bin_path.name, new_raw)

        if out_log_path is not None:
            _write_staged_text(staging_fd, out_log_path.name, new_log_text)

        _write_staged_text(staging_fd, "sanitization.json", json.dumps(ledger, indent=2) + "\n")

        # All three staged files are fully written -- best-effort narrowing
        # re-check that the final --out name is still absent, then publish
        # the whole staging directory as --out in a single atomic rename.
        # This is not a full close of the TOCTOU window (see the residual
        # documented on this function) but it does shrink it right up to
        # the rename itself.
        _assert_absent_fd(
            parent_fd,
            out_dir.name,
            message=(
                f"refusing to write: --out directory {out_dir} already "
                "exists (fd-relative re-check right before publish) -- the "
                "--out directory must not exist; choose a fresh --out path"
            ),
        )
        _publish_staging_dir(parent_fd, staging_name, out_dir.name)
        published = True
    finally:
        if not published:
            # Best-effort cleanup: remove EVERY entry actually present inside
            # staging (enumerated via os.scandir on the fd itself, not a
            # fixed list of names this function meant to write) -- this
            # covers both the normal case (our own partially-written files)
            # and a planted/unexpected entry (e.g. a test seam, or a race)
            # that appeared inside staging before or during this run --
            # then the (now-empty) staging directory itself, so <out> never
            # exists after a failure and <out>.staging is not left behind
            # for any failure this process can itself detect and unwind (a
            # truly pathological failure -- e.g. the process being killed --
            # can still leave it; that is the documented crashed-prior-run
            # posture a subsequent run's up-front check surfaces).
            if staging_fd is not None:
                try:
                    entries = list(os.scandir(staging_fd))
                except OSError:
                    entries = []
                for entry in entries:
                    try:
                        os.unlink(entry.name, dir_fd=staging_fd)
                    except OSError:
                        try:
                            os.rmdir(entry.name, dir_fd=staging_fd)
                        except OSError:
                            pass  # best effort -- leave it for manual inspection
                os.close(staging_fd)
                try:
                    os.rmdir(staging_name, dir_fd=parent_fd)
                except OSError:
                    pass
        elif staging_fd is not None:
            os.close(staging_fd)
        os.close(parent_fd)

    return SanitizeResult(
        bin_path=out_bin_path,
        log_path=out_log_path,
        ledger_path=ledger_path,
        token=resolved_token,
        occurrences=len(occurrences),
    )
