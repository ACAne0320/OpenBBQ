from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import tomllib
from typing import Any

from openbbq.errors import ValidationError
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeSettings,
)

DEFAULT_USER_CONFIG_PATH = Path("~/.openbbq/config.toml")
DEFAULT_CACHE_ROOT = Path("~/.cache/openbbq")
SUPPORTED_PROVIDER_TYPES = {"openai_compatible"}


def default_user_config_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    configured = env.get("OPENBBQ_USER_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_USER_CONFIG_PATH.expanduser().resolve()


def load_runtime_settings(
    config_path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> RuntimeSettings:
    env = os.environ if env is None else env
    path = (
        Path(config_path).expanduser().resolve()
        if config_path is not None
        else default_user_config_path(env)
    )
    raw = _load_toml_mapping(path)
    version = raw.get("version", 1)
    if type(version) is not int or version != 1:
        raise ValidationError("Runtime settings version must be 1.")

    cache_root = _cache_root(raw, env, path.parent)
    faster_whisper = _faster_whisper_settings(raw, cache_root, path.parent)
    providers = _provider_profiles(raw)
    return RuntimeSettings(
        version=1,
        config_path=path,
        cache=CacheSettings(root=cache_root),
        providers=providers,
        models=ModelsSettings(faster_whisper=faster_whisper),
    )


def runtime_settings_to_toml(settings: RuntimeSettings) -> str:
    lines = ["version = 1", ""]
    lines.extend(["[cache]", f'root = "{_escape_toml(str(settings.cache.root))}"', ""])
    if settings.providers:
        for name, provider in sorted(settings.providers.items()):
            lines.append(f"[providers.{name}]")
            lines.append(f'type = "{_escape_toml(provider.type)}"')
            if provider.base_url is not None:
                lines.append(f'base_url = "{_escape_toml(provider.base_url)}"')
            if provider.api_key is not None:
                lines.append(f'api_key = "{_escape_toml(provider.api_key)}"')
            if provider.default_chat_model is not None:
                lines.append(
                    f'default_chat_model = "{_escape_toml(provider.default_chat_model)}"'
                )
            if provider.display_name is not None:
                lines.append(f'display_name = "{_escape_toml(provider.display_name)}"')
            lines.append("")
    if settings.models is not None:
        model = settings.models.faster_whisper
        lines.append("[models.faster_whisper]")
        lines.append(f'cache_dir = "{_escape_toml(str(model.cache_dir))}"')
        lines.append(f'default_model = "{_escape_toml(model.default_model)}"')
        lines.append(f'default_device = "{_escape_toml(model.default_device)}"')
        lines.append(f'default_compute_type = "{_escape_toml(model.default_compute_type)}"')
        lines.append("")
    return "\n".join(lines)


def write_runtime_settings(settings: RuntimeSettings) -> None:
    settings.config_path.parent.mkdir(parents=True, exist_ok=True)
    settings.config_path.write_text(runtime_settings_to_toml(settings), encoding="utf-8")


def _load_toml_mapping(path: Path) -> dict[str, Any]:
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


def _cache_root(raw: Mapping[str, Any], env: Mapping[str, str], base_dir: Path) -> Path:
    env_value = env.get("OPENBBQ_CACHE_DIR")
    if env_value:
        return Path(env_value).expanduser().resolve()
    cache_raw = _optional_mapping(raw.get("cache"), "cache")
    return _resolve_user_path(cache_raw.get("root", DEFAULT_CACHE_ROOT), base_dir, "cache.root")


def _faster_whisper_settings(
    raw: Mapping[str, Any],
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
    )


def _provider_profiles(raw: Mapping[str, Any]) -> dict[str, ProviderProfile]:
    providers_raw = _optional_mapping(raw.get("providers"), "providers")
    providers: dict[str, ProviderProfile] = {}
    for name, provider_raw in providers_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Provider names must be non-empty strings.")
        profile_raw = _require_mapping(provider_raw, f"providers.{name}")
        provider_type = _required_string(profile_raw.get("type"), f"providers.{name}.type")
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_PROVIDER_TYPES))
            raise ValidationError(f"providers.{name}.type must be one of: {allowed}.")
        providers[name] = ProviderProfile(
            name=name,
            type=provider_type,
            base_url=_optional_string(profile_raw.get("base_url"), f"providers.{name}.base_url"),
            api_key=_optional_string(profile_raw.get("api_key"), f"providers.{name}.api_key"),
            default_chat_model=_optional_string(
                profile_raw.get("default_chat_model"),
                f"providers.{name}.default_chat_model",
            ),
            display_name=_optional_string(
                profile_raw.get("display_name"), f"providers.{name}.display_name"
            ),
        )
    return providers


def _resolve_user_path(value: Any, base_dir: Path, field_path: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValidationError(f"{field_path} must be a string path.")
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    if path == DEFAULT_CACHE_ROOT:
        return path.expanduser().resolve()
    return (base_dir / path).resolve()


def _require_mapping(value: Any, field_path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_path} must be a mapping.")
    return value


def _optional_mapping(value: Any, field_path: str) -> dict[str, Any]:
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


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
