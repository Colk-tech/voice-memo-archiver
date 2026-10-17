import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from voice_memo_archiver.bootstrap.probe import main


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
