from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import os
import re
from typing import Any, TypeVar

from pydantic import ValidationError as PydanticValidationError
import yaml

from openbbq.domain.base import JsonObject, OpenBBQModel, PluginInputs, format_pydantic_error
from openbbq.domain.models import (
    ARTIFACT_TYPES,
    PluginConfig,
    ProjectConfig,
    ProjectMetadata,
    StepConfig,
    StepOutput,
    StorageConfig,
    WorkflowConfig,
)
from openbbq.errors import ValidationError

WORKFLOW_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")
STEP_ID_PATTERN = WORKFLOW_ID_PATTERN
STEP_SELECTOR_PATTERN = re.compile(r"^([a-z0-9_-]+)\.([a-z0-9_-]+)$")
VALID_ON_ERROR = {"abort", "retry", "skip"}
DEFAULT_STORAGE_ROOT = Path(".openbbq")
DEFAULT_CONFIG_NAME = "openbbq.yaml"
BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "builtin_plugins"
TModel = TypeVar("TModel", bound=OpenBBQModel)


def load_project_config(
    project_root: Path | str,
    config_path: Path | str | None = None,
    extra_plugin_paths: Iterable[Path | str] | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectConfig:
    env = os.environ if env is None else env
    root_path = Path(project_root).expanduser().resolve()
    resolved_config_path = _resolve_config_path(root_path, config_path)
    raw_config = _load_yaml_mapping(resolved_config_path)

    version = raw_config.get("version")
    if type(version) is not int or version != 1:
        raise ValidationError("Project config version must be 1.")

    project_raw = _require_mapping(raw_config.get("project"), "project")
    project_name = _require_nonempty_string(project_raw.get("name"), "project.name")
    project_id = project_raw.get("id")
    if project_id is not None:
        project_id = _require_nonempty_string(project_id, "project.id")

    storage_raw = _optional_mapping(raw_config.get("storage"), "storage")
    storage_root = _resolve_path(
        root_path, storage_raw.get("root", DEFAULT_STORAGE_ROOT), "storage.root"
    )
    artifacts_path = _resolve_path(
        root_path,
        storage_raw.get("artifacts", storage_root / "artifacts"),
        "storage.artifacts",
    )
    state_path = _resolve_path(
        root_path, storage_raw.get("state", storage_root / "state"), "storage.state"
    )
    storage = _build_model(
        StorageConfig,
        "storage",
        root=storage_root,
        artifacts=artifacts_path,
        state=state_path,
    )

    config_plugin_paths = _load_plugin_paths(root_path, raw_config, env)
    cli_plugin_paths = _normalize_plugin_paths(
        root_path, extra_plugin_paths or [], "extra_plugin_paths"
    )
    plugin_paths = _merge_paths(
        cli_plugin_paths, _merge_paths(config_plugin_paths, [BUILTIN_PLUGIN_ROOT])
    )
    plugins = _build_model(PluginConfig, "plugins", paths=tuple(plugin_paths))

    workflows_raw = _require_mapping(raw_config.get("workflows"), "workflows")
    workflows: dict[str, WorkflowConfig] = {}
    for workflow_id, workflow_raw in workflows_raw.items():
        workflow_id = _require_nonempty_string(workflow_id, "workflows.<workflow_id>")
        _validate_identifier(workflow_id, "workflow id")
        workflow_mapping = _require_mapping(workflow_raw, f"workflows.{workflow_id}")
        workflow_name = _require_nonempty_string(
            workflow_mapping.get("name"), f"workflows.{workflow_id}.name"
        )
        steps_raw = workflow_mapping.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValidationError(f"Workflow '{workflow_id}' must define a non-empty steps list.")

        steps: list[StepConfig] = []
        step_ids: list[str] = []
        step_outputs: dict[str, set[str]] = {}
        input_refs: list[tuple[str, int, PluginInputs]] = []
        seen_step_ids: set[str] = set()
        for index, step_raw in enumerate(steps_raw):
            step_mapping = _require_mapping(step_raw, f"workflows.{workflow_id}.steps[{index}]")
            step_id = _require_nonempty_string(
                step_mapping.get("id"), f"workflows.{workflow_id}.steps[{index}].id"
            )
            _validate_identifier(step_id, "step id")
            if step_id in seen_step_ids:
                raise ValidationError(
                    f"Duplicate step id '{step_id}' in workflow '{workflow_id}'.",
                )
            seen_step_ids.add(step_id)
            step_name = _require_nonempty_string(
                step_mapping.get("name"), f"workflows.{workflow_id}.steps[{index}].name"
            )
            tool_ref = _require_nonempty_string(
                step_mapping.get("tool_ref"),
                f"workflows.{workflow_id}.steps[{index}].tool_ref",
            )
            inputs = _optional_mapping(
                step_mapping.get("inputs"), f"workflows.{workflow_id}.steps[{index}].inputs"
            )
            input_refs.append((step_id, index, inputs))
            parameters = _optional_mapping(
                step_mapping.get("parameters"),
                f"workflows.{workflow_id}.steps[{index}].parameters",
            )
            outputs_raw = step_mapping.get("outputs")
            if not isinstance(outputs_raw, list) or not outputs_raw:
                raise ValidationError(
                    f"Step '{step_id}' in workflow '{workflow_id}' must define at least one output.",
                )
            outputs: list[StepOutput] = []
            seen_output_names: set[str] = set()
            for output_index, output_raw in enumerate(outputs_raw):
                output_mapping = _require_mapping(
                    output_raw,
                    f"workflows.{workflow_id}.steps[{index}].outputs[{output_index}]",
                )
                output_name = _require_nonempty_string(
                    output_mapping.get("name"),
                    f"workflows.{workflow_id}.steps[{index}].outputs[{output_index}].name",
                )
                if output_name in seen_output_names:
                    raise ValidationError(
                        f"Duplicate output name '{output_name}' in step '{step_id}' of workflow '{workflow_id}'.",
                    )
                seen_output_names.add(output_name)
                output_type = _require_nonempty_string(
                    output_mapping.get("type"),
                    f"workflows.{workflow_id}.steps[{index}].outputs[{output_index}].type",
                )
                if output_type not in ARTIFACT_TYPES:
                    raise ValidationError(
                        f"Output type '{output_type}' in step '{step_id}' of workflow '{workflow_id}' is not registered.",
                    )
                outputs.append(
                    _build_model(
                        StepOutput,
                        f"workflows.{workflow_id}.steps[{index}].outputs[{output_index}]",
                        name=output_name,
                        type=output_type,
                    )
                )

            on_error = step_mapping.get("on_error", "abort")
            if not isinstance(on_error, str) or on_error not in VALID_ON_ERROR:
                raise ValidationError(
                    f"Step '{step_id}' in workflow '{workflow_id}' has invalid on_error '{on_error}'.",
                )

            max_retries = step_mapping.get("max_retries", 0)
            if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
                raise ValidationError(
                    f"Step '{step_id}' in workflow '{workflow_id}' has invalid max_retries '{max_retries}'.",
                )

            pause_before = _require_bool(
                step_mapping.get("pause_before", False),
                f"workflows.{workflow_id}.steps[{index}].pause_before",
            )
            pause_after = _require_bool(
                step_mapping.get("pause_after", False),
                f"workflows.{workflow_id}.steps[{index}].pause_after",
            )

            steps.append(
                _build_model(
                    StepConfig,
                    f"workflows.{workflow_id}.steps[{index}]",
                    id=step_id,
                    name=step_name,
                    tool_ref=tool_ref,
                    inputs=dict(inputs),
                    outputs=tuple(outputs),
                    parameters=dict(parameters),
                    on_error=on_error,
                    max_retries=max_retries,
                    pause_before=pause_before,
                    pause_after=pause_after,
                )
            )
            step_ids.append(step_id)
            step_outputs[step_id] = {output.name for output in outputs}

        step_positions = {step_id: position for position, step_id in enumerate(step_ids)}
        for step_id, step_index, inputs in input_refs:
            _validate_step_inputs(
                inputs, step_id, workflow_id, step_index, step_positions, step_outputs
            )

        workflows[workflow_id] = _build_model(
            WorkflowConfig,
            f"workflows.{workflow_id}",
            id=workflow_id,
            name=workflow_name,
            steps=tuple(steps),
        )

    project = _build_model(ProjectMetadata, "project", id=project_id, name=project_name)
    return _build_model(
        ProjectConfig,
        "project config",
        version=1,
        root_path=root_path,
        config_path=resolved_config_path,
        project=project,
        storage=storage,
        plugins=plugins,
        workflows=workflows,
    )


def _load_yaml_mapping(path: Path) -> JsonObject:
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ValidationError(f"Project config '{path}' was not found.") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"Project config '{path}' contains malformed YAML.") from exc
    if not isinstance(raw, dict):
        raise ValidationError(f"Project config '{path}' must contain a YAML mapping.")
    return raw


def _build_model(model_type: type[TModel], field_path: str, **values: Any) -> TModel:
    try:
        return model_type(**values)
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error(field_path, exc)) from exc


def _resolve_config_path(project_root: Path, config_path: Path | str | None) -> Path:
    if config_path is None:
        return (project_root / DEFAULT_CONFIG_NAME).resolve()
    path = Path(config_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _resolve_path(project_root: Path, value: Path | str, field_path: str) -> Path:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError, OSError) as exc:
        raise ValidationError(
            f"{field_path} must be a string path relative to the project root."
        ) from exc
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _load_plugin_paths(
    project_root: Path, raw_config: JsonObject, env: Mapping[str, str]
) -> list[Path]:
    config_plugins = _optional_mapping(raw_config.get("plugins"), "plugins")
    config_paths = config_plugins.get("paths", [])
    if not isinstance(config_paths, list):
        raise ValidationError("plugins.paths must be a list when provided.")

    env_paths_raw = env.get("OPENBBQ_PLUGIN_PATH", "")
    env_paths = [path for path in env_paths_raw.split(os.pathsep) if path]
    return _normalize_plugin_paths(project_root, env_paths + config_paths, "plugins.paths")


def _normalize_plugin_paths(
    project_root: Path, paths: Iterable[Path | str], field_path: str
) -> list[Path]:
    normalized: list[Path] = []
    seen: set[Path] = set()
    for index, raw_path in enumerate(paths):
        path = _resolve_path(project_root, raw_path, f"{field_path}[{index}]")
        if path not in seen:
            seen.add(path)
            normalized.append(path)
    return normalized


def _merge_paths(preferred: Iterable[Path], fallback: Iterable[Path]) -> list[Path]:
    merged: list[Path] = []
    seen: set[Path] = set()
    for path in list(preferred) + list(fallback):
        if path not in seen:
            seen.add(path)
            merged.append(path)
    return merged


def _require_mapping(value: Any, field_path: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_path} must be a mapping.")
    return value


def _optional_mapping(value: Any, field_path: str) -> JsonObject:
    if value is None:
        return {}
    return _require_mapping(value, field_path)


def _require_nonempty_string(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_path} must be a non-empty string.")
    return value


def _require_bool(value: Any, field_path: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field_path} must be a boolean.")
    return value


def _validate_identifier(value: str, label: str) -> None:
    if not WORKFLOW_ID_PATTERN.fullmatch(value):
        raise ValidationError(f"Invalid {label}: '{value}'.")


def _validate_step_inputs(
    inputs: PluginInputs,
    step_id: str,
    workflow_id: str,
    step_index: int,
    step_positions: Mapping[str, int],
    step_outputs: Mapping[str, set[str]],
) -> None:
    for input_name, input_value in inputs.items():
        if not isinstance(input_value, str):
            continue
        selector = STEP_SELECTOR_PATTERN.fullmatch(input_value)
        if selector is None:
            continue
        selector_step_id = selector.group(1)
        if selector_step_id == "project":
            continue
        if selector_step_id == step_id:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' has a self-reference in input '{input_name}'.",
            )
        selector_position = step_positions.get(selector_step_id)
        if selector_position is None:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' references unknown step '{selector_step_id}' in input '{input_name}'.",
            )
        if selector_position > step_index:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' has a forward reference in input '{input_name}'.",
            )
        selector_output_name = selector.group(2)
        declared_outputs = step_outputs.get(selector_step_id, set())
        if selector_output_name not in declared_outputs:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' references unknown output '{selector_output_name}' on step '{selector_step_id}' in input '{input_name}'.",
            )
