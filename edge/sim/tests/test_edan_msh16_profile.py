"""LIS-110 — vendor-aware ``MSH-16`` result-type profile, EDAN semantics.

Before this slice ``_result_type(msh16)`` applied the Seamaty SD1 encoding
(0=patient/1=calibration/2=QC) to every HL7 vendor, including the EDAN H60/H90
family. The EDAN LIS Communication Protocol KB (``EDAN\\WI\\82-01.54.460907``
§3.2.1) uses a different map with **no calibration value**: 0/empty=sample
(patient), 1=QC. The 2026-07-06/07 physical H60S bench
(``docs/runbooks/edan-h60s-bench-conformance.md``) additionally observed
MSH-16=2 on the MSH-only connection-test ping and =3 on a host-query
``QRY^R02`` — neither documented in the KB, and neither ever carrying a real
result (both are payload-less frames). Any EDAN MSH-16 value this profile does
not recognize (including the bench-observed 2/3) fails closed to QC: it is
never routed to the patient stream (mirrors the bridge
``HL7ResultParser.fromEdanMsh16``).

A second delta rides on top: the EDAN **QC OBR layout** (KB §3.2.3) is PID-less
and repurposes OBR-2/OBR-3/OBR-13 (QC file No. / level / lot) instead of the
patient-layout OBR-3/OBR-14/OBR-20 fields — used only when MSH-16 is exactly
``"1"`` (``edan_qc_layout`` in :mod:`edge_sim.oru`); an unrecognized
(fail-closed-QC) EDAN frame keeps the patient-layout field positions/blanking.

Finally, ``normalize.normalize_report``'s QC branch is widened from
``message_type == "ASTM^E1394"`` to also re-kind EDAN HL7 QC (``report.edan``)
out of the patient (``KIND_RESULT``) stream into ``KIND_QC`` — the SD1/generic
HL7 QC gap (a non-EDAN analyzer whose MSH-16 says QC) is a **deliberately
unfixed bound** left over from LIS-33, tracked separately under LIS-95.
"""

from pathlib import Path

from edge_sim.fixtures import load_fixture
from edge_sim.milestone import run_milestone
from edge_sim.normalize import KIND_QC, KIND_RESULT, Normalizer
from edge_sim.oru import (
    RESULT_TYPE_CALIBRATION,
    RESULT_TYPE_PATIENT,
    RESULT_TYPE_QC,
    parse_oru_r01,
)

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
H60S = FIXTURES_ROOT / "edan-h60s-oru-r01"
H60S_QC = FIXTURES_ROOT / "edan-h60s-oru-r01-qc"


# --- _result_type: the vendor-aware dispatch itself -------------------------


def test_result_type_edan_branches():
    """EDAN (KB §3.2.1): 0/empty=patient, 1=QC, any other value fails closed to QC
    (no calibration value exists for this vendor)."""
    from edge_sim.oru import _result_type  # noqa: PLC0415 - test-only introspection

    assert _result_type("", edan=True) == RESULT_TYPE_PATIENT
    assert _result_type("0", edan=True) == RESULT_TYPE_PATIENT
    assert _result_type("1", edan=True) == RESULT_TYPE_QC
    assert _result_type("2", edan=True) == RESULT_TYPE_QC  # bench-observed connection-test ping
    assert _result_type("3", edan=True) == RESULT_TYPE_QC  # bench-observed host-query
    assert _result_type("9", edan=True) == RESULT_TYPE_QC  # unrecognized -> fail closed


def test_result_type_non_edan_branch_unchanged():
    """The default (Seamaty SD1 / generic-HL7) branch is byte-for-byte unchanged:
    0/empty=patient, 1=calibration, 2=QC."""
    from edge_sim.oru import _result_type  # noqa: PLC0415 - test-only introspection

    assert _result_type("", edan=False) == RESULT_TYPE_PATIENT
    assert _result_type("1", edan=False) == RESULT_TYPE_CALIBRATION
    assert _result_type("2", edan=False) == RESULT_TYPE_QC


# --- EDAN QC OBR layout fixture: end to end ---------------------------------


def test_h60s_qc_fixture_parses_qc_layout_fields():
    """MSH-16=1 triggers both the QC result type and the PID-less QC OBR layout
    (KB §3.2.3): specimen id is the OBR-2 QC file No. (NOT any OBR-20 value —
    OBR-20 is the patient-layout barcode only), qc_type is the raw OBR-3 level
    digit, qc_lot_number is OBR-13, and there is no patient id at all."""
    report = parse_oru_r01(load_fixture(H60S_QC).message_bytes)
    fx_expected = load_fixture(H60S_QC).expected

    assert report.result_type == RESULT_TYPE_QC
    assert report.edan is True
    assert report.specimen_id == "1" == fx_expected["specimen_id"]
    assert report.qc_lot_number == "QC2026071" == fx_expected["qc_lot_number"]
    assert report.qc_type == "2" == fx_expected["qc_type"]
    assert report.barcode == ""
    assert report.patient_id == ""


def test_h60s_qc_fixture_normalizes_every_row_out_of_patient_stream():
    """Through the normalizer, every analyte row is re-kinded QC — nothing from
    this fixture is left in the patient (KIND_RESULT) stream."""
    fx = load_fixture(H60S_QC)
    report = parse_oru_r01(fx.message_bytes)
    rows = Normalizer.from_fixture(fx).normalize_report(report)

    assert len(rows) == len(fx.expected["results"]) == 4
    assert all(row.kind == KIND_QC for row in rows)
    assert not any(row.kind == KIND_RESULT for row in rows)
    for row, exp in zip(rows, fx.expected["results"]):
        assert row.raw_code == exp["raw_code"]
        assert row.value == exp["value"]
        assert row.loinc == exp["loinc"], row.raw_code
        assert row.ucum_value == exp["ucum_value"], row.raw_code
        assert row.status == exp["status"], row.raw_code


def test_h60s_qc_fixture_milestone_ingests_nothing():
    """End to end: the QC-mode upload is ACKed (it carries OBX rows) but nothing
    from it reaches the core ingest payload — it is QC, not a patient result, and
    (like every other EDAN upload) carries no OBX-11 Table-0085 finality either;
    ``ingest_payload`` admits only final ``KIND_RESULT`` rows."""
    out = run_milestone(load_fixture(H60S_QC).message_bytes)

    assert out.accepted is True
    assert out.report.result_type == RESULT_TYPE_QC
    assert out.ingest_payload() == []
    assert not any(o.kind == KIND_RESULT for o in out.observations)


# --- AC anchor: MSH-16=0 (existing H60S fixture) stays patient/KIND_RESULT --


def test_h60s_patient_fixture_msh16_0_stays_patient_and_kind_result():
    """The graduated (MSH-16=0) H60S patient fixture must not regress: it stays
    RESULT_TYPE_PATIENT and every analyte row stays KIND_RESULT."""
    report = parse_oru_r01(load_fixture(H60S).message_bytes)
    assert report.result_type == RESULT_TYPE_PATIENT
    assert report.edan is True

    rows = Normalizer().normalize_report(report)
    results = [r for r in rows if r.raw_code in {"WBC", "RBC", "HGB", "HCT", "MCV", "PLT"}]
    assert len(results) == 6
    assert all(r.kind == KIND_RESULT for r in results)


# --- AC branch: EDAN message with MSH-16 empty -> PATIENT -------------------


def test_edan_msh16_empty_is_patient():
    """A trailing-truncated EDAN MSH (MSH-16 absent, not just blank) must resolve
    the same as an explicit 0 -- patient, not a fail-closed QC hold."""
    msg = (
        "MSH|^~\\&|H90^^507|EDANLAB|||20260701||ORU^R01|10|P|2.4\r"
        "PID|6|H90-EMPTY-01|^0||DOE^JOHN||19900101|M\r"
        "OBR|1|H90-EMPTY-SPEC||EDANLAB^H90|||20260701\r"
        "OBX||NM|0|WBC|7.1|10\\S\\9/L|4.0-10.0|0|0|0||7.1^10\\S\\9/L"
    ).encode("utf-8")
    report = parse_oru_r01(msg)
    assert report.edan is True
    assert report.result_type == RESULT_TYPE_PATIENT
    rows = Normalizer().normalize_report(report)
    assert all(r.kind == KIND_RESULT for r in rows)


# --- deliberate bound: SD1/generic-HL7 QC gap is untouched (LIS-95) --------


def test_non_edan_sd1_qc_result_type_still_normalizes_as_kind_result():
    """Pin the deliberately-unfixed bound: a non-EDAN (SD1-shaped) HL7 report
    classified QC by MSH-16 still normalizes its rows as KIND_RESULT in the sim
    -- LIS-110 widens the QC re-kind gate for ASTM E1394 and EDAN HL7 only; the
    generic-HL7 (SD1) case is untouched here and remains tracked under LIS-95."""
    msg = (
        "MSH|^~\\&|SMT|SD1|||20201207144113||ORU^R01|1|P|2.3.1||||2||ASCII\r"
        "PID|1|SD1-0042|||DELA CRUZ^JUAN||1990|M\r"
        "OBR|1||SD1-SPEC-0007|SD1||||||||||SD1-LOT-2026A||||||QC-NORMAL\r"
        "OBX|1|NM|GLU|GLU|95|mg/dL|70-110|N|||F"
    ).encode("ascii")
    report = parse_oru_r01(msg)
    assert report.edan is False
    assert report.result_type == RESULT_TYPE_QC

    rows = Normalizer().normalize_report(report)
    assert all(r.kind == KIND_RESULT for r in rows)  # unchanged: LIS-95 gap, not LIS-110 scope
