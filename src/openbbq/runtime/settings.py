from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from openbbq.runtime.models import (
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeDefaults,
    RuntimeSettings,
)
from openbbq.runtime.settings_parser import (
    DEFAULT_CACHE_ROOT as DEFAULT_CACHE_ROOT,
    load_toml_mapping,
    parse_runtime_settings,
)
from openbbq.runtime.user_db import UserRuntimeDatabase

DEFAULT_USER_CONFIG_PATH = Path("~/.openbbq/config.toml")


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
    merge_default_user_db = env is None
    env = os.environ if env is None else env
    path = (
        Path(config_path).expanduser().resolve()
        if config_path is not None
        else default_user_config_path(env)
    )
    settings = parse_runtime_settings(load_toml_mapping(path), config_path=path, env=env)
    providers = dict(settings.providers)
    if merge_default_user_db or "OPENBBQ_USER_DB" in env or "OPENBBQ_USER_CONFIG" in env:
        providers.update(
            {provider.name: provider for provider in UserRuntimeDatabase(env=env).list_providers()}
        )
    return settings.model_copy(update={"providers": providers})


def runtime_settings_to_toml(settings: RuntimeSettings) -> str:
    lines = [
        "version = 1",
        "",
        "[defaults]",
        f'llm_provider = "{_escape_toml(settings.defaults.llm_provider)}"',
        f'asr_provider = "{_escape_toml(settings.defaults.asr_provider)}"',
        "",
    ]
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
                lines.append(f'default_chat_model = "{_escape_toml(provider.default_chat_model)}"')
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


def with_provider_profile(
    settings: RuntimeSettings,
    provider: ProviderProfile,
) -> RuntimeSettings:
    providers = dict(settings.providers)
    providers[provider.name] = provider
    return settings.model_copy(update={"providers": providers})


def with_runtime_defaults(
    settings: RuntimeSettings,
    defaults: RuntimeDefaults,
) -> RuntimeSettings:
    update: dict[str, object] = {"defaults": defaults}
    if settings.models is None:
        update["models"] = _default_models_settings(settings)
    return settings.model_copy(update=update)


def with_faster_whisper_settings(
    settings: RuntimeSettings,
    faster_whisper: FasterWhisperSettings,
) -> RuntimeSettings:
    return settings.model_copy(update={"models": ModelsSettings(faster_whisper=faster_whisper)})


def _default_models_settings(settings: RuntimeSettings) -> ModelsSettings:
    return ModelsSettings(
        faster_whisper=FasterWhisperSettings(
            cache_dir=settings.cache.root / "models" / "faster-whisper",
        )
    )


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
