import pytest

from openbbq.errors import ValidationError
from openbbq.runtime.models import CacheSettings, ProviderProfile, RuntimeSettings
from openbbq.runtime.settings import (
    DEFAULT_CACHE_ROOT,
    load_runtime_settings,
    runtime_settings_to_toml,
    with_provider_profile,
)


def test_load_runtime_settings_defaults_when_file_is_absent(tmp_path, monkeypatch):
    missing = tmp_path / "missing.toml"
    monkeypatch.delenv("OPENBBQ_CACHE_DIR", raising=False)

    settings = load_runtime_settings(config_path=missing, env={})

    assert settings.version == 1
    assert settings.config_path == missing.resolve()
    assert settings.cache.root == DEFAULT_CACHE_ROOT.expanduser().resolve()
    assert (
        settings.models.faster_whisper.cache_dir
        == (DEFAULT_CACHE_ROOT / "models" / "faster-whisper").expanduser().resolve()
    )
    assert settings.providers == {}


def test_load_runtime_settings_from_toml(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
version = 1

[cache]
root = "runtime-cache"

[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"
display_name = "OpenAI"

[models.faster_whisper]
cache_dir = "models/fw"
default_model = "base"
default_device = "cpu"
default_compute_type = "int8"
""",
        encoding="utf-8",
    )

    settings = load_runtime_settings(config_path=config, env={})

    provider = settings.providers["openai"]
    assert provider.name == "openai"
    assert provider.type == "openai_compatible"
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.api_key == "env:OPENBBQ_LLM_API_KEY"
    assert provider.default_chat_model == "gpt-4o-mini"
    assert provider.display_name == "OpenAI"
    assert settings.cache.root == (tmp_path / "runtime-cache").resolve()
    assert settings.models.faster_whisper.cache_dir == (tmp_path / "models/fw").resolve()


def test_cache_env_overrides_user_config(tmp_path):
    config = tmp_path / "config.toml"
    env_cache = tmp_path / "env-cache"
    config.write_text(
        'version = 1\n[cache]\nroot = "file-cache"\n',
        encoding="utf-8",
    )

    settings = load_runtime_settings(
        config_path=config,
        env={"OPENBBQ_CACHE_DIR": str(env_cache)},
    )

    assert settings.cache.root == env_cache.resolve()
    assert (
        settings.models.faster_whisper.cache_dir
        == (env_cache / "models" / "faster-whisper").resolve()
    )


def test_rejects_unknown_runtime_settings_version(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("version = 2\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="version"):
        load_runtime_settings(config_path=config, env={})


def test_rejects_unknown_provider_type(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
version = 1
[providers.bad]
type = "custom"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="providers.bad.type"):
        load_runtime_settings(config_path=config, env={})


def test_rejects_invalid_provider_name(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
version = 1
[providers."bad name"]
type = "openai_compatible"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="Provider names"):
        load_runtime_settings(config_path=config, env={})


def test_rejects_literal_provider_api_key(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
version = 1
[providers.openai]
type = "openai_compatible"
api_key = "sk-should-not-be-here"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="providers.openai.api_key"):
        load_runtime_settings(config_path=config, env={})


def test_with_provider_profile_validates_profile(tmp_path):
    settings = RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
    )

    with pytest.raises(ValidationError, match="providers.openai.type"):
        with_provider_profile(settings, ProviderProfile(name="openai", type="custom"))

    with pytest.raises(ValidationError, match="providers.openai.api_key"):
        with_provider_profile(
            settings,
            ProviderProfile(
                name="openai",
                type="openai_compatible",
                api_key="sk-should-not-be-here",
            ),
        )


def test_runtime_settings_to_toml_round_trips_provider(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
version = 1
[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"
""",
        encoding="utf-8",
    )
    settings = load_runtime_settings(config_path=config, env={})

    rendered = runtime_settings_to_toml(settings)

    assert "version = 1" in rendered
    assert "[providers.openai]" in rendered
    assert 'type = "openai_compatible"' in rendered
    assert 'api_key = "env:OPENBBQ_LLM_API_KEY"' in rendered
