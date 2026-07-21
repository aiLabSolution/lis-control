"""``edge-sim`` command line: list, validate, replay, archive, roundtrip, ack,
normalize, milestone, query, parse-astm fixtures."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .ack import Hl7AckError, build_ack
from .archive import RawMessageArchive, archive_fixture
from .e1394 import parse_e1394
from .fixtures import DEFAULT_FIXTURES_ROOT, FixtureError, load_fixture, load_fixtures
from .milestone import run_milestone
from .normalize import (
    KIND_ANOMALY,
    KIND_ATTACHMENT,
    KIND_BLANK,
    KIND_RESULT,
    KIND_WARNING,
    Normalizer,
)
from .oru import OruParseError, parse_oru_r01
from .sanitize import TOKEN_CLASSES, SanitizeError, sanitize_capture
from .query import (
    QueryError,
    WorklistOrder,
    build_worklist_query_response,
    build_query_response,
    correlates,
    parse_query,
    parse_query_response,
    parse_worklist_query_response,
    worklist_correlates,
)
from .replay import check_against_expected, deterministic_round_trip, replay
from .transport import (
    AstmTransport,
    LoopbackTransport,
    MllpTransport,
    SnibeLisTcpTransport,
    TransportError,
)

__all__ = ["main"]

_TRANSPORTS = {
    "loopback": LoopbackTransport,
    "mllp": MllpTransport,
    "astm": AstmTransport,
    "snibelis-astm": SnibeLisTcpTransport,
}

# Default scratch archive for the CLI (gitignored; content-addressed so re-runs of
# the same fixture are idempotent rather than accumulating).
DEFAULT_ARCHIVE_DIR = Path(".edge-archive")


def _now_iso() -> str:
    """The receive instant the CLI stamps on an archived message."""
    return datetime.now(timezone.utc).isoformat()


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


def _build_transport(args: argparse.Namespace):
    """Construct the transport named by ``args.transport``. ``snibelis-astm`` is a
    real TCP client (LIS-174 / D6) so it alone takes the ``--host``/``--port``/
    ``--timeout`` options; the in-memory transports keep their zero-arg form."""
    cls = _TRANSPORTS[args.transport]
    if cls is SnibeLisTcpTransport:
        return cls(host=args.host, port=args.port, timeout=args.timeout)
    return cls()


def _cmd_replay(args: argparse.Namespace) -> int:
    fx = _resolve(args.root, args.fixture)
    transport = _build_transport(args)
    try:
        return _replay_and_report(fx, transport)
    finally:
        transport.close()  # a real-socket transport (snibelis-astm) must not leak its connection


def _cmd_archive(args: argparse.Namespace) -> int:
    """Archive a fixture's captured message into the content-addressed raw-message
    archive and print its digest (the key a Result is later re-derived from)."""
    fx = _resolve(args.root, args.fixture)
    entry = archive_fixture(RawMessageArchive(args.dir), fx, received_at=_now_iso())
    print(f"archived {fx.id} -> {entry.digest} ({entry.byte_count} bytes) in {args.dir}")
    return 0


def _cmd_roundtrip(args: argparse.Namespace) -> int:
    """Deterministic replay round-trip: archive a fixture's message, replay it back
    *from the archive* through a transport, normalize the ORU^R01, and check the
    normalized Result against the manifest's asserted ``expected`` rows. Exit 1 if
    the bytes don't survive the wire or the Result doesn't match expected."""
    fx = _resolve(args.root, args.fixture)
    transport = _build_transport(args)
    try:
        try:
            res = deterministic_round_trip(
                fx, transport, archive=RawMessageArchive(args.dir),
                received_at=_now_iso(),
            )
        except OruParseError as exc:
            print(f"error: cannot replay {fx.id} as ORU^R01: {exc}", file=sys.stderr)
            return 2
    finally:
        transport.close()  # a real-socket transport (snibelis-astm) must not leak its connection

    bytes_status = "OK" if res.round_trip_ok else "MISMATCH"
    print(
        f"roundtrip {fx.id} via {res.transport}: bytes {bytes_status} | "
        f"src {res.digest[:12]} -> result {res.result_digest[:12]}"
    )
    print(f"  {res.message_type}\tpatient={res.patient_id}\tspecimen={res.specimen_id}")
    for o in res.observations:
        print(
            f"  OBX-{o.set_id}\t{o.raw_code} {o.value} {o.raw_unit}"
            f"\t-> LOINC {o.loinc or '-'} / UCUM {o.ucum_value or '-'}\t[{o.status}]"
        )

    problems = check_against_expected(res, fx.expected) if fx.expected else []
    if not fx.expected:
        print("  expected: (none asserted in manifest)")
    elif problems:
        print("  expected: MISMATCH")
        for p in problems:
            print(f"    - {p}")
    else:
        print("  expected: OK")
    return 0 if res.round_trip_ok and not problems else 1


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


def _cmd_normalize(args: argparse.Namespace) -> int:
    """Parse a fixture's ORU^R01 and print each observation's normalized
    LOINC/UCUM intermediate row (raw code/unit beside the resolved LOINC/UCUM)."""
    fx = _resolve(args.root, args.fixture)
    try:
        report = parse_oru_r01(fx.message_bytes)
    except OruParseError as exc:
        print(f"error: cannot parse {fx.id} as ORU^R01: {exc}", file=sys.stderr)
        return 2
    rows = Normalizer().normalize_report(report)
    print(f"{fx.id}\t{report.message_type}\tpatient={report.patient_id}\tspecimen={report.specimen_id}")
    for r in rows:
        label = _non_result_label(r.kind)
        if label:
            print(f"  OBX-{r.set_id}\t{r.raw_code}\t-> [{label}] {r.value}")
            continue
        print(
            f"  OBX-{r.set_id}\t{r.raw_code} {r.value} {r.raw_unit}"
            f"\t-> LOINC {r.loinc or '-'} / UCUM {r.ucum_value or '-'}\t[{r.status}]"
        )
    return 0


def _cmd_milestone(args: argparse.Namespace) -> int:
    """Stage-1 milestone E2E (LIS-17 / S1.5): replay a fixture's ORU^R01 over MLLP,
    acknowledge it (ACK^R01 / MSA-1=AA), normalize it to a Result, and print the
    core ingest contract DTO. Exit 1 unless the message survived the wire, was
    accepted (AA), and every observation is a final, fully-normalized result."""
    fx = _resolve(args.root, args.fixture)
    try:
        out = run_milestone(fx.message_bytes)
    except (OruParseError, Hl7AckError) as exc:
        print(f"error: cannot run milestone for {fx.id}: {exc}", file=sys.stderr)
        return 2

    verdict = "ACCEPTED" if out.accepted else f"NOT-ACCEPTED ({out.ack_code})"
    print(
        f"milestone {fx.id} via mllp: {verdict} "
        f"(ACK^{out.ack_trigger_event} MSA-1={out.ack_code})"
    )
    print(
        f"  {out.report.message_type}\tpatient={out.report.patient_id}"
        f"\tspecimen={out.report.specimen_id}"
    )
    all_normalized = True
    for o, fin in zip(out.observations, out.result_statuses):
        label = _non_result_label(o.kind)
        if label:
            print(f"  OBX-{o.set_id}\t{o.raw_code}\t-> [{label}] {o.value}")
            continue
        all_normalized = all_normalized and bool(o.loinc and o.ucum_value)
        print(
            f"  OBX-{o.set_id}\t{o.raw_code} {o.value} {o.raw_unit}"
            f"\t-> LOINC {o.loinc or '-'} / UCUM {o.ucum_value or '-'}\t[{o.status}] ({fin})"
        )
    print(f"  ingest contract (core ADR-0003): {len(out.ingest_payload())} observation(s)")
    ok = out.round_trip_ok and out.accepted and out.all_final and all_normalized
    return 0 if ok else 1


def _cmd_query(args: argparse.Namespace) -> int:
    """Bidirectional host-query (LIS-18 / S1.6): parse a QRY^R02 host-query, have the
    host answer it (ORF^R04 / MSA-1=AA, echoing the query id) carrying the result
    fixture, and print the correlation + the normalized rows. Exit 1 unless the answer
    correlates to the query and every returned observation is fully normalized."""
    qfx = _resolve(args.root, args.query)
    rfx = _resolve(args.root, args.result)
    try:
        query = parse_query(qfx.message_bytes)
        result = parse_oru_r01(rfx.message_bytes)
    except (QueryError, OruParseError) as exc:
        print(f"error: cannot run query exchange: {exc}", file=sys.stderr)
        return 2

    orf = build_query_response(
        query, result, response_datetime=query.query_datetime, control_id=f"ORF{query.query_id}"
    )
    resp = parse_query_response(orf)
    correlated = correlates(query, resp)
    rows = Normalizer().normalize_report(resp.report)

    print(
        f"query {qfx.id}: QRY^R02 id={query.query_id} subject={query.subject_id} "
        f"what={query.what_subject}"
    )
    print(
        f"answer {rfx.id}: ORF^R04 MSA-1={resp.ack_code} echoed-id={resp.query_id} "
        f"specimen={resp.report.specimen_id} correlates={correlated}"
    )
    result_rows = [r for r in rows if r.kind == KIND_RESULT]
    all_normalized = bool(result_rows)  # an answer with no result rows is not a success
    for r in rows:
        label = _non_result_label(r.kind)
        if label:
            print(f"  OBX-{r.set_id}\t{r.raw_code}\t-> [{label}] {r.value}")
            continue
        all_normalized = all_normalized and bool(r.loinc and r.ucum_value)
        print(
            f"  OBX-{r.set_id}\t{r.raw_code} {r.value} {r.raw_unit}"
            f"\t-> LOINC {r.loinc or '-'} / UCUM {r.ucum_value or '-'}\t[{r.status}]"
        )
    if not rows:
        print("  (no result rows returned)")
    return 0 if correlated and all_normalized else 1


def _cmd_worklist_query(args: argparse.Namespace) -> int:
    """H99S order-download query: parse a QRY^R02 barcode query, have the host answer
    with ORF^R04 PID/OBR order rows, and print the barcode -> accession reconciliation."""
    qfx = _resolve(args.root, args.query)
    try:
        query = parse_query(qfx.message_bytes)
    except QueryError as exc:
        print(f"error: cannot run worklist query exchange: {exc}", file=sys.stderr)
        return 2

    codes = tuple(code.strip() for code in args.codes.split(",") if code.strip())
    order = WorklistOrder(
        accession_number=args.accession,
        patient_id=args.patient,
        analyzer_codes=codes,
    )
    orf = build_worklist_query_response(
        query, (order,), response_datetime=query.query_datetime, control_id=f"ORF{query.query_id}"
    )
    resp = parse_worklist_query_response(orf)
    correlated = worklist_correlates(query, resp)
    # An EDAN H90-series worklist order is panel-level (a panel int in OBR-11, no
    # per-analyte codes), so a populated panel_code counts as a returned order too.
    has_orders = any(order.analyzer_codes or order.panel_code for order in resp.orders)

    print(
        f"query {qfx.id}: QRY^R02 id={query.query_id} "
        f"barcode={query.subject_id} what={query.what_subject}"
    )
    print(
        f"answer worklist: ORF^R04 MSA-1={resp.ack_code} echoed-id={resp.query_id} "
        f"barcode={resp.subject_id} correlates={correlated}"
    )
    for order_row in resp.orders:
        tests = ",".join(order_row.analyzer_codes) or (
            f"panel:{order_row.panel_code}" if order_row.panel_code else "-"
        )
        # Generic orders carry the accession in OBR-2/3; EDAN orders carry the scanned
        # barcode in OBR-20 (the accession stays host-side, off the download wire).
        print(
            f"  OBR\taccession={order_row.accession_number or '-'}\t"
            f"barcode={order_row.barcode or '-'}\t"
            f"patient={order_row.patient_id or '-'}\ttests={tests}"
        )
    if not has_orders:
        print("  (no order rows returned)")
    return 0 if correlated and has_orders else 1


def _non_result_label(kind: str) -> str:
    if kind == KIND_WARNING:
        return "WARNING note"
    if kind == KIND_ANOMALY:
        return "ANOMALY note"
    if kind == KIND_ATTACHMENT:
        return "ATTACHMENT media"
    if kind == KIND_BLANK:
        return "BLANK material"
    return ""


def _cmd_parse_astm(args: argparse.Namespace) -> int:
    """Parse a fixture's ASTM E1394 records and print the typed record tree."""
    fx = _resolve(args.root, args.fixture)
    msg = parse_e1394(fx.message_bytes)
    sender = f"{msg.header.sender_name}/{msg.header.sender_model}" if msg.header else "(no header)"
    print(f"{fx.id}\t{sender}\tpatients={len(msg.patients)}\tterminator={msg.terminator_code or '-'}")
    for p in msg.patients:
        print(f"  P {p.patient_id or '-'} {p.name or ''}".rstrip())
        for o in p.orders:
            print(f"    O {o.specimen_id or '-'} test={o.test_code or '-'}")
            for r in o.results:
                print(f"      R {r.test_code} {r.value} {r.units}\t[{r.abnormal_flags or '-'}/{r.status or '-'}]")
    return 0


def _cmd_sanitize(args: argparse.Namespace) -> int:
    """Redact a PHI-bearing ASTM field from a quarantined raw bench capture
    (+ its matching annotated log) into a sanitized capture + a
    ``sanitization.json`` transformation ledger (LIS-319, quarantine-first
    intake). Exit 1 on any refusal (nothing is written on refusal)."""
    try:
        result = sanitize_capture(
            args.capture,
            args.log,
            record=args.record,
            field=args.field,
            cls=args.cls,
            token=args.token,
            ordinal=args.ordinal,
            length_preserving=args.length_preserving,
            out_dir=args.out,
        )
    except SanitizeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"sanitized {args.capture} -> {result.bin_path} "
        f"({result.occurrences} occurrence(s) of {args.record}.{args.field} "
        f"redacted to {result.token!r}); ledger: {result.ledger_path}"
    )
    return 0


def _add_snibelis_tcp_args(parser: argparse.ArgumentParser) -> None:
    """``--host``/``--port``/``--timeout``: only meaningful for ``--transport
    snibelis-astm`` (:class:`~edge_sim.transport.SnibeLisTcpTransport`, LIS-174 /
    D6), the one transport that dials a real socket instead of replaying
    in-memory. Harmless no-ops for every other transport choice."""
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="host to dial for --transport snibelis-astm (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="port to dial for --transport snibelis-astm (required for that transport)",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="seconds to wait for each ACK with --transport snibelis-astm (default: 10.0)",
    )


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
    _add_snibelis_tcp_args(replay_parser)
    replay_parser.set_defaults(func=_cmd_replay)
    archive_parser = sub.add_parser(
        "archive", help="archive a fixture's captured message (content-addressed)"
    )
    archive_parser.add_argument("fixture", help="fixture id or directory path")
    archive_parser.add_argument(
        "--dir", type=Path, default=DEFAULT_ARCHIVE_DIR,
        help=f"raw-message archive directory (default: {DEFAULT_ARCHIVE_DIR})",
    )
    archive_parser.set_defaults(func=_cmd_archive)
    roundtrip_parser = sub.add_parser(
        "roundtrip",
        help="archive + deterministic replay -> normalized Result, checked vs expected",
    )
    roundtrip_parser.add_argument("fixture", help="fixture id or directory path")
    roundtrip_parser.add_argument(
        "--transport", choices=sorted(_TRANSPORTS), default="loopback",
        help="transport to replay through (default: loopback)",
    )
    roundtrip_parser.add_argument(
        "--dir", type=Path, default=DEFAULT_ARCHIVE_DIR,
        help=f"raw-message archive directory (default: {DEFAULT_ARCHIVE_DIR})",
    )
    _add_snibelis_tcp_args(roundtrip_parser)
    roundtrip_parser.set_defaults(func=_cmd_roundtrip)
    ack_parser = sub.add_parser("ack", help="print the HL7 ACK for a fixture's message")
    ack_parser.add_argument("fixture", help="fixture id or directory path")
    ack_parser.set_defaults(func=_cmd_ack)
    normalize_parser = sub.add_parser(
        "normalize", help="parse a fixture's ORU^R01 and print the normalized LOINC/UCUM rows"
    )
    normalize_parser.add_argument("fixture", help="fixture id or directory path")
    normalize_parser.set_defaults(func=_cmd_normalize)
    milestone_parser = sub.add_parser(
        "milestone",
        help="Stage-1 E2E: replay ORU^R01 over MLLP -> normalized Result + ACK (AA)",
    )
    milestone_parser.add_argument("fixture", help="fixture id or directory path")
    milestone_parser.set_defaults(func=_cmd_milestone)
    query_parser = sub.add_parser(
        "query",
        help="bidirectional host-query: answer a QRY^R02 (QRD/QRF) -> ORF^R04 + normalized Result",
    )
    query_parser.add_argument("query", help="QRY^R02 query fixture id or directory path")
    query_parser.add_argument(
        "--result", default="edan-h60s-oru-r01",
        help="result fixture the host answers with (default: edan-h60s-oru-r01)",
    )
    query_parser.set_defaults(func=_cmd_query)
    worklist_query_parser = sub.add_parser(
        "worklist-query",
        help="order-download host-query: answer QRY^R02 -> ORF^R04 PID/OBR worklist rows",
    )
    worklist_query_parser.add_argument("query", help="QRY^R02 query fixture id or directory path")
    worklist_query_parser.add_argument(
        "--accession",
        required=True,
        help="host accession number returned in OBR-2/3",
    )
    worklist_query_parser.add_argument(
        "--patient",
        required=True,
        help="patient id returned in PID-3",
    )
    worklist_query_parser.add_argument(
        "--codes",
        required=True,
        help="comma-separated analyzer test codes returned as OBR rows",
    )
    worklist_query_parser.set_defaults(func=_cmd_worklist_query)
    parse_astm_parser = sub.add_parser(
        "parse-astm", help="parse a fixture's ASTM E1394 records and print the record tree"
    )
    parse_astm_parser.add_argument("fixture", help="fixture id or directory path")
    parse_astm_parser.set_defaults(func=_cmd_parse_astm)
    sanitize_parser = sub.add_parser(
        "sanitize",
        help="redact a PHI-bearing ASTM field from a raw bench capture (quarantine-first)",
    )
    sanitize_parser.add_argument(
        "capture", help="path to the raw capture .bin file (must be outside the repo tree)"
    )
    sanitize_parser.add_argument(
        "--out", required=True, type=Path,
        help="output directory for the sanitized capture + transformation ledger",
    )
    sanitize_parser.add_argument(
        "--record", required=True, help="ASTM record type to redact within (e.g. O)"
    )
    sanitize_parser.add_argument(
        "--field", required=True, type=int,
        help="1-based ASTM field number to redact (e.g. 3 for O.3, the specimen-id position)",
    )
    sanitize_parser.add_argument(
        "--class", required=True, dest="cls", choices=sorted(TOKEN_CLASSES),
        help="canonical redaction token class",
    )
    sanitize_parser.add_argument(
        "--log", default=None, help="path to the matching annotated .log file (optional)"
    )
    sanitize_parser.add_argument(
        "--token", default=None,
        help="explicit replacement token (default: derived from --class + --ordinal)",
    )
    sanitize_parser.add_argument(
        "--ordinal", type=int, default=1,
        help="ordinal suffix for the class-derived token (default: 1)",
    )
    sanitize_parser.add_argument(
        "--no-length-preserving", dest="length_preserving", action="store_false", default=True,
        help="allow the redacted field to change byte length (recomputes RECV "
        "byte counts in the log; default is length-preserving)",
    )
    sanitize_parser.set_defaults(func=_cmd_sanitize)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FixtureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except TransportError as exc:
        # e.g. --transport snibelis-astm with no --port, or a dead link talking
        # to a live bridge (LIS-174 / D6) -- a clean CLI error, not a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
