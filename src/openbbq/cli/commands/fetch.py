from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console, Group, RenderableType
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress as RichProgress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.style import Style
from rich.table import Table
from rich.text import Text

from ...core import fetch as fetchlib
from ...core import workspace as ws
from ...schemas import Manifest, Progress, Stage, StageState, StageStatus
from ..output import Output
from ..results import Result
from ..stage_execution import run_stage_once


class FetchResult(Result):
    workspace: str
    artifact: str
    title: str | None = None
    author: str | None = None
    thumbnail: str | None = None
    auth: str | None = None
    max_height: int | None = None
    reference_caption: str | None = None

    def _artifact_text(self, artifact: str) -> Text:
        uri = (Path(self.workspace) / artifact).resolve().as_uri()
        return Text(artifact, style=Style(color="cyan", link=uri))

    def _workspace_text(self) -> Text:
        uri = Path(self.workspace).resolve().as_uri()
        return Text(self.workspace, style=Style(color="cyan", link=uri))

    def render(self) -> RenderableType:
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", style="dim", no_wrap=True)
        table.add_column(ratio=1)
        if self.title:
            table.add_row("title", Text(self.title, style="bold"))
        if self.author:
            table.add_row("author", Text(self.author))
        table.add_row("workspace", self._workspace_text())
        table.add_row("file", self._artifact_text(self.artifact))
        if self.thumbnail:
            table.add_row("cover", self._artifact_text(self.thumbnail))
        if self.reference_caption:
            table.add_row("ASR reference", self._artifact_text(self.reference_caption))
        if self.auth:
            table.add_row("auth", Text(self.auth))
        if self.max_height is not None:
            table.add_row("quality", Text(f"≤ {self.max_height}p"))
        return Group(Text.assemble(("✓", "green"), (" media fetched", "bold")), table)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip_label(label: str) -> str:
    return f"{label[:87]}..." if len(label) > 90 else label


def _fallback_label(auth_site: str | None) -> str:
    return f"fetch media ({auth_site})" if auth_site else "fetch media"


def _download_action(progress: fetchlib.FetchProgress) -> str:
    if progress.vcodec == "none" and progress.acodec and progress.acodec != "none":
        action = "Downloading audio"
    elif progress.acodec == "none" and progress.vcodec and progress.vcodec != "none":
        action = "Downloading video"
    else:
        action = "Downloading media"
    details = " ".join(
        part for part in (progress.ext, progress.format_note) if part and part != "NA"
    )
    return f"{action} ({details})" if details else action


def _postprocess_action(progress: fetchlib.FetchProgress) -> str:
    return {
        "Merger": "Merging media",
        "MoveFilesAfterDownload": "Moving files",
        "Metadata": "Writing metadata",
        "EmbedThumbnail": "Embedding thumbnail",
        "FFmpegVideoRemuxer": "Remuxing media",
        "FFmpegVideoConvertor": "Converting media",
    }.get(progress.postprocessor or "", "Finalizing")


def _progress_label(
    auth_site: str | None,
    progress: fetchlib.FetchProgress | None = None,
) -> str:
    if progress is None:
        action = "Fetching metadata"
    elif progress.phase == "download":
        action = _download_action(progress)
    elif progress.phase == "postprocess":
        action = _postprocess_action(progress)
    else:
        action = _fallback_label(auth_site)
    return _clip_label(action)


def _record_fetch_running(
    path: Path,
    manifest: Manifest,
    done: int,
    total: int | None,
    label: str | None = None,
) -> None:
    ws.record_stage(
        path,
        manifest,
        Stage.FETCH,
        StageState(
            status=StageStatus.RUNNING,
            progress=Progress(done=done, total=total, label=label),
            updated_at=_now(),
        ),
    )


def _record_fetch_started(path: Path, manifest: Manifest) -> None:
    ws.record_stage(
        path,
        manifest,
        Stage.FETCH,
        StageState(status=StageStatus.RUNNING, updated_at=_now()),
    )


def _metadata_recorder(
    path: Path, manifest: Manifest
) -> Callable[[fetchlib.FetchMetadata], None]:
    def record(metadata: fetchlib.FetchMetadata) -> None:
        ws.record_source_metadata(
            path,
            manifest,
            title=metadata.title,
            author=metadata.author,
            author_if_missing=True,
        )

    return record


def _progress_recorder(
    path: Path,
    manifest: Manifest,
    auth_site: str | None,
    *,
    min_interval_s: float = 0.5,
) -> Callable[[fetchlib.FetchProgress], None]:
    last_write = 0.0
    last_label: str | None = None
    recorded_nonzero = False

    def record(progress: fetchlib.FetchProgress) -> None:
        nonlocal last_label, last_write, recorded_nonzero
        label = _progress_label(auth_site, progress)
        now = time.monotonic()
        first_real_progress = progress.done > 0 and not recorded_nonzero
        label_changed = label != last_label
        if (
            not label_changed
            and not first_real_progress
            and now - last_write < min_interval_s
        ):
            return
        recorded_nonzero = recorded_nonzero or progress.done > 0
        last_label = label
        last_write = now
        _record_fetch_running(path, manifest, progress.done, progress.total, label)

    return record


@run_stage_once(Stage.FETCH)
def fetch(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    auth: Annotated[
        str | None,
        typer.Option("--auth", help="site app session to use, e.g. youtube"),
    ] = None,
    no_auth: Annotated[
        bool,
        typer.Option("--no-auth", help="force anonymous yt-dlp download"),
    ] = False,
    max_height: Annotated[
        int | None,
        typer.Option(
            "--max-height",
            min=144,
            help="limit video height (e.g. 1080); default is yt-dlp best quality",
        ),
    ] = None,
) -> None:
    """Download URL source media with yt-dlp."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    auth_site = (
        None if no_auth else auth or fetchlib.auto_auth_site(manifest.source.ref)
    )
    should_record = manifest.source.type == "url"
    record_progress = _progress_recorder(path, manifest, auth_site)
    record_metadata = _metadata_recorder(path, manifest)
    if should_record:
        _record_fetch_started(path, manifest)
    try:
        if output.json_mode:
            result = fetchlib.fetch_media(
                path,
                manifest,
                auth_site=auth_site,
                max_height=max_height,
                on_progress=record_progress,
                on_metadata=record_metadata,
            )
        else:
            console = Console()
            metadata_status = console.status("Fetching metadata", spinner="dots")
            progress = RichProgress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            )
            task: TaskID | None = None
            status_running = False
            progress_running = False

            def metadata_cb(metadata: fetchlib.FetchMetadata) -> None:
                record_metadata(metadata)

            def cb(fetch_progress: fetchlib.FetchProgress) -> None:
                nonlocal progress_running, status_running, task
                label = _progress_label(auth_site, fetch_progress)
                if fetch_progress.phase == "download":
                    if status_running:
                        metadata_status.stop()
                        status_running = False
                    if not progress_running:
                        progress.start()
                        progress_running = True
                    if task is None:
                        task = progress.add_task(
                            label, total=fetch_progress.total or None
                        )
                    progress.update(
                        task,
                        completed=fetch_progress.done,
                        total=fetch_progress.total or None,
                        description=label,
                    )
                else:
                    if progress_running:
                        progress.stop()
                        progress_running = False
                    metadata_status.update(label)
                    if not status_running:
                        metadata_status.start()
                        status_running = True
                record_progress(fetch_progress)

            try:
                metadata_status.start()
                status_running = True
                result = fetchlib.fetch_media(
                    path,
                    manifest,
                    auth_site=auth_site,
                    max_height=max_height,
                    on_progress=cb,
                    on_metadata=metadata_cb,
                )
            finally:
                if status_running:
                    metadata_status.stop()
                if progress_running:
                    progress.stop()
    except BaseException as err:
        if should_record:
            ws.record_stage(
                path,
                manifest,
                Stage.FETCH,
                StageState(
                    status=StageStatus.FAILED,
                    error="interrupted"
                    if isinstance(err, KeyboardInterrupt)
                    else str(err),
                    updated_at=_now(),
                ),
            )
        raise
    if should_record:
        ws.record_source_metadata(
            path,
            manifest,
            title=result.title,
            author=result.author,
            thumbnail=result.thumbnail,
        )
        ws.record_stage(
            path,
            manifest,
            Stage.FETCH,
            StageState(
                status=StageStatus.DONE,
                artifact=result.artifact,
                updated_at=_now(),
            ),
        )
    output.emit(
        FetchResult(
            workspace=str(path),
            artifact=result.artifact,
            title=result.title,
            author=result.author,
            thumbnail=result.thumbnail,
            auth=result.auth,
            max_height=result.max_height,
            reference_caption=result.reference_caption,
            next="openbbq extract-audio",
        )
    )
