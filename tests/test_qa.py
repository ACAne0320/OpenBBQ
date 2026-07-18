from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from pydantic import ValidationError

from openbbq.cli.commands.qa import attest as attest_cmd
from openbbq.cli.commands.qa import check as check_cmd
from openbbq.cli.commands.qa import render as render_cmd
from openbbq.cli.output import Output
from openbbq.core import media
from openbbq.core import qa as qalib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Cue,
    Cues,
    Manifest,
    QaFrame,
    QaReport,
    QaVisualIssueCode,
    SegmentParams,
    Source,
    Stage,
    StageState,
    StageStatus,
    Translation,
    TranslationItem,
    Budget,
)


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _payload(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return cast(dict[str, object], json.loads(capsys.readouterr().out))


def _cues() -> Cues:
    return Cues(
        source_lang="en",
        params=SegmentParams(
            max_cps=21,
            max_chars_per_line=50,
            max_lines=1,
            min_dur=1,
            max_dur=7,
            min_gap=0.083,
        ),
        cues=[
            Cue(id=index, start=(index - 1) * 2, end=index * 2, source=f"cue {index}")
            for index in range(1, 6)
        ],
    )


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    cues = path / "cues.json"
    cues.write_text(_cues().model_dump_json(), encoding="utf-8")
    subtitle = path / "out" / "zh.ass"
    subtitle.parent.mkdir()
    subtitle.write_text("[Script Info]\n", encoding="utf-8")
    video = path / "out" / "zh-burned.mp4"
    video.write_bytes(b"burned-video")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_video", ref=str(source)),
        stages={
            Stage.SEGMENT: StageState(
                status=StageStatus.DONE,
                artifact="cues.json",
            ),
            Stage.BURN: StageState(
                status=StageStatus.DONE,
                artifact="out/zh-burned.mp4",
            ),
        },
    )
    ws.write_manifest(path, manifest)
    ws.record_artifact_provenance(
        path,
        video,
        Stage.BURN,
        inputs=[source, subtitle],
    )
    return path, video


def _patch_render(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_render(
        src: Path,
        dst: Path,
        *,
        at_s: float,
        ffmpeg: str | None = None,
    ) -> str:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(f"frame at {at_s}".encode())
        return ffmpeg or "/fake/ffmpeg"

    monkeypatch.setattr(media, "render_video_frame", fake_render)
    monkeypatch.setattr(media, "media_duration", lambda path: 10.0)


def test_select_frame_points_spans_first_middle_last_cues() -> None:
    points = qalib.select_frame_points(_cues(), count=3)
    assert [(point.cue_id, point.at) for point in points] == [
        (1, 1.0),
        (3, 5.0),
        (5, 9.0),
    ]


def test_select_frame_points_prioritizes_seven_distinct_visual_risks() -> None:
    cues = Cues(
        source_lang="en",
        params=_cues().params,
        cues=[
            Cue(id=1, start=0, end=2, source="first"),
            Cue(id=2, start=2, end=12, source="a very long source subtitle line here"),
            Cue(id=3, start=12, end=12.2, source="short"),
            Cue(id=4, start=13, end=14, source="many source words packed tightly"),
            Cue(id=5, start=14, end=16, source="middle"),
            Cue(id=6, start=16, end=20, source="target risk"),
            Cue(id=7, start=20, end=22, source="filler seven"),
            Cue(id=8, start=22, end=24, source="filler eight"),
            Cue(id=9, start=24, end=26, source="last"),
        ],
    )
    translation = Translation(
        source_lang="en",
        target_lang="zh",
        params=_cues().params,
        items=[
            TranslationItem(
                id=cue.id,
                source=cue.source,
                target="这是一个特别长、最容易产生换行或遮挡问题的译文" if cue.id == 6 else "译文",
                budget=Budget(max_chars=40, seconds=cue.end - cue.start),
            )
            for cue in cues.cues
        ],
    )

    points = qalib.select_frame_points(cues, count=7, translation=translation)

    assert [point.cue_id for point in points] == [1, 2, 3, 4, 5, 6, 9]
    reasons = {reason for point in points for reason in point.reasons}
    assert {
        "boundary_start",
        "timeline_middle",
        "boundary_end",
        "longest_source",
        "longest_target",
        "shortest_duration",
        "highest_source_cps",
    } <= reasons


def test_qa_report_rejects_fake_visual_status_without_attestation() -> None:
    with pytest.raises(ValidationError):
        QaReport.model_validate(
            {
                "artifact": "out/video.mp4",
                "artifact_sha256": "0" * 64,
                "artifact_bytes": 1,
                "duration_s": 1,
                "frames": [
                    {"path": "frame.png", "cue_id": 1, "at": 0.5, "sha256": "1" * 64}
                ],
                "created_at": datetime.now(timezone.utc),
                "visual_status": "pass",
            }
        )


def test_qa_v2_rejects_visual_failure_without_structured_issue() -> None:
    with pytest.raises(ValidationError):
        QaReport.model_validate(
            {
                "artifact": "out/video.mp4",
                "artifact_sha256": "0" * 64,
                "artifact_bytes": 1,
                "duration_s": 1,
                "frames": [
                    {"path": "frame.png", "cue_id": 1, "at": 0.5, "sha256": "1" * 64}
                ],
                "created_at": datetime.now(timezone.utc),
                "visual_status": "fail",
                "visual_reason": "Subtitle overlaps the speaker label.",
                "visual_attested_at": datetime.now(timezone.utc),
            }
        )


def test_assessment_rejects_frame_paths_outside_workspace(tmp_path: Path) -> None:
    path, video = _workspace(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"frame")
    report = QaReport(
        artifact="out/zh-burned.mp4",
        artifact_sha256=qalib.hash_file(video),
        artifact_bytes=video.stat().st_size,
        duration_s=10,
        frames=[
            QaFrame(
                path="../outside.png",
                cue_id=1,
                at=1,
                sha256=qalib.hash_file(outside),
            )
        ],
        created_at=datetime.now(timezone.utc),
    )

    assessment = qalib.assess(
        report,
        artifact="out/zh-burned.mp4",
        artifact_path=video,
        workspace=path,
    )

    assert assessment.mechanical_status == "stale"
    assert assessment.issues == ("frame_path_invalid:../outside.png",)


def test_render_records_mechanical_evidence_without_claiming_visual_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path)
    _patch_render(monkeypatch)

    render_cmd(_ctx(), workspace=str(path), count=3)

    payload = _payload(capsys)
    report = ws.read_qa_optional(path)
    assert report is not None
    assert payload["mechanical_status"] == "pass"
    assert payload["visual_status"] == "not_performed"
    assert report.visual_status == "not_performed"
    assert [frame.cue_id for frame in report.frames] == [1, 3, 5]


def test_check_is_read_only_and_attestation_becomes_stale_with_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, video = _workspace(tmp_path)
    _patch_render(monkeypatch)
    render_cmd(_ctx(), workspace=str(path))
    capsys.readouterr()
    before = {
        file.relative_to(path): file.read_bytes()
        for file in path.rglob("*")
        if file.is_file()
    }

    check_cmd(_ctx(), workspace=str(path))

    assert _payload(capsys)["mechanical_status"] == "pass"
    after = {
        file.relative_to(path): file.read_bytes()
        for file in path.rglob("*")
        if file.is_file()
    }
    assert after == before
    attest_cmd(
        _ctx(),
        result="pass",
        reason="All three frames show both subtitle lines inside the safe area.",
        workspace=str(path),
    )
    assert _payload(capsys)["visual_status"] == "pass"
    video.write_bytes(b"modified-after-attestation")

    check_cmd(_ctx(), workspace=str(path))

    stale = _payload(capsys)
    assert stale["mechanical_status"] == "stale"
    assert stale["visual_status"] == "stale"
    issues = stale["mechanical_issues"]
    assert isinstance(issues, list)
    assert "artifact_content_changed" in issues


def test_failed_attestation_requires_structured_issue_and_suggests_compact_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path)
    _patch_render(monkeypatch)
    render_cmd(_ctx(), workspace=str(path))
    capsys.readouterr()

    with pytest.raises(OpenBBQError) as raised:
        attest_cmd(
            _ctx(),
            result="fail",
            reason="Subtitle overlaps the video's lower third.",
            issue=None,
            workspace=str(path),
        )
    assert raised.value.code == "qa_issue_required"

    attest_cmd(
        _ctx(),
        result="fail",
        reason="Subtitle overlaps the video's lower third.",
        issue=[QaVisualIssueCode.LOWER_THIRD_CONFLICT],
        workspace=str(path),
    )

    payload = _payload(capsys)
    assert payload["visual_issues"] == [
        {"code": "lower_third_conflict", "cue_ids": []}
    ]
    next_step = payload["next"]
    assert isinstance(next_step, str)
    assert "fansub-compact" in next_step


def test_failed_rerender_keeps_previous_qa_report_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path)
    _patch_render(monkeypatch)
    render_cmd(_ctx(), workspace=str(path))
    capsys.readouterr()
    previous = ws.qa_path(path).read_bytes()
    calls = 0

    def fail_second_frame(
        src: Path,
        dst: Path,
        *,
        at_s: float,
        ffmpeg: str | None = None,
    ) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OpenBBQError("ffmpeg_failed", detail="simulated failure")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"new frame")
        return "/fake/ffmpeg"

    monkeypatch.setattr(media, "render_video_frame", fail_second_frame)

    with pytest.raises(OpenBBQError):
        render_cmd(_ctx(), workspace=str(path))

    assert ws.qa_path(path).read_bytes() == previous
    check_cmd(_ctx(), workspace=str(path))
    assert _payload(capsys)["mechanical_status"] == "pass"
