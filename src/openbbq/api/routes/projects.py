from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess, ProjectInfoData, ProjectInitData, ProjectInitRequest
from openbbq.application.projects import ProjectInitRequest as ApplicationProjectInitRequest
from openbbq.application.projects import init_project, project_info
from openbbq.errors import ValidationError

router = APIRouter(tags=["projects"])


@router.post("/projects/init", response_model=ApiSuccess[ProjectInitData])
def init_project_route(body: ProjectInitRequest) -> ApiSuccess[ProjectInitData]:
    result = init_project(
        ApplicationProjectInitRequest(
            project_root=body.project_root,
            config_path=body.config_path,
        )
    )
    return ApiSuccess(data=ProjectInitData(**result.model_dump()))


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
