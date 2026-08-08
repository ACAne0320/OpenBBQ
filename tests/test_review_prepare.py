from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from openbbq.cli import main
from openbbq.core import review as reviewlib
from openbbq.core import review_prepare
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
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
    Suggestion,
    SuggestionPatch,
    Suggestions,
    SuggestionStatus,
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


def _workspace(path: Path) -> Path:
    path.mkdir()
    source = path / "source.wav"
    source.write_bytes(b"fake-audio")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(source), title="Prepare fixture"),
        stages={
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
            Cue(id=1, start=0, end=1.9, source="Hello world"),
            Cue(id=2, start=3, end=4.9, source="Second cue"),
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
                source="Hello world",
                budget=Budget(max_chars=20, seconds=1.9),
                target="你好世界",
            ),
            TranslationItem(
                id=2,
                source="Second cue",
                budget=Budget(max_chars=20, seconds=1.9),
                target="第二句",
            ),
        ],
    )
    ws.write_text_atomic(
        path / "translation.zh.json", translation.model_dump_json(indent=2)
    )
    transcript = Transcript(
        language="en",
        duration=5.0,
        asr=ASRInfo(
            backend="fixture",
            model="fixture",
            created_at=datetime.now(timezone.utc),
        ),
        segments=[
            Segment(
                id=0,
                start=0,
                end=5,
                text="Hello world, second cue",
                words=[Word(word="Hello", start=0, end=0.7, prob=0.3)],
            )
        ],
    )
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))
    return path


def _run_cli(
    args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any]]:
    monkeypatch.setattr(sys, "argv", ["openbbq", *args])
    with pytest.raises(SystemExit) as raised:
        main()
    code = raised.value.code
    assert isinstance(code, int)
    stdout = capsys.readouterr().out
    assert stdout.endswith("\n") and "\n" not in stdout.removesuffix("\n")
    return code, json.loads(stdout)


def test_prepare_payload_shape(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")

    payload = review_prepare.build_prepare_payload(path, "zh")

    assert payload["workspace"] == str(path)
    assert payload["title"] == "Prepare fixture"
    assert payload["source_lang"] == "en"
    assert payload["target_lang"] == "zh"
    assert payload["max_suggestions"] == review_prepare.MAX_PREPARE_SUGGESTIONS
    first, second = payload["items"]
    assert first == {
        "cue_id": 1,
        "start": 0,
        "end": 1.9,
        "source": "Hello world",
        "target": "你好世界",
        "rule_issues": ["asr_confidence"],
    }
    assert second["cue_id"] == 2
    assert second["rule_issues"] == []
    suggestion_schema = payload["response_schema"]["suggestions"][0]
    assert set(suggestion_schema) == {
        "cue_id",
        "message",
        "patch",
        "severity",
        "kind",
    }
    argv = payload["apply_argv"]
    assert argv[:5] == ["openbbq", "--json", "review", "--prepare", "--apply"]
    assert "--to" in argv and "zh" in argv
    assert "conflict" in payload["note"]
    # No review lock, no review session files.
    assert not (path / ".openbbq" / "review" / "session.lock").exists()


def test_apply_writes_pending_suggestions_with_real_hashes(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    response = {
        "suggestions": [
            {"cue_id": 1, "message": "greeting may be too literal",
             "patch": {"target": "哈喽，世界"}},
            {
                "cue_id": 2,
                "kind": "timing",
                "severity": "warning",
                "message": "consider moving the start earlier",
                "patch": {"start": 2.8},
            },
        ]
    }

    result = review_prepare.apply_prepare_response(path, "zh", json.dumps(response))

    file = reviewlib.suggestions_path(path, "zh")
    assert result == {"written": 2, "path": str(file), "suggestions_total": 2}
    doc = ws.read_suggestions(file)
    assert doc.source_lang == "en"
    assert doc.target_lang == "zh"
    first, second = doc.suggestions
    assert first.id.startswith("prep-")
    assert second.id.startswith("prep-")
    assert first.id != second.id
    assert first.status is SuggestionStatus.PENDING
    assert first.kind == "agent_note"
    assert first.severity == "info"
    assert second.kind == "timing"
    assert second.severity == "warning"
    assert second.patch.start == 2.8
    cues = ws.read_cues(path / "cues.json")
    worksheet = ws.read_translation(ws.worksheet_path(path, "zh"))
    assert first.content_hash == reviewlib.review_hash(cues.cues[0], worksheet)
    assert second.content_hash == reviewlib.review_hash(cues.cues[1], worksheet)
    assert not (path / ".openbbq" / "review" / "session.lock").exists()


def test_apply_merges_preserving_existing_entries(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    existing = Suggestions(
        source_lang="en",
        target_lang="zh",
        suggestions=[
            Suggestion(
                id="tr-deadbeef",
                cue_id=1,
                kind="agent_note",
                message="earlier accepted note",
                patch=SuggestionPatch(target="旧译"),
                content_hash="sha256:" + "a" * 64,
                status=SuggestionStatus.ACCEPTED,
                created_at=datetime.now(timezone.utc),
                resolved_at=datetime.now(timezone.utc),
            )
        ],
    )
    ws.write_text_atomic(
        reviewlib.suggestions_path(path, "zh"), existing.model_dump_json(indent=2)
    )

    result = review_prepare.apply_prepare_response(
        path,
        "zh",
        json.dumps(
            {"suggestions": [{"cue_id": 2, "message": "new", "patch": {"target": "新"}}]}
        ),
    )

    assert result["written"] == 1
    assert result["suggestions_total"] == 2
    doc = ws.read_suggestions(reviewlib.suggestions_path(path, "zh"))
    first, second = doc.suggestions
    assert first.id == "tr-deadbeef"
    assert first.status is SuggestionStatus.ACCEPTED
    assert first.resolved_at is not None
    assert second.id != first.id
    assert second.status is SuggestionStatus.PENDING


def test_apply_rejects_unknown_cue_cap_and_invalid_response(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")

    with pytest.raises(OpenBBQError) as raised:
        review_prepare.apply_prepare_response(
            path,
            "zh",
            json.dumps(
                {"suggestions": [{"cue_id": 99, "message": "x", "patch": {"target": "译"}}]}
            ),
        )
    assert raised.value.code == "agent_response_invalid"
    assert raised.value.context["ids"] == [99]

    with pytest.raises(OpenBBQError) as raised:
        review_prepare.apply_prepare_response(
            path,
            "zh",
            json.dumps(
                {
                    "suggestions": [
                        {
                            "cue_id": 1,
                            "message": f"note {index}",
                            "patch": {"target": f"译{index}"},
                        }
                        for index in range(review_prepare.MAX_PREPARE_SUGGESTIONS + 1)
                    ]
                }
            ),
        )
    assert raised.value.code == "agent_response_invalid"

    with pytest.raises(OpenBBQError) as raised:
        review_prepare.apply_prepare_response(path, "zh", "not json")
    assert raised.value.code == "agent_response_invalid"

    with pytest.raises(OpenBBQError) as raised:
        review_prepare.apply_prepare_response(
            path,
            "zh",
            json.dumps({"suggestions": [{"cue_id": 1, "message": "x", "patch": {}}]}),
        )
    assert raised.value.code == "agent_response_invalid"

    assert not reviewlib.suggestions_path(path, "zh").exists()


def test_prepare_and_apply_through_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(tmp_path / "ws")

    code, payload = _run_cli(
        ["--json", "review", "--prepare", "--workspace", str(path), "--to", "zh"],
        monkeypatch,
        capsys,
    )
    assert code == 0
    assert payload["ok"] is True
    assert len(payload["items"]) == 2

    response = tmp_path / "response.json"
    response.write_text(
        json.dumps(
            {"suggestions": [{"cue_id": 1, "message": "cli", "patch": {"target": "译"}}]}
        ),
        encoding="utf-8",
    )
    code, applied = _run_cli(
        [
            "--json",
            "review",
            "--prepare",
            "--apply",
            str(response),
            "--workspace",
            str(path),
            "--to",
            "zh",
        ],
        monkeypatch,
        capsys,
    )
    assert code == 0
    assert applied["written"] == 1
    doc = ws.read_suggestions(reviewlib.suggestions_path(path, "zh"))
    assert [suggestion.message for suggestion in doc.suggestions] == ["cli"]
