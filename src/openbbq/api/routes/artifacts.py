from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from openbbq.api.schemas import ApiSuccess, ArtifactImportRequest
from openbbq.application.artifacts import (
    ArtifactImportRequest as ApplicationArtifactImportRequest,
    diff_artifact_versions,
    import_artifact,
    list_artifacts,
    show_artifact,
    show_artifact_version,
)
from openbbq.errors import ValidationError

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts", response_model=ApiSuccess[dict[str, Any]])
def get_artifacts(
    request: Request,
    workflow_id: str | None = None,
    step_id: str | None = None,
    artifact_type: str | None = None,
) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    artifacts = list_artifacts(
        project_root=settings.project_root,
        config_path=settings.config_path,
        workflow_id=workflow_id,
        step_id=step_id,
        artifact_type=artifact_type,
    )
    return ApiSuccess(
        data={"artifacts": [artifact.model_dump(mode="json") for artifact in artifacts]}
    )


@router.get("/artifacts/{artifact_id}", response_model=ApiSuccess[dict[str, Any]])
def get_artifact(artifact_id: str, request: Request) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    result = show_artifact(
        project_root=settings.project_root,
        config_path=settings.config_path,
        artifact_id=artifact_id,
    )
    return ApiSuccess(
        data={
            "artifact": result.artifact.model_dump(mode="json"),
            "current_version": {
                "record": result.current_version.record.model_dump(mode="json"),
                "content": _jsonable_content(result.current_version.content),
            },
        }
    )


@router.get(
    "/artifact-versions/{from_version_id}/diff/{to_version_id}",
    response_model=ApiSuccess[dict[str, Any]],
)
def get_artifact_diff(
    from_version_id: str,
    to_version_id: str,
    request: Request,
) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    return ApiSuccess(
        data=diff_artifact_versions(
            project_root=settings.project_root,
            config_path=settings.config_path,
            from_version=from_version_id,
            to_version=to_version_id,
        )
    )


@router.get("/artifact-versions/{version_id}", response_model=ApiSuccess[dict[str, Any]])
def get_artifact_version(version_id: str, request: Request) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    version = show_artifact_version(
        project_root=settings.project_root,
        config_path=settings.config_path,
        version_id=version_id,
    )
    return ApiSuccess(
        data={
            "record": version.record.model_dump(mode="json"),
            "content": _jsonable_content(version.content),
        }
    )


@router.post("/artifacts/import", response_model=ApiSuccess[dict[str, Any]])
def post_artifact_import(
    body: ArtifactImportRequest,
    request: Request,
) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    result = import_artifact(
        ApplicationArtifactImportRequest(
            project_root=settings.project_root,
            config_path=body.config_path or settings.config_path,
            path=body.path,
            artifact_type=body.artifact_type,
            name=body.name,
        )
    )
    return ApiSuccess(
        data={
            "artifact": result.artifact.model_dump(mode="json"),
            "version": result.version.record.model_dump(mode="json"),
        }
    )


@router.get("/artifact-versions/{version_id}/file")
def get_artifact_version_file(version_id: str, request: Request) -> FileResponse:
    settings = _settings(request)
    version = show_artifact_version(
        project_root=settings.project_root,
        config_path=settings.config_path,
        version_id=version_id,
    )
    return FileResponse(
        version.record.content_path,
        media_type="application/octet-stream",
        filename=version.record.content_path.name,
    )


def _settings(request: Request):
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return settings


def _jsonable_content(content):
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content
