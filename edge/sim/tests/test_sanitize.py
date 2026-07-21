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
