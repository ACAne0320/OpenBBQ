from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

import pytest

from openbbq.cli import main
from openbbq.cli.commands.status import StatusResult
from openbbq.cli.delivery import assess_delivery
from openbbq.core import qa as qalib
from openbbq.core import export as exportlib
from openbbq.core import translation_audit as auditlib
from openbbq.core import workspace as ws
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
    TranslationAuditDecision,
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
    visual_status: Literal["pass", "fail"] = "pass",
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
                target="你好",
                budget=Budget(max_chars=20, seconds=3),
            )
        ],
    )
    translation_path = path / "translation.zh.json"
    translation_path.write_text(translation.model_dump_json(), encoding="utf-8")
    audit_items = auditlib.audit_items(cues, translation, None, coverage="all")
    audit = auditlib.apply_decisions(
        cues,
        translation,
        None,
        audit_items,
        {
            1: TranslationAuditDecision(
                action="accept",
                reason="The source meaning and Chinese translation match.",
            )
        },
        coverage="all",
    ).audit
    ws.write_translation_audit(path, "zh", audit)

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

    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_video", ref=str(source)),
        stages={
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
    ws.record_artifact_provenance(
        path,
        subtitle,
        Stage.EXPORT,
        inputs=[cues_path, translation_path, ws.translation_audit_path(path, "zh")],
    )
    ws.record_artifact_provenance(
        path,
        burned,
        Stage.BURN,
        inputs=[source, subtitle],
    )

    frame = path / ".openbbq" / "qa" / "frame.png"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"frame")
    report = qalib.create_report(
        artifact="out/zh-burned.mp4",
        artifact_path=burned,
        duration_s=3,
        frames=[
            qalib.FrameEvidence(
                path=str(frame.relative_to(path)), cue_id=1, at=1.5, file=frame
            )
        ],
    )
    report = qalib.attest(
        report,
        result=visual_status,
        reason="Every rendered frame was inspected.",
        issues=["subtitle_overlap"] if visual_status == "fail" else None,
    )
    ws.write_qa(path, report)
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


def test_delivery_assessment_passes_complete_fresh_workflow(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path)

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is True
    assert assessment.issues == ()
    assert assessment.lang == "zh"

    status = StatusResult.of(path, ws.read_manifest(path)).payload()
    assert status["delivery_ready"] is True
    assert status["delivery_lang"] == "zh"
    assert status["delivery_issues"] == []


def test_delivery_cli_visual_failure_does_not_block_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _workspace(tmp_path, visual_status="fail")

    code, payload = _run_cli(
        ["--json", "delivery", "check", "--workspace", str(path), "--to", "zh"],
        monkeypatch,
        capsys,
    )

    assert code == 0
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert "qa_visual" not in cast(dict[str, bool], payload["gates"])


def test_delivery_does_not_require_rendered_frame_qa(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    ws.qa_path(path).unlink()

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is True
    assert assessment.gates["qa_mechanical"] is True
    assert "qa_visual" not in assessment.gates


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
    assert payload["ready"] is True
    assert payload["issues"] == []
    assert all(cast(dict[str, bool], payload["gates"]).values())


def test_delivery_detects_stale_full_coverage_semantic_review(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    translation_path = path / "translation.zh.json"
    translation = ws.read_translation(translation_path)
    translation.items[0].target = "您好"
    translation_path.write_text(translation.model_dump_json(), encoding="utf-8")

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    codes = {issue.code for issue in assessment.issues}
    assert assessment.ready is False
    assert "translation_audit_incomplete" in codes
    assert "export_stale_artifact" in codes


def test_delivery_rejects_source_only_ass_even_when_hashes_are_fresh(tmp_path: Path) -> None:
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
            ws.translation_audit_path(path, "zh"),
        ],
    )

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert "export_not_bilingual_ass" in {
        issue.code for issue in assessment.issues
    }


def test_delivery_detects_segment_stale_after_transcript_change(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    transcript_path = path / "transcript.json"
    transcript = ws.read_transcript(transcript_path)
    transcript.segments[0].text = "Changed source."
    transcript_path.write_text(transcript.model_dump_json(), encoding="utf-8")

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert "segment_stale_artifact" in {
        issue.code for issue in assessment.issues
    }


@pytest.mark.parametrize(
    ("relative_path", "expected_code"),
    [
        (".openbbq/asr-review.json", "invalid_asr_review"),
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


def test_delivery_ignores_optional_malformed_visual_qa(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    ws.qa_path(path).write_text("{}", encoding="utf-8")

    assessment = assess_delivery(path, ws.read_manifest(path), lang="zh")

    assert assessment.ready is True


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
