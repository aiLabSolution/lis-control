"""MLLP wire codec: frame/de-frame + the streaming de-framer (LIS-13 / S1.1).

Unit-level proof (verification pyramid level 1, plan §1) that the
``0x0B <msg> 0x1C 0x0D`` envelope is applied and stripped byte-faithfully, and
that the stream de-framer copes with the realities of a byte stream: partial
frames, several frames in one read, and inter-frame noise.
"""

import pytest

from edge_sim.mllp import CR, EB, SB, MllpDecoder, MllpError, deframe, frame

PAYLOAD = b"MSH|^~\\&|SIM-1\rOBX|1|NM|718-7^Hemoglobin^LN\r"


def test_block_char_constants():
    assert (SB, EB, CR) == (0x0B, 0x1C, 0x0D)


def test_frame_wraps_payload_in_block_chars():
    f = frame(PAYLOAD)
    assert f[0] == SB
    assert f[-2] == EB
    assert f[-1] == CR
    assert f[1:-2] == PAYLOAD


def test_frame_empty_payload_is_three_bytes():
    assert frame(b"") == bytes([SB, EB, CR])


def test_frame_rejects_non_bytes():
    with pytest.raises(TypeError):
        frame("not-bytes")  # type: ignore[arg-type]


def test_frame_rejects_reserved_block_chars():
    # MLLP reserves SB/EB; a payload containing them would make framing ambiguous.
    with pytest.raises(MllpError):
        frame(b"before" + bytes([SB]) + b"after")
    with pytest.raises(MllpError):
        frame(b"before" + bytes([EB]) + b"after")


@pytest.mark.parametrize("payload", [b"", b"x", PAYLOAD, bytes(range(1, 11))])
def test_deframe_is_inverse_of_frame(payload):
    assert deframe(frame(payload)) == payload


def test_deframe_rejects_missing_start_block():
    with pytest.raises(MllpError, match="start"):
        deframe(PAYLOAD + bytes([EB, CR]))


def test_deframe_rejects_missing_end_block():
    with pytest.raises(MllpError):
        deframe(bytes([SB]) + PAYLOAD)


def test_deframe_rejects_missing_trailing_cr():
    with pytest.raises(MllpError):
        deframe(bytes([SB]) + PAYLOAD + bytes([EB]))


def test_deframe_rejects_too_short():
    with pytest.raises(MllpError):
        deframe(b"")
    with pytest.raises(MllpError):
        deframe(bytes([SB, CR]))


def test_decoder_single_frame():
    dec = MllpDecoder()
    assert dec.feed(frame(PAYLOAD)) == [PAYLOAD]


def test_decoder_two_frames_in_one_feed():
    dec = MllpDecoder()
    assert dec.feed(frame(b"AAA") + frame(b"BBB")) == [b"AAA", b"BBB"]


def test_decoder_partial_frame_buffers_until_complete():
    dec = MllpDecoder()
    f = frame(PAYLOAD)
    assert dec.feed(f[:6]) == []
    assert dec.pending is True
    assert dec.feed(f[6:]) == [PAYLOAD]
    assert dec.pending is False


def test_decoder_split_at_trailing_cr():
    # EB has arrived but the trailing CR has not — still incomplete.
    dec = MllpDecoder()
    f = frame(PAYLOAD)
    assert dec.feed(f[:-1]) == []
    assert dec.feed(f[-1:]) == [PAYLOAD]


def test_decoder_skips_interframe_noise():
    dec = MllpDecoder()
    data = b"\r\n" + frame(b"X") + b"  keep-alive junk  " + frame(b"Y")
    assert dec.feed(data) == [b"X", b"Y"]


def test_decoder_resyncs_after_corrupt_trailing_byte():
    # EB not followed by CR is a malformed frame end: drop it, do not wedge, and
    # still decode a valid frame that follows.
    dec = MllpDecoder()
    corrupt = bytes([SB]) + b"X" + bytes([EB]) + b"Z"  # EB not followed by CR
    assert dec.feed(corrupt) == []
    assert dec.resync_count == 1
    assert dec.feed(frame(PAYLOAD)) == [PAYLOAD]


def test_decoder_resyncs_on_stray_start_block_in_noise():
    # A stray SB in inter-frame noise must not swallow the next real frame.
    dec = MllpDecoder()
    data = b"junk" + bytes([SB]) + b"morejunk" + frame(b"REALMSG")
    assert dec.feed(data) == [b"REALMSG"]
    assert dec.resync_count == 1


def test_decoder_resyncs_aborted_then_retransmitted_frame():
    # SB ... (no EB) ... SB <real> EB CR  -> only the retransmitted frame survives.
    dec = MllpDecoder()
    assert dec.feed(bytes([SB]) + b"ABORTED" + frame(b"GOOD")) == [b"GOOD"]


def test_decoder_preserves_good_frames_before_corruption():
    dec = MllpDecoder()
    data = frame(b"GOOD") + bytes([SB]) + b"X" + bytes([EB]) + b"Z"
    assert dec.feed(data) == [b"GOOD"]


def test_decoder_caps_unbounded_frame():
    # A start block with no end block must not grow the buffer without bound.
    dec = MllpDecoder(max_frame_bytes=16)
    assert dec.feed(bytes([SB]) + b"A" * 32) == []
    assert dec.pending is False  # over-long in-flight frame dropped
    assert dec.resync_count == 1
    assert dec.feed(frame(b"OK")) == [b"OK"]


def test_decoder_drops_leading_bytes_without_start_block():
    dec = MllpDecoder()
    assert dec.feed(b"no start block here") == []
    assert dec.pending is False  # nothing worth keeping
