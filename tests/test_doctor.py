from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openbbq.cli.commands.doctor import DoctorResult
from openbbq.core import doctor
from openbbq.core import skill as skilllib


def test_ffmpeg_missing_hint_uses_platform_package_manager(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    assert doctor._ffmpeg().fix == "brew install ffmpeg"

    monkeypatch.setattr(doctor.sys, "platform", "linux")
    linux_fix = doctor._ffmpeg().fix or ""
    assert "apt install ffmpeg" in linux_fix
    assert "distro" in linux_fix

    monkeypatch.setattr(doctor.sys, "platform", "win32")
    win_fix = doctor._ffmpeg().fix or ""
    assert "winget install" in win_fix
    assert "choco install ffmpeg" in win_fix


def test_external_dependency_hints_are_platform_specific(monkeypatch) -> None:
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor, "_HOMEBREW_FFMPEG_FULL", ())

    subtitle_fix = doctor._ffmpeg_subtitle_filters().fix or ""
    ytdlp_fix = doctor._yt_dlp().fix or ""

    assert "apt install ffmpeg" in subtitle_fix
    assert "libass" in subtitle_fix
    assert "apt install yt-dlp" in ytdlp_fix
    assert "distro" in ytdlp_fix


def test_ffmpeg_filter_names_reads_filter_name_column(monkeypatch) -> None:
    proc = SimpleNamespace(
        returncode=0,
        stdout=(
            " .. ass               V->V       Render ASS subtitles\n"
            " .. subtitles         V->V       Render text subtitles\n"
        ),
    )
    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: proc)

    assert doctor._ffmpeg_filter_names("/fake/ffmpeg") == {"ass", "subtitles"}


def test_ffmpeg_subtitle_filters_accepts_ffmpeg_full_fallback(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(
        doctor,
        "_HOMEBREW_FFMPEG_FULL",
        (Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),),
    )
    monkeypatch.setattr(Path, "exists", lambda self: True)

    def fake_filters(executable):
        if "ffmpeg-full" in str(executable):
            return {"ass", "subtitles"}
        return {"scale"}

    monkeypatch.setattr(doctor, "_ffmpeg_filter_names", fake_filters)

    check = doctor._ffmpeg_subtitle_filters()

    assert check.ok is True
    assert "ffmpeg-full" in check.detail


def test_ffmpeg_subtitle_filters_reports_missing_libass(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/opt/homebrew/bin/ffmpeg")
    monkeypatch.setattr(doctor, "_HOMEBREW_FFMPEG_FULL", ())
    monkeypatch.setattr(doctor, "_ffmpeg_filter_names", lambda executable: {"scale"})

    check = doctor._ffmpeg_subtitle_filters()

    assert check.ok is False
    assert "missing ass, subtitles" in check.detail
    assert check.fix is not None


def test_agent_skill_check_reports_missing_without_failing_doctor(tmp_path) -> None:
    check = doctor._agent_skill(tmp_path)

    assert check.name == "agent skill"
    assert check.ok is False
    assert check.required is False
    assert "missing" in check.detail
    assert check.fix == "openbbq skill install"
    assert DoctorResult.of([check]).healthy is True


def test_agent_skill_check_reports_ok(tmp_path) -> None:
    install = skilllib.install(tmp_path)

    check = doctor._agent_skill(tmp_path)

    assert check.ok is True
    assert check.detail == str(install.path / "SKILL.md")
    assert check.fix is None


def test_agent_skill_check_reports_any_supported_agent_install_ok(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    install = skilllib.install_for_agent(skilllib.SkillAgent.CODEX)[0]

    check = doctor._agent_skill()

    assert check.ok is True
    assert "codex:" in check.detail
    assert str(install.path / "SKILL.md") in check.detail
    assert check.fix is None


def test_agent_skill_check_reports_all_supported_targets_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    check = doctor._agent_skill()

    assert check.ok is False
    assert ".claude" in check.detail
    assert ".codex" in check.detail
    assert ".agents" in check.detail
    assert ".copilot" not in check.detail
    assert check.fix == "openbbq skill install"


def test_agent_skill_check_reports_outdated(tmp_path) -> None:
    install = skilllib.install(tmp_path)
    (install.path / "SKILL.md").write_text("stale\n", encoding="utf-8")

    check = doctor._agent_skill(tmp_path)

    assert check.ok is False
    assert check.required is False
    assert "outdated" in check.detail
    assert check.fix == "openbbq skill install --force"
    assert DoctorResult.of([check]).healthy is True
