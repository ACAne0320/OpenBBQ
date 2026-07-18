from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer

from openbbq.cli.commands.burn import burn
from openbbq.cli.output import Output
from openbbq.core import media
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import Manifest, Source, Stage, StageState, StageStatus


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _workspace(tmp_path: Path) -> tuple[Path, Manifest]:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_video", ref=str(source)),
        stages={},
    )
    ws.write_manifest(path, manifest)
    return path, manifest


def _with_export(
    path: Path,
    manifest: Manifest,
    artifact: str = "out/zh.ass",
    *,
    inputs: list[Path] | None = None,
) -> Path:
    sub = path / artifact
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text("[Script Info]\n")
    manifest.stages[Stage.EXPORT] = StageState(
        status=StageStatus.DONE,
        artifact=artifact,
        updated_at=datetime.now(timezone.utc),
    )
    ws.write_manifest(path, manifest)
    ws.record_artifact_provenance(
        path,
        sub,
        Stage.EXPORT,
        inputs=[] if inputs is None else inputs,
    )
    return sub


def _patch_burn(monkeypatch: pytest.MonkeyPatch, calls: dict[str, object]) -> None:
    def fake_burn(
        src: Path,
        subtitle: Path,
        dst: Path,
        *,
        ffmpeg: str | None = None,
        on_progress=None,
    ) -> media.BurnOutcome:
        calls["src"] = src
        calls["subtitle"] = subtitle
        calls["dst"] = dst
        calls["ffmpeg"] = ffmpeg
        if on_progress is not None:
            on_progress(media.BurnProgress(done=500, total=1000))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"mp4")
        return media.BurnOutcome(duration_s=1.0, ffmpeg="/fake/ffmpeg")

    monkeypatch.setattr(media, "burn_subtitles", fake_burn)


def test_burn_uses_last_ass_export_and_records_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, manifest = _workspace(tmp_path)
    sub = _with_export(path, manifest)
    calls: dict[str, object] = {}
    _patch_burn(monkeypatch, calls)

    burn(_ctx(), workspace=str(path))

    assert calls["subtitle"] == sub
    assert calls["dst"] == path / "out" / "zh-burned.mp4"
    final = ws.read_manifest(path).stages[Stage.BURN]
    assert final.status is StageStatus.DONE
    assert final.artifact == "out/zh-burned.mp4"
    ws.require_fresh_artifact(path, path / final.artifact, Stage.BURN)
    assert "openbbq --json status --workspace" in capsys.readouterr().err


@pytest.mark.parametrize("changed", ["video", "source", "subtitle"])
def test_burn_provenance_detects_changed_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    path, manifest = _workspace(tmp_path)
    sub = _with_export(path, manifest)
    calls: dict[str, object] = {}
    _patch_burn(monkeypatch, calls)
    burn(_ctx(), workspace=str(path))
    video = path / "out" / "zh-burned.mp4"
    source = Path(manifest.source.ref)
    {"video": video, "source": source, "subtitle": sub}[changed].write_bytes(
        b"changed"
    )

    with pytest.raises(OpenBBQError) as exc:
        ws.require_fresh_artifact(path, video, Stage.BURN)

    assert exc.value.code == "stale_artifact"


def test_burn_accepts_output_and_ffmpeg_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    _with_export(path, manifest)
    calls: dict[str, object] = {}
    _patch_burn(monkeypatch, calls)

    burn(_ctx(), workspace=str(path), output="render/final.mp4", ffmpeg="/opt/ffmpeg")

    assert calls["dst"] == path / "render" / "final.mp4"
    assert calls["ffmpeg"] == "/opt/ffmpeg"
    assert ws.read_manifest(path).stages[Stage.BURN].artifact == "render/final.mp4"


def test_burn_requires_export_artifact(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path)

    with pytest.raises(OpenBBQError) as exc:
        burn(_ctx(), workspace=str(path))

    assert exc.value.code == "missing_input"
    assert exc.value.context["stage"] == "export"


def test_burn_rejects_non_ass_export(tmp_path: Path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_export(path, manifest, "out/zh.srt")

    with pytest.raises(OpenBBQError) as exc:
        burn(_ctx(), workspace=str(path))

    assert exc.value.code == "unsupported_subtitle_format"
    assert exc.value.fix == "openbbq export --format ass"


def test_burn_rejects_modified_export_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    sub = _with_export(path, manifest)
    sub.write_text("[Script Info]\n; manually changed\n")
    calls: dict[str, object] = {}
    _patch_burn(monkeypatch, calls)

    with pytest.raises(OpenBBQError) as exc:
        burn(_ctx(), workspace=str(path))

    assert exc.value.code == "stale_artifact"
    assert calls == {}


def test_burn_rejects_untracked_workspace_subtitle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = _workspace(tmp_path)
    manual = path / "manual.ass"
    manual.write_text("[Script Info]\n")
    calls: dict[str, object] = {}
    _patch_burn(monkeypatch, calls)

    with pytest.raises(OpenBBQError) as exc:
        burn(_ctx(), workspace=str(path), subtitle="manual.ass")

    assert exc.value.code == "artifact_unverified"
    assert calls == {}


def test_burn_allows_explicit_stale_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = _workspace(tmp_path)
    manual = path / "manual.ass"
    manual.write_text("[Script Info]\n")
    calls: dict[str, object] = {}
    _patch_burn(monkeypatch, calls)

    burn(
        _ctx(),
        workspace=str(path),
        subtitle="manual.ass",
        allow_stale=True,
    )

    assert calls["subtitle"] == manual


def test_burn_allows_explicit_external_subtitle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = _workspace(tmp_path)
    external = tmp_path / "external.ass"
    external.write_text("[Script Info]\n")
    calls: dict[str, object] = {}
    _patch_burn(monkeypatch, calls)

    burn(_ctx(), workspace=str(path), subtitle=str(external))

    assert calls["subtitle"] == external


def test_burn_records_failed_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    _with_export(path, manifest)

    def fail(*args, **kwargs):
        raise OpenBBQError("ffmpeg_failed", detail="nope")

    monkeypatch.setattr(media, "burn_subtitles", fail)

    with pytest.raises(OpenBBQError):
        burn(_ctx(), workspace=str(path))

    failed = ws.read_manifest(path).stages[Stage.BURN]
    assert failed.status is StageStatus.FAILED
    assert failed.error == "ffmpeg_failed"


def test_parse_progress_time_uses_milliseconds() -> None:
    assert media._parse_progress_time("out_time=00:00:01.250000", 10.0) == 1250
    assert media._parse_progress_time("out_time_us=2500000", 10.0) == 2500
    assert media._parse_progress_time("out_time_us=2500000", 1.0) == 1000


def test_has_ass_filter_reads_ffmpeg_filter_name_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = SimpleNamespace(
        returncode=0,
        stdout=" .. null              V->V       Pass the source unchanged\n"
        " .. ass               V->V       Render ASS subtitles\n",
    )
    monkeypatch.setattr(media.subprocess, "run", lambda *args, **kwargs: proc)

    assert media._has_ass_filter(Path("/fake/ffmpeg")) is True
