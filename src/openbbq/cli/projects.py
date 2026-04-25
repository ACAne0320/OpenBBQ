from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.application.projects import (
    ProjectInitRequest,
    init_project as init_project_command,
    project_info as project_info_command,
)
from openbbq.cli.context import load_config as _load_config
from openbbq.cli.output import emit as _emit


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    parents: list[argparse.ArgumentParser],
) -> None:
    subparsers.add_parser("init", parents=parents)

    project = subparsers.add_parser("project", parents=parents)
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_sub.add_parser("list", parents=parents)
    project_sub.add_parser("info", parents=parents)


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command == "init":
        return _init_project(args)
    if args.command == "project":
        if args.project_command == "list":
            return _project_list(args)
        if args.project_command == "info":
            return _project_info(args)
    return None


def _init_project(args: argparse.Namespace) -> int:
    result = init_project_command(
        ProjectInitRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
        )
    )
    _emit(
        {"ok": True, "config_path": str(result.config_path)},
        args.json_output,
        f"Initialized {result.config_path}",
    )
    return 0


def _project_list(args: argparse.Namespace) -> int:
    config = _load_config(args)
    payload = {
        "ok": True,
        "projects": [
            {
                "id": config.project.id,
                "name": config.project.name,
                "root_path": str(config.root_path),
            }
        ],
    }
    _emit(payload, args.json_output, config.project.name)
    return 0


def _project_info(args: argparse.Namespace) -> int:
    info = project_info_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
    )
    payload = {
        "ok": True,
        "project": {"id": info.id, "name": info.name},
        "root_path": str(info.root_path),
        "config_path": str(info.config_path),
        "workflow_count": info.workflow_count,
        "plugin_paths": [str(path) for path in info.plugin_paths],
        "artifact_storage_path": str(info.artifact_storage_path),
    }
    _emit(payload, args.json_output, f"{info.name}: {info.workflow_count} workflow(s)")
    return 0
