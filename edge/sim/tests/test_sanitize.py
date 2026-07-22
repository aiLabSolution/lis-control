"""Capture-sanitize tooling conformance -- LIS-319.

All session content here is wholly synthetic (invented sample id, assay
codes, values, units, ranges and timestamps) -- never the real bench
measurement values from evidence/bench/maglumi-x3/ (citing, not inlining,
per the project's ratified rule for new artifacts). The synthetic session
shape (envelope framing, record layout, RECV/decode/CAPTURE-SUMMARY log line
format) mirrors evidence/bench/maglumi-x3/20260717-0101010034012301113/
annotated-20260717-144818-005.log and scripts/x3_astm_capture.py, which this
module's log rewriting must match byte-for-byte.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from edge_sim import sanitize
from edge_sim.astm import CR, ENQ, EOT, ETX, STX
from edge_sim.e1394 import parse_e1394
from edge_sim.sanitize import (
    LEGACY_TOKENS,
    TOKEN_CLASSES,
    SanitizeError,
    sanitize_capture,
)
from edge_sim.snibelis import SnibeLisReceiver

# Invented sender identity constants only (protocol/vendor identity, not PHI --
# already used by the checked-in synthetic snibelis-maglumi-x3-* fixtures).
_HEADER = "H|\\^&||PSWD|Maglumi X3|||||Lis||P|E1394-97|20260101"


def _envelope_records(
    assay: str, value: str, unit: str, ref_range: str, ts: str, sample_id: str
) -> list[str]:
    """One synthetic ASTM E1394 envelope's records: H/P/O/R/L, mirroring the
    real X3 envelope shape (H resent every envelope; O.3 = specimen/sample id;
    O.5 = ``^^^<assay>``; R.13 = completion timestamp) -- all-invented content."""
    return [
        _HEADER,
        "P|1",
        f"O|1|{sample_id}||^^^{assay}",
        f"R|1|^^^{assay}|{value}|{unit}|{ref_range}|N||||||{ts}",
        "L|1|N",
    ]


def _build_session_with_log(envelopes: list[list[str]]) -> tuple[bytes, str]:
    """Build a synthetic raw capture + its annotated log, in the exact
    RECV/decode/CAPTURE-SUMMARY line format scripts/x3_astm_capture.py emits
    (ENQ, STX, header, P/O/R record group, L+ETX+EOT group -- the chunking
    pattern observed in the first envelope of
    evidence/bench/maglumi-x3/20260717-0101010034012301113/annotated-20260717-
    144818-005.log)."""
    raw = bytearray()
    log_lines = [
        "# X3 ASTM capture session synthetic-000 from ('127.0.0.1', 0), ACK mode=simplified"
    ]
    counter = 0

    def _ts() -> str:
        nonlocal counter
        counter += 1
        return f"2026-01-01T00:00:{counter:02d}.000"

    def _chunk(data: bytes) -> None:
        raw.extend(data)
        log_lines.append(f"[{_ts()}] RECV {len(data)}B  hex={data.hex(' ')}")
        log_lines.append(f"                 decode={sanitize._render_decode(data)}")

    for records in envelopes:
        _chunk(bytes([ENQ]))
        log_lines.append("                 SEND <ACK> (for <ENQ>)")
        _chunk(bytes([STX]))
        log_lines.append("                 SEND <ACK> (for <STX>)")
        header_bytes = (records[0] + "\r").encode("latin-1")
        _chunk(header_bytes)
        middle = "\r".join(records[1:-1]) + "\r"
        _chunk(middle.encode("latin-1"))
        last_bytes = (records[-1] + "\r").encode("latin-1") + bytes([ETX, EOT])
        _chunk(last_bytes)
        log_lines.append("                 SEND <ACK> (for <ETX>)")
        log_lines.append("                 SEND <ACK> (for <EOT>)")

        o_fields = records[2].split("|")
        sample_id = o_fields[2]
        assay = records[2].rsplit("^^^", 1)[-1]
        log_lines.append("")
        log_lines.append("================= CAPTURE SUMMARY =================")
        log_lines.append(f"Order (O): sample_id={sample_id!r}  assays=['{assay}']")
        log_lines.append("===================================================")
        log_lines.append("")

    return bytes(raw), "\n".join(log_lines) + "\n"


def _build_split_field_session(sample_id: str) -> tuple[bytes, str]:
    """Build a single-envelope synthetic session whose O.3 (specimen-id) value
    is deliberately split across TWO RECV chunks -- the bench-real scenario
    (bench chunking is nondeterministic) the old substring-replacement
    ``_rewrite_log`` silently mishandled (LIS-319 adversarial review P1):
    neither chunk contains the complete pristine value as a contiguous
    substring, so a per-chunk search-and-replace finds nothing in either
    chunk and leaves both raw fragments in the log even though the bin itself
    (redacted as one contiguous byte array) is fully clean."""
    assay, value, unit, ref_range, ts = "ZZQS", "9.99", "zzU/L", "0.0 - 9.9", "20260101000009"
    r_line = f"R|1|^^^{assay}|{value}|{unit}|{ref_range}|N||||||{ts}"
    l_line = "L|1|N"
    mid = len(sample_id) // 2
    first_half = sample_id[:mid]
    second_half = sample_id[mid:]
    assert first_half and second_half  # sanity: the split is non-trivial

    raw = bytearray()
    log_lines = [
        "# X3 ASTM capture session synthetic-split-000 from ('127.0.0.1', 0), ACK mode=simplified"
    ]
    counter = 0

    def _ts() -> str:
        nonlocal counter
        counter += 1
        return f"2026-01-01T00:00:{counter:02d}.000"

    def _chunk(data: bytes) -> None:
        raw.extend(data)
        log_lines.append(f"[{_ts()}] RECV {len(data)}B  hex={data.hex(' ')}")
        log_lines.append(f"                 decode={sanitize._render_decode(data)}")

    _chunk(bytes([ENQ]))
    log_lines.append("                 SEND <ACK> (for <ENQ>)")
    _chunk(bytes([STX]))
    log_lines.append("                 SEND <ACK> (for <STX>)")
    _chunk((_HEADER + "\r").encode("latin-1"))
    # Chunk A ends mid-way through the O.3 value; chunk B starts with the rest.
    _chunk(f"P|1\rO|1|{first_half}".encode("latin-1"))
    _chunk(f"{second_half}||^^^{assay}\r{r_line}\r".encode("latin-1"))
    _chunk((l_line + "\r").encode("latin-1") + bytes([ETX, EOT]))
    log_lines.append("                 SEND <ACK> (for <ETX>)")
    log_lines.append("                 SEND <ACK> (for <EOT>)")

    log_lines.append("")
    log_lines.append("================= CAPTURE SUMMARY =================")
    log_lines.append(f"Order (O): sample_id={sample_id!r}  assays=['{assay}']")
    log_lines.append("===================================================")
    log_lines.append("")

    return bytes(raw), "\n".join(log_lines) + "\n"


def _concat_hex_chunks(log_text: str) -> bytes:
    """Concatenate every ``RECV ... hex=`` line's decoded bytes, in order --
    used to verify a rewritten log's hex= lines re-decode to exactly the
    sanitized bin, end to end."""
    out = bytearray()
    for line in log_text.split("\n"):
        recv_idx = line.find(" RECV ")
        hex_idx = line.find("B  hex=") if recv_idx != -1 else -1
        if hex_idx != -1:
            hexpart = line[hex_idx + len("B  hex=") :]
            out.extend(bytes.fromhex(hexpart.replace(" ", "")))
    return bytes(out)


def _write_quarantined_capture(tmp_path, raw: bytes, log_text: str | None = None):
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    bin_path = quarantine / "raw-synthetic.bin"
    bin_path.write_bytes(raw)
    log_path = None
    if log_text is not None:
        log_path = quarantine / "annotated-synthetic.log"
        log_path.write_text(log_text, encoding="utf-8")
    return bin_path, log_path


# --- (1) redaction + determinism -------------------------------------------
def test_sanitize_redacts_every_occurrence_and_is_deterministic(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"  # 19 chars: matches "SPECIMEN-REDACTED-1"
    envelopes = [
        _envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id),
        _envelope_records("ZZQ2", "2.22", "zzU/L", "1.0 - 8.8", "20260101000002", sample_id),
        _envelope_records("ZZQ3", "3.33", "zzU/L", "2.0 - 7.7", "20260101000003", sample_id),
    ]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)

    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"

    result1 = sanitize_capture(bin_path, log_path, record="O", field=3, cls="specimen-id", ordinal=1, out_dir=out1)
    result2 = sanitize_capture(bin_path, log_path, record="O", field=3, cls="specimen-id", ordinal=1, out_dir=out2)

    assert result1.token == "SPECIMEN-REDACTED-1"
    assert result1.occurrences == 3

    # Deterministic: byte-identical bin, log, and ledger across two runs.
    assert result1.bin_path.read_bytes() == result2.bin_path.read_bytes()
    assert result1.log_path.read_text() == result2.log_path.read_text()
    assert result1.ledger_path.read_text() == result2.ledger_path.read_text()

    sanitized_bin = result1.bin_path.read_bytes()
    sanitized_log = result1.log_path.read_text(encoding="utf-8")

    # Every occurrence redacted, none of the original text/hex left anywhere.
    assert sample_id.encode("latin-1") not in sanitized_bin
    assert sample_id not in sanitized_log
    assert sample_id.encode("latin-1").hex(" ") not in sanitized_log
    assert sanitized_bin.count(b"SPECIMEN-REDACTED-1") == 3
    assert sanitized_log.count("SPECIMEN-REDACTED-1") >= 3  # decode= + summary lines

    ledger = json.loads(result1.ledger_path.read_text(encoding="utf-8"))
    assert ledger["transformations"] == [
        {
            "record": "O",
            "field": 3,
            "class": "specimen-id",
            "token": "SPECIMEN-REDACTED-1",
            "token_length": 19,
            "length_preserving": True,
            "occurrences": 3,
        }
    ]
    assert ledger["structure_verified"] is True
    assert ledger["review"] == {"privacy_reviewed_by": None, "reviewed_at": None}
    assert ledger["sanitizer"]["name"] == "edge-sim sanitize"


# --- (2) length-preserving mismatch refuses, writes nothing -----------------
def test_length_preserving_mismatch_refuses_and_writes_nothing(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"  # 19 chars
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    with pytest.raises(SanitizeError, match="exact-length --token"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", token="TOO-SHORT",
            out_dir=out_dir,
        )
    assert not out_dir.exists()


# --- (3a) delimiter char in token rejected ----------------------------------
def test_token_with_delimiter_char_rejected(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, _ = _build_session_with_log(envelopes)
    bin_path, _ = _write_quarantined_capture(tmp_path, raw)
    out_dir = tmp_path / "out"

    with pytest.raises(SanitizeError, match="forbidden delimiter"):
        sanitize_capture(
            bin_path, None,
            record="O", field=3, cls="specimen-id",
            token="BAD|TOKEN|19CHARS!!", length_preserving=False,
            out_dir=out_dir,
        )
    assert not out_dir.exists()


# --- (3b) genuine structural corruption caught before any file exists -------
def test_structural_corruption_caught_before_any_file_exists(tmp_path, monkeypatch):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, _ = _build_session_with_log(envelopes)
    bin_path, _ = _write_quarantined_capture(tmp_path, raw)
    out_dir = tmp_path / "out"

    real_apply = sanitize._apply_redactions

    def _corrupting_apply(raw_bytes, occurrences, token_bytes):
        corrupted = bytearray(real_apply(raw_bytes, occurrences, token_bytes))
        idx = corrupted.index(CR)  # drop a record-separator CR -> merges two records
        del corrupted[idx]
        return bytes(corrupted)

    monkeypatch.setattr(sanitize, "_apply_redactions", _corrupting_apply)

    with pytest.raises(SanitizeError, match="structure verification failed"):
        sanitize_capture(
            bin_path, None,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )
    assert not out_dir.exists()


# --- (4) replay-equivalence: same parser, same session machinery -----------
def test_replay_equivalence_and_in_process_session_completes(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [
        _envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id),
        _envelope_records("ZZQ2", "2.22", "zzU/L", "1.0 - 8.8", "20260101000002", sample_id),
        _envelope_records("ZZQ3", "3.33", "zzU/L", "2.0 - 7.7", "20260101000003", sample_id),
    ]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    result = sanitize_capture(
        bin_path, log_path,
        record="O", field=3, cls="specimen-id", ordinal=1,
        out_dir=out_dir,
    )
    sanitized_raw = result.bin_path.read_bytes()

    # Cheap in-process session replay: the same SnibeLisReceiver state machine
    # LIS-174 parity / test_snibelis_tcp.py drive over a real socket, fed
    # in-memory -- the sanitized session completes exactly like the original.
    orig_receiver = SnibeLisReceiver()
    orig_receiver.feed(raw)
    sanitized_receiver = SnibeLisReceiver()
    sanitized_receiver.feed(sanitized_raw)

    assert orig_receiver.complete is True
    assert sanitized_receiver.complete is True
    assert orig_receiver.envelope_count == 3
    assert sanitized_receiver.envelope_count == 3

    for orig_payload, sanitized_payload in zip(orig_receiver.envelopes, sanitized_receiver.envelopes):
        orig_msg = parse_e1394(orig_payload)
        sanitized_msg = parse_e1394(sanitized_payload)

        assert sanitized_msg.header.sender_name == orig_msg.header.sender_name
        assert sanitized_msg.header.version == orig_msg.header.version
        assert len(sanitized_msg.patients) == len(orig_msg.patients)

        orig_order = orig_msg.patients[0].orders[0]
        sanitized_order = sanitized_msg.patients[0].orders[0]
        assert orig_order.specimen_id == sample_id
        assert sanitized_order.specimen_id == result.token  # the ONLY field that differs
        assert sanitized_order.test_code == orig_order.test_code
        assert sanitized_order.assays == orig_order.assays

        orig_result = orig_order.results[0]
        sanitized_result = sanitized_order.results[0]
        assert sanitized_result.value == orig_result.value
        assert sanitized_result.units == orig_result.units
        assert sanitized_result.reference_range == orig_result.reference_range
        assert sanitized_result.abnormal_flags == orig_result.abnormal_flags
        assert sanitized_result.completion_time == orig_result.completion_time


# --- (5) ledger fields + no leakage of original value/length/paths ---------
def test_ledger_omits_original_value_length_and_absolute_paths(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"  # 19 chars
    token = "SID-99"  # 6 chars: deliberately NOT length-preserving
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    result = sanitize_capture(
        bin_path, log_path,
        record="O", field=3, cls="specimen-id", token=token,
        length_preserving=False,
        out_dir=out_dir,
    )

    ledger_text = result.ledger_path.read_text(encoding="utf-8")
    ledger = json.loads(ledger_text)

    transformation = ledger["transformations"][0]
    assert set(transformation.keys()) == {
        "record", "field", "class", "token", "token_length",
        "length_preserving", "occurrences",
    }  # no "original_length"/"original_value" key ever added
    assert transformation["token_length"] == len(token)
    assert transformation["length_preserving"] is False
    assert transformation["occurrences"] == 1

    assert ledger["input"]["filename"] == "raw-synthetic.bin"
    assert ledger["output"]["filename"] == "raw-synthetic.bin"
    assert "/" not in ledger["input"]["filename"]
    assert "/" not in ledger["output"]["filename"]
    assert ledger["review"] == {"privacy_reviewed_by": None, "reviewed_at": None}
    assert ledger["structure_verified"] is True

    assert sample_id not in ledger_text
    assert str(tmp_path) not in ledger_text

    sanitized_bin = result.bin_path.read_bytes()
    sanitized_log = result.log_path.read_text(encoding="utf-8")
    assert sample_id.encode("latin-1") not in sanitized_bin
    assert sample_id not in sanitized_log
    assert sample_id.encode("latin-1").hex(" ") not in sanitized_log


# --- (6) quarantine: input inside the repo tree refuses ---------------------
def test_quarantine_refuses_capture_inside_repo_tree(tmp_path):
    # edge/sim/tests/test_sanitize.py -> parents[1] == edge/sim -- solidly
    # inside the repo working tree. Never created on disk (craft, don't write).
    inside_repo_path = Path(__file__).resolve().parents[1] / "not-a-real-quarantine-file.bin"
    out_dir = tmp_path / "out"

    with pytest.raises(SanitizeError, match="quarantine-first"):
        sanitize_capture(
            inside_repo_path, None,
            record="O", field=3, cls="specimen-id",
            out_dir=out_dir,
        )
    assert not out_dir.exists()
    assert not inside_repo_path.exists()


# --- bonus: canonical vocabulary never emits the grandfathered legacy token -
def test_token_classes_never_produce_a_legacy_token():
    for cls, prefix in TOKEN_CLASSES.items():
        for ordinal in range(1, 5):
            assert f"{prefix}{ordinal}" not in LEGACY_TOKENS


# --- (7) P1: value split across two RECV chunks is still fully redacted ----
def test_chunk_split_redaction_leaves_no_pristine_fragment(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"  # 19 chars: matches "SPECIMEN-REDACTED-1"
    raw, log_text = _build_split_field_session(sample_id)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    result = sanitize_capture(
        bin_path, log_path,
        record="O", field=3, cls="specimen-id", ordinal=1,
        out_dir=out_dir,
    )

    sanitized_bin = result.bin_path.read_bytes()
    sanitized_log = result.log_path.read_text(encoding="utf-8")

    assert sample_id.encode("latin-1") not in sanitized_bin
    # Neither raw half-fragment (the two RECV chunks' pristine content) may
    # survive -- this is exactly what the old substring-based rewrite missed.
    mid = len(sample_id) // 2
    first_half, second_half = sample_id[:mid], sample_id[mid:]
    assert first_half not in sanitized_log
    assert second_half not in sanitized_log
    assert sample_id not in sanitized_log
    assert sample_id.encode("latin-1").hex(" ") not in sanitized_log
    assert result.token in sanitized_log

    # The log's hex must re-decode to exactly the sanitized bin's bytes, end
    # to end -- log/bin can never structurally diverge.
    assert _concat_hex_chunks(sanitized_log) == sanitized_bin


# --- (8) P1: the addressed value recurring outside the field refuses -------
def test_value_recurring_outside_addressed_field_refuses(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00002"
    assay, value, unit, ref_range, ts = "ZZQ9", "9.99", "zzU/L", "0.0 - 9.9", "20260101000009"
    records = [
        _HEADER,
        f"P|1||{sample_id}",  # planted recurrence at P.4 -- NOT the addressed field
        f"O|1|{sample_id}||^^^{assay}",
        f"R|1|^^^{assay}|{value}|{unit}|{ref_range}|N||||||{ts}",
        "L|1|N",
    ]
    raw, log_text = _build_session_with_log([records])
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    with pytest.raises(SanitizeError, match=r"P\.4"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )
    assert not out_dir.exists()


# --- (9) P1: a log that doesn't tile the bin refuses -----------------------
def test_log_bin_hex_mismatch_refuses(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00003"
    envelopes = [_envelope_records("ZZQM", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    # Corrupt the first RECV chunk's declared hex (the lone ENQ byte, 0x05)
    # so the log no longer tiles the raw capture.
    corrupted_log = log_text.replace("hex=05\n", "hex=06\n", 1)
    assert corrupted_log != log_text  # sanity: the replace actually matched
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, corrupted_log)
    out_dir = tmp_path / "out"

    with pytest.raises(SanitizeError, match="does not correspond to this capture"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )
    assert not out_dir.exists()


# --- (10) P1: non-length-preserving chunk mapping recomputes RECV/hex ------
def test_non_length_preserving_chunk_mapping_recomputes_recv_and_hex(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-LONGVALUE-0001"  # deliberately longer than the token
    envelopes = [_envelope_records("ZZQL", "4.44", "zzU/L", "0.0 - 9.9", "20260101000004", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"
    token = "SID-1"  # shorter than sample_id; occurrence sits mid-chunk (P/O/R joined)

    result = sanitize_capture(
        bin_path, log_path,
        record="O", field=3, cls="specimen-id", token=token,
        length_preserving=False,
        out_dir=out_dir,
    )
    sanitized_bin = result.bin_path.read_bytes()
    sanitized_log = result.log_path.read_text(encoding="utf-8")

    assert sample_id not in sanitized_log
    assert token in sanitized_log
    assert _concat_hex_chunks(sanitized_log) == sanitized_bin

    for line in sanitized_log.split("\n"):
        recv_idx = line.find(" RECV ")
        hex_idx = line.find("B  hex=") if recv_idx != -1 else -1
        if hex_idx != -1:
            count_str = line[recv_idx + len(" RECV ") : hex_idx]
            hexpart = line[hex_idx + len("B  hex=") :]
            decoded = bytes.fromhex(hexpart.replace(" ", ""))
            assert int(count_str) == len(decoded)


# --- (11) LIS-319 hardening: token charset is printable ASCII only ---------
@pytest.mark.parametrize(
    "bad_char, char_name",
    [
        ("\x0a", "LF"),
        ("\x00", "NUL"),
        ("\x09", "TAB"),
        ("\x7f", "DEL"),
    ],
)
def test_token_with_c0_or_del_byte_rejected_and_writes_nothing(tmp_path, bad_char, char_name):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, _ = _build_session_with_log(envelopes)
    bin_path, _ = _write_quarantined_capture(tmp_path, raw)
    out_dir = tmp_path / "out"
    bad_token = f"BAD{bad_char}TOKEN"  # same "shape" as an accepted token, one bad byte

    with pytest.raises(SanitizeError):
        sanitize_capture(
            bin_path, None,
            record="O", field=3, cls="specimen-id",
            token=bad_token, length_preserving=False,
            out_dir=out_dir,
        )
    # Nothing written -- refusal happens before any filesystem write.
    assert not out_dir.exists()


# --- (12) LIS-319 hardening: --out aliasing the input's own directory ------
def test_out_dir_equal_to_input_parent_refuses_and_preserves_pristine_input(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()
    original_log_text = log_path.read_text(encoding="utf-8")

    out_dir = bin_path.parent  # aliases the input capture's own directory

    with pytest.raises(SanitizeError, match="pristine"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    # The pristine quarantined capture/log must be byte-for-byte untouched.
    assert bin_path.read_bytes() == original_bin_bytes
    assert log_path.read_text(encoding="utf-8") == original_log_text


# --- (13) LIS-319 hardening: pre-existing --out directory refuses ---------
def test_existing_out_dir_refuses_and_preserves_pristine_input(tmp_path):
    """New output contract (Codex round-3 P0/P1 fix): --out is a single
    atomically-published unit, so the ONLY thing that matters is whether the
    --out directory name itself already exists -- not whether some subset of
    its three files happen to be present. A pre-created --out (even with a
    stale ledger inside, left over from some unrelated prior use of that
    path) refuses up front."""
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stale_ledger = out_dir / "sanitization.json"
    stale_ledger.write_text('{"stale": true}\n', encoding="utf-8")

    with pytest.raises(SanitizeError, match="already exists"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    assert bin_path.read_bytes() == original_bin_bytes
    assert stale_ledger.read_text(encoding="utf-8") == '{"stale": true}\n'


# --- (14) LIS-319 hardening: success leaves exactly the 3 final files, no
# staging sibling left behind ------------------------------------------------
def test_success_leaves_exactly_three_files_and_no_staging_sibling(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    sanitize_capture(
        bin_path, log_path,
        record="O", field=3, cls="specimen-id", ordinal=1,
        out_dir=out_dir,
    )

    assert sorted(p.name for p in out_dir.iterdir()) == sorted(
        [bin_path.name, log_path.name, "sanitization.json"]
    )
    assert not (tmp_path / (out_dir.name + ".staging")).exists()


# --- (15) LIS-319 hardening: mid-write failure leaves no final output -----
def test_mid_write_failure_leaves_no_final_named_output(tmp_path, monkeypatch):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    # sanitize.py writes every staged file via the fd-based
    # _write_staged_bytes/_write_staged_text helpers (O_EXCL | O_NOFOLLOW,
    # dir_fd-relative to the staging directory), not Path.write_bytes/
    # write_text -- so the flaky failure is injected at that seam instead.
    # The bin is written first (via _write_staged_bytes, untouched by this
    # patch); the annotated-log write is the SECOND staged write -- fail
    # exactly there, before it (or the ledger write after it) ever lands.
    real_write_staged_text = sanitize._write_staged_text

    def _flaky_write_staged_text(staging_fd, basename, text):
        if basename == log_path.name:
            raise OSError("simulated disk failure on second staged write")
        return real_write_staged_text(staging_fd, basename, text)

    monkeypatch.setattr(sanitize, "_write_staged_text", _flaky_write_staged_text, raising=True)

    with pytest.raises(OSError, match="simulated disk failure"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    # No final --out directory exists at all, and the staging sibling is
    # cleaned up (best effort) -- never a partial final set.
    assert not out_dir.exists()
    assert not (tmp_path / (out_dir.name + ".staging")).exists()


# --- (16) LIS-319 re-gate P0: symlink planted at the STAGING-DIRECTORY
# sibling name (``<out>.staging``) is never followed, and the pristine input
# is never overwritten -------------------------------------------------
def test_symlink_at_staging_name_refuses_and_leaves_input_untouched(tmp_path):
    """New output contract: staging is now a whole SIBLING DIRECTORY,
    ``<out>.staging`` (not a per-file ``<final-name>.tmp``), and ``--out``
    itself must not exist -- so this can no longer be constructed by
    planting an entry inside a pre-created --out (see the old, now-
    impossible version of this test). A symlink planted at the staging
    directory's OWN name, pointing at the input's quarantine directory,
    must refuse (``os.mkdir(dir_fd=...)`` fails closed on any pre-existing
    entry there) rather than have anything written through it."""
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    quarantine_dir = bin_path.parent
    original_bin_bytes = bin_path.read_bytes()
    original_hash = hashlib.sha256(original_bin_bytes).hexdigest()

    out_dir = tmp_path / "out"
    staging_symlink = tmp_path / (out_dir.name + ".staging")
    staging_symlink.symlink_to(quarantine_dir, target_is_directory=True)

    with pytest.raises(SanitizeError):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    # The pristine input is untouched -- byte-identical, hash-identical --
    # nothing was followed or written through the symlink.
    assert bin_path.read_bytes() == original_bin_bytes
    assert hashlib.sha256(bin_path.read_bytes()).hexdigest() == original_hash

    # The symlink itself is still present, still a symlink, still pointing at
    # the quarantine directory -- nothing followed it, nothing replaced it.
    assert staging_symlink.is_symlink()
    assert staging_symlink.resolve() == quarantine_dir.resolve()

    # No --out directory was ever produced.
    assert not out_dir.exists()


# --- (17) LIS-319 re-gate P0: bystander regular file at the staging-
# directory sibling name refuses with the crashed-prior-run message ------
def test_bystander_file_at_staging_name_refuses_and_leaves_content_unchanged(tmp_path):
    """A bystander regular file sitting at ``<out>.staging`` -- e.g. an
    unrelated file that happens to share that name -- refuses (``os.mkdir``
    fails closed: a file already occupies that name) with the crashed-
    prior-run message, and is left completely unmodified."""
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()

    out_dir = tmp_path / "out"
    bystander = tmp_path / (out_dir.name + ".staging")
    bystander_content = b"not part of any sanitize run\n"
    bystander.write_bytes(bystander_content)

    with pytest.raises(SanitizeError, match="prior run"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    assert bin_path.read_bytes() == original_bin_bytes
    assert bystander.read_bytes() == bystander_content
    assert not bystander.is_symlink()
    assert not out_dir.exists()


# --- (17b) LIS-319 re-gate P0: a DANGLING symlink at the staging-directory
# sibling name is caught by lstat semantics, not fooled by the missing
# target --------------------------------------------------------------------
def test_dangling_symlink_at_staging_name_refuses(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()

    out_dir = tmp_path / "out"
    dangling = tmp_path / (out_dir.name + ".staging")
    dangling.symlink_to(tmp_path / "does-not-exist-target")

    with pytest.raises(SanitizeError):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    assert bin_path.read_bytes() == original_bin_bytes
    assert dangling.is_symlink()
    assert not out_dir.exists()


# --- (18) LIS-319 re-gate P0: a DANGLING symlink at the final --out name
# itself is caught by lstat semantics (a symlink counts as "existing" even
# when its target is absent) -------------------------------------------------
def test_dangling_symlink_at_out_name_refuses_and_is_left_in_place(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()

    out_dir = tmp_path / "out"
    out_dir.symlink_to(tmp_path / "nonexistent-target")

    with pytest.raises(SanitizeError, match="already exists"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    assert out_dir.is_symlink()
    assert bin_path.read_bytes() == original_bin_bytes


# --- (19) LIS-319 hardening: --out's parent must already exist -------------
def test_out_dir_parent_missing_refuses_with_clear_message(tmp_path):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, _ = _build_session_with_log(envelopes)
    bin_path, _ = _write_quarantined_capture(tmp_path, raw)
    out_dir = tmp_path / "does-not-exist-parent" / "out"

    with pytest.raises(SanitizeError, match="parent"):
        sanitize_capture(
            bin_path, None,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )
    assert not out_dir.exists()
    assert not out_dir.parent.exists()


# --- (20) LIS-319 Codex round-3 P0: a parent-directory swap performed AFTER
# validation begins (post up-front checks, mid-processing) must not redirect
# any write -- the parent fd, pinned EARLY, keeps writing through the real
# original directory (now reachable only under its post-swap name), never
# through the attacker's replacement symlink -----------------------------
def test_parent_swap_after_validation_writes_through_pinned_fd(tmp_path, monkeypatch):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    quarantine_dir = bin_path.parent
    original_bin_bytes = bin_path.read_bytes()
    original_log_text = log_path.read_text(encoding="utf-8")
    original_quarantine_entries = sorted(p.name for p in quarantine_dir.iterdir())

    victim = tmp_path / "victim"
    victim.mkdir()
    victim_moved = tmp_path / "victim-moved"
    out_dir = victim / "out"

    real_build_ledger = sanitize._build_ledger
    swapped = False

    def _swap_then_build_ledger(*args, **kwargs):
        # Fires well AFTER out_dir's parent has already been pinned (see
        # sanitize_capture: the pin happens immediately after
        # _check_output_paths, long before _build_ledger is ever reached) --
        # this is deliberately a POST-pin, mid-processing attack.
        nonlocal swapped
        if not swapped:
            swapped = True
            victim.rename(victim_moved)
            victim.symlink_to(quarantine_dir, target_is_directory=True)
        return real_build_ledger(*args, **kwargs)

    monkeypatch.setattr(sanitize, "_build_ledger", _swap_then_build_ledger)

    result = sanitize_capture(
        bin_path, log_path,
        record="O", field=3, cls="specimen-id", ordinal=1,
        out_dir=out_dir,
    )

    # The pristine input is completely untouched.
    assert bin_path.read_bytes() == original_bin_bytes
    assert log_path.read_text(encoding="utf-8") == original_log_text

    # The quarantine directory gained NO new entries -- nothing was ever
    # written into it, even though the attacker's symlink pointed straight
    # at it under the swapped "victim" name.
    assert sorted(p.name for p in quarantine_dir.iterdir()) == original_quarantine_entries

    # The sanitized set landed under the REAL pinned directory
    # (victim-moved/out), reached via the fd, never via the "victim"
    # pathname (which by publish time is the attacker's symlink).
    real_out = victim_moved / "out"
    assert real_out.is_dir()
    assert sorted(p.name for p in real_out.iterdir()) == sorted(
        [bin_path.name, log_path.name, "sanitization.json"]
    )
    assert sample_id.encode("latin-1") not in (real_out / bin_path.name).read_bytes()
    assert result.token in (real_out / "sanitization.json").read_text(encoding="utf-8")


# --- (21) LIS-319 Codex round-3 P1: fault injection at every publication
# boundary (staged bin write, staged log write, staged ledger write, and the
# single final rename) must leave --out absent and the staging sibling
# cleaned up, every time -----------------------------------------------------
@pytest.mark.parametrize("boundary", ["bin", "log", "ledger", "rename"])
def test_fault_injection_at_every_publish_boundary_leaves_no_trace(tmp_path, monkeypatch, boundary):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()
    out_dir = tmp_path / "out"
    staging_sibling = tmp_path / (out_dir.name + ".staging")

    if boundary == "bin":
        def _flaky(staging_fd, basename, data):
            raise OSError("simulated fault: staged bin write")

        monkeypatch.setattr(sanitize, "_write_staged_bytes", _flaky)
    elif boundary == "log":
        real = sanitize._write_staged_text

        def _flaky(staging_fd, basename, text):
            if basename == log_path.name:
                raise OSError("simulated fault: staged log write")
            return real(staging_fd, basename, text)

        monkeypatch.setattr(sanitize, "_write_staged_text", _flaky)
    elif boundary == "ledger":
        real = sanitize._write_staged_text

        def _flaky(staging_fd, basename, text):
            if basename == "sanitization.json":
                raise OSError("simulated fault: staged ledger write")
            return real(staging_fd, basename, text)

        monkeypatch.setattr(sanitize, "_write_staged_text", _flaky)
    else:  # rename -- the single final-publish boundary
        def _flaky(parent_fd, staging_name, final_name):
            raise OSError("simulated fault: final publish rename")

        monkeypatch.setattr(sanitize, "_publish_staging_dir", _flaky)

    with pytest.raises(OSError, match="simulated fault"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    assert not out_dir.exists()
    assert not staging_sibling.exists()
    assert bin_path.read_bytes() == original_bin_bytes


# --- (22) LIS-319 hardening: a dangling symlink planted INSIDE the fresh
# staging directory (at the bin's basename) is still refused by the
# O_EXCL | O_NOFOLLOW staged-file open -- defense in depth on top of the
# staging-directory-level guard ----------------------------------------------
def test_planted_entry_inside_staging_dir_refuses_via_o_excl(tmp_path, monkeypatch):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()
    out_dir = tmp_path / "out"
    staging_sibling = tmp_path / (out_dir.name + ".staging")

    real_make_staging_dir = sanitize._make_staging_dir

    def _plant_then_make(parent_fd, staging_name):
        staging_fd = real_make_staging_dir(parent_fd, staging_name)
        # Plant a DANGLING symlink at the bin's basename, inside the fresh
        # staging dir, before the real staged bin write ever runs.
        os.symlink(
            str(tmp_path / "does-not-exist-target"),
            bin_path.name,
            dir_fd=staging_fd,
        )
        return staging_fd

    monkeypatch.setattr(sanitize, "_make_staging_dir", _plant_then_make)

    with pytest.raises(SanitizeError):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    assert bin_path.read_bytes() == original_bin_bytes
    assert not out_dir.exists()
    assert not staging_sibling.exists()


# --- (23) LIS-319 documented residual, proven: a symlink planted at the
# final --out name in the window between the pre-rename re-check and the
# publish rename makes the rename fail ENOTDIR (a directory source never
# dereferences or replaces a non-directory destination) -- fail-closed
# refusal, staging cleaned up, symlink never followed ------------------------
def test_symlink_planted_at_out_name_inside_publish_window_fails_closed(tmp_path, monkeypatch):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    quarantine_dir = bin_path.parent
    original_bin_bytes = bin_path.read_bytes()
    original_quarantine_entries = sorted(p.name for p in quarantine_dir.iterdir())
    out_dir = tmp_path / "out"
    staging_sibling = tmp_path / (out_dir.name + ".staging")

    real_publish = sanitize._publish_staging_dir

    def _plant_then_publish(parent_fd, staging_name, final_name):
        # Fires AFTER the caller's pre-rename absence re-check -- this is
        # exactly the residual window the docstring documents.
        os.symlink(str(quarantine_dir), final_name, dir_fd=parent_fd)
        return real_publish(parent_fd, staging_name, final_name)

    monkeypatch.setattr(sanitize, "_publish_staging_dir", _plant_then_publish)

    with pytest.raises(SanitizeError, match="could not rename"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    # The symlink was never followed: the quarantine directory gained no
    # entries and the pristine input is byte-unchanged.
    assert bin_path.read_bytes() == original_bin_bytes
    assert sorted(p.name for p in quarantine_dir.iterdir()) == original_quarantine_entries
    # The planted symlink survives (rename failed ENOTDIR, replaced nothing)
    # and the staging sibling is cleaned up.
    assert out_dir.is_symlink()
    assert not staging_sibling.exists()
