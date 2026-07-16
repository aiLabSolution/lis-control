"""LIS-157 — protocol-neutral ASTM specimen grouping through public APIs."""

from edge_sim.replay import parse_analyzer_report
from edge_sim.normalize import KIND_CALIBRATION, KIND_QC, KIND_RESULT, Normalizer
from edge_sim.oru import RESULT_TYPE_CALIBRATION, RESULT_TYPE_PATIENT, RESULT_TYPE_QC


def test_astm_orders_keep_their_results_and_patient_identity_in_separate_groups():
    message = (
        "H|\\^&|||SNIBE^MAGLUMI-X3|||||||P|E1394-97|20260716120000\r"
        "P|1||PAT-A||DOE^JANE\r"
        "O|1|SPEC-A||^^^TSH|R\r"
        "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N|||||20260716115900\r"
        "P|2||PAT-B||DOE^JOHN\r"
        "O|2|SPEC-B||^^^FT4|R\r"
        "R|1|^^^FT4|14.8|pmol/L|12 to 22|N|||||20260716115930\r"
        "L|1|N\r"
    ).encode("ascii")

    report = parse_analyzer_report(message)

    assert [group.patient_id for group in report.groups] == ["PAT-A", "PAT-B"]
    assert [group.specimen_id for group in report.groups] == ["SPEC-A", "SPEC-B"]
    assert [[obs.raw_code for obs in group.observations] for group in report.groups] == [
        ["TSH"],
        ["FT4"],
    ]


def test_mixed_astm_batch_classifies_and_normalizes_each_order_independently():
    message = (
        "H|\\^&|||SNIBE^MAGLUMI-X3|||||||P|E1394-97|20260716120000\r"
        "P|1||PAT-A||DOE^JANE\r"
        "O|1|SPEC-A||^^^TSH|R\r"
        "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N|||||20260716115900\r"
        "P|2||CONTROL-A||CONTROL\r"
        "O|2|QC-0157||^^^FT4|R||||||Q\r"
        "R|1|^^^FT4|14.8|pmol/L|12 to 22|N|||||20260716115910\r"
        "P|3||CALIBRATOR-A||CALIBRATOR\r"
        "O|3|CAL-0157||^^^TSH|R\r"
        "R|1|^^^TSH|2.40|uIU/mL|0.27 to 4.20|N|||||20260716115920\r"
        "L|1|N\r"
    ).encode("ascii")

    report = parse_analyzer_report(message)
    normalized = Normalizer().normalize_report(report)

    assert [group.result_type for group in report.groups] == [
        RESULT_TYPE_PATIENT,
        RESULT_TYPE_QC,
        RESULT_TYPE_CALIBRATION,
    ]
    assert [row.kind for row in normalized] == [KIND_RESULT, KIND_QC, KIND_CALIBRATION]


def test_idless_astm_order_mints_bridge_compatible_accession():
    message = (
        "H|\\^&|||SNIBE^MAGLUMI-X3|||||||P|E1394-97|20260716120000\r"
        "P|1||PAT / ASTM||DOE^JANE\r"
        "O|1|||^^^TSH|R\r"
        "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N|||||20260716115900\r"
        "L|1|N\r"
    ).encode("ascii")

    group = parse_analyzer_report(message).groups[0]

    # Bridge ASTM mint inputs are the raw H record, patient id/name, this O+R
    # group's raw records, and the O-record group index, each followed by byte
    # 0x1e.
    assert group.specimen_id == "PATASTM-a785026786"
    assert group.patient_id == "PAT / ASTM"


def test_idless_astm_orders_mint_distinct_accessions_deterministically():
    message = (
        "H|\\^&|||SNIBE^MAGLUMI-X3|||||||P|E1394-97|20260716120000\r"
        "P|1||PAT-ASTM\r"
        "O|1|||^^^TSH|R\r"
        "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N\r"
        "O|2|||^^^TSH|R\r"
        "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N\r"
        "L|1|N\r"
    ).encode("ascii")

    accessions = [group.specimen_id for group in parse_analyzer_report(message).groups]
    replayed = [group.specimen_id for group in parse_analyzer_report(message).groups]

    assert accessions == replayed
    assert accessions[0] != accessions[1]


def test_astm_mint_hashes_patient_identity_even_when_sanitized_prefixes_match():
    def accession(patient_id: str, patient_name: str) -> str:
        message = (
            "H|\\^&|||SNIBE^MAGLUMI-X3|||||||P|E1394-97|20260716120000\r"
            f"P|1||{patient_id}||{patient_name}\r"
            "O|1|||^^^TSH|R\r"
            "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N\r"
            "L|1|N\r"
        ).encode("ascii")
        return parse_analyzer_report(message).groups[0].specimen_id

    baseline = accession("PAT/A", "DOE^JANE")

    assert baseline.startswith("PATA-")
    assert accession("PAT A", "DOE^JANE") != baseline
    assert accession("PAT/A", "DOE^JOHN") != baseline


def test_astm_patient_id_precedence_matches_bridge_p3_then_p4_then_p5():
    def group(patient_record: str):
        message = (
            "H|\\^&|||SNIBE^MAGLUMI-X3|||||||P|E1394-97|20260716120000\r"
            f"{patient_record}\r"
            "O|1|||^^^TSH|R\r"
            "R|1|^^^TSH|2.31|uIU/mL|0.27 to 4.20|N\r"
            "L|1|N\r"
        ).encode("ascii")
        return parse_analyzer_report(message).groups[0]

    all_ids = group("P|1|PRACTICE-ID|LAB-ID|ALT-ID|DOE^JANE")
    p5_only = group("P|1|||ALT-ID|DOE^JANE")

    assert all_ids.patient_id == "PRACTICE-ID"
    assert all_ids.specimen_id == "PRACTICE-ID-6c998eef15"
    assert p5_only.patient_id == "ALT-ID"
    assert p5_only.specimen_id == "ALT-ID-dad311ed02"
