from __future__ import annotations

from pydantic import Field

from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.plugins.registry import PluginRegistry
from openbbq.runtime.models import RuntimeContext
from openbbq.storage.models import OutputBindings
from openbbq.storage.project_store import ProjectStore


class ExecutionContext(OpenBBQModel):
    config: ProjectConfig
    registry: PluginRegistry
    store: ProjectStore
    workflow: WorkflowConfig
    config_hash: str
    runtime_context: RuntimeContext | None = None
    step_run_ids: tuple[str, ...] = ()
    output_bindings: OutputBindings = Field(default_factory=dict)
    artifact_reuse: dict[str, str] = Field(default_factory=dict)

    @property
    def runtime_payload(self) -> JsonObject:
        return self.runtime_context.request_payload() if self.runtime_context is not None else {}

    @property
    def redaction_values(self) -> tuple[str, ...]:
        return self.runtime_context.redaction_values if self.runtime_context is not None else ()
