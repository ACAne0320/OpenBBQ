from __future__ import annotations

from pathlib import Path
from typing import Any

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.domain.models import ARTIFACT_TYPES, ProjectConfig
from openbbq.errors import OpenBBQError, ValidationError
from openbbq.storage.models import ArtifactRecord, StoredArtifactVersion
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.diff import diff_artifact_versions as diff_versions

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
    config = load_project_config(request.project_root, config_path=request.config_path)
    artifact, version = _store(config).write_artifact_version(
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
    config = load_project_config(project_root, config_path=config_path)
    store = _store(config)
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
    config = load_project_config(project_root, config_path=config_path)
    store = _store(config)
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
    config = load_project_config(project_root, config_path=config_path)
    return _store(config).read_artifact_version(version_id)


def diff_artifact_versions(
    *,
    project_root: Path,
    from_version: str,
    to_version: str,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = load_project_config(project_root, config_path=config_path)
    return diff_versions(_store(config), from_version, to_version)


def _artifact_workflow_id(store: ProjectStore, artifact: ArtifactRecord) -> str | None:
    if artifact.current_version_id is None:
        return None
    version = store.read_artifact_version(artifact.current_version_id)
    workflow_id = version.record.lineage.get("workflow_id")
    return workflow_id if isinstance(workflow_id, str) else None


def _store(config: ProjectConfig) -> ProjectStore:
    return ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
