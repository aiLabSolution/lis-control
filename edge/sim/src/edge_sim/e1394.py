"""ASTM E1394 record parser — LIS-24 / S2.2.

ASTM E1394 is the record content carried by the E1381 link layer (LIS-23 / S2.1):
a flat, ordered sequence of pipe-delimited records, each led by a single-letter
type, that imply a tree — ``H`` (header) then one or more ``P`` (patient), each
with ``O`` (order) records, each with ``R`` (result) records, closed by ``L``
(terminator); ``C`` (comment), ``Q`` (query) and ``M`` (manufacturer) records may
appear between them.

This module parses that sequence into a typed :class:`AstmMessage` tree, **tolerant
of spec deviation** (plan §2): the delimiters are taken from the ``H`` record (or
HL7-like defaults if absent); missing trailing fields yield ``""``; an ``O``/``R``
with no preceding parent gets an implicit one; and unknown record types are kept in
the flat ``records`` list without disturbing the tree. Dependency-free; mirrors the
HL7 ORU parser (S1.2) one layer up. Normalizing a parsed result to a LOINC/UCUM
Result row is a later slice (S2.4 / LIS-26).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Delimiters",
    "Record",
    "Header",
    "AstmResult",
    "AstmOrder",
    "AstmPatient",
    "AstmMessage",
    "E1394Error",
    "parse_e1394",
]

_SEGMENT_SEP = "\r"


class E1394Error(Exception):
    """Raised only when there is no parseable record at all (empty input)."""


@dataclass(frozen=True)
class Delimiters:
    """The ASTM E1394 delimiters in force, taken from the ``H`` record."""

    field: str = "|"
    repeat: str = "\\"
    component: str = "^"
    escape: str = "&"

    @classmethod
    def from_header(cls, header_record: str) -> "Delimiters":
        """Derive the delimiters from an ``H`` record. The character after ``H`` is
        the field delimiter; the next field (e.g. ``\\^&``) defines repeat, component
        and escape. Falls back to the conventional ``|\\^&`` for a non-``H`` line."""
        if len(header_record) < 2 or header_record[0] != "H":
            return cls()
        field = header_record[1]
        parts = header_record.split(field)
        defn = parts[1] if len(parts) > 1 else ""
        return cls(
            field=field,
            repeat=defn[0] if len(defn) > 0 else "\\",
            component=defn[1] if len(defn) > 1 else "^",
            escape=defn[2] if len(defn) > 2 else "&",
        )


@dataclass(frozen=True)
class Record:
    """One ASTM record: its type letter and ``field``-split fields."""

    type: str
    fields: tuple[str, ...]
    delimiters: Delimiters

    def field(self, n: int) -> str:
        """Return field ``n`` (1-based; ``field(1)`` is the record-type letter)."""
        if n < 1 or n > len(self.fields):
            return ""
        return self.fields[n - 1]

    def component(self, n: int, c: int) -> str:
        comps = self.field(n).split(self.delimiters.component)
        return comps[c - 1] if 1 <= c <= len(comps) else ""

    def test_code(self, n: int) -> str:
        """The analyzer test code from a universal-test-id field ``n`` — the last
        non-empty component (handles ``^^^GLU`` and a bare ``GLU`` alike)."""
        value = self.field(n)
        comps = [c for c in value.split(self.delimiters.component) if c]
        return comps[-1] if comps else value

    def test_codes(self, n: int) -> tuple[str, ...]:
        """Every analyzer test code from a *repeating* universal-test-id field ``n``.

        SnibeLis packs a multi-assay order into O-5 as ``^^^A\\^^^B`` where ``\\`` is
        the ASTM repetition delimiter (KB §5.3/§7); each repeat is a ``^^^``-prefixed
        code. Returns each code with its ``^^^`` prefix stripped, in transmission
        order, skipping empty repeats — a one-tuple for a single assay, empty for a
        blank field."""
        codes: list[str] = []
        for item in self.field(n).split(self.delimiters.repeat):
            comps = [c for c in item.split(self.delimiters.component) if c]
            code = comps[-1] if comps else item
            if code:
                codes.append(code)
        return tuple(codes)


@dataclass(frozen=True)
class Header:
    sender_name: str  # H-5 component 1
    sender_model: str  # H-5 component 2
    processing_id: str  # H-12
    version: str  # H-13
    raw: str


@dataclass(frozen=True)
class AstmResult:
    seq: str  # R-2
    test_code: str  # R-3 (universal test id)
    value: str  # R-4
    units: str  # R-5
    reference_range: str  # R-6
    abnormal_flags: str  # R-7
    status: str  # R-9
    completion_time: str  # R-13 (YYYYMMDDHHMMSS), "" when absent
    raw: str


@dataclass(frozen=True)
class AstmOrder:
    seq: str  # O-2
    specimen_id: str  # O-3 component 1 (accession; later components are location)
    test_code: str  # O-5 (universal test id; last code if repeated)
    assays: tuple[str, ...]  # O-5 split on the repeat delimiter (multi-assay orders)
    priority: str  # O-6
    action_code: str  # O-12 (Q = QC when the analyzer emits it)
    results: tuple[AstmResult, ...]
    raw: str


@dataclass(frozen=True)
class AstmPatient:
    seq: str  # P-2
    patient_id: str  # first nonblank P-3 (practice), P-4 (lab), then P-5 (id #3)
    name: str  # P-6
    orders: tuple[AstmOrder, ...]
    raw: str


@dataclass(frozen=True)
class AstmMessage:
    """The typed E1394 record tree."""

    header: Header | None
    patients: tuple[AstmPatient, ...]
    terminator_code: str  # L-3
    records: tuple[Record, ...]  # the flat, ordered records (incl. C/Q/M)

    @property
    def results(self) -> list[AstmResult]:
        """Every result across all patients/orders, in record order."""
        return [r for p in self.patients for o in p.orders for r in o.results]


def _split_records(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\r").replace("\n", "\r")
    return [seg for seg in normalized.split(_SEGMENT_SEP) if seg.strip()]


def _record(raw: str, delims: Delimiters) -> Record:
    return Record(type=raw[:1], fields=tuple(raw.split(delims.field)), delimiters=delims)


def parse_e1394(message: bytes | str, delimiters: Delimiters | None = None) -> AstmMessage:
    """Parse an ASTM E1394 record set into an :class:`AstmMessage` tree."""
    text = message.decode("latin-1") if isinstance(message, (bytes, bytearray)) else message
    raw_records = _split_records(text)
    if not raw_records:
        raise E1394Error("no ASTM records found")

    if delimiters is None:
        first_h = next((r for r in raw_records if r[:1] == "H"), None)
        delimiters = Delimiters.from_header(first_h) if first_h is not None else Delimiters()

    records = [_record(raw, delimiters) for raw in raw_records]

    header: Header | None = None
    patients: list[dict] = []
    terminator = ""
    cur_patient: dict | None = None
    cur_order: dict | None = None

    def ensure_patient() -> dict:
        nonlocal cur_patient
        if cur_patient is None:
            cur_patient = {"rec": None, "orders": []}
            patients.append(cur_patient)
        return cur_patient

    def ensure_order() -> dict:
        nonlocal cur_order
        if cur_order is None:
            cur_order = {"rec": None, "results": []}
            ensure_patient()["orders"].append(cur_order)
        return cur_order

    for rec in records:
        t = rec.type
        if t == "H":
            header = _header(rec)
        elif t == "P":
            cur_patient = {"rec": rec, "orders": []}
            patients.append(cur_patient)
            cur_order = None
        elif t == "O":
            cur_order = {"rec": rec, "results": []}
            ensure_patient()["orders"].append(cur_order)
        elif t == "R":
            ensure_order()["results"].append(_result(rec))
        elif t == "L":
            terminator = rec.field(3)
        # C / Q / M / unknown: retained in the flat records list, ignored in the tree

    patient_objs = tuple(_patient(p) for p in patients)
    return AstmMessage(
        header=header,
        patients=patient_objs,
        terminator_code=terminator,
        records=tuple(records),
    )


def _header(rec: Record) -> Header:
    return Header(
        sender_name=rec.component(5, 1),
        sender_model=rec.component(5, 2),
        processing_id=rec.field(12),
        version=rec.field(13),
        raw=rec.delimiters.field.join(rec.fields),
    )


def _result(rec: Record) -> AstmResult:
    return AstmResult(
        seq=rec.field(2),
        test_code=rec.test_code(3),
        value=rec.field(4),
        units=rec.field(5),
        reference_range=rec.field(6),
        abnormal_flags=rec.field(7),
        status=rec.field(9),
        completion_time=_completion_time(rec),
        raw=rec.delimiters.field.join(rec.fields),
    )


def _completion_time(rec: Record) -> str:
    """The ASTM R-13 test-completion timestamp (``YYYYMMDDHHMMSS``).

    SnibeLis documents the completion time at R-13 (KB §5.3, ASTM 10.1.13) but the
    vendor manual's worked example emits it one field earlier — an ASTM-doc
    inconsistency (KB gotcha #7/#9) we can't tie-break without a live capture
    (LIS-75). So we prefer the spec R-13 field and, when it is empty, recover the
    record's sole timestamp-shaped (14-digit) field — tolerant of either wire
    reality, in keeping with this module's spec-deviation tolerance."""
    spec = rec.field(13)
    if spec:
        return spec
    for value in rec.fields[7:]:  # after R-7 (flag); codes/values/ranges precede it
        if len(value) == 14 and value.isdigit():
            return value
    return ""


def _patient(p: dict) -> AstmPatient:
    rec: Record | None = p["rec"]
    orders = tuple(_order(o) for o in p["orders"])
    if rec is None:
        return AstmPatient(seq="", patient_id="", name="", orders=orders, raw="")
    patient_id = ""
    for field_number in (3, 4, 5):
        candidate = rec.component(field_number, 1).strip()
        if candidate:
            patient_id = candidate
            break
    return AstmPatient(
        seq=rec.field(2),
        patient_id=patient_id,
        name=rec.field(6),
        orders=orders,
        raw=rec.delimiters.field.join(rec.fields),
    )


def _order(o: dict) -> AstmOrder:
    rec: Record | None = o["rec"]
    results = tuple(o["results"])
    if rec is None:
        return AstmOrder(
            seq="",
            specimen_id="",
            test_code="",
            assays=(),
            priority="",
            action_code="",
            results=results,
            raw="",
        )
    return AstmOrder(
        seq=rec.field(2),
        specimen_id=rec.component(3, 1).strip(),
        test_code=rec.test_code(5),
        assays=rec.test_codes(5),
        priority=rec.field(6),
        action_code=rec.field(12),
        results=results,
        raw=rec.delimiters.field.join(rec.fields),
    )
