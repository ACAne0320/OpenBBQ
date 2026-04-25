from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

from openbbq import __version__
from openbbq.application.artifacts import (
    ArtifactImportRequest,
    import_artifact,
)
from openbbq.application.workflows import (
    WorkflowRunRequest,
    run_workflow_command,
    workflow_status,
)
from openbbq.cli import api, artifacts, plugins, projects, runtime, workflows
from openbbq.application.quickstart import (
    DEFAULT_YOUTUBE_QUALITY,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.cli.context import (
    load_config as _load_config,
    project_store as _project_store,
)
from openbbq.cli.output import (
    emit as _emit,
    emit_error as _emit_error,
)
from openbbq.errors import OpenBBQError
from openbbq.runtime.settings import load_runtime_settings
from openbbq.storage.models import ArtifactRecord
from openbbq.storage.project_store import ProjectStore


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        return _dispatch(args)
    except OpenBBQError as exc:
        _emit_error(exc, json_output=getattr(args, "json_output", False))
        return exc.exit_code


def _build_parser() -> argparse.ArgumentParser:
    global_options = _global_options(defaults=True)
    subcommand_global_options = _global_options(defaults=False)

    parser = argparse.ArgumentParser(prog="openbbq", parents=[global_options])
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", parents=[subcommand_global_options])
    projects.register(subparsers, [subcommand_global_options])
    workflows.register(subparsers, [subcommand_global_options])
    artifacts.register(subparsers, [subcommand_global_options])
    plugins.register(subparsers, [subcommand_global_options])

    runtime.register(subparsers, [subcommand_global_options])
    api.register(subparsers, [subcommand_global_options])

    subtitle = subparsers.add_parser("subtitle", parents=[subcommand_global_options])
    subtitle_sub = subtitle.add_subparsers(dest="subtitle_command", required=True)
    subtitle_local = subtitle_sub.add_parser("local", parents=[subcommand_global_options])
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

    subtitle_youtube = subtitle_sub.add_parser("youtube", parents=[subcommand_global_options])
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

    return parser


def _global_options(*, defaults: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    if defaults:
        parser.add_argument("--project", default=os.environ.get("OPENBBQ_PROJECT", "."))
        parser.add_argument("--config", default=os.environ.get("OPENBBQ_CONFIG"))
        parser.add_argument("--plugins", action="append", default=[])
        parser.add_argument("--json", action="store_true", dest="json_output")
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--debug", action="store_true")
    else:
        parser.add_argument("--project", default=argparse.SUPPRESS)
        parser.add_argument("--config", default=argparse.SUPPRESS)
        parser.add_argument("--plugins", action="append", default=argparse.SUPPRESS)
        parser.add_argument(
            "--json", action="store_true", dest="json_output", default=argparse.SUPPRESS
        )
        parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)
        parser.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    logging.getLogger("openbbq").setLevel(_effective_log_level(args))


def _effective_log_level(args: argparse.Namespace) -> int:
    if getattr(args, "debug", False):
        return logging.DEBUG
    env_level = os.environ.get("OPENBBQ_LOG_LEVEL")
    if env_level:
        return getattr(logging, env_level.upper(), logging.WARNING)
    if getattr(args, "verbose", False):
        return logging.INFO
    return logging.WARNING


def _dispatch(args: argparse.Namespace) -> int:
    _configure_logging(args)
    if args.command == "version":
        _emit({"ok": True, "version": __version__}, args.json_output, __version__)
        return 0
    for module in (projects, plugins, api, workflows, artifacts, runtime):
        result = module.dispatch(args)
        if result is not None:
            return result
    if args.command == "subtitle":
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
    config = _load_config(
        argparse.Namespace(
            project=generated.project_root,
            config=generated.config_path,
            plugins=args.plugins,
        )
    )
    store = _project_store(config)
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
    _emit(payload, args.json_output, f"Wrote {output_path}")
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
    config = _load_config(
        argparse.Namespace(
            project=generated.project_root,
            config=generated.config_path,
            plugins=args.plugins,
        )
    )
    store = _project_store(config)
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
    _emit(payload, args.json_output, f"Wrote {output_path}")
    return 0
