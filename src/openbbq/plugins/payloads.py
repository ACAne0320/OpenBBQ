from __future__ import annotations

from pathlib import Path
from typing import Any, TypeAlias

from pydantic import Field, model_validator

from openbbq.domain.base import ArtifactMetadata, JsonObject, JsonValue, OpenBBQModel
from openbbq.domain.base import PluginParameters
from openbbq.storage.models import OutputBinding


class PluginPayloadModel(OpenBBQModel):
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self.model_dump(mode="json", exclude_none=True) == other
        return super().__eq__(other)


class PluginLiteralInput(PluginPayloadModel):
    literal: JsonValue


class PluginArtifactInput(PluginPayloadModel):
    artifact_id: str
    artifact_version_id: str
    type: str
    metadata: ArtifactMetadata = Field(default_factory=dict)
    file_path: str | None = None
    content: JsonValue | bytes | None = None


PluginInputValue: TypeAlias = PluginLiteralInput | PluginArtifactInput
PluginInputMap: TypeAlias = dict[str, PluginInputValue]


class PluginRequest(PluginPayloadModel):
    project_root: str
    workflow_id: str
    step_id: str
    attempt: int
    tool_name: str
    parameters: PluginParameters
    inputs: PluginInputMap
    runtime: JsonObject = Field(default_factory=dict)
    work_dir: str


class PluginOutputPayload(PluginPayloadModel):
    type: str
    content: JsonValue | bytes | None = None
    file_path: Path | None = None
    metadata: ArtifactMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_payload(self) -> PluginOutputPayload:
        has_content = self.content is not None
        has_file = self.file_path is not None
        if has_content == has_file:
            raise ValueError("must include exactly one of content or file_path")
        return self


class PluginResponse(PluginPayloadModel):
    outputs: dict[str, PluginOutputPayload]
    pause_requested: bool = False


class PersistedOutput(OpenBBQModel):
    name: str
    binding: OutputBinding
