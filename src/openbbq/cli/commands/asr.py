from __future__ import annotations

import shlex
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import RenderableType
from rich.table import Table

from ...core import asr_review as reviewlib
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import AsrReview, OpenBBQModel, Stage
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)
_DETAIL_LIMIT = 20


class AsrContextWordReport(OpenBBQModel):
    index: int
    word: str
    prob: float | None = None


class AsrIssueReport(OpenBBQModel):
    id: str
    kind: Literal["word", "anomaly"]
    segment_id: int | None = None
    segment_ids: list[int] | None = None
    word_index: int | None = None
    word: str | None = None
    start: float
    end: float
    prob: float | None = None
    segment: str
    context: list[AsrContextWordReport] | None = None
    code: str | None = None
    severity: str | None = None
    previous: str | None = None
    next_segment: str | None = None
    words_per_second: float | None = None
    find: str | None = None
    replacement: str | None = None
    reference_text: str | None = None
    reference_caption: str | None = None
    resolved: bool


def _issue_report(
    issue: reviewlib.Issue | reviewlib.Anomaly,
    *,
    resolved: bool,
    captions: list[reviewlib.ReferenceCaption],
) -> AsrIssueReport:
    caption = reviewlib.reference_caption_text(
        captions,
        start=issue.start,
        end=issue.end,
    )
    if isinstance(issue, reviewlib.Anomaly):
        return AsrIssueReport(
            id=issue.id,
            kind="anomaly",
            segment_ids=list(issue.segment_ids),
            start=issue.start,
            end=issue.end,
            segment=issue.text,
            code=issue.code,
            severity=issue.severity,
            previous=issue.previous_text,
            next_segment=issue.next_text,
            words_per_second=issue.words_per_second,
            find=issue.find,
            replacement=issue.replacement,
            reference_text=issue.reference_text,
            reference_caption=caption,
            resolved=resolved,
        )
    return AsrIssueReport(
        id=issue.id,
        kind="word",
        segment_id=issue.segment_id,
        word_index=issue.word_index,
        word=issue.word,
        start=issue.start,
        end=issue.end,
        prob=issue.prob,
        segment=issue.segment_text,
        context=[
            AsrContextWordReport(index=word.index, word=word.word, prob=word.prob)
            for word in issue.context
        ],
        reference_caption=caption,
        resolved=resolved,
    )


class AsrCheckResult(Result):
    transcript_hash: str
    max_prob: float
    total: int
    word_issues: int
    anomalies: int
    resolved: int
    unresolved: int
    unresolved_ids: list[str]
    stale: bool
    ready: bool
    reference_caption_available: bool

    def render(self) -> str:
        state = "ready" if self.ready else "review required"
        stale = " · stale review" if self.stale else ""
        return (
            f"ASR review: {state}{stale}\n"
            f"  {self.resolved}/{self.total} resolved · {self.unresolved} unresolved"
            f" · {self.anomalies} segment anomaly(s)"
        )


class AsrBatchResult(Result):
    transcript_hash: str
    max_prob: float
    selected_ids: list[str]
    items: list[AsrIssueReport]
    next_offset: int | None = None
    remaining: int
    stale: bool
    reference_caption_available: bool

    def render(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("id")
        table.add_column("time", justify="right")
        table.add_column("prob", justify="right")
        table.add_column("word")
        table.add_column("segment", style="dim")
        for item in self.items:
            table.add_row(
                item.id,
                f"{item.start:.2f}s",
                f"{item.prob:.2f}" if item.prob is not None else item.severity or "—",
                item.word or item.code or "—",
                item.segment,
            )
        return table


class AsrApplyResult(Result):
    artifact: str
    applied: int
    total: int
    resolved: int
    unresolved: int
    ready: bool

    def render(self) -> str:
        return (
            f"[green]✓[/] ASR decisions applied: {self.applied}\n"
            f"  {self.resolved}/{self.total} resolved · {self.unresolved} unresolved"
        )


class AsrAmendResult(Result):
    artifact: str
    applied: int
    amendment_ids: list[str]
    ready: bool

    def render(self) -> str:
        return (
            f"[green]✓[/] contextual ASR corrections applied: {self.applied}\n"
            f"  artifact: {self.artifact}"
        )


def _load(workspace: str | None):
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    transcript_path = ws.require_artifact(
        path, manifest, Stage.TRANSCRIBE, fix="openbbq transcribe"
    )
    transcript = ws.read_transcript(transcript_path)
    review = ws.read_asr_review_optional(path)
    reference_texts = [
        text
        for text in (manifest.source.title, manifest.source.author)
        if manifest.source.type == "url" and text
    ]
    caption_source = ws.read_reference_caption_optional(path)
    captions = (
        reviewlib.parse_reference_captions(caption_source)
        if caption_source is not None
        else []
    )
    reference_words = (
        reviewlib.parse_reference_words(caption_source)
        if caption_source is not None
        else []
    )
    return path, transcript, review, reference_texts, captions, reference_words


def _write_review_and_invalidate(path: Path, review: AsrReview) -> Path:
    artifact = ws.write_asr_review(path, review)
    manifest = ws.read_manifest(path)
    transcribe_state = manifest.stages.get(Stage.TRANSCRIBE)
    if transcribe_state is not None:
        # Review data is an input to segmentation. Re-recording transcribe
        # invalidates later artifacts without changing transcript.json itself.
        ws.record_stage(path, manifest, Stage.TRANSCRIBE, transcribe_state)
    return artifact


@app.command()
def check(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    max_prob: Annotated[
        float,
        typer.Option(
            "--max-prob", help="review word occurrences below this probability"
        ),
    ] = reviewlib.DEFAULT_MAX_PROB,
) -> None:
    """Report whether every ASR word issue and segment anomaly has a decision."""
    output: Output = ctx.obj
    path, transcript, review, reference_texts, captions, reference_words = _load(
        workspace
    )
    workspace_arg = shlex.quote(str(path))
    report = reviewlib.check(
        transcript,
        review,
        max_prob=max_prob,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    output.emit(
        AsrCheckResult(
            transcript_hash=report.transcript_hash,
            max_prob=report.max_prob,
            total=len(report.issues),
            word_issues=len(report.word_issues),
            anomalies=len(report.anomalies),
            resolved=len(report.resolved_ids),
            unresolved=len(report.unresolved_ids),
            unresolved_ids=report.unresolved_ids[:_DETAIL_LIMIT],
            stale=report.stale,
            ready=report.ready,
            reference_caption_available=bool(captions),
            next=(
                f"openbbq glossary suggest --workspace {workspace_arg}"
                if report.ready
                else f"openbbq asr batch --workspace {workspace_arg} --limit 20"
            ),
        )
    )


@app.command()
def batch(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    offset: Annotated[
        int, typer.Option("--offset", help="zero-based result offset")
    ] = 0,
    limit: Annotated[
        int, typer.Option("--limit", help="maximum issues to return")
    ] = 20,
    only_unresolved: Annotated[
        bool,
        typer.Option("--only-unresolved/--all", help="exclude already resolved issues"),
    ] = True,
    max_prob: Annotated[
        float,
        typer.Option(
            "--max-prob", help="review word occurrences below this probability"
        ),
    ] = reviewlib.DEFAULT_MAX_PROB,
) -> None:
    """Read a bounded batch of ASR anomalies followed by word occurrences."""
    if offset < 0 or not 1 <= limit <= reviewlib.MAX_DECISION_BATCH:
        raise OpenBBQError(
            "invalid_batch",
            offset=offset,
            limit=limit,
            fix=f"use --offset >= 0 and --limit from 1 to {reviewlib.MAX_DECISION_BATCH}",
        )
    output: Output = ctx.obj
    path, transcript, review, reference_texts, captions, reference_words = _load(
        workspace
    )
    workspace_arg = shlex.quote(str(path))
    report = reviewlib.check(
        transcript,
        review,
        max_prob=max_prob,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    resolved = set(report.resolved_ids)
    candidates = [
        issue
        for issue in report.issues
        if not only_unresolved or issue.id not in resolved
    ]
    selected = candidates[offset : offset + limit]
    next_offset = (
        offset + len(selected) if offset + len(selected) < len(candidates) else None
    )
    output.emit(
        AsrBatchResult(
            transcript_hash=report.transcript_hash,
            max_prob=report.max_prob,
            selected_ids=[issue.id for issue in selected],
            items=[
                _issue_report(
                    issue,
                    resolved=issue.id in resolved,
                    captions=captions,
                )
                for issue in selected
            ],
            next_offset=next_offset,
            remaining=max(len(candidates) - offset - len(selected), 0),
            stale=report.stale,
            reference_caption_available=bool(captions),
            next=(
                f"openbbq asr batch --workspace {workspace_arg} "
                f"--offset {next_offset} --limit {limit}"
                if next_offset is not None
                else f"openbbq asr apply --workspace {workspace_arg} <decisions.json>"
            ),
        )
    )


@app.command(name="apply")
def apply(
    ctx: typer.Context,
    decisions: Annotated[
        str,
        typer.Argument(help="JSON object keyed by ASR issue id"),
    ],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    max_prob: Annotated[
        float,
        typer.Option(
            "--max-prob", help="review word occurrences below this probability"
        ),
    ] = reviewlib.DEFAULT_MAX_PROB,
) -> None:
    """Merge explicit accept/replace/drop/keep_first ASR decisions."""
    output: Output = ctx.obj
    path, transcript, review, reference_texts, _, reference_words = _load(workspace)
    decisions_path = Path(decisions).expanduser()
    try:
        raw = decisions_path.read_text(encoding="utf-8")
    except OSError as error:
        raise OpenBBQError(
            "asr_decisions_not_found",
            path=str(decisions_path),
            fix="write the decision JSON and try again",
        ) from error
    parsed = reviewlib.parse_decisions(raw)
    merged = reviewlib.merge_decisions(
        transcript,
        review,
        parsed,
        max_prob=max_prob,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    artifact = _write_review_and_invalidate(path, merged)
    workspace_arg = shlex.quote(str(path))
    report = reviewlib.check(
        transcript,
        merged,
        max_prob=max_prob,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    output.emit(
        AsrApplyResult(
            artifact=str(artifact.relative_to(path)),
            applied=len(parsed),
            total=len(report.issues),
            resolved=len(report.resolved_ids),
            unresolved=len(report.unresolved_ids),
            ready=report.ready,
            next=(
                f"openbbq glossary suggest --workspace {workspace_arg}"
                if report.ready
                else f"openbbq asr batch --workspace {workspace_arg} "
                "--limit 20 --only-unresolved"
            ),
        )
    )


@app.command()
def amend(
    ctx: typer.Context,
    amendments: Annotated[
        str,
        typer.Argument(help="JSON file with contextual ASR amendments"),
    ],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Apply agent-found phrase corrections without a detector issue id."""

    output: Output = ctx.obj
    path, transcript, review, reference_texts, _, reference_words = _load(workspace)
    amendments_path = Path(amendments).expanduser()
    try:
        raw = amendments_path.read_text(encoding="utf-8")
    except OSError as error:
        raise OpenBBQError(
            "asr_amendments_not_found",
            path=str(amendments_path),
            fix="write the amendment JSON and try again",
        ) from error
    parsed = reviewlib.parse_amendments(raw)
    merged, amendment_ids = reviewlib.merge_amendments(
        transcript,
        review,
        parsed,
    )
    artifact = _write_review_and_invalidate(path, merged)
    workspace_arg = shlex.quote(str(path))
    report = reviewlib.check(
        transcript,
        merged,
        max_prob=merged.max_prob,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    output.emit(
        AsrAmendResult(
            artifact=str(artifact.relative_to(path)),
            applied=len(parsed),
            amendment_ids=amendment_ids,
            ready=report.ready,
            next=(
                f"openbbq glossary suggest --workspace {workspace_arg}"
                if report.ready
                else f"openbbq asr batch --workspace {workspace_arg} "
                "--limit 20 --only-unresolved"
            ),
        )
    )
