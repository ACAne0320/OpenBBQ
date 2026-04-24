from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import JsonObject, format_pydantic_error
from openbbq.errors import ValidationError
from openbbq.domain.models import StepConfig
from openbbq.plugins.payloads import (
    PluginArtifactInput,
    PluginInputMap,
    PluginLiteralInput,
    PluginResponse,
)
from openbbq.plugins.registry import ToolSpec
from openbbq.storage.models import ArtifactRecord, OutputBinding, OutputBindings
from openbbq.storage.project_store import ProjectStore, StoredArtifactVersion

STEP_SELECTOR_PATTERN = re.compile(r"^([a-z0-9_-]+)\.([a-z0-9_-]+)$")


def parse_step_selector(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = STEP_SELECTOR_PATTERN.fullmatch(value)
    if match is None or match.group(1) == "project":
        return None
    return match.group(1), match.group(2)


def build_plugin_inputs(
    store: ProjectStore,
    step: StepConfig,
    output_bindings: OutputBindings,
) -> tuple[PluginInputMap, dict[str, str]]:
    plugin_inputs: PluginInputMap = {}
    input_artifact_version_ids: dict[str, str] = {}
    for input_name, input_value in step.inputs.items():
        if isinstance(input_value, str) and input_value.startswith("project."):
            artifact_id = input_value.removeprefix("project.")
            artifact = store.read_artifact(artifact_id)
            version = store.read_artifact_version(artifact["current_version_id"])
            plugin_inputs[input_name] = artifact_input(artifact, version)
            input_artifact_version_ids[input_value] = version.id
            continue

        selector = parse_step_selector(input_value)
        if selector is not None:
            binding = output_bindings.get(input_value)
            if binding is None:
                raise ValidationError(
                    f"Step '{step.id}' input '{input_name}' references unavailable output '{input_value}'."
                )
            artifact = store.read_artifact(binding["artifact_id"])
            version = store.read_artifact_version(binding["artifact_version_id"])
            plugin_inputs[input_name] = artifact_input(artifact, version)
            input_artifact_version_ids[input_value] = version.id
            continue

        plugin_inputs[input_name] = PluginLiteralInput(literal=input_value)
    return plugin_inputs, input_artifact_version_ids


def artifact_input(artifact: ArtifactRecord, version: StoredArtifactVersion) -> PluginArtifactInput:
    return PluginArtifactInput(
        artifact_id=artifact.id,
        artifact_version_id=version.id,
        type=artifact.type,
        metadata=version.record.metadata,
        file_path=str(version.content["file_path"])
        if version.record.content_encoding == "file"
        else None,
        content=None if version.record.content_encoding == "file" else version.content,
    )


def persist_step_outputs(
    store: ProjectStore,
    workflow_id: str,
    step: StepConfig,
    tool: ToolSpec,
    response: JsonObject | PluginResponse,
    input_artifact_version_ids: dict[str, str],
    artifact_reuse: dict[str, str] | None = None,
) -> OutputBindings:
    try:
        typed_response = (
            response
            if isinstance(response, PluginResponse)
            else PluginResponse.model_validate(response)
        )
    except PydanticValidationError as exc:
        raise ValidationError(
            f"Plugin response for step '{step.id}' is invalid: "
            f"{format_pydantic_error('response', exc)}"
        ) from exc

    response_outputs = typed_response.outputs
    if not isinstance(response_outputs, dict):
        raise ValidationError(
            f"Plugin response for step '{step.id}' must include an outputs object."
        )

    bindings: OutputBindings = {}
    declared_outputs = {output.name: output for output in step.outputs}
    for output_name, output in declared_outputs.items():
        payload = response_outputs.get(output_name)
        if payload is None:
            raise ValidationError(
                f"Plugin response for step '{step.id}' is missing output '{output_name}'."
            )
        output_type = payload.type
        if output_type != output.type:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' has type '{output_type}', expected '{output.type}'."
            )
        if output_type not in tool.output_artifact_types:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' type '{output_type}' is not allowed."
            )
        has_content = payload.content is not None
        file_path = Path(payload.file_path) if payload.file_path is not None else None
        if file_path is not None and not file_path.is_file():
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' file_path does not exist: {file_path}."
            )
        artifact, version = store.write_artifact_version(
            artifact_type=output.type,
            name=f"{step.id}.{output.name}",
            content=payload.content if has_content else None,
            file_path=file_path,
            metadata=payload.metadata,
            created_by_step_id=step.id,
            lineage={
                "workflow_id": workflow_id,
                "step_id": step.id,
                "tool_ref": step.tool_ref,
                "input_artifact_version_ids": input_artifact_version_ids,
            },
            artifact_id=(artifact_reuse or {}).get(f"{step.id}.{output.name}"),
        )
        bindings[output_name] = OutputBinding(
            artifact_id=artifact.id,
            artifact_version_id=version.id,
        )
    return bindings
