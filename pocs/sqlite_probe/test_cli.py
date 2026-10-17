import json
import runpy
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from pocs.sqlite_probe.cli import main


def test_cli_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "private.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE private_title (id TEXT)")
    monkeypatch.setattr("sys.argv", ["probe", "--database", str(path)])
    assert main() == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["acquisition_completeness"] == "UNKNOWN"
    assert result["disposal_enabled"] is False
    assert result["schema_objects"] == 1
    assert len(result["schema_sha256"]) == 64
    assert "private" not in output.out
    assert output.err == ""


def test_cli_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["probe", "--database", str(tmp_path / "secret")])
    assert main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "SQLite probe failed\n"


def test_module_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "source.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE recording (id TEXT)")
    monkeypatch.setattr("sys.argv", ["probe", "--database", str(path)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(Path(__file__).with_name("cli.py")), run_name="__main__")
    assert exit_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["schema_objects"] == 1


@pytest.mark.parametrize("case", ["valid", "missing", "no_arguments"])
def test_documented_module_command(tmp_path: Path, case: str) -> None:
    path = tmp_path / "private.sqlite"
    command = [sys.executable, "-m", "pocs.sqlite_probe.cli"]
    if case == "valid":
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE recording (id TEXT)")
    if case != "no_arguments":
        command.extend(["--database", str(path)])
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if case == "valid":
        assert result.returncode == 0
        assert json.loads(result.stdout)["acquisition_completeness"] == "UNKNOWN"
        assert result.stderr == ""
    else:
        assert result.returncode == (1 if case == "missing" else 2)
        assert result.stdout == ""
        assert str(path) not in result.stderr
