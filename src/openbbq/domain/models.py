from __future__ import annotations

from pathlib import Path
import re
from typing import Literal, TypeAlias

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from openbbq.domain.base import OpenBBQModel, PluginInputs, PluginParameters

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
        "translation_qa",
        "subtitle",
    }
)

IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_-]+$")
OnErrorPolicy: TypeAlias = Literal["abort", "retry", "skip"]


class ProjectMetadata(OpenBBQModel):
    id: str | None = None
    name: str

    @field_validator("id", "name")
    @classmethod
    def nonempty_string(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class StorageConfig(OpenBBQModel):
    root: Path
    artifacts: Path
    state: Path


class PluginConfig(OpenBBQModel):
    paths: tuple[Path, ...] = ()


class StepOutput(OpenBBQModel):
    name: str
    type: str

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("type")
    @classmethod
    def registered_artifact_type(cls, value: str) -> str:
        if value not in ARTIFACT_TYPES:
            raise ValueError(f"Artifact type '{value}' is not registered")
        return value


class StepConfig(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    inputs: PluginInputs = Field(default_factory=dict)
    outputs: tuple[StepOutput, ...]
    parameters: PluginParameters = Field(default_factory=dict)
    on_error: OnErrorPolicy = "abort"
    max_retries: StrictInt = Field(default=0, ge=0)
    pause_before: StrictBool = False
    pause_after: StrictBool = False

    @field_validator("id")
    @classmethod
    def valid_step_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        if IDENTIFIER_PATTERN.fullmatch(value) is None:
            raise ValueError(f"Invalid step id: '{value}'")
        return value

    @field_validator("name", "tool_ref")
    @classmethod
    def nonempty_string(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("outputs")
    @classmethod
    def nonempty_unique_outputs(cls, value: tuple[StepOutput, ...]) -> tuple[StepOutput, ...]:
        if not value:
            raise ValueError("must define at least one output")
        seen: set[str] = set()
        for output in value:
            if output.name in seen:
                raise ValueError(f"Duplicate output name '{output.name}'")
            seen.add(output.name)
        return value


class WorkflowConfig(OpenBBQModel):
    id: str
    name: str
    steps: tuple[StepConfig, ...]

    @field_validator("id")
    @classmethod
    def valid_workflow_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        if IDENTIFIER_PATTERN.fullmatch(value) is None:
            raise ValueError(f"Invalid workflow id: '{value}'")
        return value

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("steps")
    @classmethod
    def nonempty_steps(cls, value: tuple[StepConfig, ...]) -> tuple[StepConfig, ...]:
        if not value:
            raise ValueError("must define a non-empty steps list")
        return value

    @model_validator(mode="after")
    def unique_step_ids(self) -> WorkflowConfig:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"Duplicate step id '{step.id}'")
            seen.add(step.id)
        return self


WorkflowMap: TypeAlias = dict[str, WorkflowConfig]


class ProjectConfig(OpenBBQModel):
    version: StrictInt
    root_path: Path
    config_path: Path
    project: ProjectMetadata
    storage: StorageConfig
    plugins: PluginConfig
    workflows: WorkflowMap

    @field_validator("version")
    @classmethod
    def version_one(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Project config version must be 1")
        return value

    @property
    def plugin_paths(self) -> tuple[Path, ...]:
        return self.plugins.paths
