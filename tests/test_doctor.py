from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from openbbq import __version__
from openbbq.cli.commands.doctor import DoctorResult
from openbbq.core import doctor
from openbbq.core import skill as skilllib
from openbbq.core.asr import ASRBackend, ModelInfo


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
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(doctor, "_HOMEBREW_FFMPEG_FULL", ())

    subtitle_fix = doctor._ffmpeg_subtitle_filters().fix or ""
    ytdlp_fix = doctor._yt_dlp().fix or ""

    assert "apt install ffmpeg" in subtitle_fix
    assert "libass" in subtitle_fix
    assert "apt install yt-dlp" in ytdlp_fix
    assert "distro" in ytdlp_fix


def test_yt_dlp_accepts_the_bundled_module_fetch_falls_back_to(monkeypatch) -> None:
    # `uv tool install openbbq` installs yt-dlp as a dependency without putting it on PATH.
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    check = doctor._yt_dlp()

    assert check.ok is True
    assert check.detail.endswith("-m yt_dlp")


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
    assert check.required is True
    assert "outdated" in check.detail
    assert check.fix == "openbbq skill install --force"
    assert DoctorResult.of([check]).healthy is False


def test_doctor_result_exposes_runtime_version_and_executable() -> None:
    result = DoctorResult.of([])

    assert result.version == __version__
    assert result.executable


def test_asr_backend_reports_missing_default_vad_model() -> None:
    class Backend:
        name = "test-asr"
        install_hint = "install test-asr"

        def is_available(self) -> bool:
            return True

        def cached_models(self) -> list[str]:
            return ["base"]

        def version(self) -> str:
            return "1.0"

        def accelerator(self) -> str:
            return "CPU"

        def available_vad_models(self) -> list[ModelInfo]:
            return [ModelInfo("silero-v6.2.0", "test-vad", 1.0)]

        def default_vad_model(self) -> str:
            return "silero-v6.2.0"

        def has_vad_model(self, name: str) -> bool:
            return False

        def resolve_vad_model(self, name: str) -> Path:
            return Path("/missing")

        def pull_vad_model(self, name: str, on_progress=None) -> Path:
            raise AssertionError("doctor must be read-only")

    checks = doctor._asr_backend(cast(ASRBackend, Backend()))

    vad = next(check for check in checks if check.name == "test-asr VAD")
    assert vad.ok is False
    assert vad.detail == "silero-v6.2.0 not cached"
    assert vad.fix == "openbbq models pull-vad silero-v6.2.0"
