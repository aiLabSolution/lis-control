"""Transport abstraction for the simulator harness.

A :class:`Transport` carries an application payload from a (simulated) analyzer to
the host and back. :class:`LoopbackTransport` is the identity channel that applies
no wire framing; :class:`MllpTransport` (LIS-13 / S1.1) applies MLLP block framing;
:class:`AstmTransport` (LIS-23 / S2.1) applies ASTM E1381 frame/checksum framing.

Whatever framing a transport applies on the wire, its ``roundtrip`` MUST preserve
the application payload (frame on send, de-frame on receive) so the replay
round-trip stays byte-faithful.
"""

from __future__ import annotations

import socket
from abc import ABC, abstractmethod
from collections import deque

from .astm import ACK, MAX_FRAME_TEXT, build_frame, parse_frame
from .mllp import MllpDecoder, frame
from .snibelis import snibelis_frame

__all__ = [
    "Transport",
    "LoopbackTransport",
    "MllpTransport",
    "AstmTransport",
    "SnibeLisTcpTransport",
    "TransportError",
]


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

    def close(self) -> None:
        """Release any real resource the transport holds (e.g. a socket). A
        no-op for the in-memory transports; :class:`SnibeLisTcpTransport`
        overrides this to close its live connection. Callers that drive a
        transport once (the CLI, the replay engine) should call this in a
        ``finally`` so a real-socket transport never leaks its connection."""

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


class AstmTransport(Transport):
    """ASTM E1381 framing transport (LIS-23 / S2.1).

    ``send`` splits the payload into <=240-char text chunks and wraps each in an
    E1381 frame (``STX FN text ETX|ETB C1 C2 CR LF``, modulo-256 checksum);
    ``receive`` validates each frame's checksum and reassembles the payload — so a
    captured ASTM record survives the framing byte-for-byte (the round-trip the
    replay engine asserts). A checksum failure surfaces as a
    :class:`TransportError`; the ACK/NAK/retransmit session that recovers from one
    on a live link is :func:`edge_sim.astm.run_session`. A production serial channel
    swaps the in-memory frame queue for an RS-232 port; the codec is identical.
    """

    name = "astm"

    def __init__(self) -> None:
        self._frames: deque[bytes] = deque()

    def send(self, payload: bytes) -> None:
        if not isinstance(payload, (bytes, bytearray)):
            raise TransportError(f"payload must be bytes, got {type(payload).__name__}")
        payload = bytes(payload)
        chunks = [payload[i : i + MAX_FRAME_TEXT] for i in range(0, len(payload), MAX_FRAME_TEXT)] or [b""]
        last = len(chunks) - 1
        for idx, chunk in enumerate(chunks):
            self._frames.append(build_frame((idx + 1) % 8, chunk, final=(idx == last)))

    def receive(self) -> bytes:
        if not self._frames:
            raise TransportError("no ASTM frame available to receive")
        reassembled = bytearray()
        while self._frames:
            parsed = parse_frame(self._frames.popleft())
            if not parsed.valid:
                raise TransportError(f"ASTM frame failed validation: {parsed.error}")
            reassembled.extend(parsed.text.encode("latin-1"))
            if parsed.final:
                return bytes(reassembled)
        raise TransportError("ASTM record not terminated by a final (ETX) frame")

    def wire_bytes(self) -> bytes:
        """The framed bytes currently queued unread on the wire (for inspection)."""
        return b"".join(self._frames)


class SnibeLisTcpTransport(Transport):
    """SnibeLis simplified-envelope TCP *client* transport (LIS-174 / D6).

    Unlike the in-memory transports above, this one drives a **real socket**:
    ``send`` dials ``host:port`` (once; the connection is reused across calls)
    and plays the analyzer role over it -- ENQ, STX, the CR-separated E1394
    records (fed in one write, never individually ACKed), ETX, EOT -- blocking
    on a real read for each of the four ACKs with ``timeout`` seconds to
    respond. This is what lets the sim harness dial a *live* bridge (the LIS-75
    bench rehearsal), not just an in-memory self-test.

    Per the wire contract (KB §4), a missing/late/wrong ACK means the link is
    dead: there is no NAK and no retransmit here, only "close and report
    failure" (:class:`TransportError`). A caller that wants another attempt
    must reconnect (a fresh :class:`SnibeLisTcpTransport`, or ``close()`` this
    one and send again).

    Per the module-level ``Transport`` contract, ``roundtrip`` must preserve
    the *application* payload regardless of wire framing: ``receive()`` returns
    the exact bytes handed to ``send()`` (not the CR-normalized wire body,
    which is the framing this transport applies and is transparent to the
    caller) -- returned only once every ACK for that envelope has actually
    arrived, so ``round_trip_ok`` is a genuine delivery-confirmed check, not a
    literal echo (the wire contract carries no echo of the payload back to the
    analyzer, only ACKs).
    """

    name = "snibelis-astm"

    def __init__(self, host: str = "127.0.0.1", port: int | None = None, *, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._last_payload: bytes | None = None

    def send(self, payload: bytes) -> None:
        if not isinstance(payload, (bytes, bytearray)):
            raise TransportError(f"payload must be bytes, got {type(payload).__name__}")
        if self.port is None:
            raise TransportError(
                "snibelis-astm transport requires a port (--port) -- the live "
                "SnibeLis host to dial"
            )
        payload = bytes(payload)
        wire = snibelis_frame(payload)
        try:
            if self._sock is None:
                self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock = self._sock
            sock.settimeout(self.timeout)
            self._send_token_and_await_ack(sock, wire[0:1])  # ENQ
            self._send_token_and_await_ack(sock, wire[1:2])  # STX
            sock.sendall(wire[2:-2])  # CR-separated records -- not individually ACKed
            self._send_token_and_await_ack(sock, wire[-2:-1])  # ETX
            self._send_token_and_await_ack(sock, wire[-1:])  # EOT
        except (OSError, TransportError):
            self.close()
            raise
        self._last_payload = payload

    def receive(self) -> bytes:
        if self._last_payload is None:
            raise TransportError("no snibelis-astm envelope has been fully ACKed yet")
        return self._last_payload

    def close(self) -> None:
        """Close the underlying socket, if open (idempotent). A dead/aborted
        link never retransmits -- a subsequent ``send`` reconnects fresh."""
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        self._last_payload = None

    def _send_token_and_await_ack(self, sock: socket.socket, token: bytes) -> None:
        sock.sendall(token)
        try:
            response = sock.recv(1)
        except OSError as exc:
            raise TransportError(f"snibelis-astm link dead awaiting ACK for {token!r}: {exc}") from exc
        if response != bytes([ACK]):
            reason = "connection closed" if not response else f"got {response!r}"
            raise TransportError(f"snibelis-astm expected ACK for {token!r}, {reason}")
