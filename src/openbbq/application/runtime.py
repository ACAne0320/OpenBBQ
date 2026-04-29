from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import OpenBBQModel, format_pydantic_error
from openbbq.errors import ValidationError
from openbbq.runtime.model_download_jobs import model_download_jobs
from openbbq.runtime.models import (
    FasterWhisperSettings,
    ModelAssetStatus,
    ModelDownloadJob,
    ProviderModel,
    ProviderProfile,
    RuntimeDefaults,
    RuntimeSettings,
    SecretCheck,
)
from openbbq.runtime.models_assets import (
    download_faster_whisper_model,
    faster_whisper_model_status,
    faster_whisper_model_statuses,
    require_supported_faster_whisper_model,
)
from openbbq.runtime.provider_models import fetch_provider_models
from openbbq.runtime.provider_models import test_provider_connection
from openbbq.runtime.secrets import SecretResolver
from openbbq.runtime.settings import (
    load_runtime_settings,
    with_faster_whisper_settings,
    with_provider_profile,
    with_runtime_defaults,
    write_runtime_settings,
)
from openbbq.runtime.user_db import UserRuntimeDatabase


class SettingsShowResult(OpenBBQModel):
    settings: RuntimeSettings


class RuntimeDefaultsSetRequest(OpenBBQModel):
    llm_provider: str
    asr_provider: str = "faster-whisper"


class RuntimeSettingsSetResult(OpenBBQModel):
    settings: RuntimeSettings
    config_path: Path


class FasterWhisperSetRequest(OpenBBQModel):
    cache_dir: Path
    default_model: str
    default_device: str
    default_compute_type: str


class FasterWhisperDownloadRequest(OpenBBQModel):
    model: str


class ProviderSetRequest(OpenBBQModel):
    name: str
    type: str
    base_url: str | None = None
    api_key: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None


class ProviderSetResult(OpenBBQModel):
    provider: ProviderProfile
    config_path: Path


class AuthSetRequest(OpenBBQModel):
    name: str
    type: str = "openai_compatible"
    base_url: str | None = None
    api_key_ref: str | None = None
    secret_value: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None


class AuthSetResult(OpenBBQModel):
    provider: ProviderProfile
    secret_stored: bool
    config_path: Path


class AuthCheckResult(OpenBBQModel):
    provider: ProviderProfile
    secret: SecretCheck


class SecretCheckResult(OpenBBQModel):
    secret: SecretCheck


class SecretSetRequest(OpenBBQModel):
    reference: str
    value: str


class ModelListResult(OpenBBQModel):
    models: tuple[ModelAssetStatus, ...]


class ProviderModelListResult(OpenBBQModel):
    models: tuple[ProviderModel, ...]


class ProviderSecretValueResult(OpenBBQModel):
    value: str


class ProviderConnectionTestRequest(OpenBBQModel):
    provider_name: str | None = None
    base_url: str
    api_key: str | None = None
    model: str


class ProviderConnectionTestResult(OpenBBQModel):
    ok: bool
    message: str


class FasterWhisperDownloadResult(OpenBBQModel):
    job: ModelDownloadJob


class FasterWhisperDownloadStatusResult(OpenBBQModel):
    job: ModelDownloadJob


def settings_show() -> SettingsShowResult:
    return SettingsShowResult(settings=load_runtime_settings())


def defaults_set(request: RuntimeDefaultsSetRequest) -> RuntimeSettingsSetResult:
    try:
        defaults = RuntimeDefaults(
            llm_provider=request.llm_provider,
            asr_provider=request.asr_provider,
        )
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error("defaults", exc)) from exc
    settings = load_runtime_settings()
    updated = with_runtime_defaults(settings, defaults)
    write_runtime_settings(updated)
    return RuntimeSettingsSetResult(settings=updated, config_path=updated.config_path)


def faster_whisper_set(request: FasterWhisperSetRequest) -> RuntimeSettingsSetResult:
    _require_non_empty_string(request.default_model, "models.faster_whisper.default_model")
    _require_non_empty_string(request.default_device, "models.faster_whisper.default_device")
    _require_non_empty_string(
        request.default_compute_type,
        "models.faster_whisper.default_compute_type",
    )
    require_supported_faster_whisper_model(request.default_model)
    settings = load_runtime_settings()
    cache_dir = _resolve_cache_dir_within_root(
        request.cache_dir,
        settings.cache.root,
        "models.faster_whisper.cache_dir",
    )
    faster_whisper = FasterWhisperSettings(
        cache_dir=cache_dir,
        default_model=request.default_model,
        default_device=request.default_device,
        default_compute_type=request.default_compute_type,
    )
    updated = with_faster_whisper_settings(settings, faster_whisper)
    write_runtime_settings(updated)
    return RuntimeSettingsSetResult(settings=updated, config_path=updated.config_path)


def provider_set(request: ProviderSetRequest) -> ProviderSetResult:
    try:
        provider = ProviderProfile(
            name=request.name,
            type=request.type,
            base_url=request.base_url,
            api_key=request.api_key,
            default_chat_model=request.default_chat_model,
            display_name=request.display_name,
        )
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error(f"providers.{request.name}", exc)) from exc
    settings = load_runtime_settings()
    updated = with_provider_profile(settings, provider)
    UserRuntimeDatabase().upsert_provider(provider)
    write_runtime_settings(updated)
    return ProviderSetResult(provider=provider, config_path=updated.config_path)


def auth_set(request: AuthSetRequest) -> AuthSetResult:
    api_key_ref = request.api_key_ref
    stored_secret = False
    if request.secret_value is not None:
        api_key_ref = api_key_ref or _default_provider_sqlite_reference(request.name)
        SecretResolver().set_secret(api_key_ref, request.secret_value)
        stored_secret = True
    elif api_key_ref is None:
        raise ValidationError("auth set requires --api-key-ref when non-interactive.")
    provider = ProviderProfile(
        name=request.name,
        type=request.type,
        base_url=request.base_url,
        api_key=api_key_ref,
        default_chat_model=request.default_chat_model,
        display_name=request.display_name,
    )
    settings = load_runtime_settings()
    updated = with_provider_profile(settings, provider)
    UserRuntimeDatabase().upsert_provider(provider)
    write_runtime_settings(updated)
    return AuthSetResult(
        provider=provider,
        secret_stored=stored_secret,
        config_path=updated.config_path,
    )


def auth_check(name: str) -> AuthCheckResult:
    settings = load_runtime_settings()
    provider = settings.providers.get(name)
    if provider is None:
        raise ValidationError(f"Provider '{name}' is not configured.")
    if provider.api_key is None:
        secret = SecretCheck(
            reference="",
            resolved=False,
            display="",
            value_preview=None,
            error=f"Provider '{name}' does not define an API key reference.",
        )
    else:
        secret = SecretResolver().resolve(provider.api_key).public
    return AuthCheckResult(provider=provider, secret=secret)


def secret_check(reference: str) -> SecretCheckResult:
    return SecretCheckResult(secret=SecretResolver().resolve(reference).public)


def secret_set(request: SecretSetRequest) -> SecretCheckResult:
    SecretResolver().set_secret(request.reference, request.value)
    return SecretCheckResult(secret=SecretResolver().resolve(request.reference).public)


def model_list() -> ModelListResult:
    return ModelListResult(models=faster_whisper_model_statuses(load_runtime_settings()))


def provider_model_list(name: str) -> ProviderModelListResult:
    settings = load_runtime_settings()
    provider = settings.providers.get(name)
    if provider is None:
        raise ValidationError(f"Provider '{name}' is not configured.")

    api_key: str | None = None
    if provider.api_key is not None:
        secret = SecretResolver().resolve(provider.api_key)
        if not secret.resolved:
            raise ValidationError(secret.public.error or f"Provider '{name}' API key is unresolved.")
        api_key = secret.value

    return ProviderModelListResult(models=fetch_provider_models(provider, api_key=api_key))


def provider_secret_value(name: str) -> ProviderSecretValueResult:
    settings = load_runtime_settings()
    provider = settings.providers.get(name)
    if provider is None:
        raise ValidationError(f"Provider '{name}' is not configured.")
    if provider.api_key is None:
        raise ValidationError(f"Provider '{name}' does not define an API key reference.")
    secret = SecretResolver().resolve(provider.api_key)
    if not secret.resolved or secret.value is None:
        raise ValidationError(secret.public.error or f"Provider '{name}' API key is unresolved.")
    return ProviderSecretValueResult(value=secret.value)


def provider_connection_test(
    request: ProviderConnectionTestRequest,
) -> ProviderConnectionTestResult:
    api_key = request.api_key
    if (api_key is None or api_key == "") and request.provider_name:
        settings = load_runtime_settings()
        provider = settings.providers.get(request.provider_name)
        if provider is not None and provider.api_key is not None:
            secret = SecretResolver().resolve(provider.api_key)
            if secret.resolved:
                api_key = secret.value
    message = test_provider_connection(
        base_url=request.base_url,
        api_key=api_key,
        model=request.model,
    )
    return ProviderConnectionTestResult(ok=True, message=message)


def faster_whisper_download(
    request: FasterWhisperDownloadRequest,
) -> FasterWhisperDownloadResult:
    _require_non_empty_string(request.model, "model")
    settings = load_runtime_settings()
    require_supported_faster_whisper_model(request.model)
    faster_whisper = (
        settings.models.faster_whisper
        if settings.models is not None
        else FasterWhisperSettings(
            cache_dir=settings.cache.root / "models" / "faster-whisper",
            default_model="base",
            default_device="cpu",
            default_compute_type="int8",
        )
    )
    model_status = faster_whisper_model_status(settings, model=request.model)
    if model_status.present:
        job = model_download_jobs.completed(
            provider="faster-whisper",
            model=request.model,
            model_status=model_status,
        )
        return FasterWhisperDownloadResult(job=job)

    def worker(progress):
        download_faster_whisper_model(
            request.model,
            cache_dir=faster_whisper.cache_dir,
            device=faster_whisper.default_device,
            compute_type=faster_whisper.default_compute_type,
            progress=progress,
        )
        return faster_whisper_model_status(settings, model=request.model)

    job = model_download_jobs.start(
        provider="faster-whisper",
        model=request.model,
        worker=worker,
    )
    return FasterWhisperDownloadResult(job=job)


def faster_whisper_download_status(job_id: str) -> FasterWhisperDownloadStatusResult:
    return FasterWhisperDownloadStatusResult(job=model_download_jobs.get(job_id))


def _default_provider_sqlite_reference(name: str) -> str:
    return f"sqlite:openbbq/providers/{name}/api_key"


def _require_non_empty_string(value: str, field_path: str) -> None:
    if not value.strip():
        raise ValidationError(f"{field_path} must be a non-empty string.")


def _resolve_cache_dir_within_root(path: Path, cache_root: Path, field_path: str) -> Path:
    resolved_root = cache_root.expanduser().resolve()
    expanded = path.expanduser()
    resolved = (
        expanded.resolve() if expanded.is_absolute() else (resolved_root / expanded).resolve()
    )
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValidationError(f"{field_path} must be inside cache.root: {resolved_root}.") from exc
    return resolved
