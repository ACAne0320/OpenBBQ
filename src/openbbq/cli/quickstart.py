from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from openbbq.domain.base import OpenBBQModel

YOUTUBE_SUBTITLE_TEMPLATE_ID = "youtube-subtitle"
YOUTUBE_SUBTITLE_WORKFLOW_ID = "youtube-to-srt"
DEFAULT_YOUTUBE_QUALITY = "best[ext=mp4][height<=720]/best[height<=720]/best"
YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE = "openbbq.workflow_templates.youtube_subtitle"
YOUTUBE_SUBTITLE_TEMPLATE_NAME = "openbbq.yaml"


class GeneratedWorkflow(OpenBBQModel):
    project_root: Path
    config_path: Path
    workflow_id: str


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
) -> GeneratedWorkflow:
    generated_root = workspace_root / ".openbbq" / "generated" / YOUTUBE_SUBTITLE_TEMPLATE_ID
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
) -> dict[str, Any]:
    config = _load_youtube_subtitle_template()
    steps = _steps_by_id(config)

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


def _load_youtube_subtitle_template() -> dict[str, Any]:
    raw = (
        resources.files(YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE)
        .joinpath(YOUTUBE_SUBTITLE_TEMPLATE_NAME)
        .read_text(encoding="utf-8")
    )
    config = yaml.safe_load(raw)
    if not isinstance(config, dict):
        raise ValueError("YouTube subtitle workflow template must be a YAML mapping.")
    return config


def _steps_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workflow = config["workflows"][YOUTUBE_SUBTITLE_WORKFLOW_ID]
    return {step["id"]: step for step in workflow["steps"]}


def _set_optional(parameters: dict[str, Any], name: str, value: str | None) -> None:
    if value is None:
        parameters.pop(name, None)
        return
    parameters[name] = value
