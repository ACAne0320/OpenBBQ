from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from openbbq.cli import main
from openbbq.core import skill as skilllib


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


def _installed_files(path: Path) -> list[Path]:
    return [p for p in path.rglob("*") if p.is_file()]


def test_skill_install_copies_files_to_target_and_reports_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "install", "--target", str(tmp_path)],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    installed = tmp_path / skilllib.SKILL_NAME
    assert code == 0
    assert data["ok"] is True
    assert data["path"] == str(installed)
    assert data["files"] == len(_installed_files(installed))
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == (
        skilllib.packaged_skill_content()
    )


def test_skill_install_refuses_existing_install_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first_code, _stdout, _stderr = _run_cli(
        ["--json", "skill", "install", "--target", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    assert first_code == 0

    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "install", "--target", str(tmp_path)],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    assert code == 1
    assert data == {
        "error": "skill_exists",
        "path": str(tmp_path / skilllib.SKILL_NAME),
        "fix": "openbbq skill install --force",
    }


def test_skill_install_force_overwrites_existing_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first_code, _stdout, _stderr = _run_cli(
        ["--json", "skill", "install", "--target", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    assert first_code == 0
    installed = tmp_path / skilllib.SKILL_NAME
    (installed / "SKILL.md").write_text("stale\n", encoding="utf-8")

    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "install", "--target", str(tmp_path), "--force"],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    assert code == 0
    assert data["path"] == str(installed)
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == (
        skilllib.packaged_skill_content()
    )


def test_skill_show_returns_packaged_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "show"], monkeypatch, capsys
    )

    data = _single_json(stdout)
    assert code == 0
    assert data["path"].endswith("skills/openbbq-subtitles/SKILL.md")
    assert data["content"] == skilllib.packaged_skill_content()
