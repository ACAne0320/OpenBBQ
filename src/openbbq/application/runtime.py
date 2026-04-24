from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import OpenBBQModel, format_pydantic_error
from openbbq.errors import ValidationError
from openbbq.runtime.models import (
    ModelAssetStatus,
    ProviderProfile,
    RuntimeSettings,
    SecretCheck,
)
from openbbq.runtime.models_assets import faster_whisper_model_status
from openbbq.runtime.secrets import SecretResolver
from openbbq.runtime.settings import (
    load_runtime_settings,
    with_provider_profile,
    write_runtime_settings,
)


class SettingsShowResult(OpenBBQModel):
    settings: RuntimeSettings


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
    write_runtime_settings(updated)
    return ProviderSetResult(provider=provider, config_path=updated.config_path)


def auth_set(request: AuthSetRequest) -> AuthSetResult:
    api_key_ref = request.api_key_ref
    stored_secret = False
    if api_key_ref is None:
        if request.secret_value is None:
            raise ValidationError("auth set requires --api-key-ref when non-interactive.")
        api_key_ref = _default_provider_keyring_reference(request.name)
        SecretResolver().set_secret(api_key_ref, request.secret_value)
        stored_secret = True
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


def _default_provider_keyring_reference(name: str) -> str:
    return f"keyring:openbbq/providers/{name}/api_key"
