from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from openbbq.api.schemas import (
    ApiSuccess,
    ArtifactDiffData,
    ArtifactExportData,
    ArtifactExportRequest,
    ArtifactImportData,
    ArtifactImportRequest,
    ArtifactListData,
    ArtifactPreviewData,
    ArtifactShowData,
    ArtifactVersionData,
)
from openbbq.application.artifacts import (
    ArtifactExportRequest as ApplicationArtifactExportRequest,
    ArtifactImportRequest as ApplicationArtifactImportRequest,
    diff_artifact_versions,
    export_artifact_version,
    import_artifact,
    list_artifacts,
    preview_artifact_version,
    show_artifact,
    show_artifact_version,
)
from openbbq.errors import ValidationError

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts", response_model=ApiSuccess[ArtifactListData])
def get_artifacts(
    request: Request,
    workflow_id: str | None = None,
    step_id: str | None = None,
    artifact_type: str | None = None,
) -> ApiSuccess[ArtifactListData]:
    settings = _settings(request)
    artifacts = list_artifacts(
        project_root=settings.project_root,
        config_path=settings.config_path,
        workflow_id=workflow_id,
        step_id=step_id,
        artifact_type=artifact_type,
    )
    return ApiSuccess(data=ArtifactListData(artifacts=tuple(artifacts)))


@router.get("/artifacts/{artifact_id}", response_model=ApiSuccess[ArtifactShowData])
def get_artifact(artifact_id: str, request: Request) -> ApiSuccess[ArtifactShowData]:
    settings = _settings(request)
    result = show_artifact(
        project_root=settings.project_root,
        config_path=settings.config_path,
        artifact_id=artifact_id,
    )
    return ApiSuccess(
        data=ArtifactShowData(
            artifact=result.artifact,
            current_version=ArtifactVersionData(
                record=result.current_version.record,
                content=_jsonable_content(result.current_version.content),
            ),
        )
    )


@router.get(
    "/artifact-versions/{from_version_id}/diff/{to_version_id}",
    response_model=ApiSuccess[ArtifactDiffData],
)
def get_artifact_diff(
    from_version_id: str,
    to_version_id: str,
    request: Request,
) -> ApiSuccess[ArtifactDiffData]:
    settings = _settings(request)
    return ApiSuccess(
        data=ArtifactDiffData.model_validate(
            diff_artifact_versions(
                project_root=settings.project_root,
                config_path=settings.config_path,
                from_version=from_version_id,
                to_version=to_version_id,
            )
        )
    )


@router.get(
    "/artifact-versions/{version_id}",
    response_model=ApiSuccess[ArtifactVersionData],
)
def get_artifact_version(version_id: str, request: Request) -> ApiSuccess[ArtifactVersionData]:
    settings = _settings(request)
    version = show_artifact_version(
        project_root=settings.project_root,
        config_path=settings.config_path,
        version_id=version_id,
    )
    return ApiSuccess(
        data=ArtifactVersionData(record=version.record, content=_jsonable_content(version.content))
    )


@router.get(
    "/artifact-versions/{version_id}/preview",
    response_model=ApiSuccess[ArtifactPreviewData],
)
def get_artifact_version_preview(
    version_id: str,
    request: Request,
    max_bytes: int = 65536,
) -> ApiSuccess[ArtifactPreviewData]:
    settings = _settings(request)
    preview = preview_artifact_version(
        project_root=settings.project_root,
        config_path=settings.config_path,
        version_id=version_id,
        max_bytes=max_bytes,
    )
    return ApiSuccess(data=ArtifactPreviewData(**preview.model_dump()))


@router.post(
    "/artifact-versions/{version_id}/export",
    response_model=ApiSuccess[ArtifactExportData],
)
def post_artifact_version_export(
    version_id: str,
    body: ArtifactExportRequest,
    request: Request,
) -> ApiSuccess[ArtifactExportData]:
    settings = _settings(request)
    result = export_artifact_version(
        ApplicationArtifactExportRequest(
            project_root=settings.project_root,
            config_path=body.config_path or settings.config_path,
            version_id=version_id,
            path=body.path,
        )
    )
    return ApiSuccess(data=ArtifactExportData(**result.model_dump()))


@router.post("/artifacts/import", response_model=ApiSuccess[ArtifactImportData])
def post_artifact_import(
    body: ArtifactImportRequest,
    request: Request,
) -> ApiSuccess[ArtifactImportData]:
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
        data=ArtifactImportData(artifact=result.artifact, version=result.version.record)
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
