"""``SnibeLisTcpTransport`` -- the SnibeLis simplified-envelope TCP client --
LIS-174 / D6.

``SnibeLisTcpTransport`` is the one transport in this harness that drives a
*real* socket instead of an in-memory buffer: it is how the sim plays the X3
analyzer role against a live bridge (the LIS-75 bench rehearsal tool). These
tests serve the host/receiver side over a real localhost socket with
``SnibeLisReceiver`` -- the same state machine ``test_snibelis_receiver.py``
unit-tests in isolation -- so the "TCP loopback" proof exercises genuine
socket I/O end to end, not just the in-memory session in ``snibelis.py``.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

from edge_sim.astm import ACK
from edge_sim.cli import main
from edge_sim.fixtures import load_fixture
from edge_sim.replay import replay
from edge_sim.snibelis import SnibeLisReceiver, SnibeLisReceiverError, _payload_bytes
from edge_sim.transport import SnibeLisTcpTransport, TransportError

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
RESULT_UPLOAD = FIXTURES_ROOT / "snibelis-maglumi-x3-result-upload"


def _serve_envelopes(
    server_sock: socket.socket,
    receiver: SnibeLisReceiver,
    expected_envelopes: int,
) -> None:
    """The host/receiver side of one TCP session: accept one connection, feed
    it byte-by-byte into ``receiver`` (mirroring how a real socket read loop
    would), ACK-ing exactly where the state machine says to, until the expected
    envelopes complete or the peer closes the link."""
    conn, _ = server_sock.accept()
    with conn:
        conn.settimeout(5.0)
        while receiver.envelope_count < expected_envelopes:
            chunk = conn.recv(4096)
            if not chunk:
                return
            ack = receiver.feed(chunk)
            if ack:
                conn.sendall(ack)


def _start_loopback_server(
    receiver: SnibeLisReceiver | None = None,
    *,
    expected_envelopes: int = 1,
):
    """Bind an ephemeral localhost port, serve envelopes on one background
    thread, and return ``(port, receiver, thread)``."""
    receiver = receiver or SnibeLisReceiver()
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    thread = threading.Thread(
        target=_serve_envelopes,
        args=(server_sock, receiver, expected_envelopes),
        daemon=True,
    )
    thread.start()
    return server_sock, port, receiver, thread


def test_tcp_transport_full_envelope_round_trips_byte_exact_over_real_socket():
    """Sim TCP client <-> sim SnibeLisReceiver over a real localhost socket
    (ephemeral port): the full ENQ/STX/records/ETX/EOT exchange completes and
    the payload the server reconstructs is byte-exact against what the client
    was asked to send."""
    fx = load_fixture(RESULT_UPLOAD)
    server_sock, port, receiver, thread = _start_loopback_server()
    try:
        client = SnibeLisTcpTransport(host="127.0.0.1", port=port, timeout=5.0)
        try:
            received = client.roundtrip(fx.message_bytes)
        finally:
            client.close()
        thread.join(timeout=5.0)

        assert received == fx.message_bytes  # Transport contract: roundtrip preserves the payload
        assert receiver.complete is True
        assert receiver.envelope_count == 1
        # the server's byte-exact reconstruction of what actually crossed the wire
        assert receiver.payload == _payload_bytes(fx.message_bytes)
    finally:
        server_sock.close()


def test_tcp_transport_reuses_connection_after_idle_longer_than_ack_timeout():
    """The X3 keeps a healthy TCP channel open across uploads. An idle gap is
    not an in-flight ACK wait, so exceeding the ACK timeout must not reconnect
    or prevent the next complete envelope from using the same connection."""
    first_payload = b"H|\\^&\rP|1\rL|1|N\r"
    second_payload = b"H|\\^&\rP|2\rL|1|N\r"
    ack_timeout = 0.2
    idle_gap = 0.25
    server_sock, port, receiver, thread = _start_loopback_server(expected_envelopes=2)
    try:
        client = SnibeLisTcpTransport(host="127.0.0.1", port=port, timeout=ack_timeout)
        try:
            assert client.roundtrip(first_payload) == first_payload
            connected_socket = client._sock

            time.sleep(idle_gap)

            assert idle_gap > ack_timeout
            assert client.roundtrip(second_payload) == second_payload
            assert client._sock is connected_socket
        finally:
            client.close()
        thread.join(timeout=5.0)

        assert not thread.is_alive()
        assert receiver.envelopes == [
            _payload_bytes(first_payload),
            _payload_bytes(second_payload),
        ]
    finally:
        server_sock.close()


def test_tcp_transport_replay_engine_reports_ok_against_live_receiver():
    """The generic ``replay()`` engine (the same one CLI ``replay``/``roundtrip``
    use) treats a successful live-socket session as a clean round trip."""
    fx = load_fixture(RESULT_UPLOAD)
    server_sock, port, receiver, thread = _start_loopback_server()
    try:
        client = SnibeLisTcpTransport(host="127.0.0.1", port=port, timeout=5.0)
        try:
            result = replay(fx, client)
        finally:
            client.close()
        thread.join(timeout=5.0)

        assert result.transport == "snibelis-astm"
        assert result.round_trip_ok is True
    finally:
        server_sock.close()


def test_tcp_transport_requires_port():
    client = SnibeLisTcpTransport()
    with pytest.raises(TransportError, match="requires a port"):
        client.send(b"H|\\^&\rL|1|N")


def test_tcp_transport_missing_ack_is_a_dead_link_not_a_retry():
    """A peer that never ACKs the ENQ: the client times out, closes, and
    reports failure -- it does not retransmit (KB §4)."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    accepted = []

    def _accept_and_go_silent():
        conn, _ = server_sock.accept()
        accepted.append(conn)
        conn.recv(1)  # read the ENQ, then never respond

    thread = threading.Thread(target=_accept_and_go_silent, daemon=True)
    thread.start()
    try:
        client = SnibeLisTcpTransport(host="127.0.0.1", port=port, timeout=0.3)
        with pytest.raises(TransportError, match="ACK"):
            client.send(b"H|\\^&\rL|1|N")
        assert client._sock is None  # the transport closed the dead link itself
        thread.join(timeout=5.0)
    finally:
        for conn in accepted:
            conn.close()
        server_sock.close()


def test_tcp_transport_wrong_ack_byte_is_a_dead_link():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def _accept_and_nak():
        conn, _ = server_sock.accept()
        with conn:
            conn.recv(1)  # ENQ
            conn.sendall(bytes([0x15]))  # NAK, not ACK -- SnibeLis has no NAK vocabulary

    thread = threading.Thread(target=_accept_and_nak, daemon=True)
    thread.start()
    try:
        client = SnibeLisTcpTransport(host="127.0.0.1", port=port, timeout=2.0)
        with pytest.raises(TransportError, match="expected ACK"):
            client.send(b"H|\\^&\rL|1|N")
        thread.join(timeout=5.0)
    finally:
        server_sock.close()


def test_tcp_transport_e1381_frame_rejected_cleanly_by_receiver():
    """A checksummed E1381-style session (frame-number digit right after STX)
    aimed at a SnibeLis-only receiver is rejected, not silently accepted."""
    receiver = SnibeLisReceiver()
    receiver.feed(bytes([0x05]))  # ENQ
    receiver.feed(bytes([0x02]))  # STX
    with pytest.raises(SnibeLisReceiverError):
        receiver.feed(b"1H|\\^&" + bytes([0x17]))  # frame-number '1' then ETB


def test_cli_lists_snibelis_astm_transport_choice(capsys):
    """``--transport snibelis-astm`` is registered on the CLI (D6) and a missing
    ``--port`` fails cleanly (exit 2), not with a traceback."""
    rc = main(["replay", "snibelis-maglumi-x3-result-upload", "--transport", "snibelis-astm"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "requires a port" in err


def test_cli_replay_snibelis_astm_against_live_loopback_server(capsys):
    server_sock, port, receiver, thread = _start_loopback_server()
    try:
        rc = main(
            [
                "replay",
                "snibelis-maglumi-x3-result-upload",
                "--transport",
                "snibelis-astm",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--timeout",
                "5",
            ]
        )
        thread.join(timeout=5.0)
        out = capsys.readouterr().out
        assert rc == 0
        assert "OK" in out
        assert "snibelis-astm" in out
    finally:
        server_sock.close()
