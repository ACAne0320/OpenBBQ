from __future__ import annotations

from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TypeAlias
from uuid import uuid4

import yaml

from openbbq.domain.base import JsonObject, OpenBBQModel

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


class GeneratedWorkflow(OpenBBQModel):
    project_root: Path
    config_path: Path
    workflow_id: str
    run_id: str


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
    run_id: str | None = None,
) -> GeneratedWorkflow:
    run_id = run_id or _new_run_id()
    generated_root = (
        workspace_root / ".openbbq" / "generated" / YOUTUBE_SUBTITLE_TEMPLATE_ID / run_id
    )
    generated_root.mkdir(parents=True, exist_ok=True)
    config_path = generated_root / "openbbq.yaml"
    config = _youtube_subtitle_config(
        url=url,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
        quality=quality,
        auth=auth,
        browser=browser,
        browser_profile=browser_profile,
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
    run_id: str | None = None,
) -> GeneratedWorkflow:
    run_id = run_id or _new_run_id()
    generated_root = workspace_root / ".openbbq" / "generated" / LOCAL_SUBTITLE_TEMPLATE_ID / run_id
    generated_root.mkdir(parents=True, exist_ok=True)
    config_path = generated_root / "openbbq.yaml"
    config = _local_subtitle_config(
        video_selector=video_selector,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
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
) -> WorkflowTemplate:
    config = _load_youtube_subtitle_template()
    config["storage"] = {"root": ".openbbq"}
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

    translation_parameters = steps["translate"]["parameters"]
    translation_parameters["provider"] = provider
    translation_parameters["source_lang"] = source_lang
    translation_parameters["target_lang"] = target_lang
    _set_optional(translation_parameters, "model", model)

    return config


def _local_subtitle_config(
    *,
    video_selector: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
) -> WorkflowTemplate:
    config = _load_local_subtitle_template()
    config["storage"] = {"root": ".openbbq"}
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

    translation_parameters = steps["translate"]["parameters"]
    translation_parameters["provider"] = provider
    translation_parameters["source_lang"] = source_lang
    translation_parameters["target_lang"] = target_lang
    _set_optional(translation_parameters, "model", model)

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


def _set_optional(parameters: WorkflowTemplate, name: str, value: str | None) -> None:
    if value is None:
        parameters.pop(name, None)
        return
    parameters[name] = value


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"
