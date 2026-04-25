from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from openbbq.application.artifacts import ArtifactImportRequest, import_artifact
from openbbq.application.quickstart import (
    DEFAULT_YOUTUBE_QUALITY,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.application.workflows import (
    WorkflowRunRequest,
    run_workflow_command,
    workflow_status,
)
from openbbq.cli.context import project_store
from openbbq.cli.output import emit
from openbbq.config.loader import load_project_config
from openbbq.errors import OpenBBQError
from openbbq.runtime.settings import load_runtime_settings
from openbbq.storage.models import ArtifactRecord
from openbbq.storage.project_store import ProjectStore


def register(subparsers, parents) -> None:
    subtitle = subparsers.add_parser("subtitle", parents=parents)
    subtitle_sub = subtitle.add_subparsers(dest="subtitle_command", required=True)
    subtitle_local = subtitle_sub.add_parser("local", parents=parents)
    subtitle_local.add_argument("--input", required=True)
    subtitle_local.add_argument("--source", required=True)
    subtitle_local.add_argument("--target", required=True)
    subtitle_local.add_argument("--output", required=True)
    subtitle_local.add_argument("--provider", default="openai")
    subtitle_local.add_argument("--model")
    subtitle_local.add_argument("--asr-model")
    subtitle_local.add_argument("--asr-device")
    subtitle_local.add_argument("--asr-compute-type")
    subtitle_local.add_argument("--force", action="store_true")

    subtitle_youtube = subtitle_sub.add_parser("youtube", parents=parents)
    subtitle_youtube.add_argument("--url", required=True)
    subtitle_youtube.add_argument("--source", required=True)
    subtitle_youtube.add_argument("--target", required=True)
    subtitle_youtube.add_argument("--output", required=True)
    subtitle_youtube.add_argument("--provider", default="openai")
    subtitle_youtube.add_argument("--model")
    subtitle_youtube.add_argument("--asr-model")
    subtitle_youtube.add_argument("--asr-device")
    subtitle_youtube.add_argument("--asr-compute-type")
    subtitle_youtube.add_argument("--quality", default=DEFAULT_YOUTUBE_QUALITY)
    subtitle_youtube.add_argument(
        "--auth",
        choices=("auto", "anonymous", "browser_cookies"),
        default="auto",
    )
    subtitle_youtube.add_argument("--browser")
    subtitle_youtube.add_argument("--browser-profile")
    subtitle_youtube.add_argument("--force", action="store_true")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command != "subtitle":
        return None
    if args.subtitle_command == "local":
        return _subtitle_local(args)
    if args.subtitle_command == "youtube":
        return _subtitle_youtube(args)
    return 2


def _latest_workflow_artifact_content(
    store: ProjectStore,
    *,
    workflow_id: str,
    artifact_type: str,
    artifact_name: str,
) -> tuple[ArtifactRecord, Any]:
    matches = []
    for artifact in store.list_artifacts():
        if artifact.type != artifact_type or artifact.name != artifact_name:
            continue
        if artifact.current_version_id is None:
            continue
        version = store.read_artifact_version(artifact.current_version_id)
        if version.record.lineage.get("workflow_id") != workflow_id:
            continue
        matches.append((artifact, version))
    if not matches:
        raise OpenBBQError(
            "artifact_not_found",
            f"Workflow '{workflow_id}' did not produce artifact '{artifact_name}'.",
            1,
        )
    matches.sort(key=lambda item: item[0].updated_at)
    artifact, version = matches[-1]
    return artifact, version.content


def _subtitle_local(args: argparse.Namespace) -> int:
    workspace_root = Path(args.project).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings()
    faster_whisper = settings.models.faster_whisper
    generated = write_local_subtitle_workflow(
        workspace_root=workspace_root,
        video_selector="project.art_source_video",
        source_lang=args.source,
        target_lang=args.target,
        provider=args.provider,
        model=args.model,
        asr_model=args.asr_model or faster_whisper.default_model,
        asr_device=args.asr_device or faster_whisper.default_device,
        asr_compute_type=args.asr_compute_type or faster_whisper.default_compute_type,
    )
    imported = import_artifact(
        ArtifactImportRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            path=Path(args.input),
            artifact_type="video",
            name="source.video",
        )
    )
    generated = write_local_subtitle_workflow(
        workspace_root=workspace_root,
        video_selector=f"project.{imported.artifact.id}",
        source_lang=args.source,
        target_lang=args.target,
        provider=args.provider,
        model=args.model,
        asr_model=args.asr_model or faster_whisper.default_model,
        asr_device=args.asr_device or faster_whisper.default_device,
        asr_compute_type=args.asr_compute_type or faster_whisper.default_compute_type,
        run_id=generated.run_id,
    )
    config = load_project_config(
        generated.project_root,
        config_path=generated.config_path,
        extra_plugin_paths=args.plugins,
    )
    store = project_store(config)
    state = workflow_status(
        project_root=generated.project_root,
        config_path=generated.config_path,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=generated.workflow_id,
    )
    force = state.status == "completed" or (args.force and state.status in {"completed", "running"})
    result = run_workflow_command(
        WorkflowRunRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=generated.workflow_id,
            force=force,
        )
    )
    artifact, content = _latest_workflow_artifact_content(
        store,
        workflow_id=generated.workflow_id,
        artifact_type="subtitle",
        artifact_name="subtitle.subtitle",
    )
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(str(content), encoding="utf-8")
    payload = {
        "ok": True,
        "workflow_id": result.workflow_id,
        "status": result.status,
        "step_count": result.step_count,
        "artifact_count": result.artifact_count,
        "output_path": str(output_path),
        "source_artifact_id": imported.artifact.id,
        "subtitle_artifact_id": artifact.id,
        "generated_run_id": generated.run_id,
        "generated_project_root": str(generated.project_root),
        "generated_config_path": str(generated.config_path),
    }
    emit(payload, args.json_output, f"Wrote {output_path}")
    return 0


def _subtitle_youtube(args: argparse.Namespace) -> int:
    workspace_root = Path(args.project).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings()
    faster_whisper = settings.models.faster_whisper
    generated = write_youtube_subtitle_workflow(
        workspace_root=workspace_root,
        url=args.url,
        source_lang=args.source,
        target_lang=args.target,
        provider=args.provider,
        model=args.model,
        asr_model=args.asr_model or faster_whisper.default_model,
        asr_device=args.asr_device or faster_whisper.default_device,
        asr_compute_type=args.asr_compute_type or faster_whisper.default_compute_type,
        quality=args.quality,
        auth=args.auth,
        browser=args.browser,
        browser_profile=args.browser_profile,
    )
    config = load_project_config(
        generated.project_root,
        config_path=generated.config_path,
        extra_plugin_paths=args.plugins,
    )
    store = project_store(config)
    state = workflow_status(
        project_root=generated.project_root,
        config_path=generated.config_path,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=generated.workflow_id,
    )
    force = state.status == "completed" or (args.force and state.status in {"completed", "running"})
    result = run_workflow_command(
        WorkflowRunRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=generated.workflow_id,
            force=force,
        )
    )
    artifact, content = _latest_workflow_artifact_content(
        store,
        workflow_id=generated.workflow_id,
        artifact_type="subtitle",
        artifact_name="subtitle.subtitle",
    )
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(str(content), encoding="utf-8")
    payload = {
        "ok": True,
        "workflow_id": result.workflow_id,
        "status": result.status,
        "step_count": result.step_count,
        "artifact_count": result.artifact_count,
        "output_path": str(output_path),
        "subtitle_artifact_id": artifact.id,
        "generated_run_id": generated.run_id,
        "generated_project_root": str(generated.project_root),
        "generated_config_path": str(generated.config_path),
    }
    emit(payload, args.json_output, f"Wrote {output_path}")
    return 0
