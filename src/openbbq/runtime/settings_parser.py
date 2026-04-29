from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tomllib
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import JsonObject, format_pydantic_error
from openbbq.errors import ValidationError
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    ProviderMap,
    PROVIDER_NAME_PATTERN,
    RuntimeDefaults,
    RuntimeSettings,
    SUPPORTED_PROVIDER_TYPES,
)

DEFAULT_CACHE_ROOT = Path("~/.cache/openbbq")


def load_toml_mapping(path: Path) -> JsonObject:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"Runtime settings '{path}' contains malformed TOML.") from exc
    if not isinstance(raw, dict):
        raise ValidationError(f"Runtime settings '{path}' must contain a TOML table.")
    return raw


def parse_runtime_settings(
    raw: JsonObject,
    *,
    config_path: Path,
    env: Mapping[str, str],
) -> RuntimeSettings:
    version = raw.get("version", 1)
    if type(version) is not int or version != 1:
        raise ValidationError("Runtime settings version must be 1.")

    cache_root = _cache_root(raw, env, config_path.parent)
    defaults = _runtime_defaults(raw)
    faster_whisper = _faster_whisper_settings(raw, cache_root, config_path.parent)
    providers = _provider_profiles(raw)
    try:
        return RuntimeSettings(
            version=1,
            config_path=config_path,
            cache=CacheSettings(root=cache_root),
            defaults=defaults,
            providers=providers,
            models=ModelsSettings(faster_whisper=faster_whisper),
        )
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error("runtime settings", exc)) from exc


def _cache_root(raw: JsonObject, env: Mapping[str, str], base_dir: Path) -> Path:
    env_value = env.get("OPENBBQ_CACHE_DIR")
    if env_value:
        return Path(env_value).expanduser().resolve()
    cache_raw = _optional_mapping(raw.get("cache"), "cache")
    return _resolve_user_path(cache_raw.get("root", DEFAULT_CACHE_ROOT), base_dir, "cache.root")


def _runtime_defaults(raw: JsonObject) -> RuntimeDefaults:
    defaults_raw = _optional_mapping(raw.get("defaults"), "defaults")
    try:
        return RuntimeDefaults(
            llm_provider=_required_string(
                defaults_raw.get("llm_provider", "openai-compatible"),
                "defaults.llm_provider",
            ),
            asr_provider=_required_string(
                defaults_raw.get("asr_provider", "faster-whisper"),
                "defaults.asr_provider",
            ),
        )
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error("defaults", exc)) from exc


def _faster_whisper_settings(
    raw: JsonObject,
    cache_root: Path,
    base_dir: Path,
) -> FasterWhisperSettings:
    models_raw = _optional_mapping(raw.get("models"), "models")
    fw_raw = _optional_mapping(models_raw.get("faster_whisper"), "models.faster_whisper")
    cache_dir = _resolve_user_path(
        fw_raw.get("cache_dir", cache_root / "models" / "faster-whisper"),
        base_dir,
        "models.faster_whisper.cache_dir",
    )
    return FasterWhisperSettings(
        cache_dir=cache_dir,
        default_model=_required_string(
            fw_raw.get("default_model", "base"), "models.faster_whisper.default_model"
        ),
        default_device=_required_string(
            fw_raw.get("default_device", "cpu"), "models.faster_whisper.default_device"
        ),
        default_compute_type=_required_string(
            fw_raw.get("default_compute_type", "int8"),
            "models.faster_whisper.default_compute_type",
        ),
        enabled=_optional_bool(
            fw_raw.get("enabled", True),
            "models.faster_whisper.enabled",
        ),
    )


def _provider_profiles(raw: JsonObject) -> ProviderMap:
    providers_raw = _optional_mapping(raw.get("providers"), "providers")
    providers: dict[str, ProviderProfile] = {}
    for name, provider_raw in providers_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Provider names must be non-empty strings.")
        _validate_provider_name(name)
        profile_raw = _require_mapping(provider_raw, f"providers.{name}")
        provider_type = _required_string(profile_raw.get("type"), f"providers.{name}.type")
        _validate_provider_type(provider_type, f"providers.{name}.type")
        api_key = _optional_string(profile_raw.get("api_key"), f"providers.{name}.api_key")
        if api_key is not None:
            _validate_secret_reference(api_key, f"providers.{name}.api_key")
        try:
            providers[name] = ProviderProfile(
                name=name,
                type=provider_type,
                base_url=_optional_string(
                    profile_raw.get("base_url"), f"providers.{name}.base_url"
                ),
                api_key=api_key,
                default_chat_model=_optional_string(
                    profile_raw.get("default_chat_model"),
                    f"providers.{name}.default_chat_model",
                ),
                display_name=_optional_string(
                    profile_raw.get("display_name"), f"providers.{name}.display_name"
                ),
                enabled=_optional_bool(
                    profile_raw.get("enabled", True), f"providers.{name}.enabled"
                ),
            )
        except PydanticValidationError as exc:
            raise ValidationError(format_pydantic_error(f"providers.{name}", exc)) from exc
    return providers


def _validate_provider_name(name: str) -> None:
    if not name or PROVIDER_NAME_PATTERN.fullmatch(name) is None:
        raise ValidationError("Provider names must use only letters, digits, '_' or '-'.")


def _validate_provider_type(provider_type: str, field_path: str) -> None:
    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_PROVIDER_TYPES))
        raise ValidationError(f"{field_path} must be one of: {allowed}.")


def _validate_secret_reference(reference: str, field_path: str) -> None:
    if reference.startswith("env:"):
        if reference == "env:":
            raise ValidationError(f"{field_path} env secret reference must include a name.")
        return
    if reference.startswith("sqlite:"):
        if reference == "sqlite:":
            raise ValidationError(f"{field_path} sqlite secret reference must include a name.")
        return
    if reference.startswith("keyring:"):
        payload = reference.removeprefix("keyring:")
        service, separator, username = payload.partition("/")
        if not separator or not service or not username:
            raise ValidationError(
                f"{field_path} keyring secret reference must be keyring:<service>/<username>."
            )
        return
    raise ValidationError(f"{field_path} must use an env:, sqlite:, or keyring: secret reference.")


def _resolve_user_path(value: Any, base_dir: Path, field_path: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValidationError(f"{field_path} must be a string path.")
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    if path == DEFAULT_CACHE_ROOT:
        return path.expanduser().resolve()
    return (base_dir / path).resolve()


def _require_mapping(value: Any, field_path: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_path} must be a mapping.")
    return value


def _optional_mapping(value: Any, field_path: str) -> JsonObject:
    if value is None:
        return {}
    return _require_mapping(value, field_path)


def _required_string(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_path} must be a non-empty string.")
    return value


def _optional_string(value: Any, field_path: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field_path)


def _optional_bool(value: Any, field_path: str) -> bool:
    if type(value) is bool:
        return value
    raise ValidationError(f"{field_path} must be a boolean.")
