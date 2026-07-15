"""LOINC/UCUM normalization — LIS-14 / S1.2.

Maps an analyzer-native (vendor) observation to its normalized form: the local
observation *code* to a **LOINC** code and the raw vendor *unit* string to a
**UCUM** unit, producing a :class:`NormalizedObservation` — the LOINC/UCUM
"intermediate row" that carries the raw analyzer fields beside the normalized
ones (the same raw-beside-normalized shape the core ``clinlims.result`` table
persists, LIS-7 / S0.5).

The mapping is the edge-side analog of the core ``clinlims.vendor_code_mapping``
seed (LIS-8 / S0.6). The default :class:`TerminologyMap` ships a small RAYTO
RAC-050 CBC seed so S1.2 has one working normalization end-to-end; a richer,
per-analyzer terminology (and sourcing it from the core mapping / a shared
terminology file rather than this built-in seed) is Stage-1 normalization-service
work that later slices layer on.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .oru import OruReport, RawObservation
from .oru import RESULT_TYPE_BLANK, RESULT_TYPE_CALIBRATION, RESULT_TYPE_QC

__all__ = [
    "NormalizedObservation",
    "TerminologyMap",
    "Normalizer",
    "STATUS_NORMALIZED",
    "STATUS_PARTIAL",
    "STATUS_UNMAPPED",
    "KIND_RESULT",
    "KIND_WARNING",
    "KIND_ANOMALY",
    "KIND_ATTACHMENT",
    "KIND_QC",
    "KIND_CALIBRATION",
    "KIND_BLANK",
]

STATUS_NORMALIZED = "NORMALIZED"  # both code and unit resolved
STATUS_PARTIAL = "PARTIAL"  # exactly one of code/unit resolved
STATUS_UNMAPPED = "UNMAPPED"  # neither resolved

# Whether an OBX is a patient analyte result or an in-band instrument flag/note.
KIND_RESULT = "RESULT"  # a numeric/analyte patient result row
KIND_WARNING = "WARNING"  # an in-band instrument warning (e.g. SD1 'Alarm' OBX) — a note, not a result
KIND_ANOMALY = "ANOMALY"  # parser anomaly, e.g. NM/SN value that is not a decimal number
KIND_ATTACHMENT = "ATTACHMENT"  # analyzer media payload, e.g. EDAN histogram PNG — not a result
KIND_QC = "QC"  # quality-control row — never a patient result
KIND_CALIBRATION = "CALIBRATION"  # calibration row — never a patient result
KIND_BLANK = "BLANK"  # blank/operational material — never a patient result

# In-band warning sentinel: the Seamaty SD1 emits instrument warnings in-band as an
# ST OBX whose OBX-3 observation identifier is the literal 'Alarm' (warning code in
# OBX-4, e.g. W3001; manual §4.1.1) — an instrument flag, not a patient analyte. Such
# an OBX is routed as KIND_WARNING so it never lands as a numeric result (LIS-86 / S2.10).
_INBAND_WARNING_CODE = "ALARM"
_EDAN_HISTOGRAM_SUFFIX = "_PNG_BASE64"


@dataclass(frozen=True)
class NormalizedObservation:
    """An observation with its raw analyzer fields beside the normalized
    LOINC/UCUM form — the S1.2 intermediate row."""

    set_id: str
    value: str
    raw_code: str  # analyzer-native code, preserved
    raw_unit: str  # raw vendor unit, preserved
    loinc: str  # normalized LOINC ("" if unmapped)
    ucum_value: str  # normalized UCUM unit ("" if unmapped)
    status: str  # NORMALIZED | PARTIAL | UNMAPPED
    kind: str = KIND_RESULT  # RESULT | WARNING | ANOMALY | ATTACHMENT | QC | CALIBRATION | BLANK


# --- default RAYTO RAC-050 CBC terminology seed (LIS-14 / S1.2) -------------

# analyzer-native observation code -> LOINC
_DEFAULT_CODES: dict[str, str] = {
    "HGB": "718-7",  # Hemoglobin [Mass/volume] in Blood
    "HCT": "4544-3",  # Hematocrit [Volume Fraction] of Blood by Automated count
    "WBC": "6690-2",  # Leukocytes [#/volume] in Blood by Automated count
    "PLT": "777-3",  # Platelets [#/volume] in Blood by Automated count
    "RBC": "789-8",  # Erythrocytes [#/volume] in Blood by Automated count
    "MCV": "787-2",  # MCV [Entitic volume] by Automated count
    "GLU": "2345-7",  # Glucose [Mass/volume] in Serum or Plasma (aligns with LIS-8 seed)
    # Seamaty SD1 dry-chemistry biochem panel — serum/plasma LOINCs (LIS-86 / S2.10).
    "BUN": "3094-0",  # Urea nitrogen [Mass/volume] in Serum or Plasma
    "CREA": "2160-0",  # Creatinine [Mass/volume] in Serum or Plasma
    "AST": "1920-8",  # Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma
    "ALT": "1742-6",  # Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma
    "TP": "2885-2",  # Protein [Mass/volume] in Serum or Plasma (total protein)
}

# raw vendor unit string -> UCUM unit
_DEFAULT_UNITS: dict[str, str] = {
    "g/dL": "g/dL",
    "g/dl": "g/dL",
    "%": "%",
    "10^9/L": "10*9/L",
    "10^3/uL": "10*3/uL",
    "10*9/L": "10*9/L",
    "10*3/uL": "10*3/uL",
    "K/uL": "10*3/uL",
    "M/uL": "10*6/uL",
    "10^12/L": "10*12/L",  # EDAN H60S RBC unit (LIS-17 / S1.5)
    "10*12/L": "10*12/L",
    "g/L": "g/L",  # EDAN H60S HGB unit (g/L; RAYTO seed uses g/dL)
    "fL": "fL",
    "pg": "pg",
    "mg/dL": "mg/dL",
    "mmol/L": "mmol/L",
    "U/L": "U/L",  # enzyme catalytic activity (Seamaty SD1 AST/ALT); UCUM unit "U" per litre (LIS-86)
}


class TerminologyMap:
    """A vendor-code -> LOINC and vendor-unit -> UCUM lookup."""

    def __init__(self, codes: dict[str, str] | None = None, units: dict[str, str] | None = None):
        # code lookup is case-insensitive on the local mnemonic; unit lookup is
        # exact (after trimming) since UCUM unit case is significant.
        self._codes = {k.strip().upper(): v for k, v in (codes or {}).items()}
        self._units = {k.strip(): v for k, v in (units or {}).items()}

    @classmethod
    def default(cls) -> "TerminologyMap":
        return cls(codes=_DEFAULT_CODES, units=_DEFAULT_UNITS)

    def normalize_code(self, raw_code: str) -> str | None:
        return self._codes.get((raw_code or "").strip().upper()) or None

    def normalize_unit(self, raw_unit: str) -> str | None:
        key = (raw_unit or "").strip()
        if not key:
            return None
        return self._units.get(key) or None


class Normalizer:
    """Resolves :class:`RawObservation`\\ s to :class:`NormalizedObservation`\\ s
    through a :class:`TerminologyMap` (the default RAC-050 seed if none given)."""

    def __init__(self, terminology: TerminologyMap | None = None):
        self._tmap = terminology if terminology is not None else TerminologyMap.default()

    @classmethod
    def from_fixture(cls, fixture) -> "Normalizer":
        """Build a normalizer from a fixture's manifest terminology block.

        The simulator mirrors the production bridge contract: analyzer code →
        LOINC comes only from the channel/profile data — never the seed map,
        so a fixture proves its own code mappings (a block without ``codes``
        maps nothing, like a bridge entry with no ``codeToLoinc``). Raw unit →
        UCUM prefers the profile data and falls back to the common seed map —
        the same analyzer-map-then-common-map order the bridge's
        FhirBundleBuilder applies (the bridge has no common *code* map, only a
        common unit map). Fixtures without a terminology block keep the
        default seed maps for backwards compatibility.
        """
        terminology = getattr(fixture, "terminology", None) or {}
        codes = terminology.get("codes")
        units = terminology.get("units")
        if codes is None and units is None:
            return cls()
        return cls(
            TerminologyMap(
                codes=codes or {},
                units={**_DEFAULT_UNITS, **(units or {})},
            )
        )

    def normalize_observation(self, obs: RawObservation) -> NormalizedObservation:
        loinc = self._tmap.normalize_code(obs.raw_code) or ""
        ucum = self._tmap.normalize_unit(obs.raw_unit) or ""
        if loinc and ucum:
            status = STATUS_NORMALIZED
        elif loinc or ucum:
            status = STATUS_PARTIAL
        else:
            status = STATUS_UNMAPPED
        return NormalizedObservation(
            set_id=obs.set_id,
            value=obs.value,
            raw_code=obs.raw_code,
            raw_unit=obs.raw_unit,
            loinc=loinc,
            ucum_value=ucum,
            status=status,
            kind=_observation_kind(obs),
        )

    def normalize_report(self, report: OruReport) -> list[NormalizedObservation]:
        rows = [self.normalize_observation(obs) for obs in report.observations]
        if report.result_type == RESULT_TYPE_CALIBRATION:
            return [_with_kind(row, KIND_CALIBRATION) if row.kind == KIND_RESULT else row for row in rows]
        if report.result_type == RESULT_TYPE_BLANK:
            return [_with_kind(row, KIND_BLANK) if row.kind == KIND_RESULT else row for row in rows]
        if report.result_type == RESULT_TYPE_QC:
            # ASTM E1394 QC (LIS-33) and EDAN HL7 QC (LIS-110, report.edan — the
            # H60/H90-series MSH-16 map has no calibration value and fails closed to
            # QC, so its patient-stream rows must actually leave that stream) both
            # re-kind here. The SD1/generic-HL7 QC gap (message_type=="ORU^R01" and
            # not report.edan) is a deliberately unfixed bound left from LIS-33 —
            # those rows stay KIND_RESULT in the sim; tracked under LIS-95.
            if report.message_type == "ASTM^E1394" or report.edan:
                return [
                    _with_kind(row, KIND_QC) if row.kind == KIND_RESULT else row
                    for row in rows
                ]
            return rows
        return rows


def _is_inband_warning(obs: RawObservation) -> bool:
    """True for an in-band instrument-warning OBX (OBX-3 = 'Alarm'), routed as a
    flag/note rather than a patient result — see :data:`_INBAND_WARNING_CODE`."""
    return (obs.raw_code or "").strip().upper() == _INBAND_WARNING_CODE


def _observation_kind(obs: RawObservation) -> str:
    if _is_inband_warning(obs):
        return KIND_WARNING
    if _is_histogram_attachment(obs):
        return KIND_ATTACHMENT
    if _is_unparseable_numeric(obs):
        return KIND_ANOMALY
    return KIND_RESULT


def _is_histogram_attachment(obs: RawObservation) -> bool:
    code = (obs.raw_code or "").strip().upper()
    return (obs.value_type or "").strip().upper() == "ST" and code.endswith(_EDAN_HISTOGRAM_SUFFIX)


def _is_unparseable_numeric(obs: RawObservation) -> bool:
    value_type = (obs.value_type or "").strip().upper()
    if value_type not in {"NM", "SN"}:
        return False
    value = (obs.value or "").strip()
    if not value:
        return False
    try:
        return not Decimal(value).is_finite()
    except InvalidOperation:
        return True


def _with_kind(obs: NormalizedObservation, kind: str) -> NormalizedObservation:
    return NormalizedObservation(
        set_id=obs.set_id,
        value=obs.value,
        raw_code=obs.raw_code,
        raw_unit=obs.raw_unit,
        loinc=obs.loinc,
        ucum_value=obs.ucum_value,
        status=obs.status,
        kind=kind,
    )
