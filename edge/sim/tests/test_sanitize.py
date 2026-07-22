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


# --- (13) LIS-319 hardening: pre-existing output file refuses -------------
def test_pre_existing_output_file_refuses_and_preserves_input(tmp_path):
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


# --- (14) LIS-319 hardening: success path leaves no .tmp litter ------------
def test_success_leaves_no_tmp_files(tmp_path):
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

    assert list(out_dir.glob("*.tmp")) == []


# --- (15) LIS-319 hardening: mid-write failure leaves no final output -----
def test_mid_write_failure_leaves_no_final_named_output(tmp_path, monkeypatch):
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    out_dir = tmp_path / "out"

    # sanitize.py writes every staged temp via the fd-based
    # _write_staged_bytes/_write_staged_text helpers (O_EXCL | O_NOFOLLOW),
    # not Path.write_bytes/write_text -- so the flaky failure is injected at
    # that seam instead.
    real_write_staged_text = sanitize._write_staged_text

    def _flaky_write_staged_text(path, text, *args, **kwargs):
        # The bin temp is written first (via _write_staged_bytes, untouched
        # by this patch); the annotated-log temp is the SECOND temp write --
        # fail exactly there, before it (or the ledger temp after it) ever
        # lands.
        if path.suffix == ".tmp" and path.name.startswith("annotated-"):
            raise OSError("simulated disk failure on second temp write")
        return real_write_staged_text(path, text, *args, **kwargs)

    monkeypatch.setattr(sanitize, "_write_staged_text", _flaky_write_staged_text, raising=True)

    with pytest.raises(OSError, match="simulated disk failure"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    # No final-named output exists -- temps are cleaned up (best effort), or
    # at worst only .tmp litter remains (never a final bin/log/ledger name).
    assert not (out_dir / bin_path.name).exists()
    assert not (out_dir / log_path.name).exists()
    assert not (out_dir / "sanitization.json").exists()
    for leftover in out_dir.glob("*") if out_dir.exists() else []:
        assert leftover.suffix == ".tmp"


# --- (16) LIS-319 re-gate P0: symlink planted at a staging name is never
# followed, and the pristine input is never overwritten -----------------
def test_symlink_at_bin_staging_name_refuses_and_leaves_input_untouched(tmp_path):
    """Live-proven defect: the staged-publish temp paths (``<final-name>.tmp``)
    used to bypass both guard loops in ``_check_output_paths``, which checked
    only the three FINAL output names. A symlink planted at
    ``<out_dir>/<output-name>.tmp`` pointing at the pristine input was
    followed by the temp write, irreversibly overwriting the quarantined
    input with exit 0, and ``os.replace`` then published the symlink as the
    output. Now: the staging names are included in both guard loops (so this
    refuses up front, with the precise aliasing message), and every staging
    file is additionally created with ``O_EXCL | O_NOFOLLOW`` regardless (the
    race-free guarantee)."""
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()
    original_hash = hashlib.sha256(original_bin_bytes).hexdigest()

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    staging_symlink = out_dir / (bin_path.name + ".tmp")
    staging_symlink.symlink_to(bin_path)

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
    # the input -- nothing followed it, nothing replaced it with a real file.
    assert staging_symlink.is_symlink()
    assert staging_symlink.resolve() == bin_path.resolve()

    # No final-named output was ever produced.
    assert not (out_dir / bin_path.name).exists()
    assert not (out_dir / log_path.name).exists()
    assert not (out_dir / "sanitization.json").exists()


# --- (17) LIS-319 re-gate P0: bystander regular file at a staging name is
# refused up front (no-clobber contract), not silently overwritten -------
def test_bystander_file_at_staging_name_refuses_and_leaves_content_unchanged(tmp_path):
    """Live-proven defect: a bystander regular file named ``<output>.tmp``
    was silently overwritten and renamed away, contradicting the no-clobber
    refusal contract this tool otherwise upholds for the three final output
    names. Now the staging names are checked by the same up-front
    ``exists()`` backstop as the final names."""
    sample_id = "ZZFAKE-SAMPLE-00001"
    envelopes = [_envelope_records("ZZQ1", "1.11", "zzU/L", "0.0 - 9.9", "20260101000001", sample_id)]
    raw, log_text = _build_session_with_log(envelopes)
    bin_path, log_path = _write_quarantined_capture(tmp_path, raw, log_text)
    original_bin_bytes = bin_path.read_bytes()

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    bystander = out_dir / (bin_path.name + ".tmp")
    bystander_content = b"not part of any sanitize run\n"
    bystander.write_bytes(bystander_content)

    with pytest.raises(SanitizeError, match="already exists"):
        sanitize_capture(
            bin_path, log_path,
            record="O", field=3, cls="specimen-id", ordinal=1,
            out_dir=out_dir,
        )

    assert bin_path.read_bytes() == original_bin_bytes
    assert bystander.read_bytes() == bystander_content
    assert not bystander.is_symlink()
    assert not (out_dir / bin_path.name).exists()
    assert not (out_dir / log_path.name).exists()
    assert not (out_dir / "sanitization.json").exists()
