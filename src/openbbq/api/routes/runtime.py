from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import (
    ApiSuccess,
    DoctorData,
    ModelListData,
    ProviderAuthSetRequest,
    RuntimeSettingsData,
    SecretCheckRequest,
    SecretSetRequest,
)
from openbbq.application.diagnostics import doctor
from openbbq.application.runtime import (
    AuthCheckResult,
    AuthSetRequest,
    AuthSetResult,
    ProviderSetRequest,
    ProviderSetResult,
    auth_check,
    auth_set,
    model_list,
    provider_set,
    secret_check,
    secret_set,
    settings_show,
)
from openbbq.application.runtime import SecretSetRequest as ApplicationSecretSetRequest
from openbbq.application.runtime import SecretCheckResult
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


@router.put("/runtime/providers/{name}/auth", response_model=ApiSuccess[AuthSetResult])
def put_provider_auth(name: str, body: ProviderAuthSetRequest) -> ApiSuccess[AuthSetResult]:
    result = auth_set(
        AuthSetRequest(
            name=name,
            type=body.type,
            base_url=body.base_url,
            api_key_ref=body.api_key_ref,
            secret_value=body.secret_value,
            default_chat_model=body.default_chat_model,
            display_name=body.display_name,
        )
    )
    return ApiSuccess(data=result)


@router.post("/runtime/secrets/check", response_model=ApiSuccess[SecretCheckResult])
def post_secret_check(body: SecretCheckRequest) -> ApiSuccess[SecretCheckResult]:
    return ApiSuccess(data=secret_check(body.reference))


@router.put("/runtime/secrets", response_model=ApiSuccess[SecretCheckResult])
def put_secret(body: SecretSetRequest) -> ApiSuccess[SecretCheckResult]:
    return ApiSuccess(
        data=secret_set(ApplicationSecretSetRequest(reference=body.reference, value=body.value))
    )


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
