from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from openbbq import __version__
import openbbq.cli.commands.doctor as doctor_command
from openbbq.cli import main


def _run_cli(
    args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["openbbq", *args])
    with pytest.raises(SystemExit) as raised:
        main()
    code = raised.value.code
    assert isinstance(code, int)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _single_json(stdout: str) -> dict[str, Any]:
    assert stdout.endswith("\n")
    line = stdout.removesuffix("\n")
    assert "\n" not in line
    data = json.loads(line)
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize("args", [[], ["translate"]])
def test_no_args_non_tty_emits_single_usage_json(
    args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(args, monkeypatch, capsys)

    data = _single_json(stdout)
    assert code == 2
    assert data["error"] == "usage"
    assert "Usage:" not in stdout
    assert "Commands" not in stdout


@pytest.mark.parametrize("args", [["--json", "doctor"], ["doctor", "--json"]])
def test_json_doctor_flag_position_is_independent(
    args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(doctor_command.core, "run_checks", lambda: [])

    code, stdout, _stderr = _run_cli(args, monkeypatch, capsys)

    data = _single_json(stdout)
    assert code == 0
    assert data["ok"] is True
    assert data["healthy"] is True
    assert data["checks"] == []


@pytest.mark.parametrize("args", [["--version"], ["--json", "--version"]])
def test_version_emits_machine_readable_package_version(
    args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, stderr = _run_cli(args, monkeypatch, capsys)

    assert code == 0
    assert stderr == ""
    assert _single_json(stdout) == {"ok": True, "version": __version__}


def test_domain_error_emits_single_json_object(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    code, stdout, _stderr = _run_cli(["--json", "status"], monkeypatch, capsys)

    data = _single_json(stdout)
    assert code == 1
    assert data["error"] == "no_workspace"


def test_unexpected_exception_emits_internal_json_and_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom() -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor_command.core, "run_checks", boom)

    code, stdout, stderr = _run_cli(["--json", "doctor"], monkeypatch, capsys)

    data = _single_json(stdout)
    assert code == 1
    assert data == {"error": "internal", "message": "boom"}
    assert "Traceback" in stderr
