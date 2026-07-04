from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openbbq.core import doctor


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
