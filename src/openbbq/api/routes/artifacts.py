from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.project_refs import known_project_references
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
from openbbq.errors import ArtifactNotFoundError

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts", response_model=ApiSuccess[ArtifactListData])
def get_artifacts(
    request: Request,
    workflow_id: str | None = None,
    step_id: str | None = None,
    artifact_type: str | None = None,
) -> ApiSuccess[ArtifactListData]:
    settings = active_project_settings(request)
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
    result, _reference = _show_artifact_from_known_projects(request, artifact_id)
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
    return ApiSuccess(
        data=ArtifactDiffData.model_validate(
            _diff_artifact_versions_from_known_projects(
                request,
                from_version_id=from_version_id,
                to_version_id=to_version_id,
            )
        ),
    )


@router.get(
    "/artifact-versions/{version_id}",
    response_model=ApiSuccess[ArtifactVersionData],
)
def get_artifact_version(version_id: str, request: Request) -> ApiSuccess[ArtifactVersionData]:
    version, _reference = _show_artifact_version_from_known_projects(request, version_id)
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
    preview, _reference = _preview_artifact_version_from_known_projects(
        request,
        version_id,
        max_bytes=max_bytes,
    )
    return ApiSuccess(data=api_model(ArtifactPreviewData, preview))


@router.post(
    "/artifact-versions/{version_id}/export",
    response_model=ApiSuccess[ArtifactExportData],
)
def post_artifact_version_export(
    version_id: str,
    body: ArtifactExportRequest,
    request: Request,
) -> ApiSuccess[ArtifactExportData]:
    _version, reference = _show_artifact_version_from_known_projects(request, version_id)
    result = export_artifact_version(
        ApplicationArtifactExportRequest(
            project_root=reference.project_root,
            config_path=body.config_path or reference.config_path,
            version_id=version_id,
            path=body.path,
        )
    )
    return ApiSuccess(data=api_model(ArtifactExportData, result))


@router.post("/artifacts/import", response_model=ApiSuccess[ArtifactImportData])
def post_artifact_import(
    body: ArtifactImportRequest,
    request: Request,
) -> ApiSuccess[ArtifactImportData]:
    settings = active_project_settings(request)
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
    version, _reference = _show_artifact_version_from_known_projects(request, version_id)
    return FileResponse(
        version.record.content_path,
        media_type="application/octet-stream",
        filename=version.record.content_path.name,
    )


def _jsonable_content(content):
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content


def _show_artifact_from_known_projects(request: Request, artifact_id: str):
    for reference in known_project_references(request):
        try:
            return (
                show_artifact(
                    project_root=reference.project_root,
                    config_path=reference.config_path,
                    artifact_id=artifact_id,
                ),
                reference,
            )
        except ArtifactNotFoundError:
            continue
    raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")


def _show_artifact_version_from_known_projects(request: Request, version_id: str):
    for reference in known_project_references(request):
        try:
            return (
                show_artifact_version(
                    project_root=reference.project_root,
                    config_path=reference.config_path,
                    version_id=version_id,
                ),
                reference,
            )
        except ArtifactNotFoundError:
            continue
    raise ArtifactNotFoundError(f"artifact version not found: {version_id}")


def _preview_artifact_version_from_known_projects(
    request: Request,
    version_id: str,
    *,
    max_bytes: int,
):
    for reference in known_project_references(request):
        try:
            return (
                preview_artifact_version(
                    project_root=reference.project_root,
                    config_path=reference.config_path,
                    version_id=version_id,
                    max_bytes=max_bytes,
                ),
                reference,
            )
        except ArtifactNotFoundError:
            continue
    raise ArtifactNotFoundError(f"artifact version not found: {version_id}")


def _diff_artifact_versions_from_known_projects(
    request: Request,
    *,
    from_version_id: str,
    to_version_id: str,
):
    for reference in known_project_references(request):
        try:
            return diff_artifact_versions(
                project_root=reference.project_root,
                config_path=reference.config_path,
                from_version=from_version_id,
                to_version=to_version_id,
            )
        except ArtifactNotFoundError:
            continue
    raise ArtifactNotFoundError(f"artifact version not found: {from_version_id}")
