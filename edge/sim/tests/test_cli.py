"""CLI smoke tests: list / validate / replay against the shipped fixtures."""

from edge_sim.cli import _replay_and_report, main
from edge_sim.fixtures import DEFAULT_FIXTURES_ROOT, load_fixture
from edge_sim.transport import Transport


class _CorruptingTransport(Transport):
    """Mutates the payload so the replay round-trip fails (exit-1 path)."""

    name = "corrupting"

    def send(self, payload: bytes) -> None:
        self._buf = payload + b"X"

    def receive(self) -> bytes:
        return self._buf


def test_validate_exit_zero(capsys):
    assert main(["validate"]) == 0
    assert "validated" in capsys.readouterr().out


def test_list_shows_example(capsys):
    assert main(["list"]) == 0
    assert "example-hl7v2-oru-r01" in capsys.readouterr().out


def test_replay_exit_zero(capsys):
    assert main(["replay", "example-hl7v2-oru-r01"]) == 0
    assert "OK" in capsys.readouterr().out


def test_replay_unknown_fixture_exit_two(capsys):
    assert main(["replay", "does-not-exist"]) == 2


def test_replay_mismatch_exit_one(capsys):
    fx = load_fixture(DEFAULT_FIXTURES_ROOT / "_example")
    assert _replay_and_report(fx, _CorruptingTransport()) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_bad_root_exit_two(capsys):
    assert main(["--root", "/no/such/dir", "list"]) == 2
    assert "error:" in capsys.readouterr().err


def test_replay_via_mllp_transport_exit_zero(capsys):
    assert main(["replay", "example-mllp-oru-r01", "--transport", "mllp"]) == 0
    out = capsys.readouterr().out
    assert "via mllp" in out
    assert "OK" in out


def test_list_shows_mllp_fixture(capsys):
    assert main(["list"]) == 0
    assert "example-mllp-oru-r01" in capsys.readouterr().out


def test_ack_prints_accept_ack(capsys):
    assert main(["ack", "example-mllp-oru-r01"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("MSH|")
    assert "ACK^R01" in out
    assert "MSA|AA|MSG00050" in out


def test_archive_exit_zero_prints_digest(capsys, tmp_path):
    assert main(["archive", "rayto-rac050-oru-r01", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "archived rayto-rac050-oru-r01 ->" in out
    assert len(list(tmp_path.rglob("*.msg"))) == 1


def test_roundtrip_exit_zero_matches_expected(capsys, tmp_path):
    assert main(["roundtrip", "rayto-rac050-oru-r01", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "bytes OK" in out
    assert "expected: OK" in out
    assert "LOINC 718-7" in out


def test_roundtrip_over_mllp_exit_zero(capsys, tmp_path):
    assert main(
        ["roundtrip", "rayto-rac050-oru-r01", "--transport", "mllp", "--dir", str(tmp_path)]
    ) == 0
    out = capsys.readouterr().out
    assert "via mllp" in out
    assert "expected: OK" in out


def test_milestone_edan_exit_zero(capsys):
    assert main(["milestone", "edan-h60s-oru-r01"]) == 0
    out = capsys.readouterr().out
    assert "ACCEPTED" in out
    assert "MSA-1=AA" in out
    assert "ACK^R01" in out
    assert "LOINC 6690-2" in out
    assert "(final)" in out
    assert "ingest contract (core ADR-0003): 6 observation(s)" in out


def test_milestone_unknown_fixture_exit_two(capsys):
    assert main(["milestone", "does-not-exist"]) == 2


def test_milestone_exit_one_when_not_all_final(tmp_path, capsys):
    """The CLI gate fails (exit 1) when an observation is not final — a non-final
    result must not pass the milestone as if it were a clean first result."""
    src = DEFAULT_FIXTURES_ROOT / "edan-h60s-oru-r01"
    dst = tmp_path / "edan-prelim"
    dst.mkdir()
    manifest = (src / "manifest.json").read_text().replace(
        '"id": "edan-h60s-oru-r01"', '"id": "edan-prelim"'
    )
    (dst / "manifest.json").write_text(manifest)
    msg = (src / "message.hl7").read_bytes()
    i = msg.rfind(b"|||F")  # flip the last OBX-11 (PLT) F -> P
    (dst / "message.hl7").write_bytes(msg[:i] + b"|||P" + msg[i + 4:])

    assert main(["--root", str(tmp_path), "milestone", "edan-prelim"]) == 1
    out = capsys.readouterr().out
    assert "(preliminary)" in out  # the non-final row is reported, not hidden


def test_query_exchange_exit_zero(capsys):
    assert main(["query", "edan-h60s-host-query-qry-r02"]) == 0
    out = capsys.readouterr().out
    assert "QRY^R02 id=Q0231-01" in out
    assert "ORF^R04 MSA-1=AA" in out
    assert "correlates=True" in out
    assert "LOINC 6690-2" in out


def test_query_unknown_fixture_exit_two(capsys):
    assert main(["query", "does-not-exist"]) == 2
