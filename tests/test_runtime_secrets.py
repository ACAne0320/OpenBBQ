import pytest

from openbbq.errors import ValidationError
from openbbq.runtime.redaction import redact_values
from openbbq.runtime.secrets import SecretResolver


class FakeKeyringBackend:
    def __init__(self, values):
        self.values = values
        self.set_calls = []

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, value):
        self.set_calls.append((service, username, value))
        self.values[(service, username)] = value


def test_resolves_env_secret():
    resolver = SecretResolver(env={"OPENBBQ_LLM_API_KEY": "sk-test"})

    check = resolver.resolve("env:OPENBBQ_LLM_API_KEY")

    assert check.resolved is True
    assert check.value == "sk-test"
    assert check.public.value_preview == "sk-...test"


def test_reports_missing_env_secret_without_value():
    resolver = SecretResolver(env={})

    check = resolver.resolve("env:OPENBBQ_LLM_API_KEY")

    assert check.resolved is False
    assert check.value is None
    assert "OPENBBQ_LLM_API_KEY" in check.public.error


def test_resolves_keyring_secret_with_fake_backend():
    backend = FakeKeyringBackend({("openbbq", "providers/openai/api_key"): "sk-keyring"})
    resolver = SecretResolver(env={}, keyring_backend=backend)

    check = resolver.resolve("keyring:openbbq/providers/openai/api_key")

    assert check.resolved is True
    assert check.value == "sk-keyring"
    assert check.public.value_preview == "sk-...ring"


def test_keyring_missing_backend_reports_dependency_error():
    resolver = SecretResolver(env={}, keyring_backend=None)

    check = resolver.resolve("keyring:openbbq/providers/openai/api_key")

    assert check.resolved is False
    assert check.value is None
    assert "keyring" in check.public.error.lower()


def test_rejects_unknown_secret_reference_scheme():
    resolver = SecretResolver(env={})

    with pytest.raises(ValidationError, match="secret reference"):
        resolver.resolve("file:/tmp/key")


def test_set_keyring_secret_uses_backend():
    backend = FakeKeyringBackend({})
    resolver = SecretResolver(env={}, keyring_backend=backend)

    resolver.set_secret("keyring:openbbq/providers/openai/api_key", "sk-new")

    assert backend.values[("openbbq", "providers/openai/api_key")] == "sk-new"


def test_rejects_setting_env_secret():
    resolver = SecretResolver(env={})

    with pytest.raises(ValidationError, match="keyring"):
        resolver.set_secret("env:OPENBBQ_LLM_API_KEY", "sk-new")


def test_redact_values_removes_all_secret_values():
    message = "Plugin failed with sk-secret and bearer-token in traceback"

    redacted = redact_values(message, ["sk-secret", "bearer-token"])

    assert redacted == "Plugin failed with [REDACTED] and [REDACTED] in traceback"
