import pytest
from openbbq.runtime.context import build_runtime_context
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeSettings,
)
from openbbq.runtime.provider import llm_provider_from_request
from openbbq.runtime.secrets import SecretResolver


def runtime_settings(tmp_path):
    return RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        providers={
            "openai": ProviderProfile(
                name="openai",
                type="openai_compatible",
                base_url="https://api.openai.com/v1",
                api_key="env:OPENBBQ_LLM_API_KEY",
                default_chat_model="gpt-4o-mini",
            )
        },
        models=ModelsSettings(
            faster_whisper=FasterWhisperSettings(cache_dir=tmp_path / "cache/models/fw")
        ),
    )


def test_build_runtime_context_resolves_provider_secret(tmp_path):
    settings = runtime_settings(tmp_path)
    resolver = SecretResolver(env={"OPENBBQ_LLM_API_KEY": "sk-runtime"}, keyring_backend=None)

    context = build_runtime_context(settings, secret_resolver=resolver)

    provider = context.providers["openai"]
    assert provider.api_key == "sk-runtime"
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.default_chat_model == "gpt-4o-mini"
    cache_path = str(context.request_payload()["cache"]["faster_whisper"]).replace("\\", "/")
    assert cache_path.endswith("cache/models/fw")
    assert context.redaction_values == ("sk-runtime",)


def test_build_runtime_context_skips_unresolved_provider_secret(tmp_path):
    settings = runtime_settings(tmp_path)
    resolver = SecretResolver(env={}, keyring_backend=None)

    context = build_runtime_context(settings, secret_resolver=resolver)

    assert context.providers["openai"].api_key is None
    assert context.redaction_values == ()


def test_llm_provider_from_request_uses_named_provider():
    request = {
        "parameters": {"provider": "openai"},
        "runtime": {
            "providers": {
                "openai": {
                    "name": "openai",
                    "type": "openai_compatible",
                    "api_key": "sk-runtime",
                    "base_url": "https://api.openai.com/v1",
                    "default_chat_model": "gpt-4o-mini",
                }
            }
        },
    }

    provider = llm_provider_from_request(request, error_prefix="translation.translate")

    assert provider.name == "openai"
    assert provider.api_key == "sk-runtime"
    assert provider.model_default == "gpt-4o-mini"


def test_llm_provider_from_request_falls_back_to_legacy_env(monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-env")
    monkeypatch.setenv("OPENBBQ_LLM_BASE_URL", "https://legacy.example/v1")

    provider = llm_provider_from_request(
        {"parameters": {}, "runtime": {}},
        error_prefix="translation.translate",
    )

    assert provider.name == "openai_compatible"
    assert provider.api_key == "sk-env"
    assert provider.base_url == "https://legacy.example/v1"


def test_llm_provider_from_request_rejects_missing_named_provider():
    with pytest.raises(ValueError, match="Provider 'missing'"):
        llm_provider_from_request(
            {"parameters": {"provider": "missing"}, "runtime": {"providers": {}}},
            error_prefix="translation.translate",
        )


def test_llm_provider_from_request_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENBBQ_LLM_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="OPENBBQ_LLM_API_KEY"):
        llm_provider_from_request(
            {"parameters": {}, "runtime": {}},
            error_prefix="translation.translate",
        )
