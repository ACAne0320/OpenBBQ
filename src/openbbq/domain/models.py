from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "text",
        "video",
        "audio",
        "image",
        "asr_transcript",
        "subtitle_segments",
        "glossary",
        "translation",
        "subtitle",
    }
)


@dataclass(frozen=True, slots=True)
class ProjectMetadata:
    id: str | None
    name: str


@dataclass(frozen=True, slots=True)
class StorageConfig:
    root: Path
    artifacts: Path
    state: Path


@dataclass(frozen=True, slots=True)
class PluginConfig:
    paths: tuple[Path, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class StepOutput:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class StepConfig:
    id: str
    name: str
    tool_ref: str
    inputs: dict[str, Any]
    outputs: tuple[StepOutput, ...]
    parameters: dict[str, Any]
    on_error: str
    max_retries: int
    pause_before: bool = False
    pause_after: bool = False


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    id: str
    name: str
    steps: tuple[StepConfig, ...]


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    version: int
    root_path: Path
    config_path: Path
    project: ProjectMetadata
    storage: StorageConfig
    plugins: PluginConfig
    workflows: dict[str, WorkflowConfig]

    @property
    def plugin_paths(self) -> tuple[Path, ...]:
        return self.plugins.paths
