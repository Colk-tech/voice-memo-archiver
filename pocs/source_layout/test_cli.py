import json
import runpy
from pathlib import Path

import pytest

from pocs.source_layout import cli


def test_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "private.m4a").touch()
    monkeypatch.setattr("sys.argv", ["layout", "--source-root", str(tmp_path)])
    assert cli.main() == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["counts"]["audio_candidate"] == 1
    assert result["acquisition_completeness"] == "UNKNOWN"
    assert result["snapshot_consistency"] == result["materialization"] == "unknown"
    assert result["disposal_enabled"] is False
    assert "private" not in output.out
    assert str(tmp_path) not in output.out
    assert not output.err


def test_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["layout", "--source-root", str(tmp_path), "--entry-limit", "0"]
    )
    assert cli.main() == 1
    output = capsys.readouterr()
    assert not output.out
    assert output.err == "Invalid traversal bounds\n"


def test_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["layout", "--source-root", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(Path(__file__).with_name("cli.py")), run_name="__main__")
    assert error.value.code == 0
    assert json.loads(capsys.readouterr().out)["probe_version"] == 1
