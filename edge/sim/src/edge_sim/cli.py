"""``edge-sim`` command line: list, validate, and replay conformance fixtures."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ack import Hl7AckError, build_ack
from .fixtures import DEFAULT_FIXTURES_ROOT, FixtureError, load_fixture, load_fixtures
from .replay import replay
from .transport import LoopbackTransport, MllpTransport

__all__ = ["main"]

_TRANSPORTS = {"loopback": LoopbackTransport, "mllp": MllpTransport}


def _resolve(root: Path, fixture_ref: str):
    for fx in load_fixtures(root):
        if fx.id == fixture_ref:
            return fx
    candidate = Path(fixture_ref)
    if (candidate / "manifest.json").is_file():
        return load_fixture(candidate)
    raise FixtureError(f"fixture not found: {fixture_ref}")


def _cmd_list(args: argparse.Namespace) -> int:
    for fx in load_fixtures(args.root):
        origin = "synthetic" if fx.synthetic else "captured"
        print(f"{fx.id}\t{fx.vendor}/{fx.model}\t{fx.protocol}\t{fx.transport}\t{origin}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    fixtures = load_fixtures(args.root)
    print(f"validated {len(fixtures)} fixture(s) under {args.root}")
    return 0


def _replay_and_report(fx, transport) -> int:
    """Replay ``fx`` through ``transport``, print the verdict, and return the exit
    code (0 = byte-faithful round-trip, 1 = MISMATCH). Split out from ``_cmd_replay``
    so the MISMATCH/exit-1 path is testable without a non-loopback wire."""
    result = replay(fx, transport)
    status = "OK" if result.round_trip_ok else "MISMATCH"
    print(f"replay {fx.id} via {result.transport}: {status} ({len(result.sent)} bytes)")
    return 0 if result.round_trip_ok else 1


def _cmd_replay(args: argparse.Namespace) -> int:
    fx = _resolve(args.root, args.fixture)
    return _replay_and_report(fx, _TRANSPORTS[args.transport]())


def _cmd_ack(args: argparse.Namespace) -> int:
    """Build the HL7 ``ACK`` the listener would return for a fixture's message
    and print it (segments on their own lines for readability)."""
    fx = _resolve(args.root, args.fixture)
    try:
        ack = build_ack(fx.message_bytes)
    except Hl7AckError as exc:
        print(f"error: cannot acknowledge {fx.id}: {exc}", file=sys.stderr)
        return 2
    print(ack.decode("latin-1").replace("\r", "\n"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="edge-sim",
        description="LIS analyzer simulator harness (conformance-fixture replay).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_FIXTURES_ROOT,
        help="fixtures root directory (default: the shipped fixtures tree)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list discovered fixtures").set_defaults(func=_cmd_list)
    sub.add_parser("validate", help="validate every fixture manifest").set_defaults(func=_cmd_validate)
    replay_parser = sub.add_parser("replay", help="replay a fixture through a transport")
    replay_parser.add_argument("fixture", help="fixture id or directory path")
    replay_parser.add_argument(
        "--transport",
        choices=sorted(_TRANSPORTS),
        default="loopback",
        help="transport to replay through (default: loopback)",
    )
    replay_parser.set_defaults(func=_cmd_replay)
    ack_parser = sub.add_parser("ack", help="print the HL7 ACK for a fixture's message")
    ack_parser.add_argument("fixture", help="fixture id or directory path")
    ack_parser.set_defaults(func=_cmd_ack)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FixtureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
