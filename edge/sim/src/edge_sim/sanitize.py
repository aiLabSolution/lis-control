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
    """Resolve the (up to three) would-be output paths -- the sanitized bin,
    the sanitized log (if a log was given), and ``sanitization.json`` -- and
    refuse, up front, before any filesystem write is attempted, whenever:

    (a) any FINAL or STAGING output path would resolve to the same file as an
        input path. Staged publish (see :func:`sanitize_capture`) writes each
        output to a sibling ``<final-name>.tmp`` staging path before
        ``os.replace``-ing it onto the final name, so the staging name is
        just as capable of aliasing an input as the final name is -- both are
        checked here. If ``--out`` names the input capture's own parent
        directory, ``out_dir / bin_path.name`` (or its ``.tmp`` staging
        counterpart) ALIASES the input; checked first so this specific case
        gets the precise pristine-evidence message.

    (b) any FINAL or STAGING output path already exists. This is the general
        backstop -- it also covers every aliasing case (a) already catches,
        plus ordinary clobbering of a previous output set (e.g. a stale
        ``sanitization.json`` left over from a prior run) or a bystander file
        already sitting at a staging name.

    These up-front checks are the fast, precise-message common case, not the
    sole guarantee: a check-then-write always leaves a TOCTOU window, and an
    ``exists()`` check cannot distinguish "nothing here" from "a symlink
    planted here after this check ran." The actual race-free guarantee is
    that every staging file is created via ``os.open`` with
    ``O_EXCL | O_NOFOLLOW`` (see :func:`_open_staging_fd`), which refuses ANY
    pre-existing entry -- regular file, symlink, or otherwise -- atomically,
    independent of whether this function's checks already caught it.

    Returns ``(out_bin_path, out_log_path, ledger_path)`` for the caller to
    use as the actual (non-resolved) write targets -- the FINAL names, not
    the staging names (the caller derives the staging names itself for the
    actual staged writes).
    """
    inputs: list[tuple[str, Path, Path]] = [("capture", bin_path, bin_path.resolve())]
    if log_path is not None:
        inputs.append(("log", log_path, log_path.resolve()))

    out_bin_path = out_dir / bin_path.name
    out_log_path = out_dir / log_path.name if log_path is not None else None
    ledger_path = out_dir / "sanitization.json"

    def _staging(path: Path) -> Path:
        return path.with_name(path.name + ".tmp")

    outputs: list[tuple[str, Path]] = [
        ("bin", out_bin_path),
        ("bin staging", _staging(out_bin_path)),
    ]
    if out_log_path is not None:
        outputs.append(("log", out_log_path))
        outputs.append(("log staging", _staging(out_log_path)))
    outputs.append(("ledger", ledger_path))
    outputs.append(("ledger staging", _staging(ledger_path)))

    for out_label, out_path in outputs:
        resolved_out = out_path.resolve()
        for in_label, in_path, resolved_in in inputs:
            if resolved_out == resolved_in:
                raise SanitizeError(
                    f"refusing to write: the output {out_label} path "
                    f"({out_path}) resolves to the same file as the input "
                    f"{in_label} ({in_path}) -- this would overwrite the "
                    f"pristine quarantined {in_label}; choose a different "
                    "--out directory"
                )

    for out_label, out_path in outputs:
        if out_path.exists():
            raise SanitizeError(
                f"refusing to write: output path {out_path} already exists -- "
                "choose a fresh --out directory rather than overwrite a "
                "previous output set"
            )

    return out_bin_path, out_log_path, ledger_path


def _open_staging_fd(path: Path) -> int:
    """Open ``path`` (a ``<final-name>.tmp`` staging path) for exclusive,
    symlink-refusing creation -- the race-free guarantee behind the up-front
    checks in :func:`_check_output_paths`.

    ``O_EXCL`` refuses ANY pre-existing directory entry at ``path`` -- a
    regular file, a symlink, a FIFO, anything -- atomically: the kernel
    either creates a brand-new entry or fails, with no window in which a
    planted entry could be followed or clobbered. This holds even when the
    entry was planted, or a plain ``exists()`` check raced, after
    :func:`_check_output_paths` already ran.

    ``O_NOFOLLOW`` is belt-and-braces on top of ``O_EXCL``: if the staging
    path's last component is itself a symlink, the open fails (``ELOOP``)
    rather than following it and writing through to whatever it points at --
    e.g. a symlink planted at the sanitized-bin staging name pointing back at
    the pristine quarantined input, which a plain ``write_bytes``/
    ``open(..., "wb")`` would follow and irreversibly overwrite.

    Raises :class:`SanitizeError` naming the staging path and directing the
    operator to a fresh ``--out`` directory whenever the open fails for any
    reason (pre-existing entry of any kind, symlink, permission, etc).
    """
    try:
        return os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except OSError as exc:
        raise SanitizeError(
            f"refusing to write: could not create staging path {path} "
            f"exclusively ({exc.strerror or exc}) -- it may already exist as "
            "a file, symlink, or other entry (possibly planted, or created "
            "by a race, after the up-front output-path check); choose a "
            "fresh --out directory"
        ) from exc


def _write_staged_bytes(path: Path, data: bytes) -> None:
    """Create ``path`` exclusively (see :func:`_open_staging_fd`) and write
    binary ``data`` through the resulting file descriptor."""
    fd = _open_staging_fd(path)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _write_staged_text(path: Path, text: str) -> None:
    """Create ``path`` exclusively (see :func:`_open_staging_fd`) and write
    text ``text`` (UTF-8) through the resulting file descriptor."""
    fd = _open_staging_fd(path)
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
    * any of the (up to three) output paths -- the sanitized bin, the
      sanitized log, or ``sanitization.json`` -- OR their ``.tmp`` staging
      counterparts, would resolve to the same file as an input path (this
      would overwrite the pristine quarantined capture/log), or any of them
      already exists (no clobbering a previous output set, and no writing
      through a bystander file already sitting at a staging name) -- choose a
      fresh ``--out`` directory. These up-front checks cover the common case
      with a precise message; independent of them, every staging file is
      actually created via ``os.open`` with ``O_EXCL | O_NOFOLLOW``, so a
      racing or pre-planted entry (symlink or otherwise) at a staging name
      fails closed at creation time too -- it is never followed and never
      silently overwritten.
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

    # All verification passed -- now, and only now, write outputs. Staged
    # publish: write every output to a sibling ``.tmp`` file first, then
    # ``os.replace`` each temp onto its final name only after ALL temps are
    # fully written -- so bin, log, and ledger are never left as a partial or
    # mismatched set if a mid-sequence failure (e.g. disk full) strikes while
    # writing the second or third file. Temp files are cleaned up (best
    # effort) if anything fails before every replace has happened.
    #
    # Every temp is created via _write_staged_bytes/_write_staged_text, which
    # open it with O_EXCL | O_NOFOLLOW (see _open_staging_fd): this refuses,
    # race-free, ANY pre-existing entry at the staging name -- a symlink
    # planted there is never followed (so it can never redirect this write
    # onto e.g. the pristine input), and a bystander regular file there is
    # never silently overwritten. _check_output_paths already refuses the
    # common case (a staging name that already exists) up front, with a
    # precise message; this is the guarantee that also holds under a race.
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp_bin_path = out_bin_path.with_name(out_bin_path.name + ".tmp")
    tmp_log_path = out_log_path.with_name(out_log_path.name + ".tmp") if out_log_path is not None else None
    tmp_ledger_path = ledger_path.with_name(ledger_path.name + ".tmp")

    tmp_written: list[Path] = []
    published = False
    try:
        _write_staged_bytes(tmp_bin_path, new_raw)
        tmp_written.append(tmp_bin_path)

        if out_log_path is not None:
            _write_staged_text(tmp_log_path, new_log_text)
            tmp_written.append(tmp_log_path)

        _write_staged_text(tmp_ledger_path, json.dumps(ledger, indent=2) + "\n")
        tmp_written.append(tmp_ledger_path)

        # All temps fully written -- publish: rename each onto its final name.
        os.replace(tmp_bin_path, out_bin_path)
        if out_log_path is not None:
            os.replace(tmp_log_path, out_log_path)
        os.replace(tmp_ledger_path, ledger_path)
        published = True
    finally:
        if not published:
            for tmp_path_ in tmp_written:
                tmp_path_.unlink(missing_ok=True)

    return SanitizeResult(
        bin_path=out_bin_path,
        log_path=out_log_path,
        ledger_path=ledger_path,
        token=resolved_token,
        occurrences=len(occurrences),
    )
