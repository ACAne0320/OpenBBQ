from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer

import openbbq.cli.commands.transcribe as transcribecmd
from openbbq.cli.commands.transcribe import transcribe
from openbbq.cli.commands.extract_audio import extract_audio
from openbbq.cli.output import Output
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import Manifest, Source, Stage, StageState, StageStatus


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _workspace(tmp_path: Path) -> tuple[Path, Manifest]:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.wav"
    source.write_bytes(b"")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(source)),
        stages={},
    )
    ws.write_manifest(path, manifest)
    return path, manifest


def test_transcribe_missing_input_does_not_touch_stage(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)

    try:
        transcribe(_ctx(), workspace=str(path), model="experiments/models/ggml-base.bin")
    except OpenBBQError as err:
        assert err.code == "missing_input"
    else:
        raise AssertionError("expected OpenBBQError")

    assert ws.read_manifest(path).stages == manifest.stages


def test_transcribe_model_missing_does_not_touch_stage(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    path, manifest = _workspace(tmp_path)
    audio = path / "media" / "audio.16k.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"not needed for this preflight")
    manifest.stages[Stage.EXTRACT_AUDIO] = StageState(
        status=StageStatus.DONE,
        artifact="media/audio.16k.wav",
        updated_at=datetime.now(timezone.utc),
    )
    ws.write_manifest(path, manifest)

    try:
        transcribe(_ctx(), workspace=str(path), model="missing-model")
    except OpenBBQError as err:
        assert err.code == "model_missing"
        assert err.context["model"] == "missing-model"
    else:
        raise AssertionError("expected OpenBBQError")

    assert ws.read_manifest(path).stages == manifest.stages


def test_transcribe_keyboard_interrupt_records_failed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    audio = path / "media" / "audio.16k.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"not needed")
    manifest.stages[Stage.EXTRACT_AUDIO] = StageState(
        status=StageStatus.DONE,
        artifact="media/audio.16k.wav",
        updated_at=datetime.now(timezone.utc),
    )
    ws.write_manifest(path, manifest)

    class InterruptingBackend:
        name = "test-asr"
        install_hint = "install test-asr"
        capabilities = set()

        def default_model(self) -> str:
            return "fake-model"

        def has_model(self, name: str) -> bool:
            return True

        def is_available(self) -> bool:
            return True

        def transcribe(self, *args, **kwargs) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        transcribecmd, "get_backend", lambda backend: InterruptingBackend()
    )
    monkeypatch.setattr(transcribecmd.media, "wav_duration", lambda path: 2.0)

    with pytest.raises(KeyboardInterrupt):
        transcribe(_ctx(), workspace=str(path), model="fake-model")

    failed = ws.read_manifest(path).stages[Stage.TRANSCRIBE]
    assert failed.status is StageStatus.FAILED
    assert failed.error == "interrupted"


def test_extract_audio_rejects_duration_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _manifest_doc = _workspace(tmp_path)

    def fake_extract(_source: Path, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"wav")

    monkeypatch.setattr(transcribecmd.media, "extract_audio", fake_extract)
    monkeypatch.setattr(transcribecmd.media, "media_duration", lambda _path: 100.0)
    monkeypatch.setattr(transcribecmd.media, "wav_duration", lambda _path: 130.0)

    with pytest.raises(OpenBBQError) as raised:
        extract_audio(_ctx(), workspace=str(path))

    assert raised.value.code == "media_duration_mismatch"
    assert ws.read_manifest(path).stages[Stage.EXTRACT_AUDIO].status is StageStatus.FAILED
