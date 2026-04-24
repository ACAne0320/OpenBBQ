from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess, ProjectInfoData
from openbbq.application.projects import project_info
from openbbq.errors import ValidationError

router = APIRouter(tags=["projects"])


@router.get("/projects/current", response_model=ApiSuccess[ProjectInfoData])
def current_project(request: Request) -> ApiSuccess[ProjectInfoData]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    info = project_info(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=ProjectInfoData(**info.model_dump()))
