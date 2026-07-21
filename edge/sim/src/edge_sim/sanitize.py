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

# A token must never contain an ASTM delimiter or the record separator -- it
# would corrupt the field/record structure it is substituted into.
_FORBIDDEN_TOKEN_CHARS = frozenset("|\\^&\r")

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

    Tolerant of a truncated final envelope (no ``EOT``, or even no ``ETX``) so
    a mid-session link drop is still sanitizable, but otherwise strict: any
    byte sequence that does not look like ``ENQ STX ... ETX [EOT]`` raises
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
        token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SanitizeError(f"token must be ASCII, got {token!r}") from exc
    bad = _FORBIDDEN_TOKEN_CHARS & set(token)
    if bad:
        raise SanitizeError(
            f"token {token!r} contains a forbidden delimiter/control character "
            f"{sorted(bad)!r} -- a token must never contain an ASTM delimiter "
            "(| \\ ^ &) or CR"
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


# --- annotated-log rewriting ----------------------------------------------
def _render_decode(chunk: bytes) -> str:
    """Mirror of scripts/x3_astm_capture.py's ``_decode_chunk``: control
    tokens named, printable ASCII shown verbatim, everything else
    ``\\xHH``-escaped. Used only to verify a redacted RECV chunk's hex= and
    decode= renderings would still agree -- never imported from the bench
    script itself, which is a standalone tool, not a package dependency."""
    out: list[str] = []
    for byte in chunk:
        if byte in _CTRL_NAME_FOR_LOG:
            out.append(f"<{_CTRL_NAME_FOR_LOG[byte]}>")
        elif 0x20 <= byte < 0x7F:
            out.append(chr(byte))
        else:
            out.append(f"\\x{byte:02x}")
    return "".join(out)


def _replace_bytes(data: bytes, distinct_values: list[str], token_bytes: bytes) -> bytes:
    for value in distinct_values:
        data = data.replace(value.encode("latin-1"), token_bytes)
    return data


def _replace_text(text: str, distinct_values: list[str], token: str) -> str:
    for value in distinct_values:
        text = text.replace(value, token)
    return text


def _is_summary_close_marker(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) == {"="}


def _rewrite_log(text: str, *, distinct_values: list[str], token: str) -> str:
    """Rewrite an annotated log's ``RECV ... hex=`` / ``decode=`` line pairs
    and ``CAPTURE SUMMARY`` block, replacing every occurrence of any value in
    ``distinct_values`` with ``token``. Recomputes the ``RECV <n>B`` prefix
    from the rewritten hex bytes (a no-op under length-preserving redaction).
    Raises :class:`SanitizeError` -- writing nothing -- if a rewritten hex=
    line's bytes would no longer decode to the rewritten decode= line's text,
    i.e. the two renderings of one RECV chunk would go out of sync."""
    token_bytes = token.encode("ascii")
    lines = text.split("\n")
    out_lines: list[str] = []
    in_summary = False
    pending_new_bytes: bytes | None = None

    for line in lines:
        if "CAPTURE SUMMARY" in line:
            in_summary = True
            out_lines.append(line)
            continue
        if in_summary and _is_summary_close_marker(line):
            in_summary = False
            out_lines.append(line)
            continue

        recv_idx = line.find(" RECV ")
        hex_idx = line.find("B  hex=") if recv_idx != -1 else -1
        if recv_idx != -1 and hex_idx != -1:
            prefix = line[: recv_idx + len(" RECV ")]
            count_end = hex_idx
            hex_marker_end = hex_idx + len("B  hex=")
            hexpart = line[hex_marker_end:]
            raw_bytes = bytes.fromhex(hexpart.replace(" ", ""))
            new_bytes = _replace_bytes(raw_bytes, distinct_values, token_bytes)
            new_line = f"{prefix}{len(new_bytes)}B  hex={new_bytes.hex(' ')}"
            out_lines.append(new_line)
            pending_new_bytes = new_bytes
            continue

        stripped = line.lstrip(" ")
        if stripped.startswith("decode="):
            indent = line[: len(line) - len(stripped)]
            content = stripped[len("decode=") :]
            new_content = _replace_text(content, distinct_values, token)
            if pending_new_bytes is not None:
                expected = _render_decode(pending_new_bytes)
                if expected != new_content:
                    raise SanitizeError(
                        "refusing to write: a redacted hex= line would no longer "
                        "decode to its paired decode= line's text -- "
                        f"expected {expected!r}, rewritten decode is {new_content!r}"
                    )
            pending_new_bytes = None
            out_lines.append(f"{indent}decode={new_content}")
            continue

        if in_summary:
            out_lines.append(_replace_text(line, distinct_values, token))
            continue

        out_lines.append(line)

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
    * the token contains a delimiter/control byte (``| \\ ^ &`` or CR) or a
      non-ASCII character.
    * length-preserving redaction is requested but the token's length does
      not match the original field's length.
    * the sanitized capture's structure (envelope count, control-token
      sequence -- and, under length-preserving redaction, control-token byte
      offsets and total length -- record-type sequence, per-record field
      count, delimiter bytes) would differ from the original's.
    * a redacted ``hex=``/``decode=`` line pair in the annotated log would go
      out of sync.

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
        new_log_text = _rewrite_log(log_text, distinct_values=distinct_values, token=resolved_token)

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

    # All verification passed -- now, and only now, write outputs.
    out_dir.mkdir(parents=True, exist_ok=True)
    out_bin_path = out_dir / bin_path.name
    out_bin_path.write_bytes(new_raw)

    out_log_path: Path | None = None
    if log_path is not None:
        out_log_path = out_dir / log_path.name
        out_log_path.write_text(new_log_text, encoding="utf-8")

    ledger_path = out_dir / "sanitization.json"
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    return SanitizeResult(
        bin_path=out_bin_path,
        log_path=out_log_path,
        ledger_path=ledger_path,
        token=resolved_token,
        occurrences=len(occurrences),
    )
