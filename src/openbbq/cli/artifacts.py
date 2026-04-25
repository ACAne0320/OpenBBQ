from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.application.artifacts import (
    ArtifactImportRequest,
    diff_artifact_versions as diff_artifact_versions_command,
    import_artifact,
    list_artifacts as list_artifacts_command,
    show_artifact,
)
from openbbq.cli.output import emit, jsonable_content


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    parents: list[argparse.ArgumentParser],
) -> None:
    artifact = subparsers.add_parser("artifact", parents=parents)
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_sub.add_parser("list", parents=parents)
    artifact_list.add_argument("--workflow")
    artifact_list.add_argument("--step")
    artifact_list.add_argument("--type", dest="artifact_type")
    artifact_show = artifact_sub.add_parser("show", parents=parents)
    artifact_show.add_argument("artifact_id")
    artifact_diff = artifact_sub.add_parser("diff", parents=parents)
    artifact_diff.add_argument("from_version")
    artifact_diff.add_argument("to_version")
    artifact_import = artifact_sub.add_parser("import", parents=parents)
    artifact_import.add_argument("path")
    artifact_import.add_argument("--type", dest="artifact_type", required=True)
    artifact_import.add_argument("--name", required=True)


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command != "artifact":
        return None
    if args.artifact_command == "diff":
        return _artifact_diff(args)
    if args.artifact_command == "import":
        return _artifact_import(args)
    if args.artifact_command == "list":
        return _artifact_list(args)
    if args.artifact_command == "show":
        return _artifact_show(args)
    return 2


def _artifact_list(args: argparse.Namespace) -> int:
    artifacts = list_artifacts_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        workflow_id=args.workflow,
        step_id=args.step,
        artifact_type=args.artifact_type,
    )
    payload = {"ok": True, "artifacts": artifacts}
    emit(payload, args.json_output, "\n".join(artifact.id for artifact in artifacts))
    return 0


def _artifact_diff(args: argparse.Namespace) -> int:
    result = diff_artifact_versions_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        from_version=args.from_version,
        to_version=args.to_version,
    )
    payload = {"ok": True, **result}
    emit(payload, args.json_output, result["diff"])
    return 0


def _artifact_import(args: argparse.Namespace) -> int:
    result = import_artifact(
        ArtifactImportRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
            path=Path(args.path),
            artifact_type=args.artifact_type,
            name=args.name,
        )
    )
    payload = {"ok": True, "artifact": result.artifact, "version": result.version.record}
    emit(payload, args.json_output, result.artifact.id)
    return 0


def _artifact_show(args: argparse.Namespace) -> int:
    result = show_artifact(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        artifact_id=args.artifact_id,
    )
    payload = {
        "ok": True,
        "artifact": result.artifact,
        "current_version": {
            "record": result.current_version.record,
            "content": jsonable_content(result.current_version.content),
        },
    }
    emit(payload, args.json_output, jsonable_content(result.current_version.content))
    return 0
