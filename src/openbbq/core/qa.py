from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Cues,
    QaFrame,
    QaReport,
    QaVisualIssue,
    QaVisualIssueCode,
    Translation,
)


@dataclass(frozen=True)
class FramePoint:
    cue_id: int
    at: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrameEvidence:
    path: str
    cue_id: int
    at: float
    file: Path
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assessment:
    mechanical_status: Literal["pass", "stale"]
    issues: tuple[str, ...]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise OpenBBQError("missing_input", artifact=str(path)) from error
    return digest.hexdigest()


def select_frame_points(
    cues: Cues,
    *,
    count: int,
    translation: Translation | None = None,
) -> list[FramePoint]:
    if not 1 <= count <= 9:
        raise OpenBBQError("invalid_qa_frame_count", count=count, fix="use 1..9")
    if not cues.cues:
        raise OpenBBQError("qa_no_cues", fix="openbbq segment")
    selected_count = min(count, len(cues.cues))
    reasons: dict[int, list[str]] = {}

    def add(index: int, reason: str) -> None:
        cue_id = cues.cues[index].id
        if cue_id in reasons:
            reasons[cue_id].append(reason)
        elif len(reasons) < selected_count:
            reasons[cue_id] = [reason]

    last = len(cues.cues) - 1
    add(0, "boundary_start")
    add(len(cues.cues) // 2, "timeline_middle")
    add(last, "boundary_end")

    longest_source = max(
        range(len(cues.cues)), key=lambda index: len(cues.cues[index].source)
    )
    add(longest_source, "longest_source")
    shortest_duration = min(
        range(len(cues.cues)),
        key=lambda index: cues.cues[index].end - cues.cues[index].start,
    )
    add(shortest_duration, "shortest_duration")
    highest_source_cps = max(
        range(len(cues.cues)),
        key=lambda index: len(cues.cues[index].source)
        / max(cues.cues[index].end - cues.cues[index].start, 0.001),
    )
    add(highest_source_cps, "highest_source_cps")

    if translation is not None:
        target_by_id = {item.id: item.target or "" for item in translation.items}
        longest_target = max(
            range(len(cues.cues)),
            key=lambda index: len(target_by_id.get(cues.cues[index].id, "")),
        )
        add(longest_target, "longest_target")

    if len(reasons) < selected_count:
        for position in range(selected_count):
            index = (
                len(cues.cues) // 2
                if selected_count == 1
                else round(position * last / (selected_count - 1))
            )
            add(index, "coverage_fill")
    if len(reasons) < selected_count:
        for index in range(len(cues.cues)):
            add(index, "coverage_fill")

    selected_ids = set(reasons)
    return [
        FramePoint(
            cue_id=cue.id,
            at=(cue.start + cue.end) / 2,
            reasons=tuple(reasons[cue.id]),
        )
        for cue in cues.cues
        if cue.id in selected_ids
    ]


def create_report(
    *,
    artifact: str,
    artifact_path: Path,
    duration_s: float,
    frames: list[FrameEvidence],
) -> QaReport:
    try:
        artifact_bytes = artifact_path.stat().st_size
    except OSError as error:
        raise OpenBBQError("missing_input", artifact=str(artifact_path)) from error
    if artifact_bytes <= 0 or duration_s <= 0:
        raise OpenBBQError(
            "invalid_burn_output",
            artifact=str(artifact_path),
            bytes=artifact_bytes,
            duration_s=duration_s,
            fix="openbbq burn",
        )
    return QaReport(
        artifact=artifact,
        artifact_sha256=hash_file(artifact_path),
        artifact_bytes=artifact_bytes,
        duration_s=duration_s,
        frames=[
            QaFrame(
                path=frame.path,
                cue_id=frame.cue_id,
                at=frame.at,
                sha256=hash_file(frame.file),
                reasons=list(frame.reasons),
            )
            for frame in frames
        ],
        created_at=datetime.now(timezone.utc),
    )


def assess(
    report: QaReport,
    *,
    artifact: str,
    artifact_path: Path,
    workspace: Path,
) -> Assessment:
    issues: list[str] = []
    if report.artifact != artifact:
        issues.append("artifact_changed")
    try:
        artifact_bytes = artifact_path.stat().st_size
        artifact_hash = hash_file(artifact_path)
    except (OpenBBQError, OSError):
        issues.append("artifact_missing")
    else:
        if artifact_bytes <= 0:
            issues.append("artifact_empty")
        if artifact_bytes != report.artifact_bytes or artifact_hash != report.artifact_sha256:
            issues.append("artifact_content_changed")
    for frame in report.frames:
        frame_path = Path(frame.path)
        if frame_path.is_absolute():
            issues.append(f"frame_path_invalid:{frame.path}")
            continue
        frame_path = (workspace / frame_path).resolve()
        try:
            frame_path.relative_to(workspace.resolve())
        except ValueError:
            issues.append(f"frame_path_invalid:{frame.path}")
            continue
        try:
            current_hash = hash_file(frame_path)
        except OpenBBQError:
            issues.append(f"frame_missing:{frame.path}")
            continue
        if current_hash != frame.sha256:
            issues.append(f"frame_content_changed:{frame.path}")
    return Assessment(
        mechanical_status="stale" if issues else "pass",
        issues=tuple(issues),
    )


def attest(
    report: QaReport,
    *,
    result: Literal["pass", "fail"],
    reason: str,
    issues: Sequence[QaVisualIssueCode | str] | None = None,
) -> QaReport:
    reason = reason.strip()
    if not reason:
        raise OpenBBQError("invalid_qa_attestation", fix="provide a non-blank --reason")
    issue_codes = [QaVisualIssueCode(code) for code in (issues or [])]
    if result == "fail" and not issue_codes:
        raise OpenBBQError(
            "qa_issue_required",
            fix="add --issue content_error|lower_third_conflict|subtitle_overlap|...",
        )
    if result == "pass" and issue_codes:
        raise OpenBBQError(
            "qa_issue_invalid",
            fix="remove --issue when --result pass",
        )
    return QaReport.model_validate(
        {
            **report.model_dump(mode="python"),
            "schema": "openbbq/qa@2",
            "visual_status": result,
            "visual_reason": reason,
            "visual_attested_at": datetime.now(timezone.utc),
            "visual_issues": [
                QaVisualIssue(code=code, cue_ids=[]) for code in issue_codes
            ],
        }
    )
