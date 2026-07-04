from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from .common import OpenBBQModel, Stage, StageStatus

SourceType = Literal["url", "local_video", "local_audio"]


class Source(OpenBBQModel):
    type: SourceType
    ref: str  # url as-is, or absolute path for local sources
    title: str | None = None  # None until known (url) / file stem (local)
    author: str | None = None  # uploader/channel/creator when known
    thumbnail: str | None = None  # fetched cover image artifact, relative to workspace


class Progress(OpenBBQModel):
    done: int
    total: int | None = None  # None when the total is not yet known
    label: str | None = None  # current subtask, e.g. downloading video or merging


class StageState(OpenBBQModel):
    status: StageStatus
    artifact: str | None = None  # output pointer
    updated_at: datetime | None = None  # heartbeat / last write
    error: str | None = None  # message when status == failed
    progress: Progress | None = None  # long-task heartbeat (see DESIGN §4/§7)


class Manifest(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/manifest@1"], Field(alias="schema")] = (
        "openbbq/manifest@1"
    )
    created_at: datetime
    source: Source
    glossary: str | None = (
        None  # bound glossary name in the global library (DESIGN glossary spec §4)
    )
    stages: dict[Stage, StageState]  # work log: only stages actually run
