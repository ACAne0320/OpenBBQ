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


def test_skill_install_defaults_to_shared_agents_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "install"],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    installed = tmp_path / ".agents" / "skills" / skilllib.SKILL_NAME
    assert code == 0
    assert data["path"] == str(installed)
    assert data["language"] == "en"
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == (
        skilllib.packaged_skill_content()
    )
    assert not (installed / "SKILL.zh-CN.md").exists()
    assert (installed / "references" / "glossary.md").is_file()
    assert (installed / "references" / "workflows.md").is_file()
    assert not (installed / "references" / "glossary.zh-CN.md").exists()
    assert not (installed / "references" / "workflows.zh-CN.md").exists()
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".codex").exists()


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
    assert data["language"] == "en"
    assert data["files"] == len(_installed_files(installed))
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == (
        skilllib.packaged_skill_content()
    )
    assert not (installed / "SKILL.zh-CN.md").exists()
    assert (installed / "references" / "glossary.md").is_file()
    assert (installed / "references" / "workflows.md").is_file()
    assert not (installed / "references" / "glossary.zh-CN.md").exists()
    assert not (installed / "references" / "workflows.zh-CN.md").exists()


def test_skill_install_can_choose_bilibili_cover_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(
        [
            "--json",
            "skill",
            "install",
            "--target",
            str(tmp_path),
            "--name",
            "bilibili-cover-safe-area",
        ],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    name = skilllib.SkillName.BILIBILI_COVER_SAFE_AREA
    installed = tmp_path / name.value
    assert code == 0
    assert data["path"] == str(installed)
    assert data["language"] == "en"
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == (
        skilllib.packaged_skill_content(name=name)
    )
    assert not (installed / "SKILL.zh-CN.md").exists()
    assert not (installed / "scripts").exists()


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


def test_skill_install_agent_codex_uses_codex_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "install", "--agent", "codex"],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    installed = tmp_path / ".codex" / "skills" / skilllib.SKILL_NAME
    assert code == 0
    assert data["path"] == str(installed)
    assert data["language"] == "en"
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == (
        skilllib.packaged_skill_content()
    )


def test_skill_install_agent_all_installs_supported_targets_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "install", "--agent", "all"],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    expected = {
        tmp_path / ".claude" / "skills" / skilllib.SKILL_NAME,
        tmp_path / ".codex" / "skills" / skilllib.SKILL_NAME,
        tmp_path / ".agents" / "skills" / skilllib.SKILL_NAME,
    }
    installed = {Path(item["path"]) for item in data["installs"]}
    languages = {item["language"] for item in data["installs"]}
    assert code == 0
    assert installed == expected
    assert languages == {"en"}
    assert not (tmp_path / ".copilot").exists()


def test_skill_install_target_cannot_be_combined_with_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(
        [
            "--json",
            "skill",
            "install",
            "--agent",
            "codex",
            "--target",
            str(tmp_path),
        ],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    assert code == 1
    assert data == {
        "error": "invalid_skill_options",
        "fix": "use either --agent or --target, not both",
    }


def test_skill_show_returns_packaged_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(["--json", "skill", "show"], monkeypatch, capsys)

    data = _single_json(stdout)
    assert code == 0
    assert data["path"].endswith("skills/openbbq-subtitles/SKILL.md")
    assert data["content"] == skilllib.packaged_skill_content()


def test_skill_show_can_return_chinese_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "show", "--language", "zh-CN"], monkeypatch, capsys
    )

    data = _single_json(stdout)
    assert code == 0
    assert data["path"].endswith("skills/openbbq-subtitles/SKILL.zh-CN.md")
    assert data["content"] == skilllib.packaged_skill_content(
        skilllib.SkillLanguage.ZH_CN
    )


def test_skill_show_can_choose_bilibili_cover_skill(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, _stderr = _run_cli(
        ["--json", "skill", "show", "--name", "bilibili-cover-safe-area"],
        monkeypatch,
        capsys,
    )

    data = _single_json(stdout)
    name = skilllib.SkillName.BILIBILI_COVER_SAFE_AREA
    assert code == 0
    assert data["path"].endswith("skills/bilibili-cover-safe-area/SKILL.md")
    assert data["content"] == skilllib.packaged_skill_content(name=name)


def test_subtitle_skill_documents_draft_happy_path_in_both_languages() -> None:
    chinese = skilllib.packaged_skill_content(skilllib.SkillLanguage.ZH_CN)
    english = skilllib.packaged_skill_content()

    for content in (chinese, english):
        assert "agent init" in content
        assert "agent next" in content
        assert "agent apply" in content
        assert "agent finish" in content
        assert "`translate`" in content
        assert "review_source" in content
        assert "structural" in content or "结构性" in content
        assert "`quality`" in content
        assert "`human_reviewed`" in content
        assert "openbbq review --workspace" in content
        assert "Aegisub" in content
        assert "fansub-compact" in content
        assert "glossary audit" not in content
        assert "qa render" not in content
        assert "outside_required" in content
        assert "must_continue" in content
        assert "cpu_fallback" in content
        assert "reference_evidence" in content
        assert "search the web" in content or "自行联网" in content
        assert "smallest stable" in content or "最小稳定" in content
        assert "generation_policy" in content
        assert "generation_mode" in content
        assert "external translation" in content or "外部翻译" in content
        assert "process/session ID" in content
        assert "empty stdout" in content or "空 stdout" in content


def test_subtitle_skill_keeps_finish_single_pass_and_translation_id_contract() -> None:
    for content in (
        skilllib.packaged_skill_content(skilllib.SkillLanguage.ZH_CN),
        skilllib.packaged_skill_content(),
    ):
        assert "selected_id" in content
        assert "batch_id" in content
        assert "policy_hash" in content
        assert "response_schema" in content
        assert "once" in content or "一次" in content
