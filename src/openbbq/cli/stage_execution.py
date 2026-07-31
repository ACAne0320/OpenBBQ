"""Process-wide idempotency for long-running mechanical CLI stages."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from inspect import signature
from pathlib import Path
from typing import Any, TypeVar, cast

import typer

from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import Stage, StageStatus

from .output import Output
from .results import Result

_Command = TypeVar("_Command", bound=Callable[..., None])

_NEXT = {
    Stage.FETCH: "openbbq extract-audio",
    Stage.EXTRACT_AUDIO: "openbbq transcribe",
    Stage.TRANSCRIBE: "openbbq segment",
    Stage.SEGMENT: "openbbq translate init <lang>",
}


class ReusedStageResult(Result):
    workspace: str
    stage: Stage
    artifact: str
    reused: bool = True

    def render(self) -> str:
        return f"[green]✓[/] reused completed {self.stage.value}: {self.artifact}"


def run_stage_once(stage: Stage) -> Callable[[_Command], _Command]:
    """Serialize a stage and reuse a completed artifact after lock acquisition."""

    def decorate(command: _Command) -> _Command:
        @wraps(command)
        def wrapped(ctx: typer.Context, *args: Any, **kwargs: Any) -> None:
            bound = signature(command).bind_partial(ctx, *args, **kwargs)
            explicit = bound.arguments.get("workspace")
            path = ws.resolve_workspace(cast(str | None, explicit))
            with ws.stage_execution_lock(path, stage):
                manifest = ws.read_manifest(path)
                state = manifest.stages.get(stage)
                if (
                    state is not None
                    and state.status is StageStatus.DONE
                    and state.artifact is not None
                ):
                    artifact = Path(state.artifact)
                    if not artifact.is_absolute():
                        artifact = path / artifact
                    fresh = artifact.is_file()
                    if fresh and stage is Stage.SEGMENT:
                        try:
                            ws.require_fresh_artifact(path, artifact, stage)
                        except OpenBBQError:
                            fresh = False
                    if fresh:
                        output: Output = ctx.obj
                        output.emit(
                            ReusedStageResult(
                                workspace=str(path),
                                stage=stage,
                                artifact=state.artifact,
                                next=_NEXT.get(stage),
                            )
                        )
                        return
                command(ctx, *args, **kwargs)

        return cast(_Command, wrapped)

    return decorate
