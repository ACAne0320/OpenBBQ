from __future__ import annotations

import re
from typing import Any

from openbbq.errors import ValidationError
from openbbq.models.workflow import StepConfig
from openbbq.plugins import ToolSpec
from openbbq.storage import ProjectStore, StoredArtifactVersion

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
    output_bindings: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    plugin_inputs: dict[str, dict[str, Any]] = {}
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

        plugin_inputs[input_name] = {"literal": input_value}
    return plugin_inputs, input_artifact_version_ids


def artifact_input(artifact: dict[str, Any], version: StoredArtifactVersion) -> dict[str, Any]:
    return {
        "artifact_id": artifact["id"],
        "artifact_version_id": version.id,
        "type": artifact["type"],
        "content": version.content,
        "metadata": version.record.get("metadata", {}),
    }


def persist_step_outputs(
    store: ProjectStore,
    workflow_id: str,
    step: StepConfig,
    tool: ToolSpec,
    response: dict[str, Any],
    input_artifact_version_ids: dict[str, str],
    artifact_reuse: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    response_outputs = response.get("outputs")
    if not isinstance(response_outputs, dict):
        raise ValidationError(
            f"Plugin response for step '{step.id}' must include an outputs object."
        )

    bindings: dict[str, dict[str, str]] = {}
    declared_outputs = {output.name: output for output in step.outputs}
    for output_name, output in declared_outputs.items():
        payload = response_outputs.get(output_name)
        if not isinstance(payload, dict):
            raise ValidationError(
                f"Plugin response for step '{step.id}' is missing output '{output_name}'."
            )
        output_type = payload.get("type")
        if output_type != output.type:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' has type '{output_type}', expected '{output.type}'."
            )
        if output_type not in tool.output_artifact_types:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' type '{output_type}' is not allowed."
            )
        artifact, version = store.write_artifact_version(
            artifact_type=output.type,
            name=f"{step.id}.{output.name}",
            content=payload.get("content"),
            metadata=payload.get("metadata", {}),
            created_by_step_id=step.id,
            lineage={
                "workflow_id": workflow_id,
                "step_id": step.id,
                "tool_ref": step.tool_ref,
                "input_artifact_version_ids": input_artifact_version_ids,
            },
            artifact_id=(artifact_reuse or {}).get(f"{step.id}.{output.name}"),
        )
        bindings[output_name] = {
            "artifact_id": artifact.id,
            "artifact_version_id": version.id,
        }
    return bindings
