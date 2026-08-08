from __future__ import annotations

import math
import struct
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.core import review as reviewlib
from openbbq.core import workspace as ws
from openbbq.review_server.app import ReviewManager, create_app
from openbbq.schemas import (
    ASRInfo,
    Budget,
    Cue,
    Cues,
    GlossaryRef,
    Manifest,
    Segment,
    SegmentParams,
    Source,
    Stage,
    StageState,
    StageStatus,
    Suggestion,
    SuggestionPatch,
    Suggestions,
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


# --- P1: new contract endpoints -------------------------------------------------


def _write_suggestions(path: Path, items: list[Suggestion]) -> None:
    doc = Suggestions(source_lang="en", target_lang="zh", suggestions=items)
    ws.write_text_atomic(
        reviewlib.suggestions_path(path, "zh"), doc.model_dump_json(indent=2)
    )


def _suggestion(id_: str, cue_id: int, patch: SuggestionPatch) -> Suggestion:
    return Suggestion(
        id=id_,
        cue_id=cue_id,
        kind="agent_note",
        message=f"suggestion {id_}",
        patch=patch,
        content_hash="sha256:" + "a" * 64,
        created_at=datetime.now(timezone.utc),
    )


def test_cue_payload_grows_issues_and_keeps_legacy_booleans(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    translation = ws.read_translation(path / "translation.zh.json")
    translation.glossary = [GlossaryRef(source="Hello", target="哈喽")]
    ws.write_text_atomic(
        path / "translation.zh.json", translation.model_dump_json(indent=2)
    )
    transcript = ws.read_transcript(path / "transcript.json")
    transcript.segments[0].words = [
        Word(word="Hello", start=0, end=0.7, prob=0.3),
        Word(word="world", start=1, end=1.7),
    ]
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))

    with _client(path) as client:
        response = client.get("/api/cues")

    assert response.status_code == 200
    data = response.json()
    assert data["suggestions"] == []
    first, second = data["cues"]
    # Legacy booleans are untouched.
    assert first["term_warning"] is True
    assert first["time_warning"] is False
    assert first["over_budget"] is False
    assert second["term_warning"] is False
    # Structured issues carry the detail the booleans discarded.
    kinds = [issue["kind"] for issue in first["issues"]]
    assert kinds == ["term", "asr_confidence"]
    term, asr = first["issues"]
    assert term["severity"] == "warning"
    assert term["source"] == "rule"
    assert term["dismissed"] is False
    assert term["detail"] == {
        "term": "Hello",
        "expected": "哈喽",
        "occurrences": [[0, 5]],
    }
    assert asr["severity"] == "info"
    assert asr["detail"] == {
        "words": [{"word": "Hello", "prob": 0.3}],
        "threshold": 0.5,
    }
    assert second["issues"] == []


def test_dismissals_endpoint_marks_issue_dismissed(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        revision = client.get("/api/session").json()["revision"]
        dismissed = client.post(
            "/api/cues/1/dismissals",
            json={"kind": "timing", "base_revision": revision, "op_id": "d-1"},
        )
        repeated = client.post(
            "/api/cues/1/dismissals",
            json={
                "kind": "timing",
                "base_revision": dismissed.json()["revision"],
                "op_id": "d-2",
            },
        )
        stale = client.post(
            "/api/cues/1/dismissals",
            json={"kind": "timing", "base_revision": revision, "op_id": "d-3"},
        )

    assert dismissed.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["revision"] == dismissed.json()["revision"]
    assert repeated.json()["changed"] == []
    assert stale.status_code == 409


def test_suggestions_endpoints_accept_reject_reopen(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    _write_suggestions(
        path,
        [
            _suggestion("s1", 2, SuggestionPatch(target="新世界")),
            _suggestion("s2", 1, SuggestionPatch(source="Hello there")),
        ],
    )
    with _client(path) as client:
        listing = client.get("/api/suggestions")
        revision = client.get("/api/session").json()["revision"]
        accepted = client.post(
            "/api/suggestions/s1/accept",
            json={"base_revision": revision, "op_id": "acc-1"},
        )
        accept_again = client.post(
            "/api/suggestions/s1/accept",
            json={"base_revision": accepted.json()["revision"], "op_id": "acc-2"},
        )
        missing = client.post(
            "/api/suggestions/nope/accept",
            json={"base_revision": accepted.json()["revision"], "op_id": "acc-3"},
        )
        rejected = client.post(
            "/api/suggestions/s2/reject",
            json={"base_revision": accepted.json()["revision"], "op_id": "rej-1"},
        )
        cue_one_issues = [
            issue
            for cue in rejected.json()["cues"]
            if cue["id"] == 1
            for issue in cue["issues"]
        ]
        reopened = client.post(
            "/api/suggestions/s2/reopen",
            json={"base_revision": rejected.json()["revision"], "op_id": "reo-1"},
        )

    assert listing.status_code == 200
    assert [s["id"] for s in listing.json()["suggestions"]] == ["s1", "s2"]
    assert accepted.status_code == 200
    assert accepted.json()["changed"] == [2]
    assert accepted.json()["suggestions"][0]["status"] == "accepted"
    translation = ws.read_translation(path / "translation.zh.json")
    assert translation.items[1].target == "新世界"
    assert accept_again.status_code == 422
    assert accept_again.json()["error"] == "suggestion_not_pending"
    assert missing.status_code == 404
    assert missing.json()["error"] == "unknown_suggestion"
    assert rejected.status_code == 200
    assert rejected.json()["suggestions"][1]["status"] == "rejected"
    # A resolved suggestion no longer projects an agent_note issue.
    assert [issue["kind"] for issue in cue_one_issues] == []
    assert reopened.status_code == 200
    reopened_suggestion = reopened.json()["suggestions"][1]
    assert reopened_suggestion["status"] == "pending"
    assert reopened_suggestion["resolved_at"] is None


def test_batch_endpoint_dry_run_then_execute(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        revision = client.get("/api/session").json()["revision"]
        dry = client.post(
            "/api/cues/batch",
            json={
                "find": "o",
                "replace": "0",
                "fields": ["source"],
                "dry_run": True,
                "base_revision": revision,
                "op_id": "dry-1",
            },
        )
        invalid_regex = client.post(
            "/api/cues/batch",
            json={
                "find": "[",
                "replace": "x",
                "fields": ["source"],
                "regex": True,
                "base_revision": revision,
                "op_id": "bad-1",
            },
        )
        unknown_cue = client.post(
            "/api/cues/batch",
            json={
                "find": "o",
                "replace": "0",
                "fields": ["source"],
                "cue_ids": [99],
                "base_revision": revision,
                "op_id": "bad-2",
            },
        )
        executed = client.post(
            "/api/cues/batch",
            json={
                "find": "o",
                "replace": "0",
                "fields": ["source"],
                "base_revision": revision,
                "op_id": "exec-1",
            },
        )
        undone = client.post(
            "/api/undo",
            json={"base_revision": executed.json()["revision"], "op_id": "undo-1"},
        )

    assert dry.status_code == 200
    assert dry.json()["revision"] == revision
    assert [(m["cue_id"], m["field"], m["spans"]) for m in dry.json()["matches"]] == [
        (1, "source", [[4, 5]]),
        (2, "source", [[1, 2]]),
    ]
    assert invalid_regex.status_code == 422
    assert invalid_regex.json()["error"] == "invalid_regex"
    assert unknown_cue.status_code == 404
    assert unknown_cue.json()["error"] == "unknown_cue"
    assert executed.status_code == 200
    assert executed.json()["changed"] == [1, 2]
    assert [cue["source"] for cue in executed.json()["cues"]] == ["Hell0", "w0rld"]
    assert undone.status_code == 200
    assert [cue["source"] for cue in undone.json()["cues"]] == ["Hello", "world"]


def test_batch_status_endpoint_validates_before_writing(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        revision = client.get("/api/session").json()["revision"]
        reviewed = client.post(
            "/api/cues/batch-status",
            json={
                "cue_ids": [1, 2],
                "status": "reviewed",
                "base_revision": revision,
                "op_id": "bs-1",
            },
        )
        blanked = client.patch(
            "/api/cues/2",
            json={
                "target": "",
                "base_revision": reviewed.json()["revision"],
                "op_id": "blank-1",
            },
        )
        blocked = client.post(
            "/api/cues/batch-status",
            json={
                "cue_ids": [1, 2],
                "status": "reviewed",
                "base_revision": blanked.json()["revision"],
                "op_id": "bs-2",
            },
        )
        cues_after = client.get("/api/cues").json()["cues"]

    assert reviewed.status_code == 200
    assert reviewed.json()["progress"]["reviewed"] == 2
    assert blanked.status_code == 200
    assert blocked.status_code == 422
    assert blocked.json()["error"] == "review_blocked"
    assert blocked.json()["ids"] == [2]
    # All-or-nothing: cue 1 kept its earlier reviewed state, nothing moved.
    assert [cue["status"] for cue in cues_after] == ["reviewed", "unreviewed"]


def test_glossary_terms_endpoint_scaffolds_binds_and_reports(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        revision = client.get("/api/session").json()["revision"]
        created = client.post(
            "/api/glossary/terms",
            json={
                "source": "Hello",
                "target": "哈喽",
                "note": "greeting",
                "base_revision": revision,
                "op_id": "term-1",
            },
        )
        # The new term immediately drives a rule issue on cue 1, whose target
        # does not carry the expected rendering.
        cues_after = client.get("/api/cues")

    assert created.status_code == 200
    data = created.json()
    assert data["glossary"] == "ws"
    assert data["term_report"]["added"] == ["Hello"]
    glossary_file = tmp_path / "home" / "glossaries" / "ws.json"
    assert glossary_file.is_file()
    manifest = ws.read_manifest(path)
    assert manifest.glossary == "ws"
    first = next(cue for cue in cues_after.json()["cues"] if cue["id"] == 1)
    assert first["term_warning"] is True
    term = next(issue for issue in first["issues"] if issue["kind"] == "term")
    assert term["detail"]["expected"] == "哈喽"


def test_batch_delete_endpoint_is_atomic(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with _client(path) as client:
        revision = client.get("/api/session").json()["revision"]
        deleted = client.post(
            "/api/cues/batch-delete",
            json={
                "cue_ids": [1],
                "base_revision": revision,
                "op_id": "bd-1",
            },
        )
        missing = client.post(
            "/api/cues/batch-delete",
            json={
                "cue_ids": [2, 99],
                "base_revision": deleted.json()["revision"],
                "op_id": "bd-2",
            },
        )
        remaining = client.get("/api/cues").json()["cues"]
        undone = client.post(
            "/api/undo",
            json={"base_revision": deleted.json()["revision"], "op_id": "undo-bd"},
        )

    assert deleted.status_code == 200
    assert deleted.json()["changed"] == [1]
    assert [cue["id"] for cue in deleted.json()["cues"]] == [2]
    # All-or-nothing: id 99 aborts the batch, cue 2 stays.
    assert missing.status_code == 404
    assert missing.json()["error"] == "unknown_cue"
    assert [cue["id"] for cue in remaining] == [2]
    # One undo rolls the whole batch back.
    assert undone.status_code == 200
    assert [cue["id"] for cue in undone.json()["cues"]] == [1, 2]


def test_new_endpoints_require_authentication(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    with TestClient(create_app(path, "zh", secret="test-secret")) as anonymous:
        assert anonymous.get("/api/suggestions").status_code == 401
        assert anonymous.post("/api/cues/1/dismissals", json={}).status_code == 401
        assert anonymous.post("/api/cues/batch", json={}).status_code == 401
        assert anonymous.post("/api/cues/batch-status", json={}).status_code == 401
        assert anonymous.post("/api/cues/batch-delete", json={}).status_code == 401
        assert anonymous.post("/api/glossary/terms", json={}).status_code == 401
        assert anonymous.post("/api/suggestions/s1/accept", json={}).status_code == 401
