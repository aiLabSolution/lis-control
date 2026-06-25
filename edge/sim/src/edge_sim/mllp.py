"""MLLP (Minimal Lower Layer Protocol) wire codec — LIS-13 / S1.1.

HL7 v2 messages travel over a stream transport (TCP) wrapped in MLLP's block
framing: a single message is ``<SB> <message> <EB> <CR>`` where

* ``SB`` (start block) = ``0x0B``
* ``EB`` (end block)   = ``0x1C``
* ``CR`` (carriage return) = ``0x0D``

The framing carries the **application payload** verbatim — the HL7 segments,
themselves CR-separated — so frame/de-frame must be byte-faithful (the harness
asserts a lossless round-trip, plan §1). MLLP reserves the three block
characters; a conformant payload never contains ``SB`` or ``EB``, so
:func:`frame` rejects a payload that does, keeping the single-frame
:func:`deframe` and the streaming :class:`MllpDecoder` symmetric.

:func:`frame` / :func:`deframe` handle a single complete frame; :class:`MllpDecoder`
is the incremental de-framer a real TCP listener needs. It buffers partial frames
across reads, yields each complete one, and **self-resynchronises** the way a
production MLLP receiver does — inter-frame noise, an aborted/retransmitted frame
(a fresh ``SB`` before the previous frame's ``EB``), or a malformed frame end
(``EB`` not followed by ``CR``) all cause it to drop the corrupt in-flight bytes
and resume at the next ``SB`` rather than wedge or corrupt the next message.
"""

from __future__ import annotations

__all__ = [
    "SB",
    "EB",
    "CR",
    "MllpError",
    "frame",
    "deframe",
    "MllpDecoder",
    "DEFAULT_MAX_FRAME_BYTES",
]

SB = 0x0B  # start block  (vertical tab)
EB = 0x1C  # end block    (file separator)
CR = 0x0D  # carriage return

# Generous ceiling for one in-flight frame; guards the stream de-framer against
# unbounded buffer growth from a peer that opens a frame and never closes it.
DEFAULT_MAX_FRAME_BYTES = 16 * 1024 * 1024  # 16 MiB


class MllpError(Exception):
    """Raised on a malformed MLLP frame at the single-frame boundary (:func:`frame`
    / :func:`deframe`). The streaming :class:`MllpDecoder` resynchronises instead
    of raising — see its docstring."""


def frame(payload: bytes) -> bytes:
    """Wrap an application ``payload`` in the MLLP block envelope.

    Rejects a payload containing a reserved block character (``SB``/``EB``), which
    MLLP forbids and which would otherwise make the framing ambiguous.
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError(f"payload must be bytes, got {type(payload).__name__}")
    if SB in payload or EB in payload:
        raise MllpError("payload contains a reserved MLLP block character (0x0B/0x1C)")
    return bytes([SB]) + bytes(payload) + bytes([EB, CR])


def deframe(block: bytes) -> bytes:
    """Strip the MLLP envelope from one complete ``block`` and return the payload.

    Raises :class:`MllpError` if ``block`` is not exactly ``SB … EB CR``.
    """
    if len(block) < 3:
        raise MllpError(f"frame too short to hold the MLLP envelope ({len(block)} bytes)")
    if block[0] != SB:
        raise MllpError("frame missing start block (0x0B)")
    if block[-1] != CR or block[-2] != EB:
        raise MllpError("frame missing end block + carriage return (0x1C 0x0D)")
    return bytes(block[1:-2])


class MllpDecoder:
    """Incremental, self-resynchronising MLLP de-framer for a byte stream.

    Feed it whatever arrives off the wire; it returns the list of complete,
    de-framed payloads now available and retains any trailing partial frame for
    the next :meth:`feed`. It never raises on a corrupt stream and never wedges —
    matching how a production MLLP receiver behaves:

    * Bytes before the next start block are discarded as inter-frame noise.
    * A fresh ``SB`` seen before the in-flight frame's ``EB`` means that frame was
      aborted (or was noise): the in-flight bytes are dropped and framing restarts
      at the new ``SB``.
    * An ``EB`` not followed by ``CR`` is a malformed frame end: the corrupt frame
      is dropped and de-framing resumes after it.
    * A frame that exceeds ``max_frame_bytes`` before its ``EB`` arrives is dropped
      (a never-terminated frame can't grow the buffer without bound).

    Each resynchronisation increments :attr:`resync_count`, so a corrupt stream is
    observable without exceptions.
    """

    def __init__(self, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> None:
        self._buf = bytearray()
        self._max = max_frame_bytes
        self.resync_count = 0

    @property
    def pending(self) -> bool:
        """True while a partial frame is buffered awaiting more bytes."""
        return len(self._buf) > 0

    def feed(self, data: bytes) -> list[bytes]:
        """Append ``data`` and return every complete payload it now completes."""
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"data must be bytes, got {type(data).__name__}")
        self._buf.extend(data)
        out: list[bytes] = []
        buf = self._buf
        while True:
            start = buf.find(SB)
            if start == -1:
                buf.clear()  # no frame in flight: discard inter-frame noise entirely
                break
            if start > 0:
                del buf[:start]  # drop bytes before the start block
            next_sb = buf.find(SB, 1)
            end = buf.find(EB, 1)
            if next_sb != -1 and (end == -1 or next_sb < end):
                # A new start block arrived before this frame closed: the in-flight
                # bytes were an aborted frame or noise — resync to the new SB.
                del buf[:next_sb]
                self.resync_count += 1
                continue
            if end == -1:
                # Start block seen, end block not yet: wait — unless the in-flight
                # frame has grown past the cap, in which case drop it.
                if len(buf) > self._max:
                    buf.clear()
                    self.resync_count += 1
                break
            if end + 1 >= len(buf):
                break  # end block seen, trailing byte not yet — wait for more
            if buf[end + 1] != CR:
                # Malformed frame end (EB not followed by CR): drop through the bad
                # EB and resync rather than wedge the stream.
                del buf[: end + 1]
                self.resync_count += 1
                continue
            out.append(bytes(buf[1:end]))
            del buf[: end + 2]
        return out
