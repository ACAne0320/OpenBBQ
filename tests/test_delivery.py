from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from openbbq.cli import main
from openbbq.cli.delivery import assess_delivery
from openbbq.core import agent_workflow
from openbbq.core import media
from openbbq.core import export as exportlib
from openbbq.core import review as reviewlib
from openbbq.core import workspace as ws
from openbbq.schemas import (
    ASRInfo,
    Budget,
    Cue,
    Cues,
    Manifest,
    ReviewStatus,
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
    max_cps=17,
    max_chars_per_line=42,
    max_lines=1,
    min_dur=0.83,
    max_dur=7,
    min_gap=0.083,
)


def _workspace(
    tmp_path: Path,
    *,
    agent_draft: bool = True,
    target: str = "你好",
) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")

    transcript = Transcript(
        language="en",
        duration=3,
        asr=ASRInfo(
            backend="test",
            model="test",
            created_at=datetime.now(timezone.utc),
        ),
        segments=[
            Segment(
                id=0,
                start=0,
                end=3,
                text="Hello there.",
                words=[Word(word="Hello", start=0, end=1, prob=0.99)],
            )
        ],
    )
    transcript_path = path / "transcript.json"
    transcript_path.write_text(transcript.model_dump_json(), encoding="utf-8")

    cues = Cues(
        source_lang="en",
        params=PARAMS,
        cues=[Cue(id=1, start=0, end=3, source="Hello there.")],
    )
    cues_path = path / "cues.json"
    cues_path.write_text(cues.model_dump_json(), encoding="utf-8")

    translation = Translation(
        source_lang="en",
        target_lang="zh",
        params=PARAMS,
        items=[
            TranslationItem(
                id=1,
                source="Hello there.",
                target=target,
                budget=Budget(max_chars=20, seconds=3),
            )
        ],
    )
    translation_path = path / "translation.zh.json"
    translation_path.write_text(translation.model_dump_json(), encoding="utf-8")

    audio = path / "media" / "audio.16k.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"normalized-audio")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_video", ref=str(source)),
        stages={
            Stage.EXTRACT_AUDIO: StageState(
                status=StageStatus.DONE,
                artifact="media/audio.16k.wav",
            ),
            Stage.TRANSCRIBE: StageState(
                status=StageStatus.DONE, artifact="transcript.json"
            ),
            Stage.SEGMENT: StageState(status=StageStatus.DONE, artifact="cues.json"),
            Stage.TRANSLATE: StageState(
                status=StageStatus.DONE, artifact="translation.zh.json"
            ),
            Stage.EXPORT: StageState(status=StageStatus.DONE, artifact="out/zh.ass"),
            Stage.BURN: StageState(
                status=StageStatus.DONE, artifact="out/zh-burned.mp4"
            ),
        },
    )
    ws.write_manifest(path, manifest)
    ws.record_artifact_provenance(
        path,
        cues_path,
        Stage.SEGMENT,
        inputs=[transcript_path],
    )

    if agent_draft:
        session = agent_workflow.create_session(path, "zh")
        action = agent_workflow.next_action(path, manifest, session)
        assert action["action"] == "translate"
        agent_workflow.apply_response(
            path,
            manifest,
            session,
            json.dumps(
                {
                    "batch_id": action["batch_id"],
                    "policy_hash": action["policy_hash"],
                    "generation_mode": action["generation_policy"]["mode"],
                    "translations": {"1": target},
                    "source_fixes": [],
                    "glossary_updates": [],
                }
            ),
        )
        session = ws.read_agent_session_optional(path, "zh")
        assert session is not None
        translation = ws.read_translation(translation_path)

    subtitle = path / "out" / "zh.ass"
    subtitle.parent.mkdir()
    subtitle.write_text(
        exportlib.render_ass(
            cues,
            exportlib.ExportMode.BILINGUAL,
            translation=translation,
        ),
        encoding="utf-8",
    )
    burned = path / "out" / "zh-burned.mp4"
    burned.write_bytes(b"burned-video")
    ws.record_artifact_provenance(
        path,
        subtitle,
        Stage.EXPORT,
        inputs=[cues_path, translation_path],
    )
    ws.record_artifact_provenance(
        path,
        burned,
        Stage.BURN,
        inputs=[source, subtitle],
    )
    manifest = ws.read_manifest(path)
    manifest.stages[Stage.EXPORT] = StageState(
        status=StageStatus.DONE,
        artifact="out/zh.ass",
    )
    manifest.stages[Stage.BURN] = StageState(
        status=StageStatus.DONE,
        artifact="out/zh-burned.mp4",
    )
    ws.write_manifest(path, manifest)

    return path


def _run_cli(
    args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(sys, "argv", ["openbbq", *args])
    with pytest.raises(SystemExit) as raised:
        main()
    captured = capsys.readouterr()
    code = raised.value.code
    assert isinstance(code, int)
    return code, json.loads(captured.out)


def _write_current_delivery_outputs(path: Path) -> None:
    manifest = ws.read_manifest(path)
    cues_path = path / "cues.json"
    translation_path = path / "translation.zh.json"
    cues = ws.read_cues(cues_path)
    translation = ws.read_translation(translation_path)
    subtitle = path / "out" / "zh.ass"
    subtitle.write_text(
        exportlib.render_ass(
            cues,
            exportlib.ExportMode.BILINGUAL,
            translation=translation,
        ),
        encoding="utf-8",
    )
    provenance_inputs = [cues_path, translation_path]
    review_path = reviewlib.review_path(path, "zh")
    if review_path.is_file():
        provenance_inputs.append(review_path)
    ws.record_artifact_provenance(
        path,
        subtitle,
        Stage.EXPORT,
        inputs=provenance_inputs,
    )
    burned = path / "out" / "zh-burned.mp4"
    burned.write_bytes(b"burned-video")
    ws.record_artifact_provenance(
        path,
        burned,
        Stage.BURN,
        inputs=[Path(manifest.source.ref), subtitle],
    )
    manifest.stages[Stage.EXPORT] = StageState(
        status=StageStatus.DONE,
        artifact="out/zh.ass",
    )
    manifest.stages[Stage.BURN] = StageState(
        status=StageStatus.DONE,
        artifact="out/zh-burned.mp4",
    )
    ws.write_manifest(path, manifest)


def test_delivery_assessment_passes_complete_fresh_workflow(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is True
    assert assessment.issues == ()
    assert assessment.lang == "zh"
    assert assessment.gates["translation"] is True
    assert assessment.gates["translation_evidence"] is True


def test_complete_human_review_is_valid_evidence_without_agent_session(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path, agent_draft=False)
    review = reviewlib.ReviewSession.open(path, "zh")
    snapshot = review.snapshot()
    updated = review.update_cue(
        1,
        target="您好",
        base_revision=snapshot.revision,
        op_id="human-edit",
    )
    review.set_status(
        1,
        ReviewStatus.REVIEWED,
        base_revision=updated.revision,
        op_id="human-reviewed",
    )
    ws.refresh_artifact_provenance(path, path / "cues.json", Stage.SEGMENT)
    _write_current_delivery_outputs(path)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is True
    assert assessment.issues == ()


def test_human_review_cannot_make_a_missing_target_deliverable(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path, agent_draft=False)
    reviewlib.ReviewSession.open(path, "zh")
    translation_path = path / "translation.zh.json"
    translation = ws.read_translation(translation_path)
    translation.items[0].target = None
    ws.write_text_atomic(translation_path, translation.model_dump_json(indent=2))
    ws.refresh_artifact_provenance(path, path / "cues.json", Stage.SEGMENT)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is False
    assert "translation_incomplete" in {issue.code for issue in assessment.issues}


def test_delivery_does_not_require_rendered_frame_qa(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    assert not ws.qa_path(path).exists()

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is True
    assert set(assessment.gates) == {
        "asr",
        "segment",
        "translation",
        "translation_evidence",
        "export",
        "burn",
    }


def test_delivery_cli_complete_workspace_exits_zero_ready_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _workspace(tmp_path)

    code, payload = _run_cli(
        ["--json", "delivery", "check", "--workspace", str(path), "--to", "zh"],
        monkeypatch,
        capsys,
    )

    assert code == 0
    assert payload["ok"] is True
    assert payload["artifact_ready"] is True
    assert payload["issues"] == []
    assert all(cast(dict[str, bool], payload["gates"]).values())


def test_delivery_rejects_stale_agent_evidence(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path)
    translation_path = path / "translation.zh.json"
    translation = ws.read_translation(translation_path)
    translation.items[0].target = "您好"
    translation_path.write_text(translation.model_dump_json(), encoding="utf-8")

    _write_current_delivery_outputs(path)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    codes = {issue.code for issue in assessment.issues}
    assert assessment.ready is False
    assert "agent_session_stale" in codes


def test_delivery_rejects_translation_without_review_or_agent_evidence(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path, agent_draft=False)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is False
    assert "translation_evidence_missing" in {issue.code for issue in assessment.issues}


def test_delivery_rejects_source_only_ass_even_when_hashes_are_fresh(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path)
    cues = ws.read_cues(path / "cues.json")
    subtitle = path / "out" / "zh.ass"
    subtitle.write_text(
        exportlib.render_ass(cues, exportlib.ExportMode.SOURCE),
        encoding="utf-8",
    )
    ws.record_artifact_provenance(
        path,
        subtitle,
        Stage.EXPORT,
        inputs=[
            path / "cues.json",
            path / "translation.zh.json",
        ],
    )

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert "export_not_bilingual_ass" in {issue.code for issue in assessment.issues}


def test_delivery_detects_segment_stale_after_transcript_change(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    transcript_path = path / "transcript.json"
    transcript = ws.read_transcript(transcript_path)
    transcript.segments[0].text = "Changed source."
    transcript_path.write_text(transcript.model_dump_json(), encoding="utf-8")

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert "segment_stale_artifact" in {issue.code for issue in assessment.issues}


def test_delivery_rejects_zero_duration_cues_even_with_nonempty_burn(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path)
    cues_path = path / "cues.json"
    cues = ws.read_cues(cues_path)
    cues.cues[0].end = cues.cues[0].start
    cues_path.write_text(cues.model_dump_json(), encoding="utf-8")
    ws.refresh_artifact_provenance(path, cues_path, Stage.SEGMENT)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is False
    assert assessment.gates["segment"] is False
    assert "invalid_cue_timeline" in {issue.code for issue in assessment.issues}


def test_delivery_rejects_cues_beyond_source_media_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path)
    cues_path = path / "cues.json"
    cues = ws.read_cues(cues_path)
    cues.cues[0].start = 3.2
    cues.cues[0].end = 4.0
    cues_path.write_text(cues.model_dump_json(), encoding="utf-8")
    ws.refresh_artifact_provenance(path, cues_path, Stage.SEGMENT)
    monkeypatch.setattr(media, "media_duration", lambda _path: 3.0)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is False
    assert assessment.gates["segment"] is False
    assert "cues_exceed_media_duration" in {issue.code for issue in assessment.issues}


def test_delivery_rejects_long_cue_gap_containing_timed_reference_speech(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path, agent_draft=False)
    cues_path = path / "cues.json"
    cues = ws.read_cues(cues_path)
    cues.cues = [
        Cue(id=1, start=0.0, end=2.0, source="Opening sentence."),
        Cue(id=2, start=12.0, end=14.0, source="Closing sentence."),
    ]
    ws.write_text_atomic(cues_path, cues.model_dump_json(indent=2))
    ws.refresh_artifact_provenance(path, cues_path, Stage.SEGMENT)
    ws.write_reference_caption(
        path,
        "WEBVTT\n\n00:00:03.000 --> 00:00:10.000\n"
        "<00:00:03.000><c>there are several clearly timed spoken words "
        "inside this otherwise empty subtitle gap</c>\n",
    )
    monkeypatch.setattr(media, "media_duration", lambda _path: 15.0)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is False
    assert assessment.gates["segment"] is False
    gap_issue = next(
        issue for issue in assessment.issues if issue.code == "reference_speech_gap"
    )
    assert "2.000s-12.000s" in gap_issue.detail


def test_media_duration_is_unknown_when_ffprobe_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_ffprobe(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(media.subprocess, "run", missing_ffprobe)

    assert media.media_duration(tmp_path / "source.mp4") is None


@pytest.mark.parametrize(
    ("relative_path", "expected_code"),
    [
        (".openbbq/asr-review.json", "invalid_asr_review"),
        (".openbbq/agent-session.zh.json", "invalid_agent_session"),
    ],
)
def test_delivery_turns_malformed_sidecars_into_ready_false_issues(
    tmp_path: Path,
    relative_path: str,
    expected_code: str,
) -> None:
    path = _workspace(tmp_path)
    (path / relative_path).write_text("{}", encoding="utf-8")

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is False
    assert expected_code in {issue.code for issue in assessment.issues}


def test_delivery_incomplete_workspace_reports_actionable_gate_not_exception(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_video", ref=str(source)),
        stages={},
    )
    ws.write_manifest(path, manifest)

    assessment = assess_delivery(path, manifest)

    assert assessment.ready is False
    assert assessment.issues[0].code == "translation_not_found"
    assert any(issue.code == "missing_transcribe" for issue in assessment.issues)
