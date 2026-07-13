from __future__ import annotations

import math
import struct
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.core import workspace as ws
from openbbq.review_server.app import ReviewManager, create_app
from openbbq.schemas import (
    ASRInfo,
    Budget,
    Cue,
    Cues,
    Manifest,
    Segment,
    SegmentParams,
    Source,
    Stage,
    StageState,
    StageStatus,
    Transcript,
    Translation,
    TranslationItem,
    Word,
)


PARAMS = SegmentParams(
    max_cps=20,
    max_chars_per_line=80,
    max_lines=1,
    min_dur=0.5,
    max_dur=7,
    min_gap=0.1,
)


def _wav(path: Path, duration: float = 2.0) -> None:
    rate = 16_000
    frames = bytearray()
    for i in range(round(rate * duration)):
        value = round(12_000 * math.sin(2 * math.pi * 220 * i / rate))
        frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)


def _workspace(path: Path) -> Path:
    path.mkdir()
    media = path / "media"
    media.mkdir()
    audio = media / "audio.16k.wav"
    _wav(audio)
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(audio), title="Real review API"),
        stages={
            Stage.EXTRACT_AUDIO: StageState(
                status=StageStatus.DONE, artifact="media/audio.16k.wav"
            ),
            Stage.TRANSCRIBE: StageState(
                status=StageStatus.DONE, artifact="transcript.json"
            ),
            Stage.SEGMENT: StageState(status=StageStatus.DONE, artifact="cues.json"),
            Stage.TRANSLATE: StageState(
                status=StageStatus.DONE, artifact="translation.zh.json"
            ),
        },
    )
    ws.write_manifest(path, manifest)
    cues = Cues(
        source_lang="en",
        params=PARAMS,
        cues=[
            Cue(id=1, start=0, end=0.9, source="Hello"),
            Cue(id=2, start=1, end=1.9, source="world"),
        ],
    )
    ws.write_text_atomic(path / "cues.json", cues.model_dump_json(indent=2))
    translation = Translation(
        source_lang="en",
        target_lang="zh",
        params=PARAMS,
        items=[
            TranslationItem(
                id=1,
                source="Hello",
                budget=Budget(max_chars=9, seconds=0.9),
                target="你好",
            ),
            TranslationItem(
                id=2,
                source="world",
                budget=Budget(max_chars=9, seconds=0.9),
                target="世界",
            ),
        ],
    )
    ws.write_text_atomic(
        path / "translation.zh.json", translation.model_dump_json(indent=2)
    )
    transcript = Transcript(
        language="en",
        duration=2.0,
        asr=ASRInfo(
            backend="fixture",
            model="fixture",
            created_at=datetime.now(timezone.utc),
        ),
        segments=[
            Segment(
                id=0,
                start=0,
                end=2,
                text="Hello world",
                words=[
                    Word(word="Hello", start=0, end=0.7),
                    Word(word="world", start=1, end=1.7),
                ],
            )
        ],
    )
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))
    return path


def _client(path: Path) -> TestClient:
    client = TestClient(create_app(path, "zh", secret="test-secret"))
    response = client.post("/api/auth/session", json={"secret": "test-secret"})
    assert response.status_code == 204
    return client


def test_api_requires_session_and_returns_real_session_state(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    app = create_app(path, "zh", secret="test-secret")

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/session").status_code == 401

    with _client(path) as client:
        response = client.get("/api/session")

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Real review API"
    assert data["target_lang"] == "zh"
    assert data["languages"] == ["zh"]
    assert data["media"]["kind"] == "audio"
    assert data["media"]["duration"] == 2.0
    assert data["progress"] == {
        "reviewed": 0,
        "flagged": 0,
        "unreviewed": 2,
        "total": 2,
    }


def test_api_cue_edit_persists_and_revision_conflicts(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        before = client.get("/api/session").json()
        response = client.patch(
            "/api/cues/1",
            json={
                "base_revision": before["revision"],
                "op_id": "edit-1",
                "source": "Hello there",
                "target": "你好呀",
            },
        )
        stale = client.patch(
            "/api/cues/2",
            json={
                "base_revision": before["revision"],
                "op_id": "stale",
                "source": "stale edit",
            },
        )

    assert response.status_code == 200
    assert response.json()["changed"] == [1]
    assert stale.status_code == 409
    assert stale.json()["error"] == "review_conflict"
    cues = ws.read_cues(path / "cues.json")
    translation = ws.read_translation(path / "translation.zh.json")
    assert cues.cues[0].source == "Hello there"
    assert translation.items[0].target == "你好呀"


def test_media_supports_range_and_waveform_window(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        ranged = client.get("/api/media", headers={"Range": "bytes=0-31"})
        middle = client.get("/api/media", headers={"Range": "bytes=32-47"})
        tail = client.get("/api/media", headers={"Range": "bytes=-16"})
        invalid = client.get("/api/media", headers={"Range": "bytes=999999-"})
        multiple = client.get("/api/media", headers={"Range": "bytes=0-1,4-5"})
        waveform_response = client.get(
            "/api/waveform", params={"start": 0, "end": 1, "pixels": 80}
        )

    assert ranged.status_code == 206
    assert ranged.headers["accept-ranges"] == "bytes"
    assert ranged.headers["content-range"].startswith("bytes 0-31/")
    assert len(ranged.content) == 32
    assert middle.status_code == 206
    assert middle.headers["content-range"].startswith("bytes 32-47/")
    assert len(middle.content) == 16
    assert tail.status_code == 206
    assert tail.headers["content-length"] == "16"
    assert invalid.status_code == 416
    assert invalid.headers["content-range"].startswith("bytes */")
    assert multiple.status_code == 416
    assert waveform_response.status_code == 200
    waveform_data = waveform_response.json()
    assert waveform_data["sample_rate"] == 16000
    assert waveform_data["duration"] == 2.0
    assert 1 <= len(waveform_data["peaks"]) <= 80
    assert all(len(pair) == 2 for pair in waveform_data["peaks"])
    assert list((path / ".openbbq" / "review" / "cache").glob("waveform-*.json"))


def test_word_window_and_language_switch(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        words = client.get("/api/transcript/words", params={"start": 0.5, "end": 1.2})
        revision = client.get("/api/session").json()["revision"]
        switched = client.post(
            "/api/session/target",
            json={
                "base_revision": revision,
                "op_id": "switch-source",
                "target_lang": None,
            },
        )

    assert words.status_code == 200
    assert [word["word"] for word in words.json()["words"]] == ["Hello", "world"]
    assert switched.status_code == 200
    assert switched.json()["target_lang"] is None


def test_root_serves_packaged_review_ui_with_security_headers(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with TestClient(create_app(path, "zh", secret="test-secret")) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "OpenBBQ Review" in response.text
    assert "content-security-policy" in response.headers


def test_server_rejects_host_origin_and_unauthenticated_media(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with TestClient(create_app(path, "zh", secret="test-secret")) as client:
        bad_host = client.get("/", headers={"Host": "evil.example"})
        bad_origin = client.post(
            "/api/auth/session",
            headers={"Origin": "https://evil.example"},
            json={"secret": "test-secret"},
        )
        cross_port_origin = client.post(
            "/api/auth/session",
            headers={"Origin": "http://testserver:9999"},
            json={"secret": "test-secret"},
        )
        media = client.get("/api/media")
        same_origin = client.post(
            "/api/auth/session",
            headers={"Origin": "http://testserver"},
            json={"secret": "test-secret"},
        )

    assert bad_host.status_code == 403
    assert bad_origin.status_code == 403
    assert cross_port_origin.status_code == 403
    assert same_origin.status_code == 204
    assert media.status_code == 401


def test_incompatible_video_builds_and_serves_review_proxy(
    tmp_path: Path, monkeypatch
) -> None:
    path = _workspace(tmp_path / "ws")
    video = path / "source.mkv"
    video.write_bytes(b"incompatible-video")
    manifest = ws.read_manifest(path)
    manifest.source.type = "local_video"
    manifest.source.ref = str(video)
    ws.write_manifest(path, manifest)

    def transcode(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        assert command[0] == "ffmpeg"
        assert "libx264" in command
        assert "aac" in command
        assert check and capture_output and text
        Path(command[-1]).write_bytes(b"proxy-video" * 16)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", transcode)

    with _client(path) as client:
        before = client.get("/api/session").json()
        assert before["media"]["playable"] is False
        assert before["media"]["preview_status"] == "needed"

        started = client.post("/api/media/preview")
        assert started.status_code == 202
        state = started.json()
        deadline = time.monotonic() + 10
        while state["status"] == "building" and time.monotonic() < deadline:
            time.sleep(0.05)
            state = client.get("/api/media/preview-status").json()

        assert state == {"status": "ready", "error": None}
        ranged = client.get("/api/media", headers={"Range": "bytes=0-63"})

    assert ranged.status_code == 206
    assert len(ranged.content) == 64
    assert list((path / ".openbbq" / "review" / "cache").glob("preview-*.mp4"))


def test_browser_can_request_proxy_after_supported_container_fails(
    tmp_path: Path, monkeypatch
) -> None:
    path = _workspace(tmp_path / "ws")
    video = path / "source.mp4"
    video.write_bytes(b"original-video")
    manifest = ws.read_manifest(path)
    manifest.source.type = "local_video"
    manifest.source.ref = str(video)
    ws.write_manifest(path, manifest)

    def build_preview(manager: ReviewManager) -> None:
        assert manager._preview_path is not None
        manager._preview_path.parent.mkdir(parents=True, exist_ok=True)
        manager._preview_path.write_bytes(b"browser-compatible-proxy")
        manager._serving_preview = True
        manager._preview_status = "ready"

    monkeypatch.setattr(ReviewManager, "_build_preview", build_preview)

    with _client(path) as client:
        initial = client.get("/api/session").json()
        assert initial["media"]["playable"] is True
        assert initial["media"]["preview_status"] == "ready"
        assert client.get("/api/media").content == b"original-video"

        client.post("/api/media/preview")
        state = client.get("/api/media/preview-status").json()
        deadline = time.monotonic() + 2
        while state["status"] == "building" and time.monotonic() < deadline:
            time.sleep(0.01)
            state = client.get("/api/media/preview-status").json()

        assert state == {"status": "ready", "error": None}
        assert client.get("/api/media").content == b"browser-compatible-proxy"
