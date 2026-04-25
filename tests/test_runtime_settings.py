from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.errors import ValidationError
from openbbq.runtime import models as runtime_models
from openbbq.runtime.models import (
    CacheSettings,
    DoctorCheck,
    ModelAssetStatus,
    ProviderProfile,
    ResolvedProvider,
    RuntimeSettings,
)
from openbbq.runtime.settings import (
    DEFAULT_CACHE_ROOT,
    load_runtime_settings,
    runtime_settings_to_toml,
    with_provider_profile,
)
from openbbq.runtime.settings_parser import parse_runtime_settings
from openbbq.runtime.user_db import UserRuntimeDatabase


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


def test_parse_runtime_settings_does_not_open_user_database(tmp_path):
    config = tmp_path / "config.toml"
    db_path = tmp_path / "openbbq.db"

    settings = parse_runtime_settings(
        {
            "version": 1,
            "cache": {"root": "runtime-cache"},
            "providers": {
                "file": {
                    "type": "openai_compatible",
                    "api_key": "env:FILE_PROVIDER_KEY",
                }
            },
        },
        config_path=config.resolve(),
        env={"OPENBBQ_USER_DB": str(db_path)},
    )

    assert settings.config_path == config.resolve()
    assert settings.cache.root == (tmp_path / "runtime-cache").resolve()
    assert sorted(settings.providers) == ["file"]
    assert settings.providers["file"].api_key == "env:FILE_PROVIDER_KEY"
    assert not db_path.exists()


def test_load_runtime_settings_merges_user_database_provider_over_file_provider(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
version = 1

[providers.openai]
type = "openai_compatible"
api_key = "env:FILE_PROVIDER_KEY"
default_chat_model = "file-model"
display_name = "File Provider"
""",
        encoding="utf-8",
    )
    env = {"OPENBBQ_USER_DB": str(tmp_path / "openbbq.db")}
    UserRuntimeDatabase(env=env).upsert_provider(
        ProviderProfile(
            name="openai",
            type="openai_compatible",
            api_key="sqlite:openai",
            default_chat_model="db-model",
            display_name="Database Provider",
        )
    )

    settings = load_runtime_settings(config_path=config, env=env)

    provider = settings.providers["openai"]
    assert provider.api_key == "sqlite:openai"
    assert provider.default_chat_model == "db-model"
    assert provider.display_name == "Database Provider"


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


def test_provider_profile_rejects_unknown_type():
    with pytest.raises(PydanticValidationError) as exc:
        ProviderProfile(name="openai", type="custom")

    assert "type" in str(exc.value)


def test_with_provider_profile_adds_profile(tmp_path):
    settings = RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
    )

    updated = with_provider_profile(
        settings,
        ProviderProfile(
            name="openai",
            type="openai_compatible",
            api_key="env:OPENBBQ_LLM_API_KEY",
        ),
    )

    assert updated.providers["openai"].api_key == "env:OPENBBQ_LLM_API_KEY"
    assert settings.providers == {}


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


def test_provider_profile_rejects_literal_api_key():
    with pytest.raises(PydanticValidationError) as exc:
        ProviderProfile(
            name="openai",
            type="openai_compatible",
            api_key="sk-not-allowed",
        )

    assert "api_key" in str(exc.value)


def test_runtime_model_payload_methods_delegate_to_model_payload(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_model_payload(value):
        calls.append(type(value).__name__)
        return {"kind": type(value).__name__}

    monkeypatch.setattr(runtime_models, "model_payload", fake_model_payload, raising=False)

    assert ProviderProfile(name="openai", type="openai_compatible").public_dict() == {
        "kind": "ProviderProfile"
    }
    assert RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
    ).public_dict() == {"kind": "RuntimeSettings"}
    assert ResolvedProvider(
        name="openai",
        type="openai_compatible",
        api_key=None,
        base_url=None,
    ).request_payload() == {"kind": "ResolvedProvider"}
    assert ModelAssetStatus(
        provider="faster_whisper",
        model="base",
        cache_dir=Path("models"),
        present=False,
    ).public_dict() == {"kind": "ModelAssetStatus"}
    assert DoctorCheck(
        id="runtime.settings",
        status="passed",
        severity="info",
        message="Runtime settings are valid.",
    ).public_dict() == {"kind": "DoctorCheck"}
    assert calls == [
        "ProviderProfile",
        "RuntimeSettings",
        "ResolvedProvider",
        "ModelAssetStatus",
        "DoctorCheck",
    ]


def test_runtime_settings_model_copy_preserves_provider_models(tmp_path):
    settings = RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        providers={
            "openai": ProviderProfile(
                name="openai",
                type="openai_compatible",
                api_key="env:OPENBBQ_LLM_API_KEY",
            )
        },
    )

    copied = settings.model_copy()

    assert copied.providers["openai"].api_key == "env:OPENBBQ_LLM_API_KEY"
