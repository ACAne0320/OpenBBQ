import pytest

from openbbq.application.diagnostics import doctor
from openbbq.application.runtime import (
    AuthSetRequest,
    ProviderSetRequest,
    auth_check,
    auth_set,
    model_list,
    provider_set,
    secret_check,
    settings_show,
)
from openbbq.errors import ValidationError


def test_provider_set_and_settings_show_use_runtime_config(tmp_path, monkeypatch):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    provider = provider_set(
        ProviderSetRequest(
            name="openai",
            type="openai_compatible",
            base_url="https://api.openai.com/v1",
            api_key="env:OPENBBQ_LLM_API_KEY",
            default_chat_model="gpt-4o-mini",
        )
    )
    settings = settings_show()

    assert provider.provider.name == "openai"
    assert settings.settings.providers["openai"].api_key == "env:OPENBBQ_LLM_API_KEY"


def test_auth_set_requires_secret_reference_in_noninteractive_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))

    with pytest.raises(ValidationError, match="api-key-ref"):
        auth_set(AuthSetRequest(name="openai", type="openai_compatible"))


def test_auth_check_reports_unresolved_env_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)
    auth_set(
        AuthSetRequest(
            name="openai",
            type="openai_compatible",
            api_key_ref="env:OPENBBQ_LLM_API_KEY",
        )
    )

    result = auth_check("openai")

    assert result.secret.resolved is False
    assert "OPENBBQ_LLM_API_KEY" in str(result.secret.error)


def test_secret_check_and_model_list_return_pydantic_results(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))
    result = secret_check("env:OPENBBQ_MISSING_SECRET")
    models = model_list()

    assert result.secret.resolved is False
    assert models.models[0].provider == "faster_whisper"


def test_doctor_service_reports_setting_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)

    result = doctor(project_root=tmp_path)

    assert isinstance(result.ok, bool)
    assert result.checks
