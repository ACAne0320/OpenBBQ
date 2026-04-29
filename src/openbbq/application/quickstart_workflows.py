from __future__ import annotations

from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TypeAlias
from uuid import uuid4

import yaml

from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.plugins.models import ToolSpec
from openbbq.plugins.registry import discover_plugins

YOUTUBE_SUBTITLE_TEMPLATE_ID = "youtube-subtitle"
YOUTUBE_SUBTITLE_WORKFLOW_ID = "youtube-to-srt"
DEFAULT_YOUTUBE_QUALITY = "best[ext=mp4][height<=720]/best[height<=720]/best"
YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE = "openbbq.workflow_templates.youtube_subtitle"
YOUTUBE_SUBTITLE_TEMPLATE_NAME = "openbbq.yaml"
LOCAL_SUBTITLE_TEMPLATE_ID = "local-subtitle"
LOCAL_SUBTITLE_WORKFLOW_ID = "local-to-srt"
LOCAL_SUBTITLE_TEMPLATE_PACKAGE = "openbbq.workflow_templates.local_subtitle"
LOCAL_SUBTITLE_TEMPLATE_NAME = "openbbq.yaml"
WorkflowTemplate: TypeAlias = JsonObject
SubtitleSourceKind: TypeAlias = str

_PARAMETER_LABELS = {
    "url": "URL",
    "format": "Format",
    "quality": "Quality",
    "auth": "Auth",
    "browser": "Browser",
    "browser_profile": "Browser profile",
    "sample_rate": "Sample rate",
    "channels": "Channels",
    "model": "Model",
    "device": "Device",
    "compute_type": "Compute",
    "language": "Language",
    "word_timestamps": "Word timestamps",
    "vad_filter": "VAD filter",
    "source_lang": "Source language",
    "target_lang": "Target language",
    "temperature": "Temperature",
    "max_duration_seconds": "Max duration seconds",
    "max_lines": "Max lines",
    "max_chars_per_line": "Max chars per line",
    "max_chars_per_second": "Max chars per second",
}

_SELECT_PARAMETER_OPTIONS = {
    ("ffmpeg.extract_audio", "format"): ("wav",),
    ("faster_whisper.transcribe", "language"): ("en", "auto"),
    ("faster_whisper.transcribe", "model"): (
        "tiny",
        "base",
        "small",
        "medium",
        "large-v3",
    ),
    ("faster_whisper.transcribe", "device"): ("cpu", "cuda"),
    ("faster_whisper.transcribe", "compute_type"): ("int8", "float16", "float32"),
    ("subtitle.export", "format"): ("srt",),
}

_TOGGLE_DESCRIPTIONS = {
    "word_timestamps": "Include word-level timing details.",
    "vad_filter": "Filter non-speech sections before transcription.",
}

_HIDDEN_DESKTOP_PARAMETERS = {"provider", "model"}

_OUTPUT_LABELS = {
    "video": "video",
    "audio": "audio",
    "asr_transcript": "transcript",
    "subtitle_segments": "subtitle segments",
    "translation": "translation",
    "subtitle": "SRT",
}


class GeneratedWorkflow(OpenBBQModel):
    project_root: Path
    config_path: Path
    workflow_id: str
    run_id: str


def subtitle_workflow_template_for_source(
    *,
    source_kind: SubtitleSourceKind,
    url: str | None = None,
) -> WorkflowTemplate:
    if source_kind == "local_file":
        template_id = LOCAL_SUBTITLE_TEMPLATE_ID
        workflow_id = LOCAL_SUBTITLE_WORKFLOW_ID
        config = _load_local_subtitle_template()
    elif source_kind == "remote_url":
        template_id = YOUTUBE_SUBTITLE_TEMPLATE_ID
        workflow_id = YOUTUBE_SUBTITLE_WORKFLOW_ID
        config = _load_youtube_subtitle_template()
        steps = _steps_by_id(config, workflow_id)
        steps["download"]["parameters"]["url"] = url or "about:blank"
    else:
        raise ValueError(f"Unsupported subtitle source kind: {source_kind}")

    return {
        "template_id": template_id,
        "workflow_id": workflow_id,
        "steps": tuple(_desktop_step(step) for step in config["workflows"][workflow_id]["steps"]),
    }


def subtitle_workflow_tool_catalog(*, plugin_paths: tuple[Path, ...]) -> WorkflowTemplate:
    registry = discover_plugins(plugin_paths)
    tools = tuple(
        _desktop_tool(tool_ref, tool)
        for tool_ref, tool in sorted(registry.tools.items())
        if tool.outputs
    )
    return {"tools": tools}


def write_youtube_subtitle_workflow(
    *,
    workspace_root: Path,
    url: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    quality: str,
    auth: str,
    browser: str | None,
    browser_profile: str | None,
    correct_transcript: bool = True,
    step_order: tuple[str, ...] = (),
    extra_steps: tuple[WorkflowTemplate, ...] = (),
    run_id: str | None = None,
) -> GeneratedWorkflow:
    run_id = run_id or _new_run_id()
    generated_root = (
        workspace_root / ".openbbq" / "generated" / YOUTUBE_SUBTITLE_TEMPLATE_ID / run_id
    )
    generated_root.mkdir(parents=True, exist_ok=True)
    config_path = generated_root / "openbbq.yaml"
    config = _youtube_subtitle_config(
        run_id=run_id,
        url=url,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
        correct_transcript=correct_transcript,
        quality=quality,
        auth=auth,
        browser=browser,
        browser_profile=browser_profile,
        step_order=step_order,
        extra_steps=extra_steps,
    )
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return GeneratedWorkflow(
        project_root=generated_root,
        config_path=config_path,
        workflow_id=YOUTUBE_SUBTITLE_WORKFLOW_ID,
        run_id=run_id,
    )


def write_local_subtitle_workflow(
    *,
    workspace_root: Path,
    video_selector: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    correct_transcript: bool = True,
    step_order: tuple[str, ...] = (),
    extra_steps: tuple[WorkflowTemplate, ...] = (),
    run_id: str | None = None,
) -> GeneratedWorkflow:
    run_id = run_id or _new_run_id()
    generated_root = workspace_root / ".openbbq" / "generated" / LOCAL_SUBTITLE_TEMPLATE_ID / run_id
    generated_root.mkdir(parents=True, exist_ok=True)
    config_path = generated_root / "openbbq.yaml"
    config = _local_subtitle_config(
        run_id=run_id,
        video_selector=video_selector,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
        correct_transcript=correct_transcript,
        step_order=step_order,
        extra_steps=extra_steps,
    )
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return GeneratedWorkflow(
        project_root=generated_root,
        config_path=config_path,
        workflow_id=LOCAL_SUBTITLE_WORKFLOW_ID,
        run_id=run_id,
    )


def _youtube_subtitle_config(
    *,
    run_id: str,
    url: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    correct_transcript: bool,
    quality: str,
    auth: str,
    browser: str | None,
    browser_profile: str | None,
    step_order: tuple[str, ...],
    extra_steps: tuple[WorkflowTemplate, ...],
) -> WorkflowTemplate:
    config = _load_youtube_subtitle_template()
    config["storage"] = _generated_storage_config(run_id)
    steps = _steps_by_id(config, YOUTUBE_SUBTITLE_WORKFLOW_ID)

    download_parameters = steps["download"]["parameters"]
    download_parameters["url"] = url
    download_parameters["quality"] = quality
    download_parameters["auth"] = auth
    _set_optional(download_parameters, "browser", browser)
    _set_optional(download_parameters, "browser_profile", browser_profile)

    transcribe_parameters = steps["transcribe"]["parameters"]
    transcribe_parameters["model"] = asr_model
    transcribe_parameters["device"] = asr_device
    transcribe_parameters["compute_type"] = asr_compute_type
    transcribe_parameters["language"] = source_lang

    correction_parameters = steps["correct"]["parameters"]
    correction_parameters["provider"] = provider
    correction_parameters["source_lang"] = source_lang
    _set_optional(correction_parameters, "model", model)
    if not correct_transcript:
        _remove_transcript_correction(config, YOUTUBE_SUBTITLE_WORKFLOW_ID)

    translation_parameters = steps["translate"]["parameters"]
    translation_parameters["provider"] = provider
    translation_parameters["source_lang"] = source_lang
    translation_parameters["target_lang"] = target_lang
    _set_optional(translation_parameters, "model", model)

    _insert_extra_steps(config, YOUTUBE_SUBTITLE_WORKFLOW_ID, extra_steps)
    _apply_step_order(config, YOUTUBE_SUBTITLE_WORKFLOW_ID, step_order)
    return config


def _local_subtitle_config(
    *,
    run_id: str,
    video_selector: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    correct_transcript: bool,
    step_order: tuple[str, ...],
    extra_steps: tuple[WorkflowTemplate, ...],
) -> WorkflowTemplate:
    config = _load_local_subtitle_template()
    config["storage"] = _generated_storage_config(run_id)
    steps = _steps_by_id(config, LOCAL_SUBTITLE_WORKFLOW_ID)

    extract_audio_inputs = steps["extract_audio"]["inputs"]
    extract_audio_inputs["video"] = video_selector

    transcribe_parameters = steps["transcribe"]["parameters"]
    transcribe_parameters["model"] = asr_model
    transcribe_parameters["device"] = asr_device
    transcribe_parameters["compute_type"] = asr_compute_type
    transcribe_parameters["language"] = source_lang

    correction_parameters = steps["correct"]["parameters"]
    correction_parameters["provider"] = provider
    correction_parameters["source_lang"] = source_lang
    _set_optional(correction_parameters, "model", model)
    if not correct_transcript:
        _remove_transcript_correction(config, LOCAL_SUBTITLE_WORKFLOW_ID)

    translation_parameters = steps["translate"]["parameters"]
    translation_parameters["provider"] = provider
    translation_parameters["source_lang"] = source_lang
    translation_parameters["target_lang"] = target_lang
    _set_optional(translation_parameters, "model", model)

    _insert_extra_steps(config, LOCAL_SUBTITLE_WORKFLOW_ID, extra_steps)
    _apply_step_order(config, LOCAL_SUBTITLE_WORKFLOW_ID, step_order)
    return config


def _load_youtube_subtitle_template() -> WorkflowTemplate:
    return _load_template(
        package=YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE,
        name=YOUTUBE_SUBTITLE_TEMPLATE_NAME,
        description="YouTube subtitle workflow template",
    )


def _load_local_subtitle_template() -> WorkflowTemplate:
    return _load_template(
        package=LOCAL_SUBTITLE_TEMPLATE_PACKAGE,
        name=LOCAL_SUBTITLE_TEMPLATE_NAME,
        description="Local subtitle workflow template",
    )


def _load_template(*, package: str, name: str, description: str) -> WorkflowTemplate:
    raw = resources.files(package).joinpath(name).read_text(encoding="utf-8")
    config = yaml.safe_load(raw)
    if not isinstance(config, dict):
        raise ValueError(f"{description} must be a YAML mapping.")
    return config


def _steps_by_id(config: WorkflowTemplate, workflow_id: str) -> dict[str, WorkflowTemplate]:
    workflow = config["workflows"][workflow_id]
    return {step["id"]: step for step in workflow["steps"]}


def _insert_extra_steps(
    config: WorkflowTemplate,
    workflow_id: str,
    extra_steps: tuple[WorkflowTemplate, ...],
) -> None:
    if not extra_steps:
        return
    workflow = config["workflows"][workflow_id]
    step_configs = [_workflow_step_from_extra(step) for step in extra_steps]
    for index, step in enumerate(workflow["steps"]):
        if step["id"] == "subtitle":
            workflow["steps"][index:index] = step_configs
            return
    workflow["steps"].extend(step_configs)


def _apply_step_order(
    config: WorkflowTemplate, workflow_id: str, step_order: tuple[str, ...]
) -> None:
    if not step_order:
        return
    workflow = config["workflows"][workflow_id]
    steps_by_id = {step["id"]: step for step in workflow["steps"]}
    ordered_steps = [steps_by_id[step_id] for step_id in step_order if step_id in steps_by_id]
    ordered_ids = {step["id"] for step in ordered_steps}
    ordered_steps.extend(step for step in workflow["steps"] if step["id"] not in ordered_ids)
    workflow["steps"] = ordered_steps


def _workflow_step_from_extra(step: WorkflowTemplate) -> WorkflowTemplate:
    return {
        "id": step["id"],
        "name": step["name"],
        "tool_ref": step["tool_ref"],
        "inputs": step.get("inputs", {}),
        "outputs": step.get("outputs", ()),
        "parameters": step.get("parameters", {}),
        "on_error": "abort",
        "max_retries": 0,
    }


def _remove_transcript_correction(config: WorkflowTemplate, workflow_id: str) -> None:
    workflow = config["workflows"][workflow_id]
    workflow["steps"] = [step for step in workflow["steps"] if step["id"] != "correct"]
    steps = _steps_by_id(config, workflow_id)
    steps["segment"]["inputs"]["transcript"] = "transcribe.transcript"


def _desktop_step(step: WorkflowTemplate) -> WorkflowTemplate:
    step_id = str(step["id"])
    data: WorkflowTemplate = {
        "id": step_id,
        "name": str(step["name"]),
        "tool_ref": str(step["tool_ref"]),
        "summary": _desktop_step_summary(step),
        "status": "enabled" if step_id == "correct" else "locked",
        "inputs": step.get("inputs", {}),
        "outputs": tuple(step.get("outputs", ())),
        "parameters": tuple(
            _desktop_parameter(str(step["tool_ref"]), key, value)
            for key, value in step.get("parameters", {}).items()
            if key not in _HIDDEN_DESKTOP_PARAMETERS
        ),
    }
    if step_id == "transcribe":
        data["selected"] = True
    return data


def _desktop_tool(tool_ref: str, tool: ToolSpec) -> WorkflowTemplate:
    return {
        "tool_ref": tool_ref,
        "name": _tool_display_name(tool),
        "description": tool.description,
        "inputs": {
            name: {
                "artifact_types": spec.artifact_types,
                "required": spec.required,
                "multiple": spec.multiple,
            }
            for name, spec in tool.inputs.items()
        },
        "outputs": tuple(
            {"name": name, "type": spec.artifact_type} for name, spec in tool.outputs.items()
        ),
        "parameters": tuple(_desktop_parameters_from_schema(tool_ref, tool.parameter_schema)),
    }


def _tool_display_name(tool: ToolSpec) -> str:
    if tool.name == "qa":
        return f"{tool.plugin_name.replace('_', ' ').title()} QA"
    words = []
    words.append(tool.name.replace("_", " "))
    return " ".join(part.title() for part in " ".join(words).split())


def _desktop_parameters_from_schema(
    tool_ref: str, schema: WorkflowTemplate
) -> tuple[WorkflowTemplate, ...]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return ()
    parameters: list[WorkflowTemplate] = []
    for key, raw_property in properties.items():
        if key in _HIDDEN_DESKTOP_PARAMETERS or not isinstance(raw_property, dict):
            continue
        parameter = _desktop_parameter_from_property(tool_ref, key, raw_property)
        if parameter is not None:
            parameters.append(parameter)
    return tuple(parameters)


def _desktop_parameter_from_property(
    tool_ref: str,
    key: str,
    property_schema: WorkflowTemplate,
) -> WorkflowTemplate | None:
    property_type = property_schema.get("type")
    if property_type in {"array", "object"}:
        return None
    default = property_schema.get("default", "")
    label = _PARAMETER_LABELS.get(key, key.replace("_", " ").title())
    enum = property_schema.get("enum")
    if isinstance(enum, list) and enum:
        return {
            "kind": "select",
            "key": key,
            "label": label,
            "value": str(default if default != "" else enum[0]),
            "options": tuple(str(item) for item in enum),
        }
    if property_type == "boolean":
        return {
            "kind": "toggle",
            "key": key,
            "label": label,
            "description": _TOGGLE_DESCRIPTIONS.get(key, label),
            "value": bool(default),
        }
    return {
        "kind": "text",
        "key": key,
        "label": label,
        "value": str(default),
    }


def _desktop_parameter(tool_ref: str, key: str, value: object) -> WorkflowTemplate:
    label = _PARAMETER_LABELS.get(key, key.replace("_", " ").title())
    if isinstance(value, bool):
        return {
            "kind": "toggle",
            "key": key,
            "label": label,
            "description": _TOGGLE_DESCRIPTIONS.get(key, label),
            "value": value,
        }
    options = _SELECT_PARAMETER_OPTIONS.get((tool_ref, key))
    if options is not None:
        return {
            "kind": "select",
            "key": key,
            "label": label,
            "value": str(value),
            "options": options,
        }
    return {
        "kind": "text",
        "key": key,
        "label": label,
        "value": str(value),
    }


def _desktop_step_summary(step: WorkflowTemplate) -> str:
    tool_ref = str(step["tool_ref"])
    if tool_ref == "remote_video.download":
        source = "url"
    else:
        source = next(iter(step.get("inputs", {}) or {}), "input")
    outputs = step.get("outputs", ())
    output = "output"
    if outputs:
        output_type = str(outputs[0].get("type", "output"))
        output = _OUTPUT_LABELS.get(output_type, output_type.replace("_", " "))
    return f"{source} -> {output}"


def _set_optional(parameters: WorkflowTemplate, name: str, value: str | None) -> None:
    if value is None:
        parameters.pop(name, None)
        return
    parameters[name] = value


def _generated_storage_config(run_id: str) -> WorkflowTemplate:
    return {
        "root": f"../../../r/{run_id}",
        "artifacts": f"../../../a/{run_id}",
        "state": f"../../../r/{run_id}/s",
    }


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"
