from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess, PluginListData
from openbbq.application.plugins import PluginInfoResult, plugin_info, plugin_list
from openbbq.errors import ValidationError

router = APIRouter(tags=["plugins"])


@router.get("/plugins", response_model=ApiSuccess[PluginListData])
def list_plugins(request: Request) -> ApiSuccess[PluginListData]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    result = plugin_list(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=PluginListData(**result.model_dump()))


@router.get("/plugins/{plugin_name}", response_model=ApiSuccess[PluginInfoResult])
def get_plugin(plugin_name: str, request: Request) -> ApiSuccess[PluginInfoResult]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return ApiSuccess(
        data=plugin_info(
            project_root=settings.project_root,
            config_path=settings.config_path,
            plugin_paths=settings.plugin_paths,
            plugin_name=plugin_name,
        )
    )
