from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator

from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.plugins.contracts import (
    RuntimeRequirementSpec,
    ToolInputSpec,
    ToolOutputSpec,
    ToolUiSpec,
)


class ToolSpec(OpenBBQModel):
    plugin_name: str
    name: str
    description: str
    input_artifact_types: list[str]
    output_artifact_types: list[str]
    inputs: dict[str, ToolInputSpec] = Field(default_factory=dict)
    outputs: dict[str, ToolOutputSpec] = Field(default_factory=dict)
    runtime_requirements: RuntimeRequirementSpec = Field(default_factory=RuntimeRequirementSpec)
    ui: ToolUiSpec = Field(default_factory=ToolUiSpec)
    parameter_schema: JsonObject
    effects: list[str]
    manifest_path: Path

    @field_validator("plugin_name", "name", "description")
    @classmethod
    def nonempty_string(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("input_artifact_types", "output_artifact_types", "effects")
    @classmethod
    def list_of_strings(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) for item in value):
            raise ValueError("must be a list of strings")
        return value

    @field_validator("output_artifact_types")
    @classmethod
    def nonempty_output_types(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("must not be empty")
        return value


class PluginSpec(OpenBBQModel):
    name: str
    version: str
    runtime: str
    entrypoint: str
    manifest_path: Path
    tools: tuple[ToolSpec, ...] = ()


class InvalidPlugin(OpenBBQModel):
    path: Path
    error: str


class PluginRegistry(OpenBBQModel):
    plugins: dict[str, PluginSpec] = Field(default_factory=dict)
    tools: dict[str, ToolSpec] = Field(default_factory=dict)
    invalid_plugins: list[InvalidPlugin] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
