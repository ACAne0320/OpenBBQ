from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import OpenBBQModel, format_pydantic_error
from openbbq.errors import ValidationError
from openbbq.runtime.models import (
    FasterWhisperSettings,
    ModelAssetStatus,
    ProviderProfile,
    RuntimeDefaults,
    RuntimeSettings,
    SecretCheck,
)
from openbbq.runtime.models_assets import faster_whisper_model_status
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


def settings_show() -> SettingsShowResult:
    return SettingsShowResult(settings=load_runtime_settings())


def defaults_set(request: RuntimeDefaultsSetRequest) -> RuntimeSettingsSetResult:
    defaults = RuntimeDefaults(
        llm_provider=request.llm_provider,
        asr_provider=request.asr_provider,
    )
    settings = load_runtime_settings()
    updated = with_runtime_defaults(settings, defaults)
    write_runtime_settings(updated)
    return RuntimeSettingsSetResult(settings=updated, config_path=updated.config_path)


def faster_whisper_set(request: FasterWhisperSetRequest) -> RuntimeSettingsSetResult:
    settings = load_runtime_settings()
    faster_whisper = FasterWhisperSettings(
        cache_dir=request.cache_dir.expanduser().resolve(),
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
    return ModelListResult(models=(faster_whisper_model_status(load_runtime_settings()),))


def _default_provider_sqlite_reference(name: str) -> str:
    return f"sqlite:openbbq/providers/{name}/api_key"
