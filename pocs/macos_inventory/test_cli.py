import json
import runpy
from pathlib import Path

import pytest

from pocs.macos_inventory import cli, inventory
from pocs.macos_inventory.inventory import HostInventory, InventoryError

HOST = HostInventory("27.0.1", "synthetic", "com.apple.VoiceMemos", "4.0", "123")


@pytest.mark.parametrize("exists,exit_code", [(True, 0), (False, 1)])
def test_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exists: bool,
    exit_code: int,
) -> None:
    root = tmp_path / "private-root"
    if exists:
        root.mkdir()
        (root / "private-name.m4a").write_bytes(b"private-audio")
    monkeypatch.setattr(cli, "inspect_host", lambda: HOST)
    monkeypatch.setattr("sys.argv", ["inventory", "--source-root", str(root)])
    assert cli.main() == exit_code
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["source_directory"]["state"] == ("listable" if exists else "missing")
    assert result["acquisition_completeness"] == "UNKNOWN"
    assert result["materialization"] == "unknown"
    assert result["disposal_enabled"] is False
    assert "private" not in output.out
    assert output.err == ""


def test_host_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail() -> HostInventory:
        raise InventoryError("Host metadata could not be read")

    monkeypatch.setattr(cli, "inspect_host", fail)
    monkeypatch.setattr("sys.argv", ["inventory", "--source-root", "unused"])
    assert cli.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Host metadata could not be read\n"


def test_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(inventory, "inspect_host", lambda: HOST)
    monkeypatch.setattr("sys.argv", ["inventory", "--source-root", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(Path(__file__).with_name("cli.py")), run_name="__main__")
    assert error.value.code == 0
    assert json.loads(capsys.readouterr().out)["host"]["app_version"] == "4.0"
