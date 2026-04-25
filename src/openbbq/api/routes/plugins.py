from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import ApiSuccess, PluginListData
from openbbq.application.plugins import PluginInfoResult, plugin_info, plugin_list

router = APIRouter(tags=["plugins"])


@router.get("/plugins", response_model=ApiSuccess[PluginListData])
def list_plugins(request: Request) -> ApiSuccess[PluginListData]:
    settings = active_project_settings(request)
    result = plugin_list(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=api_model(PluginListData, result))


@router.get("/plugins/{plugin_name}", response_model=ApiSuccess[PluginInfoResult])
def get_plugin(plugin_name: str, request: Request) -> ApiSuccess[PluginInfoResult]:
    settings = active_project_settings(request)
    return ApiSuccess(
        data=plugin_info(
            project_root=settings.project_root,
            config_path=settings.config_path,
            plugin_paths=settings.plugin_paths,
            plugin_name=plugin_name,
        )
    )
