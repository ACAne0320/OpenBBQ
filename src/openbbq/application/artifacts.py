from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openbbq.application.project_context import load_project_context
from openbbq.domain.base import JsonValue, OpenBBQModel
from openbbq.domain.models import ARTIFACT_TYPES
from openbbq.errors import OpenBBQError, ValidationError
from openbbq.storage.models import ArtifactRecord, ArtifactVersionRecord, StoredArtifactVersion
from openbbq.workflow.diff import diff_artifact_versions as diff_versions

if TYPE_CHECKING:
    from openbbq.storage.project_store import ProjectStore

FILE_BACKED_IMPORT_TYPES = frozenset({"audio", "image", "video"})


class ArtifactImportRequest(OpenBBQModel):
    project_root: Path
    path: Path
    artifact_type: str
    name: str
    config_path: Path | None = None


class ArtifactImportResult(OpenBBQModel):
    artifact: ArtifactRecord
    version: StoredArtifactVersion


class ArtifactShowResult(OpenBBQModel):
    artifact: ArtifactRecord
    current_version: StoredArtifactVersion


class ArtifactPreviewResult(OpenBBQModel):
    version: ArtifactVersionRecord
    content: JsonValue | None
    truncated: bool
    content_encoding: str
    content_size: int


class ArtifactExportRequest(OpenBBQModel):
    project_root: Path
    version_id: str
    path: Path
    config_path: Path | None = None


class ArtifactExportResult(OpenBBQModel):
    version_id: str
    path: Path
    bytes_written: int


def import_artifact(request: ArtifactImportRequest) -> ArtifactImportResult:
    source = request.path.expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"Artifact import source is not a file: {source}")
    if request.artifact_type not in ARTIFACT_TYPES:
        raise ValidationError(f"Artifact type '{request.artifact_type}' is not registered.")
    if request.artifact_type not in FILE_BACKED_IMPORT_TYPES:
        allowed = ", ".join(sorted(FILE_BACKED_IMPORT_TYPES))
        raise ValidationError(
            f"Artifact import supports file-backed artifact types only: {allowed}."
        )
    context = load_project_context(request.project_root, config_path=request.config_path)
    artifact, version = context.store.write_artifact_version(
        artifact_type=request.artifact_type,
        name=request.name,
        content=None,
        file_path=source,
        metadata={},
        created_by_step_id=None,
        lineage={"source": "cli_import", "original_path": str(source)},
    )
    return ArtifactImportResult(artifact=artifact.record, version=version)


def list_artifacts(
    *,
    project_root: Path,
    config_path: Path | None = None,
    workflow_id: str | None = None,
    step_id: str | None = None,
    artifact_type: str | None = None,
) -> list[ArtifactRecord]:
    context = load_project_context(project_root, config_path=config_path)
    store = context.store
    artifacts = store.list_artifacts()
    if workflow_id:
        artifacts = [
            artifact
            for artifact in artifacts
            if _artifact_workflow_id(store, artifact) == workflow_id
        ]
    if step_id:
        artifacts = [
            artifact
            for artifact in artifacts
            if artifact.created_by_step_id == step_id or artifact.name.startswith(f"{step_id}.")
        ]
    if artifact_type:
        artifacts = [artifact for artifact in artifacts if artifact.type == artifact_type]
    return artifacts


def show_artifact(
    *,
    project_root: Path,
    artifact_id: str,
    config_path: Path | None = None,
) -> ArtifactShowResult:
    context = load_project_context(project_root, config_path=config_path)
    store = context.store
    artifact = store.read_artifact(artifact_id)
    if artifact.current_version_id is None:
        raise OpenBBQError(
            "artifact_not_found",
            f"Artifact '{artifact.id}' does not have a current version.",
            1,
        )
    return ArtifactShowResult(
        artifact=artifact,
        current_version=store.read_artifact_version(artifact.current_version_id),
    )


def show_artifact_version(
    *,
    project_root: Path,
    version_id: str,
    config_path: Path | None = None,
) -> StoredArtifactVersion:
    context = load_project_context(project_root, config_path=config_path)
    return context.store.read_artifact_version(version_id)


def preview_artifact_version(
    *,
    project_root: Path,
    version_id: str,
    max_bytes: int = 65536,
    config_path: Path | None = None,
) -> ArtifactPreviewResult:
    if max_bytes < 1:
        raise ValidationError("Artifact preview max_bytes must be at least 1.")
    context = load_project_context(project_root, config_path=config_path)
    version = context.store.read_artifact_version_record(version_id)
    if version.content_encoding in {"bytes", "file"}:
        return ArtifactPreviewResult(
            version=version,
            content=None,
            truncated=False,
            content_encoding=version.content_encoding,
            content_size=version.content_size,
        )
    text, truncated = _read_bounded_text(version.content_path, max_bytes)
    content: JsonValue = text
    if version.content_encoding == "json" and not truncated:
        content = json.loads(text)
    return ArtifactPreviewResult(
        version=version,
        content=content,
        truncated=truncated,
        content_encoding=version.content_encoding,
        content_size=version.content_size,
    )


def export_artifact_version(request: ArtifactExportRequest) -> ArtifactExportResult:
    version = show_artifact_version(
        project_root=request.project_root,
        config_path=request.config_path,
        version_id=request.version_id,
    )
    if version.record.content_encoding == "file":
        raise ValidationError("Artifact export supports stored text, JSON, and bytes content only.")
    output_path = request.path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(version.content, bytes):
        payload = version.content
        output_path.write_bytes(payload)
    else:
        payload = _content_text(version.content).encode("utf-8")
        output_path.write_bytes(payload)
    return ArtifactExportResult(
        version_id=version.record.id,
        path=output_path,
        bytes_written=len(payload),
    )


def diff_artifact_versions(
    *,
    project_root: Path,
    from_version: str,
    to_version: str,
    config_path: Path | None = None,
) -> dict[str, Any]:
    context = load_project_context(project_root, config_path=config_path)
    return diff_versions(context.store, from_version, to_version)


def _artifact_workflow_id(store: "ProjectStore", artifact: ArtifactRecord) -> str | None:
    if artifact.current_version_id is None:
        return None
    version = store.read_artifact_version(artifact.current_version_id)
    workflow_id = version.record.lineage.get("workflow_id")
    return workflow_id if isinstance(workflow_id, str) else None


def _content_text(content: Any) -> str:
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)
    return str(content)


def _read_bounded_text(path: Path, max_bytes: int) -> tuple[str, bool]:
    with path.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    truncated = len(payload) > max_bytes
    if truncated:
        payload = payload[:max_bytes]
    return payload.decode("utf-8", errors="ignore"), truncated
