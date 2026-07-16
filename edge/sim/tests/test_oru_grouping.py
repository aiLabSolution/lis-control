"""LIS-157 — ADR-0018 specimen grouping and accession identity mirror."""

from pathlib import Path

from edge_sim.fixtures import load_fixture
from edge_sim.normalize import KIND_BLANK, KIND_RESULT, Normalizer
from edge_sim.oru import parse_oru_r01


FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MULTI_OBR = FIXTURES_ROOT / "rayto-rac050-multi-obr-oru-r01"


def test_multi_obr_fixture_keeps_each_obx_with_its_specimen():
    fixture = load_fixture(MULTI_OBR)

    report = parse_oru_r01(fixture.message_bytes)
    expected = fixture.expected["groups"]

    assert report.message_type == fixture.expected["message_type"]
    assert report.patient_id == fixture.expected["patient_id"]
    assert [group.specimen_id for group in report.groups] == [
        group["specimen_id"] for group in expected
    ]
    assert [[obs.raw_code for obs in group.observations] for group in report.groups] == [
        group["raw_codes"] for group in expected
    ]
    assert report.specimen_id == expected[0]["specimen_id"]
    assert [obs.raw_code for obs in report.observations] == ["GLU", "NA", "HGB"]


def test_idless_hl7_group_mints_bridge_compatible_accession_beside_patient_identity():
    message = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260716120000||ORU^R01|LIS157-MINT|P|2.3\r"
        "PID|1||PAT / 0157||DOE^JANE\r"
        "OBR|1|||CHEM^Chemistry^99RAC\r"
        "OBX|1|NM|GLU^Glucose^99RAC||98|mg/dL|70-110|N|||F\r"
    ).encode("ascii")

    group = parse_oru_r01(message).groups[0]

    # Bridge AccessionMinter anchor: SHA-256 over analyzer identity, MSH-7,
    # MSH-10, raw OBR+OBX records, and group index; each part ends in 0x1e.
    assert group.specimen_id == "PAT0157-5134815b45"
    assert group.patient_id == "PAT / 0157"
    assert len(group.specimen_id) <= 25


def test_normalization_applies_result_type_to_each_specimen_group():
    message = (
        "MSH|^~\\&|H90^^507|EDANLAB|||20260703135352||ORU^R01|5|P|2.4||||0||UTF8\r"
        "PID|3|PAT-157|^0\r"
        "OBR||SPEC-BLANK||EDANLAB^H90|||20260703125023||||||||^^Blank sample||\r"
        "OBX||NM|0|WBC|5.0|10\\S\\9/L|4.00-20.00|0|0|0||5.0^10\\S\\9/L\r"
        "OBR||SPEC-PATIENT||EDANLAB^H90|||20260703125500\r"
        "OBX||NM|0|HGB|113|g/L|110-160|0|0|0||112.65^g/L\r"
    ).encode("ascii")

    normalized = Normalizer().normalize_report(parse_oru_r01(message))

    assert [row.kind for row in normalized] == [KIND_BLANK, KIND_RESULT]


def test_standard_hl7_uses_obr2_placer_before_minting_an_accession():
    message = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260716120000||ORU^R01|LIS157-OBR2|P|2.3\r"
        "PID|1||PID-0157\r"
        "OBR|1|PLACER-0157||CHEM\r"
        "OBX|1|NM|GLU||98|mg/dL\r"
    ).encode("ascii")

    group = parse_oru_r01(message).groups[0]

    assert group.specimen_id == "PLACER-0157"


def test_hl7_mint_sanitizes_raw_patient_component_but_keeps_unescaped_identity():
    message = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260716120000||ORU^R01|LIS157-ESC|P|2.3\r"
        "PID|1||PAT\\F\\0157\r"
        "OBR|1|||CHEM\r"
        "OBX|1|NM|GLU||98|mg/dL\r"
    ).encode("ascii")

    group = parse_oru_r01(message).groups[0]

    assert group.specimen_id == "PATF0157-616589d3b4"
    assert group.patient_id == "PAT|0157"


def test_idless_hl7_groups_mint_distinct_capped_accessions_deterministically():
    message = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260716120000||ORU^R01|LIS157-TWO|P|2.3\r"
        "PID|1||PATIENT-IDENTIFIER-OVER-25\r"
        "OBR|1|||CHEM\r"
        "OBX|1|NM|GLU||98|mg/dL\r"
        "OBR|2|||CHEM\r"
        "OBX|1|NM|GLU||98|mg/dL\r"
    ).encode("ascii")

    accessions = [group.specimen_id for group in parse_oru_r01(message).groups]
    replayed = [group.specimen_id for group in parse_oru_r01(message).groups]

    assert accessions == replayed
    assert accessions[0] != accessions[1]
    assert all(len(accession) == 25 for accession in accessions)
    assert all(accession.startswith("PATIENT-IDENTI-") for accession in accessions)


def test_idless_hl7_group_without_patient_uses_protocol_prefix():
    message = (
        "MSH|^~\\&|RAC-050|RAYTO|LIS|LAB|20260716120000||ORU^R01|LIS157-NOPID|P|2.3\r"
        "OBR|1|||CHEM\r"
        "OBX|1|NM|GLU||98|mg/dL\r"
    ).encode("ascii")

    group = parse_oru_r01(message).groups[0]

    assert group.patient_id == ""
    assert group.specimen_id.startswith("HL7-")
    assert len(group.specimen_id) == 14
