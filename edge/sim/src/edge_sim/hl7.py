"""Tolerant HL7 v2 message parser — LIS-14 / S1.2.

Dependency-free. Splits an HL7 v2 message into segments and their
fields / components / repetitions, honouring the encoding characters declared in
``MSH-2`` and decoding the standard escape sequences. Tolerant by design (plan
§1): ``\\r`` / ``\\n`` / ``\\r\\n`` segment terminators, missing trailing fields,
and short/empty segments all parse without raising.

This is the general parser the ``ORU^R01`` extractor (:mod:`edge_sim.oru`) builds
on. The MLLP listener's MSH-only reader (:mod:`edge_sim.ack`) stays separate — it
needs only enough of ``MSH`` to acknowledge, before this parser existed.

Field numbering follows HL7 convention, so callers use the numbers from the
spec/manual directly:

* For ``MSH``, ``field(1)`` is the field separator itself and ``field(2)`` the
  encoding characters (``MSH`` consumes its first separator as a value).
* For every other segment, ``field(n)`` is the n-th ``|``-delimited field.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Encoding",
    "Segment",
    "Message",
    "Hl7Error",
    "DEFAULT_ENCODING_CHARS",
    "parse_message",
    "unescape",
]

_SEGMENT_SEP = "\r"
DEFAULT_ENCODING_CHARS = "^~\\&"  # component ^, repetition ~, escape \, subcomponent &


class Hl7Error(Exception):
    """Raised only when a message is too malformed to parse at all (empty, or no
    segment begins with a 3-character segment id)."""


@dataclass(frozen=True)
class Encoding:
    """The HL7 delimiters in force for a message (from ``MSH-1``/``MSH-2``)."""

    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"

    @classmethod
    def from_msh(cls, field_sep: str, encoding_chars: str) -> "Encoding":
        ec = encoding_chars
        return cls(
            field=field_sep or "|",
            component=ec[0] if len(ec) > 0 else "^",
            repetition=ec[1] if len(ec) > 1 else "~",
            escape=ec[2] if len(ec) > 2 else "\\",
            subcomponent=ec[3] if len(ec) > 3 else "&",
        )


@dataclass(frozen=True)
class Segment:
    """One HL7 segment: its 3-char ``name`` and ``|``-split ``fields``.

    ``fields`` is the raw split including the leading segment name at index 0
    (so for ``OBX`` it indexes naturally: ``fields[3]`` is ``OBX-3``). ``MSH`` is
    special — see :meth:`field`.
    """

    name: str
    fields: tuple[str, ...]
    encoding: Encoding

    @property
    def is_msh(self) -> bool:
        return self.name == "MSH"

    def field(self, n: int) -> str:
        """Return ``<SEG>-n`` (1-based, HL7 numbering), or ``""`` if absent."""
        if n < 1:
            return ""
        if self.is_msh:
            if n == 1:
                return self.encoding.field
            idx = n - 1  # MSH-2 is fields[1], MSH-9 is fields[8], ...
        else:
            idx = n
        return self.fields[idx] if idx < len(self.fields) else ""

    def component(self, n: int, c: int) -> str:
        """Return component ``c`` (1-based) of ``<SEG>-n``, or ``""`` if absent.

        The first repetition only — call :meth:`repetitions` for repeats.
        """
        first_rep = self.field(n).split(self.encoding.repetition, 1)[0]
        comps = first_rep.split(self.encoding.component)
        return comps[c - 1] if 1 <= c <= len(comps) else ""

    def repetitions(self, n: int) -> list[str]:
        """Return the repetitions of ``<SEG>-n`` (split on the repetition sep)."""
        value = self.field(n)
        return value.split(self.encoding.repetition) if value else []


@dataclass(frozen=True)
class Message:
    """A parsed HL7 v2 message: its delimiters and ordered segments."""

    encoding: Encoding
    segments: tuple[Segment, ...]

    def first(self, name: str) -> Segment | None:
        for seg in self.segments:
            if seg.name == name:
                return seg
        return None

    def all(self, name: str) -> tuple[Segment, ...]:
        return tuple(seg for seg in self.segments if seg.name == name)


def _split_segments(text: str) -> list[str]:
    # Tolerate \r, \n, or \r\n terminators; drop blank/whitespace-only segments.
    normalized = text.replace("\r\n", "\r").replace("\n", "\r")
    return [s for s in normalized.split(_SEGMENT_SEP) if s.strip()]


def parse_message(raw: bytes | str) -> Message:
    """Parse ``raw`` (latin-1 bytes or str) into a :class:`Message`.

    The encoding characters are read from the first ``MSH`` segment; if the
    message does not start with ``MSH`` the HL7 defaults (``|^~\\&``) are assumed
    so non-MSH-led fragments still parse. Raises :class:`Hl7Error` only if there
    is no parseable segment at all.
    """
    # latin-1 (ISO-8859-1) is a deliberate, lossless byte→codepoint decode: it never
    # raises, is a strict superset of ASCII, and matches MSH-18/ISO-8859-1 declarations
    # (e.g. the Seamaty SD1, manual §1.6). A per-analyzer encoding that is actually
    # UTF-8 (the SD1 manual's p4 remark conflicts) is confirmed at the bench capture
    # (LIS-79) and applied there; until then this superset decode is safe for the
    # ASCII-only synthetic fixtures (LIS-86 / S2.10).
    text = raw.decode("latin-1") if isinstance(raw, (bytes, bytearray)) else raw
    raw_segments = _split_segments(text)
    if not raw_segments:
        raise Hl7Error("no HL7 segments found")

    # Determine the encoding from MSH if present.
    encoding = Encoding()
    first = raw_segments[0]
    if first.startswith("MSH") and len(first) >= 4:
        field_sep = first[3]
        fields = first.split(field_sep)
        encoding = Encoding.from_msh(field_sep, fields[1] if len(fields) > 1 else "")

    segments: list[Segment] = []
    for seg_text in raw_segments:
        if len(seg_text) < 3:
            continue
        name = seg_text[:3]
        if name == "MSH":
            field_sep = seg_text[3] if len(seg_text) >= 4 else encoding.field
            fields = tuple(seg_text.split(field_sep))
        else:
            fields = tuple(seg_text.split(encoding.field))
        segments.append(Segment(name=name, fields=fields, encoding=encoding))

    if not segments:
        raise Hl7Error("no parseable HL7 segments found")
    return Message(encoding=encoding, segments=tuple(segments))


def unescape(value: str, encoding: Encoding) -> str:
    """Decode HL7 escape sequences in ``value`` (``\\F\\``, ``\\S\\``, ``\\T\\``,
    ``\\R\\``, ``\\E\\`` and ``\\Xhh..\\`` hex). Unknown escapes are left as-is."""
    esc = encoding.escape
    if esc not in value:
        return value
    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch != esc:
            out.append(ch)
            i += 1
            continue
        end = value.find(esc, i + 1)
        if end == -1:  # dangling escape char — emit literally
            out.append(ch)
            i += 1
            continue
        code = value[i + 1 : end]
        if code == "F":
            out.append(encoding.field)
        elif code == "S":
            out.append(encoding.component)
        elif code == "T":
            out.append(encoding.subcomponent)
        elif code == "R":
            out.append(encoding.repetition)
        elif code == "E":
            out.append(encoding.escape)
        elif code[:1] in ("X", "x"):
            try:
                out.append(bytes.fromhex(code[1:]).decode("latin-1"))
            except ValueError:
                out.append(esc + code + esc)  # not valid hex — leave verbatim
        else:
            out.append(esc + code + esc)  # unknown escape — leave verbatim
        i = end + 1
    return "".join(out)
