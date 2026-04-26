from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.project_refs import set_active_project
from openbbq.api.schemas import ApiSuccess, ProjectInfoData, ProjectInitData, ProjectInitRequest
from openbbq.application.projects import ProjectInitRequest as ApplicationProjectInitRequest
from openbbq.application.projects import init_project, project_info

router = APIRouter(tags=["projects"])


@router.post("/projects/init", response_model=ApiSuccess[ProjectInitData])
def init_project_route(body: ProjectInitRequest, request: Request) -> ApiSuccess[ProjectInitData]:
    result = init_project(
        ApplicationProjectInitRequest(
            project_root=body.project_root,
            config_path=body.config_path,
        )
    )
    set_active_project(
        request,
        project_root=body.project_root,
        config_path=result.config_path,
    )
    return ApiSuccess(data=api_model(ProjectInitData, result))


@router.get("/projects/current", response_model=ApiSuccess[ProjectInfoData])
def current_project(request: Request) -> ApiSuccess[ProjectInfoData]:
    settings = active_project_settings(request)
    info = project_info(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=api_model(ProjectInfoData, info))
