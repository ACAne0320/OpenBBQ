# Runtime Settings Boundary Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split runtime settings raw parsing from public settings orchestration while preserving runtime configuration behavior before desktop UI integration.

**Architecture:** Add `openbbq.runtime.settings_parser` as the raw TOML parsing and normalization boundary. Keep `openbbq.runtime.settings` as the stable public facade for path selection, file load orchestration, user database provider merging, TOML rendering, and writes. Keep Pydantic runtime models as the final validation boundary and reuse `model_payload()` for trivial JSON payload methods.

**Tech Stack:** Python 3.11, Pydantic v2, TOML via `tomllib`, pytest, Ruff, uv.

---

## File Structure

- Create `src/openbbq/runtime/settings_parser.py`
  - Own raw TOML mapping loading and raw runtime settings parsing.
  - Construct validated `RuntimeSettings` from file-backed raw settings only.
  - Keep private helper functions for mapping/string/path/provider field validation.
- Modify `src/openbbq/runtime/settings.py`
  - Keep public constants and functions.
  - Delegate raw parsing to `settings_parser.py`.
  - Keep user database provider merge and TOML writer here.
- Modify `src/openbbq/runtime/models.py`
  - Reuse `openbbq.domain.base.model_payload()` in trivial payload methods.
  - Keep `RuntimeContext.request_payload()` custom because it changes shape and redacts path types intentionally.
- Modify `tests/test_runtime_settings.py`
  - Add parser boundary tests, database provider precedence coverage, and payload helper delegation coverage.
- Modify `tests/test_package_layout.py`
  - Add `openbbq.runtime.settings_parser` to import coverage.
- Modify `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  - Mark the runtime settings audit item complete after implementation and verification.

---

### Task 1: Extract Runtime Settings Parser Boundary

**Files:**
- Create: `src/openbbq/runtime/settings_parser.py`
- Modify: `src/openbbq/runtime/settings.py`
- Modify: `tests/test_runtime_settings.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Write parser boundary tests**

Modify the imports at the top of `tests/test_runtime_settings.py` to include the new parser functions and user database:

```python
import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.errors import ValidationError
from openbbq.runtime.models import CacheSettings, ProviderProfile, RuntimeSettings
from openbbq.runtime.settings import (
    DEFAULT_CACHE_ROOT,
    load_runtime_settings,
    runtime_settings_to_toml,
    with_provider_profile,
)
from openbbq.runtime.settings_parser import parse_runtime_settings
from openbbq.runtime.user_db import UserRuntimeDatabase
```

Add these tests after `test_load_runtime_settings_from_toml`:

```python
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
```

Modify `tests/test_package_layout.py` by adding the new module string to the `modules` list in `test_new_package_modules_are_importable`:

```python
        "openbbq.runtime.settings_parser",
```

- [ ] **Step 2: Run parser boundary tests and confirm they fail for the expected reason**

Run:

```bash
uv run pytest tests/test_runtime_settings.py::test_parse_runtime_settings_does_not_open_user_database tests/test_runtime_settings.py::test_load_runtime_settings_merges_user_database_provider_over_file_provider tests/test_package_layout.py::test_new_package_modules_are_importable -q
```

Expected: FAIL because `openbbq.runtime.settings_parser` does not exist yet.

- [ ] **Step 3: Create `settings_parser.py`**

Create `src/openbbq/runtime/settings_parser.py` with this content:

```python
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
    PROVIDER_NAME_PATTERN,
    ProviderMap,
    ProviderProfile,
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
    faster_whisper = _faster_whisper_settings(raw, cache_root, config_path.parent)
    providers = _provider_profiles(raw)
    try:
        return RuntimeSettings(
            version=1,
            config_path=config_path,
            cache=CacheSettings(root=cache_root),
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
```

- [ ] **Step 4: Reduce `settings.py` to the public orchestration facade**

Replace `src/openbbq/runtime/settings.py` with this content:

```python
from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from openbbq.runtime.models import ProviderProfile, RuntimeSettings
from openbbq.runtime.settings_parser import (
    DEFAULT_CACHE_ROOT,
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
    env = os.environ if env is None else env
    path = (
        Path(config_path).expanduser().resolve()
        if config_path is not None
        else default_user_config_path(env)
    )
    settings = parse_runtime_settings(
        load_toml_mapping(path),
        config_path=path,
        env=env,
    )
    providers = dict(settings.providers)
    providers.update(
        {provider.name: provider for provider in UserRuntimeDatabase(env=env).list_providers()}
    )
    return settings.model_copy(update={"providers": providers})


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


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
```

- [ ] **Step 5: Run focused parser and runtime tests**

Run:

```bash
uv run pytest tests/test_runtime_settings.py tests/test_runtime_context.py tests/test_runtime_cli.py tests/test_application_runtime_diagnostics.py tests/test_package_layout.py::test_new_package_modules_are_importable
```

Expected: PASS.

- [ ] **Step 6: Commit parser extraction**

Run:

```bash
git add src/openbbq/runtime/settings_parser.py src/openbbq/runtime/settings.py tests/test_runtime_settings.py tests/test_package_layout.py
git commit -m "refactor: Split runtime settings parser"
```

---

### Task 2: Reuse Runtime Model Payload Serializer

**Files:**
- Modify: `src/openbbq/runtime/models.py`
- Modify: `tests/test_runtime_settings.py`

- [ ] **Step 1: Write payload helper delegation test**

Modify the imports at the top of `tests/test_runtime_settings.py` to include `Path`, the runtime models module, and the runtime status/check models:

```python
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
```

Keep the existing imports from `openbbq.runtime.settings`, `openbbq.runtime.settings_parser`, and `openbbq.runtime.user_db`.

Add this test near the model-specific tests:

```python
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
```

- [ ] **Step 2: Run the payload helper test and confirm it fails**

Run:

```bash
uv run pytest tests/test_runtime_settings.py::test_runtime_model_payload_methods_delegate_to_model_payload -q
```

Expected: FAIL because runtime model payload methods still call `self.model_dump(mode="json")` directly.

- [ ] **Step 3: Update runtime models to use `model_payload()`**

In `src/openbbq/runtime/models.py`, change the domain import to:

```python
from openbbq.domain.base import JsonObject, OpenBBQModel, model_payload
```

Update these methods:

```python
    def public_dict(self) -> JsonObject:
        return model_payload(self)
```

Apply that method body to `ProviderProfile.public_dict()`, `RuntimeSettings.public_dict()`, and `ModelAssetStatus.public_dict()`.

Update `ResolvedProvider.request_payload()`:

```python
    def request_payload(self) -> JsonObject:
        return model_payload(self)
```

Update `DoctorCheck.public_dict()`:

```python
    def public_dict(self) -> JsonObject:
        return model_payload(self)
```

- [ ] **Step 4: Run runtime settings tests**

Run:

```bash
uv run pytest tests/test_runtime_settings.py tests/test_runtime_context.py tests/test_runtime_doctor.py
```

Expected: PASS.

- [ ] **Step 5: Commit payload cleanup**

Run:

```bash
git add src/openbbq/runtime/models.py tests/test_runtime_settings.py
git commit -m "refactor: Reuse runtime model payload helper"
```

---

### Task 3: Update Audit Tracking And Verify

**Files:**
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`

- [ ] **Step 1: Update audit closure status**

In `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`, add this item to the `### Done` list after the built-in LLM item:

```markdown
- **P2: Runtime settings validation is split between model validators and
  loader helpers**
  - Completed by adding `src/openbbq/runtime/settings_parser.py` as the raw
    TOML parsing boundary, keeping `src/openbbq/runtime/settings.py` as the
    public load/write orchestration facade, preserving user database provider
    precedence, and reusing `model_payload()` for trivial runtime payload
    methods.
```

Remove this item from the `### Remaining` list:

```markdown
- **P2: Runtime settings validation is split between model validators and
  loader helpers**
```

Change the first item under `## Execution strategy` from runtime settings to config loader cleanup, so the list begins:

```markdown
1. **Config loader phase cleanup**
   - Split parsing, path normalization, Pydantic model construction, and
     workflow validation helpers without changing existing exception messages.
```

Replace the `## Next slice` paragraph with:

```markdown
The next implementation slice should be **Config loader phase cleanup**. It
should split parsing, path normalization, Pydantic model construction, and
workflow validation helpers without changing existing exception messages.
```

- [ ] **Step 2: Run full verification**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected:

- `uv run pytest`: PASS with all current tests passing and existing skips only.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS.

- [ ] **Step 3: Commit audit tracking update**

Run:

```bash
git add docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
git commit -m "docs: Track runtime settings cleanup completion"
```

---

## Final Review

After all tasks are complete, run:

```bash
git status -sb
git log --oneline -5
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected:

- Worktree is clean.
- The latest commits cover parser extraction, payload helper cleanup, and audit tracking.
- Full test and Ruff verification pass.
