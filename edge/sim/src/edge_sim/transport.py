"""Transport abstraction for the simulator harness.

A :class:`Transport` carries an application payload from a (simulated) analyzer to
the host and back. :class:`LoopbackTransport` is the identity channel that applies
no wire framing; :class:`MllpTransport` (LIS-13 / S1.1) applies MLLP block framing.
The remaining framed transport is its own slice:

* **ASTM E1381** — ENQ/ACK/NAK contention + modulo-256 checksum — LIS-23 / S2.1.

Whatever framing a transport applies on the wire, its ``roundtrip`` MUST preserve
the application payload (frame on send, de-frame on receive) so the replay
round-trip stays byte-faithful.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

from .mllp import MllpDecoder, frame

__all__ = ["Transport", "LoopbackTransport", "MllpTransport", "TransportError"]


class TransportError(RuntimeError):
    """Raised on a transport-level fault (e.g. reading from an empty channel)."""


class Transport(ABC):
    """A bidirectional byte channel. Subclasses implement ``send``/``receive``;
    ``roundtrip`` is the send-then-receive convenience the replay engine uses."""

    name: str = "transport"

    @abstractmethod
    def send(self, payload: bytes) -> None:
        """Transmit ``payload`` (the host/analyzer writing one message)."""

    @abstractmethod
    def receive(self) -> bytes:
        """Receive the next message; raise :class:`TransportError` if none."""

    def roundtrip(self, payload: bytes) -> bytes:
        """Send ``payload`` then receive it back (de-framed)."""
        self.send(payload)
        return self.receive()


class LoopbackTransport(Transport):
    """In-memory identity transport: bytes written are read back unchanged, FIFO.

    Models a simulated analyzer emitting a captured message that the host reads
    verbatim — no wire framing applied. This is what makes the replay self-test a
    pure byte-faithfulness check of the harness itself.
    """

    name = "loopback"

    def __init__(self) -> None:
        self._buffer: deque[bytes] = deque()

    def send(self, payload: bytes) -> None:
        if not isinstance(payload, (bytes, bytearray)):
            raise TransportError(f"payload must be bytes, got {type(payload).__name__}")
        self._buffer.append(bytes(payload))

    def receive(self) -> bytes:
        if not self._buffer:
            raise TransportError("receive on empty loopback buffer")
        return self._buffer.popleft()


class MllpTransport(Transport):
    """MLLP framing transport (LIS-13 / S1.1).

    ``send`` writes the MLLP-framed payload to an in-memory wire buffer; ``receive``
    de-frames the next complete frame off it via :class:`~edge_sim.mllp.MllpDecoder`.
    This exercises the real frame/de-frame codec on every replay while keeping the
    harness in-memory and dependency-free, so a captured payload survives the
    ``0x0B … 0x1C 0x0D`` envelope byte-for-byte (the round-trip the replay engine
    asserts). A production listener swaps the in-memory wire for a TCP socket; the
    codec and the de-framer are identical.
    """

    name = "mllp"

    def __init__(self) -> None:
        self._wire = bytearray()
        self._decoder = MllpDecoder()
        self._ready: deque[bytes] = deque()

    def send(self, payload: bytes) -> None:
        if not isinstance(payload, (bytes, bytearray)):
            raise TransportError(f"payload must be bytes, got {type(payload).__name__}")
        self._wire.extend(frame(payload))

    def receive(self) -> bytes:
        if not self._ready:
            # Snapshot and clear the wire *before* de-framing so consumed bytes are
            # never re-fed; the self-resyncing decoder retains any partial frame.
            data = bytes(self._wire)
            self._wire.clear()
            self._ready.extend(self._decoder.feed(data))
        if not self._ready:
            raise TransportError("no complete MLLP frame available to receive")
        return self._ready.popleft()

    def wire_bytes(self) -> bytes:
        """The framed bytes currently sitting unread on the wire (for inspection)."""
        return bytes(self._wire)
