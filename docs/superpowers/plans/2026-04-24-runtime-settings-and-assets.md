# Runtime Settings and Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI-first runtime settings layer for provider profiles, secret references, model cache settings, runtime plugin context, and preflight checks that the Desktop UI can reuse.

**Architecture:** Add a focused `openbbq.runtime` package that owns user settings, secret resolution, redaction, model asset checks, and doctor output. Workflow execution builds an in-memory runtime context and passes it to built-in plugins without persisting secrets. Existing environment-variable LLM behavior remains compatible while named provider profiles become the preferred path.

**Tech Stack:** Python 3.11, dataclasses, `tomllib`, optional `keyring`, argparse CLI, pytest, Ruff.

---

## File Structure

Create these files:

- `src/openbbq/runtime/__init__.py`: package marker and public exports.
- `src/openbbq/runtime/models.py`: dataclasses for settings, providers, secret checks, runtime context, model assets, and doctor checks.
- `src/openbbq/runtime/settings.py`: user settings path resolution, TOML loading, TOML writing for provider profiles, cache defaults.
- `src/openbbq/runtime/secrets.py`: `env:` and `keyring:` secret resolver with injectable keyring backend.
- `src/openbbq/runtime/redaction.py`: redacts resolved secret values from messages before persistence.
- `src/openbbq/runtime/context.py`: builds in-memory runtime context from settings and environment.
- `src/openbbq/runtime/provider.py`: helper used by built-in plugins to select LLM provider credentials from a request.
- `src/openbbq/runtime/models_assets.py`: faster-whisper cache status and disk usage helpers.
- `src/openbbq/runtime/doctor.py`: structured preflight checks for settings and workflow dependencies.
- `tests/test_runtime_settings.py`: settings loader and writer coverage.
- `tests/test_runtime_secrets.py`: secret resolver and redaction coverage.
- `tests/test_runtime_context.py`: provider resolution and context serialization coverage.
- `tests/test_runtime_engine.py`: verifies runtime context is in plugin requests but not persisted.
- `tests/test_runtime_cli.py`: settings, secret, models, and doctor CLI coverage.
- `tests/test_runtime_doctor.py`: workflow-specific preflight checks with fake probes.

Modify these files:

- `pyproject.toml`: add optional `secrets` dependency.
- `src/openbbq/cli/app.py`: add `settings`, `secret`, `models`, and `doctor` subcommands.
- `src/openbbq/engine/service.py`: accept optional runtime context and pass it into workflow execution.
- `src/openbbq/workflow/execution.py`: include runtime context in plugin requests and redact plugin errors.
- `src/openbbq/plugins/registry.py`: accept an optional redactor when wrapping plugin exceptions.
- `src/openbbq/builtin_plugins/translation/openbbq.plugin.toml`: allow named provider strings.
- `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`: add optional named provider string.
- `src/openbbq/builtin_plugins/transcript/openbbq.plugin.toml`: add optional named provider string.
- `src/openbbq/builtin_plugins/translation/plugin.py`: use provider profiles, default models, and legacy env fallback.
- `src/openbbq/builtin_plugins/llm/plugin.py`: pass the updated translation behavior through.
- `src/openbbq/builtin_plugins/transcript/plugin.py`: use provider profiles, default models, and legacy env fallback.
- `src/openbbq/builtin_plugins/faster_whisper/plugin.py`: pass configured `download_root` to the model factory.
- `tests/test_builtin_plugins.py`: provider-profile and faster-whisper cache tests.
- `tests/test_package_layout.py`: optional `secrets` dependency check.
- `docs/Target-Workflows.md`: document provider profiles and runtime settings.
- `README.md`: document where API keys and model files live.

## Task 1: Runtime Settings Loader

**Files:**
- Create: `src/openbbq/runtime/__init__.py`
- Create: `src/openbbq/runtime/models.py`
- Create: `src/openbbq/runtime/settings.py`
- Test: `tests/test_runtime_settings.py`

- [ ] **Step 1: Write failing settings tests**

Create `tests/test_runtime_settings.py`:

```python
from pathlib import Path

import pytest

from openbbq.errors import ValidationError
from openbbq.runtime.settings import (
    DEFAULT_CACHE_ROOT,
    load_runtime_settings,
    runtime_settings_to_toml,
)


def test_load_runtime_settings_defaults_when_file_is_absent(tmp_path, monkeypatch):
    missing = tmp_path / "missing.toml"
    monkeypatch.delenv("OPENBBQ_CACHE_DIR", raising=False)

    settings = load_runtime_settings(config_path=missing, env={})

    assert settings.version == 1
    assert settings.config_path == missing.resolve()
    assert settings.cache.root == DEFAULT_CACHE_ROOT.expanduser().resolve()
    assert settings.models.faster_whisper.cache_dir == (
        DEFAULT_CACHE_ROOT / "models" / "faster-whisper"
    ).expanduser().resolve()
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
        "version = 1\n[cache]\nroot = \"file-cache\"\n",
        encoding="utf-8",
    )

    settings = load_runtime_settings(
        config_path=config,
        env={"OPENBBQ_CACHE_DIR": str(env_cache)},
    )

    assert settings.cache.root == env_cache.resolve()
    assert settings.models.faster_whisper.cache_dir == (
        env_cache / "models" / "faster-whisper"
    ).resolve()


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_runtime_settings.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'openbbq.runtime'`.

- [ ] **Step 3: Create runtime models**

Create `src/openbbq/runtime/__init__.py`:

```python
from __future__ import annotations

from openbbq.runtime.models import (
    CacheSettings,
    DoctorCheck,
    FasterWhisperSettings,
    ModelAssetStatus,
    ModelsSettings,
    ProviderProfile,
    ResolvedProvider,
    RuntimeContext,
    RuntimeSettings,
    SecretCheck,
)

__all__ = [
    "CacheSettings",
    "DoctorCheck",
    "FasterWhisperSettings",
    "ModelAssetStatus",
    "ModelsSettings",
    "ProviderProfile",
    "ResolvedProvider",
    "RuntimeContext",
    "RuntimeSettings",
    "SecretCheck",
]
```

Create `src/openbbq/runtime/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CacheSettings:
    root: Path


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    name: str
    type: str
    base_url: str | None = None
    api_key: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.type,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "default_chat_model": self.default_chat_model,
            "display_name": self.display_name,
        }


@dataclass(frozen=True, slots=True)
class FasterWhisperSettings:
    cache_dir: Path
    default_model: str = "base"
    default_device: str = "cpu"
    default_compute_type: str = "int8"


@dataclass(frozen=True, slots=True)
class ModelsSettings:
    faster_whisper: FasterWhisperSettings


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    version: int
    config_path: Path
    cache: CacheSettings
    providers: dict[str, ProviderProfile] = field(default_factory=dict)
    models: ModelsSettings | None = None

    def public_dict(self) -> dict[str, object]:
        models = self.models
        return {
            "version": self.version,
            "config_path": str(self.config_path),
            "cache": {"root": str(self.cache.root)},
            "providers": {
                name: provider.public_dict() for name, provider in sorted(self.providers.items())
            },
            "models": {
                "faster_whisper": {
                    "cache_dir": str(models.faster_whisper.cache_dir),
                    "default_model": models.faster_whisper.default_model,
                    "default_device": models.faster_whisper.default_device,
                    "default_compute_type": models.faster_whisper.default_compute_type,
                }
            }
            if models is not None
            else {},
        }


@dataclass(frozen=True, slots=True)
class SecretCheck:
    reference: str
    resolved: bool
    display: str
    value_preview: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    name: str
    type: str
    api_key: str | None
    base_url: str | None
    default_chat_model: str | None = None

    def request_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.type,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "default_chat_model": self.default_chat_model,
        }


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    providers: dict[str, ResolvedProvider] = field(default_factory=dict)
    cache_root: Path | None = None
    faster_whisper_cache_dir: Path | None = None
    redaction_values: tuple[str, ...] = ()

    def request_payload(self) -> dict[str, object]:
        return {
            "providers": {
                name: provider.request_payload()
                for name, provider in sorted(self.providers.items())
            },
            "cache": {
                "root": str(self.cache_root) if self.cache_root is not None else None,
                "faster_whisper": str(self.faster_whisper_cache_dir)
                if self.faster_whisper_cache_dir is not None
                else None,
            },
        }


@dataclass(frozen=True, slots=True)
class ModelAssetStatus:
    provider: str
    model: str
    cache_dir: Path
    present: bool
    size_bytes: int = 0
    error: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "cache_dir": str(self.cache_dir),
            "present": self.present,
            "size_bytes": self.size_bytes,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    id: str
    status: str
    severity: str
    message: str

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
        }
```

- [ ] **Step 4: Implement settings loader**

Create `src/openbbq/runtime/settings.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
from typing import Any
import tomllib

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
    path = Path(config_path).expanduser().resolve() if config_path is not None else default_user_config_path(env)
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
        default_model=_optional_string(
            fw_raw.get("default_model", "base"), "models.faster_whisper.default_model"
        ),
        default_device=_optional_string(
            fw_raw.get("default_device", "cpu"), "models.faster_whisper.default_device"
        ),
        default_compute_type=_optional_string(
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
        provider_type = _optional_string(profile_raw.get("type"), f"providers.{name}.type")
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ValidationError(
                f"providers.{name}.type must be one of: {', '.join(sorted(SUPPORTED_PROVIDER_TYPES))}."
            )
        providers[name] = ProviderProfile(
            name=name,
            type=provider_type,
            base_url=_optional_nullable_string(profile_raw.get("base_url"), f"providers.{name}.base_url"),
            api_key=_optional_nullable_string(profile_raw.get("api_key"), f"providers.{name}.api_key"),
            default_chat_model=_optional_nullable_string(
                profile_raw.get("default_chat_model"), f"providers.{name}.default_chat_model"
            ),
            display_name=_optional_nullable_string(
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
    return (base_dir / path).resolve()


def _require_mapping(value: Any, field_path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_path} must be a mapping.")
    return value


def _optional_mapping(value: Any, field_path: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _require_mapping(value, field_path)


def _optional_string(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_path} must be a non-empty string.")
    return value


def _optional_nullable_string(value: Any, field_path: str) -> str | None:
    if value is None:
        return None
    return _optional_string(value, field_path)


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
```

- [ ] **Step 5: Run settings tests**

Run:

```bash
uv run pytest tests/test_runtime_settings.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit runtime settings loader**

```bash
git add src/openbbq/runtime/__init__.py src/openbbq/runtime/models.py src/openbbq/runtime/settings.py tests/test_runtime_settings.py
git commit -m "feat: add runtime settings loader"
```

## Task 2: Secret Resolver and Redaction

**Files:**
- Create: `src/openbbq/runtime/secrets.py`
- Create: `src/openbbq/runtime/redaction.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_package_layout.py`
- Test: `tests/test_runtime_secrets.py`

- [ ] **Step 1: Write failing secret tests**

Create `tests/test_runtime_secrets.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_runtime_secrets.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `openbbq.runtime.secrets` or `openbbq.runtime.redaction`.

- [ ] **Step 3: Implement secret resolver**

Create `src/openbbq/runtime/secrets.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from typing import Protocol

from openbbq.errors import ValidationError
from openbbq.runtime.models import SecretCheck


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None:
        ...

    def set_password(self, service_name: str, username: str, password: str) -> None:
        ...


@dataclass(frozen=True, slots=True)
class ResolvedSecret:
    reference: str
    resolved: bool
    value: str | None
    public: SecretCheck


class SecretResolver:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        keyring_backend: KeyringBackend | None = None,
    ) -> None:
        self.env = os.environ if env is None else env
        self.keyring_backend = keyring_backend if keyring_backend is not None else _load_keyring()

    def resolve(self, reference: str) -> ResolvedSecret:
        if reference.startswith("env:"):
            name = reference.removeprefix("env:")
            if not name:
                raise ValidationError("env secret reference must include a variable name.")
            value = self.env.get(name)
            if value is None:
                return ResolvedSecret(
                    reference=reference,
                    resolved=False,
                    value=None,
                    public=SecretCheck(
                        reference=reference,
                        resolved=False,
                        display=reference,
                        error=f"Environment variable '{name}' is not set.",
                    ),
                )
            return ResolvedSecret(
                reference=reference,
                resolved=True,
                value=value,
                public=SecretCheck(
                    reference=reference,
                    resolved=True,
                    display=reference,
                    value_preview=_preview(value),
                ),
            )
        if reference.startswith("keyring:"):
            service, username = _parse_keyring_reference(reference)
            if self.keyring_backend is None:
                return ResolvedSecret(
                    reference=reference,
                    resolved=False,
                    value=None,
                    public=SecretCheck(
                        reference=reference,
                        resolved=False,
                        display=reference,
                        error="Python keyring support is not installed or not available.",
                    ),
                )
            value = self.keyring_backend.get_password(service, username)
            if value is None:
                return ResolvedSecret(
                    reference=reference,
                    resolved=False,
                    value=None,
                    public=SecretCheck(
                        reference=reference,
                        resolved=False,
                        display=reference,
                        error=f"Keyring secret '{reference}' was not found.",
                    ),
                )
            return ResolvedSecret(
                reference=reference,
                resolved=True,
                value=value,
                public=SecretCheck(
                    reference=reference,
                    resolved=True,
                    display=reference,
                    value_preview=_preview(value),
                ),
            )
        raise ValidationError("Unsupported secret reference scheme. Use env: or keyring:.")

    def set_secret(self, reference: str, value: str) -> None:
        if not reference.startswith("keyring:"):
            raise ValidationError("Only keyring: secret references can be set by OpenBBQ.")
        if not value:
            raise ValidationError("Secret value must be non-empty.")
        service, username = _parse_keyring_reference(reference)
        if self.keyring_backend is None:
            raise ValidationError("Python keyring support is not installed or not available.")
        self.keyring_backend.set_password(service, username, value)


def _parse_keyring_reference(reference: str) -> tuple[str, str]:
    payload = reference.removeprefix("keyring:")
    service, separator, username = payload.partition("/")
    if not separator or not service or not username:
        raise ValidationError("keyring secret reference must be keyring:<service>/<username>.")
    return service, username


def _load_keyring() -> KeyringBackend | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _preview(value: str) -> str:
    if len(value) <= 8:
        return "[REDACTED]"
    return f"{value[:3]}...{value[-4:]}"
```

- [ ] **Step 4: Implement redaction**

Create `src/openbbq/runtime/redaction.py`:

```python
from __future__ import annotations

from collections.abc import Iterable


def redact_values(message: str, values: Iterable[str]) -> str:
    redacted = message
    for value in values:
        if not value:
            continue
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted
```

- [ ] **Step 5: Add optional keyring dependency and package test**

Modify `pyproject.toml`:

```toml
[project.optional-dependencies]
media = ["faster-whisper>=1.2"]
llm = ["openai>=1.0"]
download = ["yt-dlp>=2024.12.0"]
secrets = ["keyring>=25"]
```

Add this test to `tests/test_package_layout.py`:

```python
def test_secrets_extra_declares_keyring_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["secrets"] == ["keyring>=25"]
```

- [ ] **Step 6: Run secret and package tests**

Run:

```bash
uv run pytest tests/test_runtime_secrets.py tests/test_package_layout.py::test_secrets_extra_declares_keyring_dependency -q
```

Expected: PASS.

- [ ] **Step 7: Commit secret resolver**

```bash
git add pyproject.toml src/openbbq/runtime/secrets.py src/openbbq/runtime/redaction.py tests/test_runtime_secrets.py tests/test_package_layout.py
git commit -m "feat: add runtime secret resolver"
```

## Task 3: Runtime Context and Provider Selection

**Files:**
- Create: `src/openbbq/runtime/context.py`
- Create: `src/openbbq/runtime/provider.py`
- Test: `tests/test_runtime_context.py`

- [ ] **Step 1: Write failing runtime context tests**

Create `tests/test_runtime_context.py`:

```python
import pytest

from openbbq.errors import ValidationError
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
    assert str(context.request_payload()["cache"]["faster_whisper"]).endswith("cache/models/fw")
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
```

- [ ] **Step 2: Run context tests to verify they fail**

Run:

```bash
uv run pytest tests/test_runtime_context.py -q
```

Expected: FAIL with missing `openbbq.runtime.context`.

- [ ] **Step 3: Implement runtime context builder**

Create `src/openbbq/runtime/context.py`:

```python
from __future__ import annotations

from openbbq.runtime.models import ResolvedProvider, RuntimeContext, RuntimeSettings
from openbbq.runtime.secrets import SecretResolver


def build_runtime_context(
    settings: RuntimeSettings,
    *,
    secret_resolver: SecretResolver | None = None,
) -> RuntimeContext:
    resolver = secret_resolver or SecretResolver()
    providers: dict[str, ResolvedProvider] = {}
    redaction_values: list[str] = []
    for name, profile in settings.providers.items():
        api_key = None
        if profile.api_key is not None:
            resolved = resolver.resolve(profile.api_key)
            api_key = resolved.value if resolved.resolved else None
            if api_key:
                redaction_values.append(api_key)
        providers[name] = ResolvedProvider(
            name=name,
            type=profile.type,
            api_key=api_key,
            base_url=profile.base_url,
            default_chat_model=profile.default_chat_model,
        )
    faster_whisper_cache_dir = (
        settings.models.faster_whisper.cache_dir if settings.models is not None else None
    )
    return RuntimeContext(
        providers=providers,
        cache_root=settings.cache.root,
        faster_whisper_cache_dir=faster_whisper_cache_dir,
        redaction_values=tuple(redaction_values),
    )
```

- [ ] **Step 4: Implement plugin provider helper**

Create `src/openbbq/runtime/provider.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


LEGACY_PROVIDER_NAME = "openai_compatible"


@dataclass(frozen=True, slots=True)
class LlmProviderCredentials:
    name: str
    type: str
    api_key: str
    base_url: str | None
    model_default: str | None = None


def llm_provider_from_request(request: dict[str, Any], *, error_prefix: str) -> LlmProviderCredentials:
    parameters = request.get("parameters", {})
    provider_name = parameters.get("provider")
    runtime = request.get("runtime", {})
    providers = runtime.get("providers", {}) if isinstance(runtime, dict) else {}
    if isinstance(provider_name, str) and provider_name.strip():
        provider = providers.get(provider_name)
        if not isinstance(provider, dict):
            raise ValueError(f"{error_prefix} provider '{provider_name}' is not configured.")
        provider_type = provider.get("type")
        if provider_type != "openai_compatible":
            raise ValueError(f"{error_prefix} provider '{provider_name}' must be openai_compatible.")
        api_key = provider.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise RuntimeError(f"{error_prefix} provider '{provider_name}' API key is not resolved.")
        base_url = provider.get("base_url")
        model_default = provider.get("default_chat_model")
        return LlmProviderCredentials(
            name=provider_name,
            type="openai_compatible",
            api_key=api_key,
            base_url=base_url if isinstance(base_url, str) and base_url else None,
            model_default=model_default if isinstance(model_default, str) and model_default else None,
        )

    api_key = os.environ.get("OPENBBQ_LLM_API_KEY")
    if not api_key:
        raise RuntimeError(f"OPENBBQ_LLM_API_KEY is required for {error_prefix}.")
    base_url = parameters.get("base_url") or os.environ.get("OPENBBQ_LLM_BASE_URL")
    return LlmProviderCredentials(
        name=LEGACY_PROVIDER_NAME,
        type="openai_compatible",
        api_key=api_key,
        base_url=str(base_url) if base_url else None,
        model_default=None,
    )
```

- [ ] **Step 5: Run context tests**

Run:

```bash
uv run pytest tests/test_runtime_context.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit runtime context**

```bash
git add src/openbbq/runtime/context.py src/openbbq/runtime/provider.py tests/test_runtime_context.py
git commit -m "feat: build runtime plugin context"
```

## Task 4: Engine Runtime Context Injection and Secret Redaction

**Files:**
- Modify: `src/openbbq/engine/service.py`
- Modify: `src/openbbq/workflow/execution.py`
- Modify: `src/openbbq/plugins/registry.py`
- Test: `tests/test_runtime_engine.py`

- [ ] **Step 1: Write failing engine runtime tests**

Create `tests/test_runtime_engine.py`:

```python
from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.engine.service import run_workflow
from openbbq.errors import ExecutionError
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.models import RuntimeContext
from openbbq.storage.project_store import ProjectStore


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def test_runtime_context_is_passed_to_plugin_request_without_persistence(
    tmp_path,
    monkeypatch,
):
    from openbbq.workflow import execution

    captured = {}

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None):
        captured["runtime"] = request["runtime"]
        return {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": "hello",
                    "metadata": {},
                }
            }
        }

    monkeypatch.setattr(execution, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    result = run_workflow(config, registry, "text-demo", runtime_context=context)

    assert result.status == "completed"
    assert captured["runtime"] == context.request_payload()
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    step_run = store.read_step_run("text-demo", state["step_run_ids"][0])
    assert "runtime" not in step_run


def test_plugin_error_is_redacted_before_state_and_cli_error(tmp_path, monkeypatch):
    from openbbq.workflow import execution

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None):
        raise execution.PluginError(redactor("failed with sk-secret"))

    monkeypatch.setattr(execution, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    with pytest.raises(ExecutionError) as exc:
        run_workflow(config, registry, "text-demo", runtime_context=context)

    assert "sk-secret" not in exc.value.message
    assert "[REDACTED]" in exc.value.message
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    step_run = store.read_step_run("text-demo", state["step_run_ids"][0])
    assert "sk-secret" not in step_run["error"]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_runtime_engine.py -q
```

Expected: FAIL because `run_workflow()` does not accept `runtime_context`.

- [ ] **Step 3: Modify plugin registry to redact wrapped exceptions**

Change `execute_plugin_tool()` in `src/openbbq/plugins/registry.py` to this signature and exception body:

```python
def execute_plugin_tool(
    plugin: PluginSpec,
    tool: ToolSpec,
    request: dict[str, Any],
    redactor=None,
) -> dict[str, Any]:
```

Inside the `except Exception as exc:` block, replace the current raise with:

```python
        message = f"Plugin '{plugin.name}' tool '{tool.name}' failed: {exc}"
        if redactor is not None:
            message = redactor(message)
        raise PluginError(message) from exc
```

- [ ] **Step 4: Add runtime context parameters through engine and execution**

In `src/openbbq/engine/service.py`, import `RuntimeContext`:

```python
from openbbq.runtime.models import RuntimeContext
```

Add `runtime_context: RuntimeContext | None = None` to `run_workflow()`, `_run_workflow_step()`, `_force_run_workflow()`, and `resume_workflow()` signatures. Pass the value into every call to `execute_workflow_from_start()`, `execute_workflow_step()`, and `execute_workflow_from_resume()`.

In `src/openbbq/workflow/execution.py`, import redaction and runtime context:

```python
from openbbq.runtime.models import RuntimeContext
from openbbq.runtime.redaction import redact_values
```

Add `runtime_context: RuntimeContext | None = None` to `execute_workflow_from_start()`, `execute_workflow_from_resume()`, `execute_workflow_step()`, and `execute_steps()`.

Inside `execute_steps()`, before the `for index in range(...)` loop, add:

```python
    runtime_payload = runtime_context.request_payload() if runtime_context is not None else {}
    redaction_values = runtime_context.redaction_values if runtime_context is not None else ()

    def redact_runtime_secrets(message: str) -> str:
        return redact_values(message, redaction_values)
```

In the plugin request dict, add:

```python
                    "runtime": runtime_payload,
```

Change the call to `execute_plugin_tool()`:

```python
                response = execute_plugin_tool(
                    plugin,
                    tool,
                    request,
                    redactor=redact_runtime_secrets,
                )
```

Inside the `except (PluginError, ValidationError) as exc:` block, create a redacted message before writing state:

```python
                redacted_message = redact_runtime_secrets(exc.message)
```

Use `redacted_message` in `_step_error()` and event messages. Change `_step_error()` to accept `message: str` or pass an error object whose message is already redacted. The minimal change is:

```python
                failed["error"] = _step_error(
                    exc,
                    step.id,
                    plugin.name,
                    plugin.version,
                    tool.name,
                    attempt,
                    message=redacted_message,
                )
```

Update `_step_error()` signature:

```python
def _step_error(
    error: PluginError | ValidationError,
    step_id: str,
    plugin_name: str,
    plugin_version: str,
    tool_name: str,
    attempt: int,
    *,
    message: str | None = None,
) -> dict[str, object]:
```

Set the message field:

```python
        "message": error.message if message is None else message,
```

When raising `ExecutionError`, use:

```python
                raise ExecutionError(redacted_message) from exc
```

- [ ] **Step 5: Run engine runtime tests**

Run:

```bash
uv run pytest tests/test_runtime_engine.py -q
```

Expected: PASS.

- [ ] **Step 6: Run existing engine tests**

Run:

```bash
uv run pytest tests/test_engine_run_text.py tests/test_engine_pause_resume.py tests/test_engine_error_policy.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit engine runtime context**

```bash
git add src/openbbq/engine/service.py src/openbbq/workflow/execution.py src/openbbq/plugins/registry.py tests/test_runtime_engine.py
git commit -m "feat: pass runtime context to plugins"
```

## Task 5: LLM Provider Profiles in Translation and Correction Plugins

**Files:**
- Modify: `src/openbbq/builtin_plugins/translation/openbbq.plugin.toml`
- Modify: `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`
- Modify: `src/openbbq/builtin_plugins/transcript/openbbq.plugin.toml`
- Modify: `src/openbbq/builtin_plugins/translation/plugin.py`
- Modify: `src/openbbq/builtin_plugins/transcript/plugin.py`
- Test: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Add failing provider-profile plugin tests**

Append these tests to `tests/test_builtin_plugins.py`:

```python
def test_translation_translate_uses_runtime_provider_profile():
    factory = RecordingOpenAIClientFactory('[{"index":0,"text":"Hello zh"}]')

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "target_lang": "zh-Hans",
            },
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
            "inputs": {
                "subtitle_segments": {
                    "type": "subtitle_segments",
                    "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                }
            },
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "sk-runtime", "base_url": "https://api.openai.com/v1"}]
    assert response["outputs"]["translation"]["metadata"]["provider"] == "openai"
    assert response["outputs"]["translation"]["metadata"]["model"] == "gpt-4o-mini"


def test_translation_translate_legacy_provider_still_uses_env(monkeypatch):
    factory = RecordingOpenAIClientFactory('[{"index":0,"text":"Hello zh"}]')
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-env")
    monkeypatch.setenv("OPENBBQ_LLM_BASE_URL", "https://legacy.example/v1")

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai_compatible",
                "source_lang": "en",
                "target_lang": "zh-Hans",
                "model": "gpt-4o-mini",
            },
            "inputs": {
                "subtitle_segments": {
                    "type": "subtitle_segments",
                    "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                }
            },
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "sk-env", "base_url": "https://legacy.example/v1"}]
    assert response["outputs"]["translation"]["metadata"]["provider"] == "openai_compatible"


def test_transcript_correct_uses_runtime_provider_profile():
    factory = RecordingOpenAIClientFactory('[{"index":0,"text":"OpenBBQ"}]')

    response = transcript_plugin.run(
        {
            "tool_name": "correct",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
            },
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
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [{"start": 0.0, "end": 1.0, "text": "Open BBQ"}],
                }
            },
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "sk-runtime", "base_url": "https://api.openai.com/v1"}]
    assert response["outputs"]["transcript"]["metadata"]["model"] == "gpt-4o-mini"
```

- [ ] **Step 2: Run plugin tests to verify they fail**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_translation_translate_uses_runtime_provider_profile tests/test_builtin_plugins.py::test_translation_translate_legacy_provider_still_uses_env tests/test_builtin_plugins.py::test_transcript_correct_uses_runtime_provider_profile -q
```

Expected: FAIL because plugin manifests and plugin code require the old provider contract or model parameter.

- [ ] **Step 3: Broaden provider schema for named profiles**

In `src/openbbq/builtin_plugins/translation/openbbq.plugin.toml`, replace the `provider` property with:

```toml
[tools.parameter_schema.properties.provider]
type = "string"
default = "openai_compatible"
```

In `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`, add:

```toml
[tools.parameter_schema.properties.provider]
type = "string"
```

In `src/openbbq/builtin_plugins/transcript/openbbq.plugin.toml`, add:

```toml
[tools.parameter_schema.properties.provider]
type = "string"
```

Remove `"model"` from the `required` arrays of `translation.translate`, `llm.translate`, and `transcript.correct`, because provider profiles can supply `default_chat_model`. Keep `source_lang` and `target_lang` required for translation, and keep `source_lang` required for correction.

- [ ] **Step 4: Update translation plugin provider resolution**

In `src/openbbq/builtin_plugins/translation/plugin.py`, import:

```python
from openbbq.runtime.provider import llm_provider_from_request
```

In `run_translation()`, replace provider/model/api key/base URL handling with:

```python
    provider = llm_provider_from_request(request, error_prefix=error_prefix)
    model_value = parameters.get("model") or provider.model_default
    if not isinstance(model_value, str) or not model_value.strip():
        raise ValueError(f"{error_prefix} parameter 'model' must be a non-empty string.")
    model = model_value
```

Replace client creation with:

```python
    client = client_factory(api_key=provider.api_key, base_url=provider.base_url)
```

Replace provider metadata with:

```python
        metadata["provider"] = provider.name
```

- [ ] **Step 5: Update transcript correction provider resolution**

In `src/openbbq/builtin_plugins/transcript/plugin.py`, import:

```python
from openbbq.runtime.provider import llm_provider_from_request
```

In `_run_correct()`, replace model/api key/base URL handling with:

```python
    provider = llm_provider_from_request(request, error_prefix="transcript.correct")
    model_value = parameters.get("model") or provider.model_default
    if not isinstance(model_value, str) or not model_value.strip():
        raise ValueError("transcript.correct parameter 'model' must be a non-empty string.")
    model = model_value
```

Replace client creation with:

```python
    client = client_factory(api_key=provider.api_key, base_url=provider.base_url)
```

Add provider metadata:

```python
                    "provider": provider.name,
```

- [ ] **Step 6: Run provider-profile tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_translation_translate_uses_runtime_provider_profile tests/test_builtin_plugins.py::test_translation_translate_legacy_provider_still_uses_env tests/test_builtin_plugins.py::test_transcript_correct_uses_runtime_provider_profile -q
```

Expected: PASS.

- [ ] **Step 7: Run existing LLM plugin tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_llm_translate_uses_openai_client_and_returns_translation tests/test_builtin_plugins.py::test_translation_translate_uses_openai_client_and_returns_translation tests/test_phase2_translation_slice.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit provider profile plugin support**

```bash
git add src/openbbq/builtin_plugins/translation/openbbq.plugin.toml src/openbbq/builtin_plugins/llm/openbbq.plugin.toml src/openbbq/builtin_plugins/transcript/openbbq.plugin.toml src/openbbq/builtin_plugins/translation/plugin.py src/openbbq/builtin_plugins/transcript/plugin.py tests/test_builtin_plugins.py
git commit -m "feat: use runtime provider profiles in llm tools"
```

## Task 6: Faster-Whisper Cache Directory

**Files:**
- Modify: `src/openbbq/builtin_plugins/faster_whisper/plugin.py`
- Test: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Add failing faster-whisper cache test**

Append this test to `tests/test_builtin_plugins.py`:

```python
def test_faster_whisper_transcribe_uses_runtime_cache_dir(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    calls = []

    class FakeWord:
        start = 0.0
        end = 0.5
        word = "Hello"
        probability = 0.9

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello"
        avg_logprob = -0.1
        words = [FakeWord()]

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeWhisperModel:
        def transcribe(self, audio_path, **kwargs):
            return [FakeSegment()], FakeInfo()

    def fake_model_factory(model_name, *, device, compute_type, download_root=None):
        calls.append(
            {
                "model_name": model_name,
                "device": device,
                "compute_type": compute_type,
                "download_root": download_root,
            }
        )
        return FakeWhisperModel()

    whisper_plugin.run(
        {
            "tool_name": "transcribe",
            "parameters": {"model": "base", "device": "cpu", "compute_type": "int8"},
            "runtime": {"cache": {"faster_whisper": str(tmp_path / "models/fw")}},
            "inputs": {"audio": {"type": "audio", "file_path": str(audio)}},
        },
        model_factory=fake_model_factory,
    )

    assert calls == [
        {
            "model_name": "base",
            "device": "cpu",
            "compute_type": "int8",
            "download_root": str(tmp_path / "models/fw"),
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_faster_whisper_transcribe_uses_runtime_cache_dir -q
```

Expected: FAIL because `download_root` is not passed.

- [ ] **Step 3: Pass runtime cache to model factory**

In `src/openbbq/builtin_plugins/faster_whisper/plugin.py`, add:

```python
def _runtime_faster_whisper_cache(request: dict) -> str | None:
    runtime = request.get("runtime", {})
    if not isinstance(runtime, dict):
        return None
    cache = runtime.get("cache", {})
    if not isinstance(cache, dict):
        return None
    value = cache.get("faster_whisper")
    return value if isinstance(value, str) and value else None
```

In `run()`, before creating the model:

```python
    download_root = _runtime_faster_whisper_cache(request)
```

Change model creation:

```python
    model = model_factory(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )
```

Change the default factory signature and call:

```python
def _default_model_factory(
    model_name: str,
    *,
    device: str,
    compute_type: str,
    download_root: str | None = None,
):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Install OpenBBQ with the media optional dependencies."
        ) from exc
    return WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )
```

Add cache metadata:

```python
                    "model_cache_dir": download_root,
```

- [ ] **Step 4: Update existing fake faster-whisper tests**

Search in tests for fake model factories with the old signature:

```bash
Select-String -Path tests\*.py -Pattern "FakeWhisperModel|fake_model_factory|_default_model_factory"
```

For every fake factory used as `_default_model_factory`, add `download_root=None` to the signature. Example:

```python
class FakeWhisperModel:
    def __init__(self, model, device, compute_type, download_root=None):
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
```

- [ ] **Step 5: Run faster-whisper tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_faster_whisper_transcribe_uses_runtime_cache_dir tests/test_phase2_local_video_subtitle.py tests/test_phase2_translation_slice.py tests/test_phase2_asr_correction_segmentation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit faster-whisper cache support**

```bash
git add src/openbbq/builtin_plugins/faster_whisper/plugin.py tests/test_builtin_plugins.py tests/test_phase2_local_video_subtitle.py tests/test_phase2_translation_slice.py tests/test_phase2_asr_correction_segmentation.py
git commit -m "feat: configure faster whisper cache"
```

## Task 7: Runtime CLI Commands

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/runtime/settings.py`
- Test: `tests/test_runtime_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_runtime_cli.py`:

```python
import json

from openbbq.cli.app import main


def test_settings_show_json_uses_user_config(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    user_config.write_text(
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
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(["--json", "settings", "show"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["settings"]["providers"]["openai"]["api_key"] == "env:OPENBBQ_LLM_API_KEY"


def test_settings_set_provider_writes_user_config(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(
        [
            "--json",
            "settings",
            "set-provider",
            "openai",
            "--type",
            "openai_compatible",
            "--base-url",
            "https://api.openai.com/v1",
            "--api-key",
            "env:OPENBBQ_LLM_API_KEY",
            "--default-chat-model",
            "gpt-4o-mini",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert user_config.read_text(encoding="utf-8").count("[providers.openai]") == 1
    assert "gpt-4o-mini" in user_config.read_text(encoding="utf-8")


def test_secret_check_json_reports_unresolved_env(monkeypatch, capsys):
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)

    code = main(["--json", "secret", "check", "env:OPENBBQ_LLM_API_KEY"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["secret"]["resolved"] is False
    assert "OPENBBQ_LLM_API_KEY" in payload["secret"]["error"]


def test_secret_set_rejects_json_mode(capsys):
    code = main(["--json", "secret", "set", "keyring:openbbq/providers/openai/api_key"])

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "interactive" in payload["error"]["message"].lower()


def test_models_list_json_reports_faster_whisper_cache(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    cache_dir = tmp_path / "models/fw"
    user_config.write_text(
        f"""
version = 1
[models.faster_whisper]
cache_dir = "{cache_dir}"
default_model = "base"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(["--json", "models", "list"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["models"][0]["provider"] == "faster_whisper"
    assert payload["models"][0]["model"] == "base"
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
uv run pytest tests/test_runtime_cli.py -q
```

Expected: FAIL because the CLI commands do not exist.

- [ ] **Step 3: Add provider update helper**

In `src/openbbq/runtime/settings.py`, add:

```python
def with_provider_profile(
    settings: RuntimeSettings,
    provider: ProviderProfile,
) -> RuntimeSettings:
    providers = dict(settings.providers)
    providers[provider.name] = provider
    return RuntimeSettings(
        version=settings.version,
        config_path=settings.config_path,
        cache=settings.cache,
        providers=providers,
        models=settings.models,
    )
```

- [ ] **Step 4: Add CLI parsers**

In `_build_parser()` in `src/openbbq/cli/app.py`, add after `plugin` parser setup:

```python
    settings = subparsers.add_parser("settings", parents=[subcommand_global_options])
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("show", parents=[subcommand_global_options])
    settings_provider = settings_sub.add_parser("set-provider", parents=[subcommand_global_options])
    settings_provider.add_argument("name")
    settings_provider.add_argument("--type", required=True)
    settings_provider.add_argument("--base-url")
    settings_provider.add_argument("--api-key")
    settings_provider.add_argument("--default-chat-model")
    settings_provider.add_argument("--display-name")

    secret = subparsers.add_parser("secret", parents=[subcommand_global_options])
    secret_sub = secret.add_subparsers(dest="secret_command", required=True)
    secret_check = secret_sub.add_parser("check", parents=[subcommand_global_options])
    secret_check.add_argument("reference")
    secret_set = secret_sub.add_parser("set", parents=[subcommand_global_options])
    secret_set.add_argument("reference")

    models = subparsers.add_parser("models", parents=[subcommand_global_options])
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("list", parents=[subcommand_global_options])
```

- [ ] **Step 5: Add CLI dispatch handlers**

In `_dispatch()`, add:

```python
    if args.command == "settings":
        if args.settings_command == "show":
            return _settings_show(args)
        if args.settings_command == "set-provider":
            return _settings_set_provider(args)
    if args.command == "secret":
        if args.secret_command == "check":
            return _secret_check(args)
        if args.secret_command == "set":
            return _secret_set(args)
    if args.command == "models":
        if args.models_command == "list":
            return _models_list(args)
```

Add imports:

```python
import getpass

from openbbq.runtime.models import ProviderProfile
from openbbq.runtime.models_assets import faster_whisper_model_status
from openbbq.runtime.secrets import SecretResolver
from openbbq.runtime.settings import (
    load_runtime_settings,
    with_provider_profile,
    write_runtime_settings,
)
```

Add handlers:

```python
def _settings_show(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    payload = {"ok": True, "settings": settings.public_dict()}
    _emit(payload, args.json_output, settings.config_path)
    return 0


def _settings_set_provider(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    provider = ProviderProfile(
        name=args.name,
        type=args.type,
        base_url=args.base_url,
        api_key=args.api_key,
        default_chat_model=args.default_chat_model,
        display_name=args.display_name,
    )
    updated = with_provider_profile(settings, provider)
    write_runtime_settings(updated)
    payload = {"ok": True, "provider": provider.public_dict(), "config_path": str(updated.config_path)}
    _emit(payload, args.json_output, f"Updated provider '{provider.name}'.")
    return 0


def _secret_check(args: argparse.Namespace) -> int:
    check = SecretResolver().resolve(args.reference)
    payload = {"ok": True, "secret": check.public.__dict__}
    _emit(payload, args.json_output, check.public.display)
    return 0


def _secret_set(args: argparse.Namespace) -> int:
    if args.json_output:
        raise ValidationError("secret set requires interactive input and cannot run in JSON mode.")
    value = getpass.getpass("Secret value: ")
    SecretResolver().set_secret(args.reference, value)
    _emit({"ok": True, "reference": args.reference}, args.json_output, "Secret stored.")
    return 0


def _models_list(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    status = faster_whisper_model_status(settings)
    payload = {"ok": True, "models": [status.public_dict()]}
    _emit(payload, args.json_output, status.public_dict())
    return 0
```

If `check.public.__dict__` is unavailable because `SecretCheck` uses slots, use:

```python
    payload = {
        "ok": True,
        "secret": {
            "reference": check.public.reference,
            "resolved": check.public.resolved,
            "display": check.public.display,
            "value_preview": check.public.value_preview,
            "error": check.public.error,
        },
    }
```

- [ ] **Step 6: Implement model status helper**

Create `src/openbbq/runtime/models_assets.py`:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.runtime.models import ModelAssetStatus, RuntimeSettings


def faster_whisper_model_status(settings: RuntimeSettings) -> ModelAssetStatus:
    if settings.models is None:
        cache_dir = settings.cache.root / "models" / "faster-whisper"
        model = "base"
    else:
        cache_dir = settings.models.faster_whisper.cache_dir
        model = settings.models.faster_whisper.default_model
    present = cache_dir.exists()
    return ModelAssetStatus(
        provider="faster_whisper",
        model=model,
        cache_dir=cache_dir,
        present=present,
        size_bytes=_directory_size(cache_dir) if present else 0,
    )


def _directory_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    if not path.is_dir():
        return total
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total
```

- [ ] **Step 7: Run runtime CLI tests**

Run:

```bash
uv run pytest tests/test_runtime_cli.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit runtime CLI**

```bash
git add src/openbbq/cli/app.py src/openbbq/runtime/settings.py src/openbbq/runtime/models_assets.py tests/test_runtime_cli.py
git commit -m "feat: add runtime settings cli"
```

## Task 8: Doctor Preflight Checks

**Files:**
- Create: `src/openbbq/runtime/doctor.py`
- Modify: `src/openbbq/cli/app.py`
- Test: `tests/test_runtime_doctor.py`
- Test: `tests/test_runtime_cli.py`

- [ ] **Step 1: Write failing doctor tests**

Create `tests/test_runtime_doctor.py`:

```python
from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.doctor import DoctorProbes, check_workflow
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeSettings,
)


def settings(tmp_path):
    return RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        providers={
            "openai": ProviderProfile(
                name="openai",
                type="openai_compatible",
                api_key="env:OPENBBQ_LLM_API_KEY",
                default_chat_model="gpt-4o-mini",
            )
        },
        models=ModelsSettings(
            faster_whisper=FasterWhisperSettings(cache_dir=tmp_path / "cache/models/fw")
        ),
    )


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_doctor_reports_missing_llm_secret_for_translation_workflow(tmp_path):
    project = write_project(tmp_path, "local-video-corrected-translate-subtitle")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    probes = DoctorProbes(
        env={},
        which=lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
        importable=lambda name: True,
        path_writable=lambda path: True,
    )

    result = check_workflow(
        config=config,
        registry=registry,
        workflow_id="local-video-corrected-translate-subtitle",
        settings=settings(tmp_path),
        probes=probes,
    )

    failed = {check.id: check for check in result if check.status == "failed"}
    assert "provider.openai.api_key" in failed


def test_doctor_reports_missing_ffmpeg_for_media_workflow(tmp_path):
    project = write_project(tmp_path, "local-video-subtitle")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    probes = DoctorProbes(
        env={},
        which=lambda name: None,
        importable=lambda name: True,
        path_writable=lambda path: True,
    )

    result = check_workflow(
        config=config,
        registry=registry,
        workflow_id="local-video-subtitle",
        settings=settings(tmp_path),
        probes=probes,
    )

    failed = {check.id: check for check in result if check.status == "failed"}
    assert "binary.ffmpeg" in failed


def test_doctor_passes_writable_model_cache(tmp_path):
    project = write_project(tmp_path, "local-video-subtitle")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    probes = DoctorProbes(
        env={"OPENBBQ_LLM_API_KEY": "sk-test"},
        which=lambda name: "/usr/bin/ffmpeg",
        importable=lambda name: True,
        path_writable=lambda path: True,
    )

    result = check_workflow(
        config=config,
        registry=registry,
        workflow_id="local-video-subtitle",
        settings=settings(tmp_path),
        probes=probes,
    )

    statuses = {check.id: check.status for check in result}
    assert statuses["model.faster_whisper.cache_writable"] == "passed"
```

Append this CLI test to `tests/test_runtime_cli.py`:

```python
def test_doctor_json_reports_checks(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    source = open("tests/fixtures/projects/text-basic/openbbq.yaml", encoding="utf-8").read()
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(__import__("pathlib").Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )

    code = main(["--project", str(project), "--json", "doctor", "--workflow", "text-demo"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list)
```

- [ ] **Step 2: Run doctor tests to verify they fail**

Run:

```bash
uv run pytest tests/test_runtime_doctor.py tests/test_runtime_cli.py::test_doctor_json_reports_checks -q
```

Expected: FAIL because `openbbq.runtime.doctor` and CLI `doctor` do not exist.

- [ ] **Step 3: Implement doctor checks**

Create `src/openbbq/runtime/doctor.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import importlib.util
import os
import shutil

from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.errors import ValidationError
from openbbq.plugins.registry import PluginRegistry
from openbbq.runtime.models import DoctorCheck, RuntimeSettings
from openbbq.runtime.secrets import SecretResolver


@dataclass(frozen=True, slots=True)
class DoctorProbes:
    env: Mapping[str, str] | None = None
    which: Callable[[str], str | None] = shutil.which
    importable: Callable[[str], bool] | None = None
    path_writable: Callable[[Path], bool] | None = None


def check_workflow(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
    settings: RuntimeSettings,
    probes: DoctorProbes | None = None,
) -> list[DoctorCheck]:
    probes = probes or DoctorProbes()
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    tool_refs = {step.tool_ref for step in workflow.steps}
    checks: list[DoctorCheck] = []
    checks.append(_project_storage_check(config))
    if any(tool_ref == "ffmpeg.extract_audio" for tool_ref in tool_refs):
        checks.append(_binary_check("ffmpeg", probes))
    if any(tool_ref == "remote_video.download" for tool_ref in tool_refs):
        checks.append(_import_check("yt_dlp", "python.yt_dlp", probes))
    if any(tool_ref == "faster_whisper.transcribe" for tool_ref in tool_refs):
        checks.append(_import_check("faster_whisper", "python.faster_whisper", probes))
        checks.append(_cache_writable_check(settings, probes))
    if _workflow_uses_llm(workflow):
        checks.extend(_provider_checks(settings, probes))
    return checks


def _workflow_uses_llm(workflow: WorkflowConfig) -> bool:
    return any(
        step.tool_ref in {"translation.translate", "llm.translate", "transcript.correct"}
        for step in workflow.steps
    )


def _provider_checks(settings: RuntimeSettings, probes: DoctorProbes) -> list[DoctorCheck]:
    if settings.providers:
        checks: list[DoctorCheck] = []
        resolver = SecretResolver(env=probes.env or os.environ, keyring_backend=None)
        for name, provider in sorted(settings.providers.items()):
            if provider.api_key is None:
                checks.append(
                    DoctorCheck(
                        id=f"provider.{name}.api_key",
                        status="failed",
                        severity="error",
                        message=f"Provider '{name}' does not define an api_key secret reference.",
                    )
                )
                continue
            resolved = resolver.resolve(provider.api_key)
            checks.append(
                DoctorCheck(
                    id=f"provider.{name}.api_key",
                    status="passed" if resolved.resolved else "failed",
                    severity="error",
                    message=(
                        f"Provider '{name}' API key is resolved."
                        if resolved.resolved
                        else resolved.public.error or f"Provider '{name}' API key is not resolved."
                    ),
                )
            )
        return checks
    env = probes.env or os.environ
    return [
        DoctorCheck(
            id="provider.openai_compatible.api_key",
            status="passed" if env.get("OPENBBQ_LLM_API_KEY") else "failed",
            severity="error",
            message=(
                "OPENBBQ_LLM_API_KEY is set."
                if env.get("OPENBBQ_LLM_API_KEY")
                else "OPENBBQ_LLM_API_KEY is not set."
            ),
        )
    ]


def _project_storage_check(config: ProjectConfig) -> DoctorCheck:
    return DoctorCheck(
        id="project.storage",
        status="passed",
        severity="error",
        message=f"Project storage root is {config.storage.root}.",
    )


def _binary_check(name: str, probes: DoctorProbes) -> DoctorCheck:
    path = probes.which(name)
    return DoctorCheck(
        id=f"binary.{name}",
        status="passed" if path else "failed",
        severity="error",
        message=f"{name} is available at {path}." if path else f"{name} was not found on PATH.",
    )


def _import_check(module_name: str, check_id: str, probes: DoctorProbes) -> DoctorCheck:
    importable = probes.importable
    present = importable(module_name) if importable is not None else importlib.util.find_spec(module_name) is not None
    return DoctorCheck(
        id=check_id,
        status="passed" if present else "failed",
        severity="error",
        message=f"Python module '{module_name}' is importable."
        if present
        else f"Python module '{module_name}' is not importable.",
    )


def _cache_writable_check(settings: RuntimeSettings, probes: DoctorProbes) -> DoctorCheck:
    cache_dir = (
        settings.models.faster_whisper.cache_dir
        if settings.models is not None
        else settings.cache.root / "models" / "faster-whisper"
    )
    writable_probe = probes.path_writable or _path_writable
    writable = writable_probe(cache_dir)
    return DoctorCheck(
        id="model.faster_whisper.cache_writable",
        status="passed" if writable else "failed",
        severity="error",
        message=f"faster-whisper cache directory is writable: {cache_dir}."
        if writable
        else f"faster-whisper cache directory is not writable: {cache_dir}.",
    )


def _path_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".openbbq-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True
```

- [ ] **Step 4: Add doctor CLI parser and handler**

In `_build_parser()` in `src/openbbq/cli/app.py`, add:

```python
    doctor = subparsers.add_parser("doctor", parents=[subcommand_global_options])
    doctor.add_argument("--workflow")
```

In `_dispatch()`, add:

```python
    if args.command == "doctor":
        return _doctor(args)
```

Import:

```python
from openbbq.runtime.doctor import check_workflow
```

Add handler:

```python
def _doctor(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    if args.workflow:
        config, registry = _load_config_and_plugins(args)
        checks = check_workflow(
            config=config,
            registry=registry,
            workflow_id=args.workflow,
            settings=settings,
        )
    else:
        checks = []
    payload = {"ok": all(check.status != "failed" for check in checks), "checks": [check.public_dict() for check in checks]}
    _emit(payload, args.json_output, "\n".join(check.message for check in checks))
    return 0
```

- [ ] **Step 5: Run doctor tests**

Run:

```bash
uv run pytest tests/test_runtime_doctor.py tests/test_runtime_cli.py::test_doctor_json_reports_checks -q
```

Expected: PASS.

- [ ] **Step 6: Commit doctor checks**

```bash
git add src/openbbq/runtime/doctor.py src/openbbq/cli/app.py tests/test_runtime_doctor.py tests/test_runtime_cli.py
git commit -m "feat: add runtime doctor checks"
```

## Task 9: CLI Runtime Context in Workflow Runs

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Test: `tests/test_runtime_cli.py`
- Test: `tests/test_phase2_translation_slice.py`

- [ ] **Step 1: Add failing CLI runtime integration test**

Append this test to `tests/test_runtime_cli.py`:

```python
def test_cli_run_builds_runtime_context_from_user_settings(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.translation import plugin as translation_plugin

    user_config = tmp_path / "user-config.toml"
    user_config.write_text(
        f"""
version = 1
[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"
[models.faster_whisper]
cache_dir = "{tmp_path / "models/fw"}"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-runtime")

    def fake_runner(command):
        Path(command[-1]).write_bytes(b"audio")

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello"
        avg_logprob = -0.1
        words = []

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeWhisperModel:
        def __init__(self, model, device, compute_type, download_root=None):
            assert download_root == str(tmp_path / "models/fw")

        def transcribe(self, audio_path, language=None, word_timestamps=True, vad_filter=False):
            return [FakeSegment()], FakeInfo()

    def fake_client_factory(*, api_key, base_url):
        assert api_key == "sk-runtime"
        assert base_url == "https://api.openai.com/v1"
        return FakeOpenAIClient()

    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)
    monkeypatch.setattr(translation_plugin, "_default_client_factory", fake_client_factory)

    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    source = source.replace("model: gpt-4o-mini", "provider: openai")
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")

    assert main(["--project", str(project), "--json", "artifact", "import", str(video), "--type", "video", "--name", "source.video"]) == 0
    artifact_id = json.loads(capsys.readouterr().out)["artifact"]["id"]
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "project.art_imported_video", f"project.{artifact_id}"
        ),
        encoding="utf-8",
    )

    code = main(["--project", str(project), "--json", "run", "local-video-corrected-translate-subtitle"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
```

If `FakeOpenAIClient` is not available in `tests/test_runtime_cli.py`, copy the fake client classes from `tests/test_phase2_translation_slice.py` into the file.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_runtime_cli.py::test_cli_run_builds_runtime_context_from_user_settings -q
```

Expected: FAIL because CLI run does not build runtime context.

- [ ] **Step 3: Build runtime context in CLI run and resume paths**

In `src/openbbq/cli/app.py`, import:

```python
from openbbq.runtime.context import build_runtime_context
```

Add helper:

```python
def _runtime_context():
    return build_runtime_context(load_runtime_settings())
```

Change `_run()`:

```python
    result = run_workflow(
        config,
        registry,
        args.workflow,
        force=args.force,
        step_id=args.step,
        runtime_context=_runtime_context(),
    )
```

Change `_resume()`:

```python
    result = resume_workflow(
        config,
        registry,
        args.workflow,
        runtime_context=_runtime_context(),
    )
```

- [ ] **Step 4: Run CLI runtime integration test**

Run:

```bash
uv run pytest tests/test_runtime_cli.py::test_cli_run_builds_runtime_context_from_user_settings -q
```

Expected: PASS.

- [ ] **Step 5: Run existing CLI tests**

Run:

```bash
uv run pytest tests/test_cli_integration.py tests/test_cli_control_flow.py tests/test_phase2_translation_slice.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit CLI runtime context**

```bash
git add src/openbbq/cli/app.py tests/test_runtime_cli.py tests/test_phase2_translation_slice.py
git commit -m "feat: use runtime context in cli runs"
```

## Task 10: Documentation and Workflow Fixture Update

**Files:**
- Modify: `docs/Target-Workflows.md`
- Modify: `README.md`
- Modify: `tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml`
- Test: `tests/test_fixtures.py`

- [ ] **Step 1: Update corrected translation fixture to use provider profile**

In `tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml`, change the `correct` and `translate` steps:

```yaml
        parameters:
          source_lang: en
          provider: openai
          temperature: 0
```

and:

```yaml
        parameters:
          provider: openai
          source_lang: en
          target_lang: zh-Hans
          temperature: 0
```

Keep `model` omitted in this fixture to prove `default_chat_model` can come from user runtime settings.

- [ ] **Step 2: Add fixture validation test for provider-profile workflow**

In `tests/test_fixtures.py`, update `test_local_video_corrected_translate_subtitle_fixture_uses_builtin_plugins()` with:

```python
    workflow = config.workflows["local-video-corrected-translate-subtitle"]
    correct_step = next(step for step in workflow.steps if step.id == "correct")
    translate_step = next(step for step in workflow.steps if step.id == "translate")
    assert correct_step.parameters["provider"] == "openai"
    assert "model" not in correct_step.parameters
    assert translate_step.parameters["provider"] == "openai"
    assert "model" not in translate_step.parameters
```

- [ ] **Step 3: Update Target Workflows documentation**

In `docs/Target-Workflows.md`, add a short section after the translation parameters table:

```markdown
Runtime provider profiles:

- `provider` may name a provider from `~/.openbbq/config.toml`, such as `openai`.
- Provider profiles store `type`, `base_url`, optional default model, and an API key reference.
- API keys must use `env:` or `keyring:` secret references and must not be written into `openbbq.yaml`.
- If `provider` is omitted, the built-in tools still accept `OPENBBQ_LLM_API_KEY` and `OPENBBQ_LLM_BASE_URL` for compatibility.
```

In the ASR section, add:

```markdown
OpenBBQ resolves the faster-whisper model cache from `OPENBBQ_CACHE_DIR` or `~/.openbbq/config.toml`. The default cache root is `~/.cache/openbbq`.
```

- [ ] **Step 4: Update README runtime setup**

In `README.md`, add a section under Phase 2 Translation Preview:

```markdown
### Runtime Settings Preview

OpenBBQ can load user runtime settings from `~/.openbbq/config.toml`. Project workflows should reference provider names, while API keys stay in environment variables or the OS keychain.

Example:

```toml
version = 1

[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"

[models.faster_whisper]
cache_dir = "~/.cache/openbbq/models/faster-whisper"
default_model = "base"
```

Run preflight checks before a real workflow:

```bash
uv run openbbq doctor --workflow local-video-corrected-translate-subtitle --project ./demo --json
```
```

- [ ] **Step 5: Run fixture and docs-related tests**

Run:

```bash
uv run pytest tests/test_fixtures.py tests/test_engine_validate.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit docs and fixture update**

```bash
git add docs/Target-Workflows.md README.md tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml tests/test_fixtures.py
git commit -m "docs: document runtime settings"
```

## Task 11: Full Verification

**Files:**
- No source edits unless verification exposes a defect.

- [ ] **Step 1: Run targeted runtime tests**

Run:

```bash
uv run pytest tests/test_runtime_settings.py tests/test_runtime_secrets.py tests/test_runtime_context.py tests/test_runtime_engine.py tests/test_runtime_cli.py tests/test_runtime_doctor.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Phase 2 plugin and fixture tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py tests/test_phase2_translation_slice.py tests/test_phase2_asr_correction_segmentation.py tests/test_phase2_local_video_subtitle.py tests/test_phase2_remote_video_slice.py tests/test_fixtures.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS. If the local sandbox cannot run `uv run pytest`, record the exact sandbox error and rerun the equivalent `.venv` pytest command with pytest cache disabled.

- [ ] **Step 4: Run lint and format checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: both commands pass.

- [ ] **Step 5: Run CLI smoke commands**

Run:

```bash
uv run openbbq --json settings show
uv run openbbq --json secret check env:OPENBBQ_LLM_API_KEY
uv run openbbq --json models list
uv run openbbq --json validate local-video-corrected-translate-subtitle --project tests/fixtures/projects/local-video-corrected-translate-subtitle
uv run openbbq --json doctor --workflow local-video-corrected-translate-subtitle --project tests/fixtures/projects/local-video-corrected-translate-subtitle
```

Expected:

- `settings show` returns `ok: true`.
- `secret check` returns `ok: true` and may report `resolved: false` if the environment variable is absent.
- `models list` returns a faster-whisper model entry.
- `validate` returns `ok: true`.
- `doctor` returns structured checks and exits 0.

- [ ] **Step 6: Confirm no secret persistence**

Run:

```bash
Select-String -Path .openbbq\**\* -Pattern "sk-runtime","sk-secret","sk-test" -ErrorAction SilentlyContinue
```

Expected: no matches in project workflow state or artifacts. If the command cannot access `.openbbq`, inspect the test project directories created during runtime engine tests.

- [ ] **Step 7: Commit verification fixes if needed**

If verification required code or doc fixes:

```bash
git add <changed-files>
git commit -m "fix: harden runtime settings verification"
```

If no fixes were needed, do not create an empty commit.

## Self-Review Checklist

- Spec coverage: user settings, provider profiles, secret refs, keyring, runtime context, plugin integration, faster-whisper cache, CLI commands, doctor checks, Desktop reuse documentation, and deterministic tests are covered.
- Placeholder scan: plan must contain no red-flag placeholder phrases or open-ended validation instructions.
- Type consistency: `RuntimeSettings`, `RuntimeContext`, `ResolvedProvider`, `ProviderProfile`, `SecretResolver`, `DoctorCheck`, and `ModelAssetStatus` names match across tasks.
- Persistence boundary: runtime context appears only in plugin request dictionaries and is not written to step run records, workflow state, artifact metadata, or event logs.
- Rollback path: existing `OPENBBQ_LLM_API_KEY` and `OPENBBQ_LLM_BASE_URL` flows remain tested.
