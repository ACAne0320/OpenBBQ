from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, cast

import typer

from ...core import agent_workflow
from ...core import export as exportlib
from ...core import glossary as glossarylib
from ...core import glossary_overlay
from ...core import media
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import Cues, Stage, Translation
from ..delivery import assess_delivery
from ..output import Output
from ..results import Result
from .burn import burn as burn_command
from .export import export as export_command

app = typer.Typer(no_args_is_help=True)


class AgentResult(Result):
    data: dict[str, Any]

    def payload(self) -> dict[str, object]:
        return {"ok": True, **self.data}

    def render(self) -> str:
        action = self.data.get("action") or self.data.get("applied") or "agent"
        if action == "run_command":
            return " ".join(str(value) for value in self.data.get("argv", []))
        if action == "done":
            return f"[green]✓[/] done: {self.data.get('video')}"
        return f"agent: {action}"


class _DiscardOutput:
    json_mode = True

    def emit(self, _result: Result) -> None:
        pass


def _capture_context() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=_DiscardOutput()))


@app.command()
def init(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="source URL or local media")],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="new workspace directory"),
    ] = None,
    to: Annotated[
        str,
        typer.Option("--to", help="target language, e.g. zh"),
    ] = "zh",
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="existing global glossary name"),
    ] = None,
) -> None:
    """Initialize the one-shot editable-draft workflow."""

    output: Output = ctx.obj
    ws.validate_lang(to)
    if glossary is not None:
        glossary_overlay.validate_name(glossary)
        glossarylib.load(glossary)
    path, _manifest = ws.init_workspace(
        source,
        workspace=workspace,
        glossary=glossary,
    )
    with ws.agent_workspace_lock(path):
        agent_workflow.create_session(
            path,
            to,
            glossary_name=glossary,
        )
    output.emit(
        AgentResult(
            data={
                "action": "initialized",
                "workspace": str(path),
                "target_lang": to,
                "terminal": False,
                "must_continue": True,
                "next_argv": [
                    "openbbq",
                    "--json",
                    "agent",
                    "next",
                    "--workspace",
                    str(path),
                ],
            }
        )
    )


@app.command(name="next")
def next_command(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace directory"),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="target language when multiple sessions exist"),
    ] = None,
) -> None:
    """Return the one authoritative next action."""

    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    with ws.agent_workspace_lock(path):
        lang = agent_workflow.resolve_session_lang(path, to)
        session = ws.read_agent_session_optional(path, lang)
        if session is None:
            raise OpenBBQError("agent_session_not_found", lang=lang)
        data = agent_workflow.next_action(path, ws.read_manifest(path), session)
    output.emit(AgentResult(data=data))


@app.command()
def apply(
    ctx: typer.Context,
    response: Annotated[
        str,
        typer.Argument(help="JSON response for the active agent batch"),
    ],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace directory"),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="target language when multiple sessions exist"),
    ] = None,
) -> None:
    """Atomically apply the complete active agent batch response."""

    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    response_path = Path(response).expanduser()
    try:
        raw = response_path.read_text(encoding="utf-8")
    except OSError as error:
        raise OpenBBQError(
            "agent_response_not_found",
            path=str(response_path),
            fix="write the JSON response returned for the active batch",
        ) from error
    with ws.agent_workspace_lock(path):
        lang = agent_workflow.resolve_session_lang(path, to)
        session = ws.read_agent_session_optional(path, lang)
        if session is None:
            raise OpenBBQError("agent_session_not_found", lang=lang)
        data = agent_workflow.apply_response(
            path,
            ws.read_manifest(path),
            session,
            raw,
        )
    output.emit(
        AgentResult(
            data={
                **data,
                "terminal": False,
                "must_continue": True,
                "next_argv": [
                    "openbbq",
                    "--json",
                    "agent",
                    "next",
                    "--workspace",
                    str(path),
                ],
            }
        )
    )


def _fresh_stage_artifact(path: Path, stage: Stage, expected: Path) -> bool:
    manifest = ws.read_manifest(path)
    state = manifest.stages.get(stage)
    if state is None or not state.artifact:
        return False
    recorded = Path(state.artifact)
    if not recorded.is_absolute():
        recorded = path / recorded
    if recorded.resolve() != expected.resolve():
        return False
    try:
        ws.require_fresh_artifact(path, expected, stage)
    except OpenBBQError:
        return False
    return True


def _fresh_agent_subtitle(
    path: Path,
    subtitle: Path,
    cues: Cues,
    worksheet: Translation,
    preset: exportlib.AssPreset,
    lang: str,
) -> bool:
    """Reuse only the exact bilingual ASS recipe owned by ``agent finish``."""

    if not _fresh_stage_artifact(path, Stage.EXPORT, subtitle):
        return False
    try:
        actual = subtitle.read_text(encoding="utf-8")
    except OSError:
        return False
    expected = exportlib.render_ass(
        cues,
        exportlib.ExportMode.BILINGUAL,
        translation=worksheet,
        preset=preset,
        translation_lang=lang,
    )
    return actual == expected


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@app.command()
def finish(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace directory"),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="target language when multiple sessions exist"),
    ] = None,
) -> None:
    """Export, burn, check delivery, and publish learned glossary terms once."""

    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    finish_pid = os.getpid()
    with ws.agent_workspace_lock(path):
        lang = agent_workflow.resolve_session_lang(path, to)
        session = ws.read_agent_session_optional(path, lang)
        if session is None:
            raise OpenBBQError("agent_session_not_found", lang=lang)
        manifest = ws.read_manifest(path)
        lease = session.active_lease
        if session.finished is None and (lease is None or lease.action != "finish"):
            raise OpenBBQError(
                "agent_finish_not_ready",
                fix=f"run openbbq agent next --workspace {path}",
            )
        if session.finish_pid is not None and _pid_alive(session.finish_pid):
            raise OpenBBQError(
                "agent_finish_in_progress",
                pid=session.finish_pid,
                fix="wait for the active openbbq agent finish process",
            )
        if (
            lease is not None
            and lease.action == "finish"
            and not agent_workflow.active_lease_fresh(path, manifest, session)
        ):
            session.active_lease = None
            ws.write_agent_session(path, session)
            raise OpenBBQError(
                "agent_lease_stale",
                fix=f"rerun openbbq agent next --workspace {path}",
            )
        # Claim under the short workspace lock, then release it before the
        # potentially long export/burn operations.
        session.finish_pid = finish_pid
        ws.write_agent_session(path, session)

    try:
        manifest = ws.read_manifest(path)
        session = ws.read_agent_session_optional(path, lang)
        if session is None or session.finish_pid != finish_pid:
            raise OpenBBQError("agent_finish_claim_lost")
        cues_path = ws.require_artifact(
            path, manifest, Stage.SEGMENT, fix="openbbq segment"
        )
        cues = ws.read_cues(cues_path)
        worksheet = ws.read_translation(ws.worksheet_path(path, lang))
        gate = agent_workflow.draft_gate(path, manifest, session, cues, worksheet)
        if not gate.ready:
            raise OpenBBQError(
                "agent_finish_not_ready",
                problems=list(gate.problems),
                fix=f"run openbbq agent next --workspace {path}",
            )
        human_reviewed = agent_workflow.human_review_is_complete(
            path,
            cues,
            worksheet,
        )
        inputs_hash = agent_workflow.draft_inputs_hash(
            path, manifest, session, cues, worksheet
        )
        agent_workflow.record_translation_progress(
            path,
            manifest,
            worksheet,
            complete=True,
        )
        subtitle_rel = f"out/{lang}.ass"
        video_rel = f"out/{lang}-burned.mp4"
        subtitle = path / subtitle_rel
        video = path / video_rel
        source = ws.media_input(manifest, path)
        dimensions = media.video_dimensions(source)
        preset = (
            exportlib.AssPreset.MOBILE
            if dimensions is not None and dimensions.height > dimensions.width
            else exportlib.AssPreset.FANSUB
        )

        if not _fresh_agent_subtitle(
            path,
            subtitle,
            cues,
            worksheet,
            preset,
            lang,
        ):
            export_context = _capture_context()
            export_command(
                export_context,
                workspace=str(path),
                to=lang,
                mode=exportlib.ExportMode.BILINGUAL,
                fmt="ass",
                output=subtitle_rel,
                ass_preset=preset,
                allow_missing=False,
                allow_unreviewed=True,
            )
        if not _fresh_stage_artifact(path, Stage.BURN, video):
            burn_context = _capture_context()
            burn_command(
                burn_context,
                workspace=str(path),
                subtitle=subtitle_rel,
                output=video_rel,
                ffmpeg=None,
                allow_stale=False,
            )

        manifest = ws.read_manifest(path)
        assessment = assess_delivery(path, manifest, lang=lang)
        if not assessment.ready:
            raise OpenBBQError(
                "delivery_not_ready",
                issues=[issue.payload() for issue in assessment.issues],
                fix=assessment.next,
            )
        with ws.agent_workspace_lock(path):
            session = ws.read_agent_session_optional(path, lang)
            if session is None or session.finish_pid != finish_pid:
                raise OpenBBQError("agent_finish_claim_lost")
            publication = (
                glossary_overlay.PublishReport(
                    published=True,
                    terms=(),
                    warnings=(),
                )
                if session.finished is not None and session.finished.glossary_published
                else glossary_overlay.publish(path)
            )
            known_warnings = {
                (warning.code, warning.detail) for warning in session.warnings
            }
            session.warnings.extend(
                warning
                for warning in publication.warnings
                if (warning.code, warning.detail) not in known_warnings
            )
            agent_workflow.record_finished(
                path,
                session,
                inputs_hash=inputs_hash,
                subtitle=subtitle_rel,
                video=video_rel,
                glossary_published=publication.published,
            )
            data = {
                "action": "done",
                "workspace": str(path),
                "target_lang": lang,
                "terminal": True,
                "must_continue": False,
                "subtitle": str(subtitle),
                "video": str(video),
                "artifact_ready": True,
                "quality": "human-reviewed" if human_reviewed else "draft",
                "human_reviewed": human_reviewed,
                "quality_warnings": agent_workflow.draft_warnings(cues, worksheet),
                "glossary_published": publication.published,
                "warnings": [
                    warning.model_dump(mode="json") for warning in session.warnings
                ],
            }
    except BaseException:
        with ws.agent_workspace_lock(path):
            current = ws.read_agent_session_optional(path, lang)
            if current is not None and current.finish_pid == finish_pid:
                current.finish_pid = None
                ws.write_agent_session(path, current)
        raise
    output.emit(AgentResult(data=data))
