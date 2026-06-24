"""Transport abstraction for the simulator harness.

A :class:`Transport` carries an application payload from a (simulated) analyzer to
the host and back. The skeleton ships only :class:`LoopbackTransport` — the
identity channel that applies no wire framing. Framed transports are the explicit
extension points filled by later slices:

* **MLLP** — ``0x0B <msg> 0x1C 0x0D`` framing + ``ACK^R01`` — LIS-13 / S1.1.
* **ASTM E1381** — ENQ/ACK/NAK contention + modulo-256 checksum — LIS-23 / S2.1.

Whatever framing a transport applies on the wire, its ``roundtrip`` MUST preserve
the application payload (frame on send, de-frame on receive) so the replay
round-trip stays byte-faithful.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

__all__ = ["Transport", "LoopbackTransport", "TransportError"]


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
