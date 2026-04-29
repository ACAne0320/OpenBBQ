import json

import pytest

from openbbq.application.runtime import (
    ProviderConnectionTestRequest,
    provider_connection_test,
    provider_model_list,
    provider_secret_value,
)
from openbbq.errors import ValidationError
from openbbq.runtime.models import ProviderProfile
from openbbq.runtime.provider_models import normalize_provider_models
from openbbq.runtime.settings import RuntimeSettings, write_runtime_settings


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_normalizes_openai_compatible_model_list():
    models = normalize_provider_models(
        {
            "object": "list",
            "data": [
                {"id": "gpt-4.1-mini", "object": "model", "owned_by": "openai"},
                {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
            ],
        }
    )

    assert [model.id for model in models] == ["gpt-4.1-mini", "deepseek-chat"]
    assert models[0].owned_by == "openai"


def test_normalizes_openrouter_context_length():
    models = normalize_provider_models(
        {
            "data": [
                {
                    "id": "openai/gpt-4.1-mini",
                    "name": "GPT-4.1 Mini",
                    "top_provider": {"context_length": 1047576},
                }
            ]
        }
    )

    assert models[0].label == "GPT-4.1 Mini"
    assert models[0].context_length == 1047576


def test_provider_model_list_uses_configured_base_url_and_secret(tmp_path, monkeypatch):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    write_runtime_settings(
        RuntimeSettings(
            version=1,
            config_path=user_config,
            cache={"root": tmp_path / "cache"},
            providers={
                "openai": ProviderProfile(
                    name="openai",
                    type="openai_compatible",
                    base_url="https://api.openai.com/v1",
                    api_key="env:OPENBBQ_LLM_API_KEY",
                )
            },
        )
    )

    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse({"data": [{"id": "gpt-4.1-mini"}]})

    monkeypatch.setattr("openbbq.runtime.provider_models.urlopen", fake_urlopen)

    result = provider_model_list("openai")

    assert [model.id for model in result.models] == ["gpt-4.1-mini"]
    assert requests[0][0].full_url == "https://api.openai.com/v1/models"
    assert requests[0][0].headers["Authorization"] == "Bearer sk-test"


def test_provider_model_list_rejects_unresolved_secret(tmp_path, monkeypatch):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)
    write_runtime_settings(
        RuntimeSettings(
            version=1,
            config_path=user_config,
            cache={"root": tmp_path / "cache"},
            providers={
                "openai": ProviderProfile(
                    name="openai",
                    type="openai_compatible",
                    base_url="https://api.openai.com/v1",
                    api_key="env:OPENBBQ_LLM_API_KEY",
                )
            },
        )
    )

    with pytest.raises(ValidationError, match="OPENBBQ_LLM_API_KEY"):
        provider_model_list("openai")


def test_provider_secret_value_returns_resolved_plaintext(tmp_path, monkeypatch):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-visible")
    write_runtime_settings(
        RuntimeSettings(
            version=1,
            config_path=user_config,
            cache={"root": tmp_path / "cache"},
            providers={
                "openai": ProviderProfile(
                    name="openai",
                    type="openai_compatible",
                    base_url="https://api.openai.com/v1",
                    api_key="env:OPENBBQ_LLM_API_KEY",
                )
            },
        )
    )

    assert provider_secret_value("openai").value == "sk-visible"


def test_provider_connection_test_posts_chat_completion(tmp_path, monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse({"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr("openbbq.runtime.provider_models.urlopen", fake_urlopen)

    result = provider_connection_test(
        ProviderConnectionTestRequest(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4.1-mini",
        )
    )

    assert result.ok is True
    request = requests[0][0]
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert json.loads(request.data.decode("utf-8"))["model"] == "gpt-4.1-mini"
