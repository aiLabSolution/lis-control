"""ASTM E1381 low-level codec + session — LIS-23 / S2.1.

Acceptance: a captured frame validates and is ACKed; a corrupted frame is NAKed
and the sender retransmits (the E1381 error-recovery the chemistry/serial fleet
relies on). E1394 record parsing is a separate slice (S2.2 / LIS-24).
"""

import pytest

from edge_sim.astm import (
    ACK,
    ENQ,
    EOT,
    ETB,
    ETX,
    NAK,
    STX,
    AstmError,
    AstmReceiver,
    build_frame,
    checksum,
    parse_frame,
    run_session,
)


# --- checksum + framing ----------------------------------------------------


def test_checksum_is_modulo_256_two_hex_uppercase():
    # ASTM checksum: sum of the covered bytes mod 256, two uppercase hex digits.
    assert checksum(b"\x01") == b"01"
    assert checksum(b"\xff\x01") == b"00"  # 256 mod 256 = 0
    assert checksum(b"7R|1|^^^Glucose|5.2\x03") == b"%02X" % (sum(b"7R|1|^^^Glucose|5.2\x03") & 0xFF)


def test_build_then_parse_roundtrips_a_frame():
    frame = build_frame(1, "R|1|^^^Glucose|5.2|mmol/L||N||F", final=True)
    assert frame[0] == STX
    assert frame[-2:] == bytes([0x0D, 0x0A])  # CR LF
    parsed = parse_frame(frame)
    assert parsed.valid is True
    assert parsed.frame_number == 1
    assert parsed.final is True
    assert parsed.text == "R|1|^^^Glucose|5.2|mmol/L||N||F"


def test_intermediate_frame_uses_etb():
    frame = build_frame(2, "continuation", final=False)
    assert ETB in frame and ETX not in frame
    assert parse_frame(frame).final is False


def test_parse_flags_corrupted_checksum_invalid_not_raising():
    frame = bytearray(build_frame(1, "R|1|data", final=True))
    # flip a text byte but leave the (now stale) checksum -> checksum mismatch
    frame[5] ^= 0xFF
    parsed = parse_frame(bytes(frame))
    assert parsed.valid is False
    assert "checksum" in parsed.error.lower()


def test_parse_raises_on_non_astm_bytes():
    with pytest.raises(AstmError):
        parse_frame(b"not a frame")


# --- receiver: ACK valid, NAK corrupt --------------------------------------


def test_receiver_acks_a_valid_frame_and_collects_the_record():
    rx = AstmReceiver()
    assert rx.feed(bytes([5])) == bytes([ACK])  # ENQ -> ACK (link established)
    resp = rx.feed(build_frame(1, "R|1|^^^Glucose|5.2", final=True))
    assert resp == bytes([ACK])
    assert rx.records == ["R|1|^^^Glucose|5.2"]


def test_receiver_naks_a_corrupted_frame():
    rx = AstmReceiver()
    rx.feed(bytes([5]))  # ENQ
    bad = bytearray(build_frame(1, "R|1|data", final=True))
    bad[6] ^= 0xFF  # corrupt the text -> checksum fails
    resp = rx.feed(bytes(bad))
    assert resp == bytes([NAK])
    assert rx.records == []  # nothing accepted


# --- full session: clean, and corrupt -> NAK -> retransmit ------------------


def test_clean_session_transfers_all_records():
    records = ["H|\\^&|||RAC", "R|1|^^^Glucose|5.2|mmol/L||N||F", "L|1|N"]
    result = run_session(records)
    assert result.complete is True
    assert result.records == records
    assert result.naks == 0
    assert result.retransmits == 0
    assert result.aborted is False


def test_corrupted_frame_naks_then_retransmits_and_completes():
    records = ["H|\\^&|||RAC", "R|1|^^^Glucose|5.2|mmol/L||N||F", "L|1|N"]

    # Corrupt the 2nd frame on its FIRST transmission only (transient line noise).
    seen: dict[int, int] = {}

    def corrupt(index: int, frame: bytes) -> bytes:
        seen[index] = seen.get(index, 0) + 1
        if index == 1 and seen[index] == 1:
            b = bytearray(frame)
            b[5] ^= 0xFF  # flip a covered byte -> checksum fails on the wire
            return bytes(b)
        return frame

    result = run_session(records, corrupt=corrupt)
    assert result.naks == 1
    assert result.retransmits == 1
    assert result.complete is True
    assert result.records == records  # the retransmit delivered it intact
    assert result.aborted is False


def test_erba_ec90_panel_corrupted_frame_naks_then_retransmits():
    """LIS-26 channel negative: a transient checksum fault on the ERBA EC90 panel
    drives NAK + retransmit and still yields the original records."""
    records = [
        "H|\\^&|||ERBA^EC90|||||||P|1",
        "P|1||PID-026||DOE^ERBA",
        "O|1|SPEC-026||^^^CHEM|R",
        "R|1|^^^GLU|98|mg/dL||N||F",
        "R|2|^^^NA|140|mmol/L||N||F",
        "R|3|^^^K|4.2|mmol/L||N||F",
        "R|4|^^^CL|103|mmol/L||N||F",
        "R|5|^^^CA|9.4|mg/dL||N||F",
        "L|1|N",
    ]
    seen: dict[int, int] = {}

    def corrupt(index: int, frame: bytes) -> bytes:
        seen[index] = seen.get(index, 0) + 1
        if index == 3 and seen[index] == 1:
            bad = bytearray(frame)
            bad[5] ^= 0xFF
            return bytes(bad)
        return frame

    result = run_session(records, corrupt=corrupt)
    assert result.naks == 1
    assert result.retransmits == 1
    assert result.complete is True
    assert result.records == records
    assert result.aborted is False


def test_session_aborts_after_max_retries_on_persistent_corruption():
    records = ["H|\\^&|||RAC", "R|1|data"]

    def always_corrupt(index: int, frame: bytes) -> bytes:
        if index == 1:
            b = bytearray(frame)
            b[5] ^= 0xFF
            return bytes(b)
        return frame

    result = run_session(records, corrupt=always_corrupt, max_retries=3)
    assert result.aborted is True
    assert result.complete is False
    assert result.naks == 1 + 3  # initial NAK + one per retry


# --- frame-number rotation: 1..7 -> 0 -> 1 wrap (LIS-23) --------------------


def test_session_wraps_frame_numbers_past_seven_through_zero():
    """A session of >8 records exercises the E1381 frame-number cycle 1..7 -> 0 -> 1.
    All records are collected in order with no NAKs — a broken modulo would put the
    8th+ frame out of sequence and NAK/abort. (No existing test drove >3 records.)"""
    records = [f"R|{i}|^^^A{i}|{i}.0|U||N||F" for i in range(1, 11)]  # 10 > 8 frames
    result = run_session(records)
    assert result.complete is True
    assert result.records == records
    assert len(result.records) == 10
    assert result.naks == 0
    assert result.retransmits == 0
    assert result.aborted is False


def test_receiver_frame_numbers_cycle_1_through_7_then_0():
    """The receiver expects FN 1,2,…,7,0,1,… — exercise the explicit wrap and assert
    each in-sequence frame is ACKed and collected across the 7 -> 0 boundary."""
    rx = AstmReceiver()
    assert rx.feed(bytes([ENQ])) == bytes([ACK])
    fns = [1, 2, 3, 4, 5, 6, 7, 0, 1, 2]  # crosses the wrap twice
    for n in fns:
        assert rx.feed(build_frame(n, f"R|{n}")) == bytes([ACK])
    assert len(rx.records) == len(fns)
    assert rx.nak_count == 0


def test_receiver_idempotently_re_acks_a_duplicate_frame_across_the_wrap():
    """A verbatim retransmit of the last-accepted frame is re-ACKed without
    re-collecting its record — including across the 7 -> 0 frame-number wrap (a lost
    ACK makes the sender resend FN 0; the receiver must not double-count it)."""
    rx = AstmReceiver()
    rx.feed(bytes([ENQ]))
    # advance through FN 1..7 so the next expected frame number is 0 (the wrap point).
    for n in [1, 2, 3, 4, 5, 6, 7]:
        rx.feed(build_frame(n, f"R|{n}"))
    assert len(rx.records) == 7

    # accept FN 0 (the wrap), then resend the SAME FN-0 frame: idempotent re-ACK.
    f0 = build_frame(0, "R|0")
    assert rx.feed(f0) == bytes([ACK])
    assert len(rx.records) == 8
    assert rx.feed(f0) == bytes([ACK])  # duplicate -> still ACK
    assert len(rx.records) == 8  # but NOT re-collected
    assert rx.nak_count == 0

    # the next in-sequence frame after the wrap (FN 1) is accepted normally.
    assert rx.feed(build_frame(1, "R|next")) == bytes([ACK])
    assert rx.records[-1] == "R|next"
