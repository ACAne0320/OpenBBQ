from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import Progress, Manifest, Source, Stage, StageState, StageStatus


def _manifest(title: str) -> Manifest:
    return Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref="/tmp/source.wav", title=title),
        stages={},
    )


def _workspace(path: Path, title: str = "workspace") -> Manifest:
    path.mkdir(parents=True)
    manifest = _manifest(title)
    ws.write_manifest(path, manifest)
    return manifest


def test_write_manifest_uses_unique_temp_files_for_concurrent_writes(tmp_path) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()

    def write(i: int) -> None:
        ws.write_manifest(wsdir, _manifest(f"title-{i}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(50)))

    manifest = ws.read_manifest(wsdir)
    assert manifest.source.title is not None
    assert not list(wsdir.glob(".manifest.json.*.tmp"))


def test_write_text_atomic_writes_utf8_bytes(tmp_path) -> None:
    path = tmp_path / "artifact.txt"

    ws.write_text_atomic(path, "字幕：你好\n")

    assert path.read_bytes() == "字幕：你好\n".encode("utf-8")


def test_write_text_atomic_replaces_existing_file(tmp_path) -> None:
    path = tmp_path / "artifact.txt"
    path.write_bytes(b"old")

    ws.write_text_atomic(path, "new")

    assert path.read_bytes() == b"new"
    assert not list(tmp_path.glob(".artifact.txt.*.tmp"))


def test_write_text_atomic_preserves_existing_file_and_cleans_temp_on_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact.txt"
    path.write_bytes(b"original")
    original_named_tempfile = ws.tempfile.NamedTemporaryFile

    class FailingTempFile:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._tmp: Any = original_named_tempfile(*args, **kwargs)
            self.name = self._tmp.name

        def __enter__(self) -> FailingTempFile:
            self._tmp.__enter__()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return self._tmp.__exit__(exc_type, exc, traceback)

        def write(self, content: str) -> int:
            self._tmp.write(content[:3])
            self._tmp.flush()
            raise OSError("interrupted")

    monkeypatch.setattr(ws.tempfile, "NamedTemporaryFile", FailingTempFile)

    with pytest.raises(OSError, match="interrupted"):
        ws.write_text_atomic(path, "new content")

    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".artifact.txt.*.tmp"))


def test_resolve_workspace_accepts_explicit_dir(tmp_path) -> None:
    wsdir = tmp_path / "ws"
    _workspace(wsdir)

    assert ws.resolve_workspace(str(wsdir)) == wsdir.resolve()


def test_resolve_workspace_walks_up_from_cwd(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    _workspace(wsdir)
    nested = wsdir / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert ws.resolve_workspace(None) == wsdir.resolve()


def test_resolve_workspace_errors_when_none_found(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OpenBBQError) as raised:
        ws.resolve_workspace(None)

    assert raised.value.code == "no_workspace"


def test_resolve_workspace_skips_foreign_manifest_and_continues_up(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "root"
    _workspace(root)
    foreign = root / "foreign"
    nested = foreign / "child"
    nested.mkdir(parents=True)
    (foreign / ws.MANIFEST_NAME).write_text(
        '{"schema":"other/tool@1","source":"not openbbq"}',
        encoding="utf-8",
    )
    monkeypatch.chdir(nested)

    assert ws.resolve_workspace(None) == root.resolve()


def test_init_workspace_derives_slug_and_rejects_collision(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "My Demo Clip.mp4"
    source.write_bytes(b"video")
    monkeypatch.chdir(tmp_path)

    path, manifest = ws.init_workspace(str(source), workspace=None)

    assert path == (tmp_path / "my-demo-clip").resolve()
    assert manifest.source.type == "local_video"
    assert manifest.source.ref == str(source.resolve())
    assert manifest.source.title == "My Demo Clip"

    with pytest.raises(OpenBBQError) as raised:
        ws.init_workspace(str(source), workspace=None)

    assert raised.value.code == "workspace_exists"


def test_require_artifact_errors_when_recorded_file_is_missing(tmp_path) -> None:
    manifest = _manifest("missing artifact")
    manifest.stages = {
        Stage.TRANSCRIBE: StageState(
            status=StageStatus.DONE,
            artifact="transcript.json",
        )
    }

    with pytest.raises(OpenBBQError) as raised:
        ws.require_artifact(
            tmp_path,
            manifest,
            Stage.TRANSCRIBE,
            fix="openbbq transcribe",
        )

    assert raised.value.code == "missing_input"
    assert raised.value.context["artifact"] == "transcript.json"


def test_media_input_uses_local_source_or_fetched_artifact(tmp_path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    media = tmp_path / "media" / "video.webm"
    media.parent.mkdir()
    media.write_bytes(b"video")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(source), title="source"),
        stages={},
    )

    assert ws.media_input(manifest, tmp_path) == source

    manifest.stages[Stage.FETCH] = StageState(
        status=StageStatus.DONE,
        artifact="media/video.webm",
    )
    assert ws.media_input(manifest, tmp_path) == media


def test_record_stage_preserves_concurrent_on_disk_change(tmp_path) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    stale = _manifest("original")
    ws.write_manifest(wsdir, stale)

    concurrent = ws.read_manifest(wsdir)
    concurrent.glossary = "frieren"
    ws.write_manifest(wsdir, concurrent)

    ws.record_stage(
        wsdir,
        stale,
        Stage.TRANSCRIBE,
        StageState(status=StageStatus.DONE, artifact="transcript.json"),
    )

    updated = ws.read_manifest(wsdir)
    assert updated.glossary == "frieren"
    assert updated.stages[Stage.TRANSCRIBE].artifact == "transcript.json"


@pytest.mark.parametrize("status", [StageStatus.RUNNING, StageStatus.DONE])
def test_record_stage_running_or_done_resets_later_stages(
    tmp_path, status: StageStatus
) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest("original")
    manifest.stages = {
        Stage.FETCH: StageState(status=StageStatus.DONE, artifact="media/video.mp4"),
        Stage.SEGMENT: StageState(status=StageStatus.DONE, artifact="cues.json"),
        Stage.TRANSLATE: StageState(
            status=StageStatus.RUNNING,
            artifact="translation.zh.json",
            progress=Progress(done=1, total=2),
        ),
        Stage.EXPORT: StageState(status=StageStatus.FAILED, error="old error"),
    }
    ws.write_manifest(wsdir, manifest)

    ws.record_stage(
        wsdir,
        manifest,
        Stage.TRANSCRIBE,
        StageState(status=status, artifact="transcript.json"),
    )

    updated = ws.read_manifest(wsdir)
    assert updated.stages[Stage.FETCH].artifact == "media/video.mp4"
    assert updated.stages[Stage.TRANSCRIBE].status is status
    assert updated.stages[Stage.SEGMENT] == StageState(status=StageStatus.PENDING)
    assert updated.stages[Stage.TRANSLATE] == StageState(status=StageStatus.PENDING)
    assert updated.stages[Stage.EXPORT] == StageState(status=StageStatus.PENDING)


def test_record_stage_failed_does_not_reset_later_stages(tmp_path) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest("original")
    manifest.stages = {
        Stage.SEGMENT: StageState(status=StageStatus.DONE, artifact="cues.json"),
        Stage.EXPORT: StageState(status=StageStatus.DONE, artifact="out/zh.srt"),
    }
    ws.write_manifest(wsdir, manifest)

    ws.record_stage(
        wsdir,
        manifest,
        Stage.TRANSCRIBE,
        StageState(status=StageStatus.FAILED, error="asr failed"),
    )

    updated = ws.read_manifest(wsdir)
    assert updated.stages[Stage.SEGMENT].artifact == "cues.json"
    assert updated.stages[Stage.EXPORT].artifact == "out/zh.srt"


def test_stage_execution_lock_serializes_long_running_mechanical_work(tmp_path) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()

    def wait_for_lock() -> str:
        with ws.stage_execution_lock(wsdir, Stage.FETCH):
            return "acquired"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with ws.stage_execution_lock(wsdir, Stage.FETCH):
            waiting = pool.submit(wait_for_lock)
            with pytest.raises(TimeoutError):
                waiting.result(timeout=0.05)
        assert waiting.result(timeout=1) == "acquired"
