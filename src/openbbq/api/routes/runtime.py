from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.context import active_project_settings
from openbbq.api.schemas import (
    ApiSuccess,
    DoctorData,
    FasterWhisperDownloadData,
    FasterWhisperDownloadRequest,
    FasterWhisperDownloadStatusData,
    FasterWhisperSettingsSetRequest,
    ModelListData,
    ProviderAuthSetRequest,
    ProviderConnectionTestData,
    ProviderConnectionTestRequest,
    ProviderModelListData,
    ProviderSecretValueData,
    RuntimeDefaultsSetRequest,
    RuntimeSettingsData,
    RuntimeSettingsSetData,
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
    defaults_set,
    faster_whisper_download,
    faster_whisper_download_status,
    faster_whisper_set,
    model_list,
    provider_model_list,
    provider_connection_test,
    provider_secret_value,
    provider_set,
    secret_check,
    secret_set,
    settings_show,
)
from openbbq.application.runtime import (
    FasterWhisperDownloadRequest as ApplicationFasterWhisperDownloadRequest,
)
from openbbq.application.runtime import (
    FasterWhisperSetRequest as ApplicationFasterWhisperSetRequest,
)
from openbbq.application.runtime import (
    RuntimeDefaultsSetRequest as ApplicationRuntimeDefaultsSetRequest,
)
from openbbq.application.runtime import SecretSetRequest as ApplicationSecretSetRequest
from openbbq.application.runtime import (
    ProviderConnectionTestRequest as ApplicationProviderConnectionTestRequest,
)
from openbbq.application.runtime import SecretCheckResult

router = APIRouter(tags=["runtime"])


@router.get("/runtime/settings", response_model=ApiSuccess[RuntimeSettingsData])
def get_runtime_settings() -> ApiSuccess[RuntimeSettingsData]:
    result = settings_show()
    return ApiSuccess(data=RuntimeSettingsData(settings=result.settings))


@router.put("/runtime/defaults", response_model=ApiSuccess[RuntimeSettingsSetData])
def put_runtime_defaults(
    body: RuntimeDefaultsSetRequest,
) -> ApiSuccess[RuntimeSettingsSetData]:
    result = defaults_set(
        ApplicationRuntimeDefaultsSetRequest(
            llm_provider=body.llm_provider,
            asr_provider=body.asr_provider,
        )
    )
    return ApiSuccess(
        data=RuntimeSettingsSetData(settings=result.settings, config_path=result.config_path)
    )


@router.put("/runtime/providers/{name}", response_model=ApiSuccess[ProviderSetResult])
def put_provider(name: str, body: ProviderSetRequest) -> ApiSuccess[ProviderSetResult]:
    result = provider_set(body.model_copy(update={"name": name}))
    return ApiSuccess(data=result)


@router.get("/runtime/providers/{name}/check", response_model=ApiSuccess[AuthCheckResult])
def check_provider(name: str) -> ApiSuccess[AuthCheckResult]:
    return ApiSuccess(data=auth_check(name))


@router.get("/runtime/providers/{name}/models", response_model=ApiSuccess[ProviderModelListData])
def get_provider_models(name: str) -> ApiSuccess[ProviderModelListData]:
    result = provider_model_list(name)
    return ApiSuccess(data=ProviderModelListData(models=result.models))


@router.get("/runtime/providers/{name}/secret", response_model=ApiSuccess[ProviderSecretValueData])
def get_provider_secret(name: str) -> ApiSuccess[ProviderSecretValueData]:
    result = provider_secret_value(name)
    return ApiSuccess(data=ProviderSecretValueData(value=result.value))


@router.post(
    "/runtime/providers/test-connection",
    response_model=ApiSuccess[ProviderConnectionTestData],
)
def post_provider_connection_test(
    body: ProviderConnectionTestRequest,
) -> ApiSuccess[ProviderConnectionTestData]:
    result = provider_connection_test(
        ApplicationProviderConnectionTestRequest(
            provider_name=body.provider_name,
            base_url=body.base_url,
            api_key=body.api_key,
            model=body.model,
        )
    )
    return ApiSuccess(data=ProviderConnectionTestData(ok=result.ok, message=result.message))


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


@router.put("/runtime/models/faster-whisper", response_model=ApiSuccess[RuntimeSettingsSetData])
def put_faster_whisper_settings(
    body: FasterWhisperSettingsSetRequest,
) -> ApiSuccess[RuntimeSettingsSetData]:
    result = faster_whisper_set(
        ApplicationFasterWhisperSetRequest(
            cache_dir=body.cache_dir,
            default_model=body.default_model,
            default_device=body.default_device,
            default_compute_type=body.default_compute_type,
        )
    )
    return ApiSuccess(
        data=RuntimeSettingsSetData(settings=result.settings, config_path=result.config_path)
    )


@router.post(
    "/runtime/models/faster-whisper/download",
    response_model=ApiSuccess[FasterWhisperDownloadData],
)
def post_faster_whisper_model_download(
    body: FasterWhisperDownloadRequest,
) -> ApiSuccess[FasterWhisperDownloadData]:
    result = faster_whisper_download(ApplicationFasterWhisperDownloadRequest(model=body.model))
    return ApiSuccess(data=FasterWhisperDownloadData(job=result.job))


@router.get(
    "/runtime/models/faster-whisper/downloads/{job_id}",
    response_model=ApiSuccess[FasterWhisperDownloadStatusData],
)
def get_faster_whisper_download(job_id: str) -> ApiSuccess[FasterWhisperDownloadStatusData]:
    result = faster_whisper_download_status(job_id)
    return ApiSuccess(data=FasterWhisperDownloadStatusData(job=result.job))


@router.get("/runtime/models", response_model=ApiSuccess[ModelListData])
def get_models() -> ApiSuccess[ModelListData]:
    result = model_list()
    return ApiSuccess(data=ModelListData(models=result.models))


@router.get("/doctor", response_model=ApiSuccess[DoctorData])
def get_doctor(request: Request, workflow_id: str | None = None) -> ApiSuccess[DoctorData]:
    settings = active_project_settings(request)
    result = doctor(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
        workflow_id=workflow_id,
    )
    return ApiSuccess(data=DoctorData(ok=result.ok, checks=result.checks))
