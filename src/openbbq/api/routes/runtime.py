from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess, DoctorData, ModelListData, RuntimeSettingsData
from openbbq.application.diagnostics import doctor
from openbbq.application.runtime import (
    AuthCheckResult,
    ProviderSetRequest,
    ProviderSetResult,
    auth_check,
    model_list,
    provider_set,
    settings_show,
)
from openbbq.errors import ValidationError

router = APIRouter(tags=["runtime"])


@router.get("/runtime/settings", response_model=ApiSuccess[RuntimeSettingsData])
def get_runtime_settings() -> ApiSuccess[RuntimeSettingsData]:
    result = settings_show()
    return ApiSuccess(data=RuntimeSettingsData(settings=result.settings))


@router.put("/runtime/providers/{name}", response_model=ApiSuccess[ProviderSetResult])
def put_provider(name: str, body: ProviderSetRequest) -> ApiSuccess[ProviderSetResult]:
    result = provider_set(body.model_copy(update={"name": name}))
    return ApiSuccess(data=result)


@router.get("/runtime/providers/{name}/check", response_model=ApiSuccess[AuthCheckResult])
def check_provider(name: str) -> ApiSuccess[AuthCheckResult]:
    return ApiSuccess(data=auth_check(name))


@router.get("/runtime/models", response_model=ApiSuccess[ModelListData])
def get_models() -> ApiSuccess[ModelListData]:
    result = model_list()
    return ApiSuccess(data=ModelListData(models=result.models))


@router.get("/doctor", response_model=ApiSuccess[DoctorData])
def get_doctor(request: Request, workflow_id: str | None = None) -> ApiSuccess[DoctorData]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    result = doctor(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
        workflow_id=workflow_id,
    )
    return ApiSuccess(data=DoctorData(ok=result.ok, checks=result.checks))
