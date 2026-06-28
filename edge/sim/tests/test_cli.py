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
