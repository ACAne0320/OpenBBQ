from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import RenderableType
from rich.table import Table

from ...core import glossary_overlay
from ...core import translate as translatelib
from ...core import translation_audit as auditlib
from ...core import translation_rules
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import (
    GlossaryRef,
    Manifest,
    OpenBBQModel,
    Progress,
    Stage,
    StageState,
    StageStatus,
    Translation,
    TranslationBrief,
)
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)
_DETAIL_LIMIT = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _filled_count(doc: Translation) -> int:
    return sum(1 for item in doc.items if translatelib.is_filled(item.target))


def _record_translate_progress(
    path: Path,
    manifest: Manifest,
    *,
    artifact: str,
    filled: int,
    total: int,
    complete: bool,
) -> None:
    # One TRANSLATE stage covers all languages; latest worksheet activity wins.
    ws.record_stage(
        path,
        manifest,
        Stage.TRANSLATE,
        StageState(
            status=StageStatus.DONE if complete else StageStatus.RUNNING,
            artifact=artifact,
            updated_at=_now(),
            progress=Progress(done=filled, total=total),
        ),
    )


# --- init ---------------------------------------------------------------------
class TranslateInitResult(Result):
    artifact: str  # worksheet path, relative to the workspace
    cues: int
    target_lang: str
    generic_profile: bool  # True when the latin fallback profile was used
    max_cps: float
    max_chars_per_line: int
    max_lines: int
    ruleset: str
    generic_translation_rules: bool
    policy_hash: str
    elapsed_s: float

    def render(self) -> str:
        gloss = "" if not self.generic_profile else "  (generic latin profile)"
        return (
            f"[green]✓[/] translation worksheet: {self.artifact}\n"
            f"  {self.cues} cues · {self.target_lang}{gloss}\n"
            f"  fill targets in batches: openbbq translate apply {self.target_lang} <targets.json>\n"
            f"  then: openbbq translate check {self.target_lang}"
        )


# --- apply --------------------------------------------------------------------
class TranslateApplyResult(Result):
    lang: str
    applied: int
    overwritten: int
    filled: int
    total: int

    def render(self) -> str:
        over = "" if not self.overwritten else f" ({self.overwritten} overwritten)"
        nxt = (
            f"openbbq translate check {self.lang}"
            if self.filled == self.total
            else f"next batch, or: openbbq translate check {self.lang}"
        )
        return (
            f"[green]✓[/] applied {self.applied} targets · {self.lang}{over}\n"
            f"  {self.filled}/{self.total} filled · {nxt}"
        )


# --- check --------------------------------------------------------------------
class TranslateCheckResult(Result):
    lang: str
    filled: int
    total: int
    missing: list[int]
    over_budget: int
    over_budget_ids: list[int]
    zero_budget: int
    zero_budget_ids: list[int]
    term_warnings: int
    term_issues: list[translatelib.TermIssue]
    quality_warnings: int
    quality_issues: list[translatelib.QualityIssue]
    ready: bool

    def render(self) -> str:
        done = self.ready
        head = "[green]✓[/] complete" if done else "[yellow]·[/] in progress"
        line = f"{head}: {self.filled}/{self.total} cues · {self.lang}"
        if self.missing:
            shown = ", ".join(str(i) for i in self.missing[:_DETAIL_LIMIT])
            more = (
                ""
                if len(self.missing) <= _DETAIL_LIMIT
                else f" (+{len(self.missing) - _DETAIL_LIMIT})"
            )
            line += f"\n  missing: {shown}{more}"
        if self.over_budget:
            shown = ", ".join(str(i) for i in self.over_budget_ids)
            more = (
                ""
                if self.over_budget <= len(self.over_budget_ids)
                else f" (+{self.over_budget - len(self.over_budget_ids)})"
            )
            line += f"\n  [yellow]over budget: {shown}{more}[/]"
        if self.term_warnings:
            line += f"\n  [yellow]term warnings: {self.term_warnings}[/]"
        if self.zero_budget:
            shown = ", ".join(str(i) for i in self.zero_budget_ids)
            line += f"\n  [red]zero-budget cues: {shown}[/]"
        if self.quality_warnings:
            shown = ", ".join(
                f"{issue.id}:{issue.code}" for issue in self.quality_issues
            )
            line += f"\n  [yellow]quality warnings: {shown}[/]"
        return line


@app.command()
def init(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="target language code, e.g. zh")],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option(
            "--glossary", help="glossary name (overrides the manifest binding)"
        ),
    ] = None,
    max_cps: Annotated[
        float | None,
        typer.Option("--max-cps", min=0.1, help="target reading-speed budget"),
    ] = None,
    max_chars_per_line: Annotated[
        int | None,
        typer.Option("--max-chars-per-line", min=1, help="target visual line width"),
    ] = None,
    max_lines: Annotated[
        int | None,
        typer.Option("--max-lines", min=1, max=3, help="target visual lines per cue"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force", help="overwrite an existing worksheet (loses filled targets)"
        ),
    ] = False,
) -> None:
    """Prepare a translation worksheet for LANG from cues + glossary."""
    output: Output = ctx.obj
    started = time.monotonic()
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    cpath = ws.require_artifact(path, manifest, Stage.SEGMENT, fix="openbbq segment")
    cues = ws.read_cues(cpath)

    wpath = ws.worksheet_path(path, lang)  # validates lang
    if wpath.exists() and not force:
        raise OpenBBQError(
            "translation_exists",
            path=str(wpath.relative_to(path)),
            fix="edit it, or pass --force to regenerate (discards filled targets)",
        )

    gloss = glossary_overlay.merged(path, glossary or manifest.glossary)
    doc, generic = translatelib.build_worksheet(
        cues,
        gloss,
        lang,
        max_cps=max_cps,
        max_chars_per_line=max_chars_per_line,
        max_lines=max_lines,
        title=manifest.source.title,
        author=manifest.source.author,
    )
    # no exclude_none: the Agent needs to see `"target": null` fields to fill them
    ws.write_text_atomic(wpath, doc.model_dump_json(indent=2))

    artifact = wpath.name
    _record_translate_progress(
        path,
        manifest,
        artifact=artifact,
        filled=_filled_count(doc),
        total=len(doc.items),
        complete=False,
    )
    output.emit(
        TranslateInitResult(
            artifact=artifact,
            cues=len(doc.items),
            target_lang=lang,
            generic_profile=generic,
            max_cps=doc.params.max_cps,
            max_chars_per_line=doc.params.max_chars_per_line,
            max_lines=doc.params.max_lines,
            ruleset=(doc.brief.ruleset if doc.brief else "generic@1"),
            generic_translation_rules=(
                doc.brief.generic_translation_rules if doc.brief else True
            ),
            policy_hash=(
                translation_rules.policy_hash(doc.brief) if doc.brief else ""
            ),
            elapsed_s=round(time.monotonic() - started, 2),
            next=f"openbbq translate apply {lang} <targets.json>",
        )
    )


@app.command()
def apply(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="target language code, e.g. zh")],
    targets: Annotated[
        str, typer.Argument(help="JSON file mapping cue id → translated text")
    ],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Merge a {id: target} JSON batch into the LANG worksheet (repeatable)."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    wpath = ws.worksheet_path(path, lang)  # validates lang
    if not wpath.is_file():
        raise OpenBBQError(
            "translation_not_found", lang=lang, fix=f"openbbq translate init {lang}"
        )
    tpath = Path(targets)
    if not tpath.is_file():
        raise OpenBBQError(
            "targets_not_found",
            path=targets,
            fix='write a JSON object mapping cue id to translated text: {"1": "译文"}',
        )

    worksheet = ws.read_translation(wpath)
    before = worksheet.model_copy(deep=True)
    existing_audit = ws.read_translation_audit_optional(path, lang)
    batch = translatelib.parse_targets(tpath.read_text(encoding="utf-8"))
    report = translatelib.apply_targets(worksheet, batch)
    updated_audit = auditlib.record_overwrites(before, worksheet, existing_audit)
    # same shape init writes: indented, `"target": null` kept visible
    ws.write_text_atomic(wpath, worksheet.model_dump_json(indent=2))
    if existing_audit is not None or updated_audit.flags or updated_audit.reviews:
        ws.write_translation_audit(path, lang, updated_audit)
    _record_translate_progress(
        path,
        manifest,
        artifact=wpath.name,
        filled=report.filled,
        total=report.total,
        # Only `translate check` can mark the stage done after every gate passes.
        complete=False,
    )
    output.emit(
        TranslateApplyResult(
            lang=lang,
            applied=report.applied,
            overwritten=report.overwritten,
            filled=report.filled,
            total=report.total,
            next=f"openbbq translate check {lang}"
            if report.filled == report.total
            else f"openbbq translate apply {lang} <targets.json>",
        )
    )


def _resolve_lang(path, manifest, explicit: str | None) -> str:
    """Explicit lang, else infer when exactly one worksheet is present."""
    if explicit is not None:
        return explicit
    present = ws.find_worksheets(path)
    if not present:
        raise OpenBBQError("translation_not_found", fix="openbbq translate init <lang>")
    if len(present) > 1:
        raise OpenBBQError(
            "ambiguous_lang",
            langs=present,
            fix="pass the language, e.g. translate check zh",
        )
    return present[0]


def _optional_transcript(path: Path, manifest: Manifest):
    state = manifest.stages.get(Stage.TRANSCRIBE)
    if state is None or state.status is not StageStatus.DONE or not state.artifact:
        return None
    artifact = Path(state.artifact)
    if not artifact.is_absolute():
        artifact = path / artifact
    return ws.read_transcript(artifact) if artifact.is_file() else None


def _audit_context(
    path: Path,
    manifest: Manifest,
    lang: str,
    *,
    coverage: Literal["risks", "all"] = "all",
):
    cpath = ws.require_artifact(path, manifest, Stage.SEGMENT, fix="openbbq segment")
    cues = ws.read_cues(cpath)
    wpath = ws.worksheet_path(path, lang)
    if not wpath.is_file():
        raise OpenBBQError(
            "translation_not_found", lang=lang, fix=f"openbbq translate init {lang}"
        )
    worksheet = ws.read_translation(wpath)
    audit_state = ws.read_translation_audit_optional(path, lang)
    uncertain = auditlib.uncertain_cue_ids(
        cues,
        _optional_transcript(path, manifest),
    )
    risks = auditlib.audit_items(
        cues,
        worksheet,
        audit_state,
        uncertain_ids=uncertain,
        coverage=coverage,
    )
    return cues, wpath, worksheet, audit_state, risks


class TranslateBatchResult(Result):
    lang: str
    selected_ids: list[int]
    items: list[translatelib.BatchItem]
    glossary: list[GlossaryRef]
    brief: TranslationBrief
    policy_hash: str
    next_from: int | None
    remaining: int

    def render(self) -> str:
        if not self.selected_ids:
            return f"[green]✓[/] no matching cues · {self.lang}"
        lines = [
            f"[green]✓[/] batch {self.selected_ids[0]}–{self.selected_ids[-1]} · {self.lang}"
        ]
        for item in self.items:
            marker = "*" if item.selected else "·"
            target = "" if item.target is None else f" → {item.target}"
            lines.append(
                f"  {marker} {item.id} [{item.budget.max_chars}]: {item.source}{target}"
            )
        if self.next_from is not None:
            lines.append(
                f"  next: --from {self.next_from} · {self.remaining} remaining"
            )
        return "\n".join(lines)


@app.command()
def batch(
    ctx: typer.Context,
    lang: Annotated[
        str | None,
        typer.Argument(help="target language (inferred if only one worksheet)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    start: Annotated[
        int, typer.Option("--from", min=1, help="first cue id to consider")
    ] = 1,
    limit: Annotated[
        int, typer.Option("--limit", min=1, max=200, help="selected cues to return")
    ] = 20,
    only_missing: Annotated[
        bool, typer.Option("--only-missing", help="skip cues that already have targets")
    ] = False,
    context: Annotated[
        int,
        typer.Option("--context", min=0, max=5, help="neighbor cues around selections"),
    ] = 1,
) -> None:
    """Read a bounded worksheet slice for context-safe Agent translation."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    resolved = _resolve_lang(path, manifest, lang)
    wpath = ws.worksheet_path(path, resolved)
    if not wpath.is_file():
        raise OpenBBQError(
            "translation_not_found",
            lang=resolved,
            fix=f"openbbq translate init {resolved}",
        )
    worksheet = ws.read_translation(wpath)
    report = translatelib.select_batch(
        worksheet,
        start=start,
        limit=limit,
        only_missing=only_missing,
        context=context,
    )
    brief = worksheet.brief or translation_rules.build_brief(
        worksheet.source_lang,
        worksheet.target_lang,
    )
    output.emit(
        TranslateBatchResult(
            lang=resolved,
            selected_ids=report.selected_ids,
            items=report.items,
            glossary=report.glossary,
            brief=brief,
            policy_hash=translation_rules.policy_hash(brief),
            next_from=report.next_from,
            remaining=report.remaining,
            next=(
                f"openbbq translate batch {resolved} --from {report.next_from} --limit {limit}"
                if report.next_from is not None
                else f"openbbq translate check {resolved}"
            ),
        )
    )


class TranslateAuditContextResult(OpenBBQModel):
    id: int
    source: str
    target: str


class TranslateAuditItemResult(OpenBBQModel):
    id: int
    source: str
    target: str
    used_chars: int
    max_chars: int
    risk_codes: list[str]
    score: int
    reviewed: bool
    previous: TranslateAuditContextResult | None = None
    next_item: TranslateAuditContextResult | None = None


class TranslateAuditResult(Result):
    lang: str
    coverage: Literal["risks", "all"]
    total_risks: int
    reviewed: int
    pending: int
    selected_ids: list[int]
    items: list[TranslateAuditItemResult]
    next_offset: int | None = None
    remaining: int
    ready: bool

    def render(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("id", justify="right")
        table.add_column("risk")
        table.add_column("budget", justify="right")
        table.add_column("source", style="dim")
        table.add_column("target")
        for item in self.items:
            table.add_row(
                str(item.id),
                ", ".join(item.risk_codes),
                f"{item.used_chars}/{item.max_chars}",
                item.source,
                item.target,
            )
        return table


class TranslateAuditApplyResult(Result):
    lang: str
    artifact: str
    reviewed: int
    revised: int
    pending: int
    ready: bool

    def render(self) -> str:
        return (
            f"[green]✓[/] translation audit applied: {self.reviewed} · {self.lang}\n"
            f"  {self.revised} revised · {self.pending} pending"
        )


def _audit_item_result(
    risk: auditlib.RiskItem,
    worksheet: Translation,
    audit_state,
    *,
    require_context: bool,
) -> TranslateAuditItemResult:
    def context(item: auditlib.AuditContext | None):
        if item is None:
            return None
        return TranslateAuditContextResult(
            id=item.id,
            source=item.source,
            target=item.target,
        )

    by_id = {item.id: item for item in worksheet.items}
    return TranslateAuditItemResult(
        id=risk.id,
        source=risk.source,
        target=risk.target,
        used_chars=risk.used_chars,
        max_chars=risk.max_chars,
        risk_codes=list(risk.risk_codes),
        score=risk.score,
        reviewed=(
            auditlib.is_reviewed_in_context(worksheet, risk.id, audit_state)
            if require_context
            else auditlib.is_reviewed(by_id[risk.id], audit_state)
        ),
        previous=context(risk.previous),
        next_item=context(risk.next),
    )


@app.command()
def audit(
    ctx: typer.Context,
    lang: Annotated[
        str | None,
        typer.Argument(help="target language (inferred if only one worksheet)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=auditlib.MAX_DECISION_BATCH),
    ] = 20,
    only_unreviewed: Annotated[
        bool,
        typer.Option("--only-unreviewed/--all", help="exclude current reviewed risks"),
    ] = True,
    coverage: Annotated[
        Literal["risks", "all"],
        typer.Option("--coverage", help="review high risks only, or every cue"),
    ] = "all",
) -> None:
    """Read a bounded semantic review batch; final delivery uses full coverage."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    resolved = _resolve_lang(path, manifest, lang)
    _, _, worksheet, audit_state, risks = _audit_context(
        path, manifest, resolved, coverage=coverage
    )
    require_context = coverage == "all"
    pending = auditlib.pending_items(
        risks,
        worksheet,
        audit_state,
        require_context=require_context,
    )
    candidates = pending if only_unreviewed else risks
    selected = candidates[offset : offset + limit]
    next_offset = offset + len(selected) if offset + len(selected) < len(candidates) else None
    reviewed_count = len(risks) - len(pending)
    output.emit(
        TranslateAuditResult(
            lang=resolved,
            coverage=coverage,
            total_risks=len(risks),
            reviewed=reviewed_count,
            pending=len(pending),
            selected_ids=[item.id for item in selected],
            items=[
                _audit_item_result(
                    item,
                    worksheet,
                    audit_state,
                    require_context=require_context,
                )
                for item in selected
            ],
            next_offset=next_offset,
            remaining=max(len(candidates) - offset - len(selected), 0),
            ready=not pending,
            next=(
                f"openbbq export --to {resolved} --mode bilingual --format ass"
                if not pending
                else f"openbbq translate audit-apply {resolved} <decisions.json>"
            ),
        )
    )


@app.command(name="audit-apply")
def audit_apply(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="target language code, e.g. zh")],
    decisions: Annotated[
        str,
        typer.Argument(help="JSON object keyed by risky cue id"),
    ],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    coverage: Annotated[
        Literal["risks", "all"],
        typer.Option("--coverage", help="review high risks only, or every cue"),
    ] = "all",
) -> None:
    """Accept or revise a bounded translation-audit batch with reasons."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    cues, wpath, worksheet, audit_state, risks = _audit_context(
        path, manifest, lang, coverage=coverage
    )
    decisions_path = Path(decisions).expanduser()
    try:
        parsed = auditlib.parse_decisions(decisions_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise OpenBBQError(
            "translation_audit_not_found",
            path=str(decisions_path),
            fix="write the audit decision JSON and try again",
        ) from error
    report = auditlib.apply_decisions(
        cues,
        worksheet,
        audit_state,
        risks,
        parsed,
        coverage=coverage,
    )
    if report.revised:
        ws.write_text_atomic(wpath, worksheet.model_dump_json(indent=2))
    artifact = ws.write_translation_audit(path, lang, report.audit)
    if report.revised:
        _record_translate_progress(
            path,
            manifest,
            artifact=wpath.name,
            filled=_filled_count(worksheet),
            total=len(worksheet.items),
            complete=False,
        )
    updated_risks = auditlib.audit_items(
        cues,
        worksheet,
        report.audit,
        uncertain_ids=auditlib.uncertain_cue_ids(
            cues,
            _optional_transcript(path, manifest),
        ),
        coverage=coverage,
    )
    pending = auditlib.pending_items(
        updated_risks,
        worksheet,
        report.audit,
        require_context=coverage == "all",
    )
    output.emit(
        TranslateAuditApplyResult(
            lang=lang,
            artifact=str(artifact.relative_to(path)),
            reviewed=report.reviewed,
            revised=report.revised,
            pending=len(pending),
            ready=not pending,
            next=(
                f"openbbq export --to {lang} --mode bilingual --format ass"
                if not pending
                else f"openbbq translate audit {lang} --limit 20"
            ),
        )
    )


@app.command()
def check(
    ctx: typer.Context,
    lang: Annotated[
        str | None,
        typer.Argument(help="target language (inferred if only one worksheet)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Validate a worksheet against its cues; report completeness + term warnings."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    cpath = ws.require_artifact(path, manifest, Stage.SEGMENT, fix="openbbq segment")
    cues = ws.read_cues(cpath)

    resolved = _resolve_lang(path, manifest, lang)
    wpath = ws.worksheet_path(path, resolved)
    if not wpath.is_file():
        raise OpenBBQError(
            "translation_not_found",
            lang=resolved,
            fix=f"openbbq translate init {resolved}",
        )
    worksheet = ws.read_translation(wpath)
    report = translatelib.check(cues, worksheet, resolved)
    output.emit(
        TranslateCheckResult(
            lang=resolved,
            filled=report.filled,
            total=report.total,
            missing=report.missing,
            over_budget=len(report.over_budget),
            over_budget_ids=report.over_budget[:_DETAIL_LIMIT],
            zero_budget=len(report.zero_budget),
            zero_budget_ids=report.zero_budget[:_DETAIL_LIMIT],
            term_warnings=report.term_warnings,
            term_issues=report.term_issues[:_DETAIL_LIMIT],
            quality_warnings=report.quality_warnings,
            quality_issues=report.quality_issues[:_DETAIL_LIMIT],
            ready=report.ready,
            next=f"openbbq translate audit {resolved} --limit 20"
            if report.ready
            else f"openbbq translate batch {resolved} --limit 20",
        )
    )
