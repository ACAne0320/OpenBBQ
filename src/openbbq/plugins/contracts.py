from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, field_validator

from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.domain.models import ARTIFACT_TYPES

PluginRuntime: TypeAlias = Literal["python"]
PluginEffect: TypeAlias = Literal["network", "reads_files", "writes_files"]


class ToolInputSpec(OpenBBQModel):
    artifact_types: tuple[str, ...]
    required: bool = True
    description: str | None = None
    multiple: bool = False

    @field_validator("artifact_types")
    @classmethod
    def registered_artifact_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("must define at least one artifact type")
        unknown = [artifact_type for artifact_type in value if artifact_type not in ARTIFACT_TYPES]
        if unknown:
            raise ValueError(f"unknown artifact types: {', '.join(sorted(unknown))}")
        return value


class ToolOutputSpec(OpenBBQModel):
    artifact_type: str
    description: str | None = None

    @field_validator("artifact_type")
    @classmethod
    def registered_artifact_type(cls, value: str) -> str:
        if value not in ARTIFACT_TYPES:
            raise ValueError(f"unknown artifact type: {value}")
        return value


class RuntimeRequirementSpec(OpenBBQModel):
    binaries: tuple[str, ...] = ()
    python_extras: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    models: tuple[str, ...] = ()


class ToolUiSpec(OpenBBQModel):
    form: JsonObject = Field(default_factory=dict)
    preview: JsonObject = Field(default_factory=dict)


class ToolContract(OpenBBQModel):
    inputs: dict[str, ToolInputSpec] = Field(default_factory=dict)
    outputs: dict[str, ToolOutputSpec]
    runtime_requirements: RuntimeRequirementSpec = Field(default_factory=RuntimeRequirementSpec)
    ui: ToolUiSpec = Field(default_factory=ToolUiSpec)
