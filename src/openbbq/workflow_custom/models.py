from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from openbbq.config.workflows import WORKFLOW_ID_PATTERN
from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.domain.models import StepOutput

WorkflowDefinitionOrigin: TypeAlias = Literal["built_in", "custom"]
WorkflowDefinitionSourceType: TypeAlias = Literal["local_file", "remote_url"]
WorkflowStepStatus: TypeAlias = Literal["locked", "enabled", "disabled"]


class WorkflowCustomStep(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    summary: str
    status: WorkflowStepStatus
    selected: bool | None = None
    inputs: dict[str, str] | None = None
    outputs: tuple[StepOutput, ...] | None = None
    parameters: tuple[JsonObject, ...] = ()


class WorkflowDefinition(OpenBBQModel):
    id: str
    name: str
    description: str = ""
    origin: WorkflowDefinitionOrigin = "custom"
    source_types: tuple[WorkflowDefinitionSourceType, ...]
    result_types: tuple[str, ...] = ("subtitle",)
    steps: tuple[WorkflowCustomStep, ...]
    updated_at: str | None = None

    @field_validator("id")
    @classmethod
    def valid_workflow_definition_id(cls, value: str) -> str:
        if WORKFLOW_ID_PATTERN.fullmatch(value) is None:
            raise ValueError(f"Invalid workflow definition id: '{value}'")
        return value

    @model_validator(mode="after")
    def nonempty_values(self) -> WorkflowDefinition:
        if not self.name.strip():
            raise ValueError("Workflow definition name must be non-empty")
        if not self.source_types:
            raise ValueError("Workflow definition must define at least one source type")
        if not self.steps:
            raise ValueError("Workflow definition must define at least one step")
        return self


class WorkflowDefinitionList(OpenBBQModel):
    workflows: tuple[WorkflowDefinition, ...] = Field(default_factory=tuple)
