# Desktop Settings MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the desktop Settings MVP so users can configure the default LLM provider and faster-whisper ASR defaults, then start quickstart subtitle tasks using those runtime defaults.

**Architecture:** Extend the Python runtime settings schema with explicit defaults, add focused runtime write routes, and make quickstart job creation resolve default provider/model values from runtime settings. Expose these routes through Electron IPC and render a sectioned Settings page in React while keeping workflow editing free of runtime provider/model controls.

**Tech Stack:** Python, Pydantic, FastAPI, pytest, TypeScript, Electron IPC, React, Vitest, Tailwind CSS.

---

## Scope Check

The approved spec covers one integrated feature slice: runtime settings contracts plus the desktop Settings UI that consumes them. This plan keeps plugin-driven workflow editing, ASR downloads, i18n, provider presets, and prompt/glossary sections out of scope.

## File Structure

Backend runtime settings:

- `src/openbbq/runtime/models.py`: add `RuntimeDefaults` and expose defaults on `RuntimeSettings`.
- `src/openbbq/runtime/settings_parser.py`: parse `[defaults]`.
- `src/openbbq/runtime/settings.py`: render `[defaults]`, add helper functions for runtime defaults and faster-whisper settings.
- `src/openbbq/application/runtime.py`: add service-layer request/result methods for defaults and faster-whisper updates.
- `src/openbbq/api/schemas.py`: add API request/response models and make quickstart runtime fields optional.
- `src/openbbq/api/routes/runtime.py`: add `PUT /runtime/defaults` and `PUT /runtime/models/faster-whisper`.

Backend quickstart:

- `src/openbbq/application/quickstart.py`: resolve omitted runtime fields from `RuntimeSettings`.
- `src/openbbq/api/routes/quickstart.py`: pass optional runtime fields through unchanged.
- `src/openbbq/api/task_history.py`: allow persisted task records to reflect runtime-resolved provider/model values if route bodies omit those fields.

Desktop bridge:

- `desktop/electron/apiTypes.ts`: add runtime settings DTOs.
- `desktop/electron/http.ts`: allow `PUT`.
- `desktop/electron/ipc.ts`: add runtime settings handlers and use sidecar defaults for quickstart runtime fields.
- `desktop/electron/preload.cts`: expose Settings IPC methods.
- `desktop/src/global.d.ts`: type the new preload methods.
- `desktop/src/lib/types.ts`: add renderer-facing runtime settings models.
- `desktop/src/lib/apiClient.ts`: extend `OpenBBQClient` and mock runtime behavior.
- `desktop/src/lib/desktopClient.ts`: forward runtime methods.

Renderer UI:

- `desktop/src/components/Settings.tsx`: new section-navigation Settings page.
- `desktop/src/components/__tests__/Settings.test.tsx`: component tests for section switching, provider save/default, ASR defaults, diagnostics, and advanced.
- `desktop/src/App.tsx`: add Settings screen and navigation behavior.
- `desktop/src/__tests__/App.test.tsx`: verify Settings opens from the global nav.

## Task 1: Runtime Defaults Schema And Writer Helpers

**Files:**
- Modify: `src/openbbq/runtime/models.py`
- Modify: `src/openbbq/runtime/settings_parser.py`
- Modify: `src/openbbq/runtime/settings.py`
- Test: `tests/test_runtime_settings.py`

- [ ] **Step 1: Write failing runtime settings tests**

Add these tests to `tests/test_runtime_settings.py` near the existing load/write tests:

```python
from openbbq.runtime.models import FasterWhisperSettings, RuntimeDefaults
from openbbq.runtime.settings import (
    with_faster_whisper_settings,
    with_runtime_defaults,
)


def test_load_runtime_settings_includes_default_runtime_providers(tmp_path):
    settings = load_runtime_settings(config_path=tmp_path / "missing.toml", env={})

    assert settings.defaults.llm_provider == "openai-compatible"
    assert settings.defaults.asr_provider == "faster-whisper"


def test_load_runtime_settings_reads_defaults_table(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
version = 1

[defaults]
llm_provider = "local-gateway"
asr_provider = "faster-whisper"
""",
        encoding="utf-8",
    )

    settings = load_runtime_settings(config_path=config, env={})

    assert settings.defaults.llm_provider == "local-gateway"
    assert settings.defaults.asr_provider == "faster-whisper"


def test_runtime_settings_to_toml_writes_defaults_and_faster_whisper(tmp_path):
    settings = RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        defaults=RuntimeDefaults(llm_provider="openai-compatible", asr_provider="faster-whisper"),
        models=runtime_models.ModelsSettings(
            faster_whisper=FasterWhisperSettings(
                cache_dir=tmp_path / "models",
                default_model="small",
                default_device="cpu",
                default_compute_type="int8",
            )
        ),
    )

    rendered = runtime_settings_to_toml(settings)

    assert "[defaults]" in rendered
    assert 'llm_provider = "openai-compatible"' in rendered
    assert 'asr_provider = "faster-whisper"' in rendered
    assert "[models.faster_whisper]" in rendered
    assert 'default_model = "small"' in rendered


def test_runtime_settings_copy_helpers_are_immutable(tmp_path):
    settings = RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
    )

    with_defaults = with_runtime_defaults(
        settings,
        RuntimeDefaults(llm_provider="local-gateway", asr_provider="faster-whisper"),
    )
    with_asr = with_faster_whisper_settings(
        with_defaults,
        FasterWhisperSettings(
            cache_dir=tmp_path / "fw-cache",
            default_model="medium",
            default_device="cuda",
            default_compute_type="float16",
        ),
    )

    assert settings.defaults.llm_provider == "openai-compatible"
    assert with_defaults.defaults.llm_provider == "local-gateway"
    assert with_asr.models.faster_whisper.default_model == "medium"
    assert with_defaults.models.faster_whisper.default_model == "base"
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run pytest tests/test_runtime_settings.py -q
```

Expected: failure for missing `RuntimeDefaults`, `defaults`, `with_runtime_defaults`, or `with_faster_whisper_settings`.

- [ ] **Step 3: Add runtime defaults model**

In `src/openbbq/runtime/models.py`, add `RuntimeDefaults` above `RuntimeSettings` and include it in `RuntimeSettings`:

```python
class RuntimeDefaults(OpenBBQModel):
    llm_provider: str = "openai-compatible"
    asr_provider: str = "faster-whisper"

    @field_validator("llm_provider", "asr_provider")
    @classmethod
    def valid_provider_name(cls, value: str) -> str:
        if not value or PROVIDER_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("Provider names must use only letters, digits, '_' or '-'")
        return value


class RuntimeSettings(OpenBBQModel):
    version: int
    config_path: Path
    cache: CacheSettings
    defaults: RuntimeDefaults = Field(default_factory=RuntimeDefaults)
    providers: ProviderMap = Field(default_factory=dict)
    models: ModelsSettings | None = None
```

Update `src/openbbq/runtime/__init__.py` to export `RuntimeDefaults`.

- [ ] **Step 4: Parse defaults from TOML**

In `src/openbbq/runtime/settings_parser.py`, import `RuntimeDefaults` and add:

```python
def _runtime_defaults(raw: JsonObject) -> RuntimeDefaults:
    defaults_raw = _optional_mapping(raw.get("defaults"), "defaults")
    try:
        return RuntimeDefaults(
            llm_provider=_required_string(
                defaults_raw.get("llm_provider", "openai-compatible"),
                "defaults.llm_provider",
            ),
            asr_provider=_required_string(
                defaults_raw.get("asr_provider", "faster-whisper"),
                "defaults.asr_provider",
            ),
        )
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error("defaults", exc)) from exc
```

Call it from `parse_runtime_settings`:

```python
defaults = _runtime_defaults(raw)
...
return RuntimeSettings(
    version=1,
    config_path=config_path,
    cache=CacheSettings(root=cache_root),
    defaults=defaults,
    providers=providers,
    models=ModelsSettings(faster_whisper=faster_whisper),
)
```

- [ ] **Step 5: Write defaults and add copy helpers**

In `src/openbbq/runtime/settings.py`, import `FasterWhisperSettings`, `ModelsSettings`, and `RuntimeDefaults`. Update `runtime_settings_to_toml` to write the defaults block immediately after `version = 1`:

```python
lines = [
    "version = 1",
    "",
    "[defaults]",
    f'llm_provider = "{_escape_toml(settings.defaults.llm_provider)}"',
    f'asr_provider = "{_escape_toml(settings.defaults.asr_provider)}"',
    "",
]
```

Add helpers:

```python
def with_runtime_defaults(
    settings: RuntimeSettings,
    defaults: RuntimeDefaults,
) -> RuntimeSettings:
    return settings.model_copy(update={"defaults": defaults})


def with_faster_whisper_settings(
    settings: RuntimeSettings,
    faster_whisper: FasterWhisperSettings,
) -> RuntimeSettings:
    return settings.model_copy(update={"models": ModelsSettings(faster_whisper=faster_whisper)})
```

- [ ] **Step 6: Run runtime settings tests**

Run:

```bash
uv run pytest tests/test_runtime_settings.py -q
```

Expected: all tests in `tests/test_runtime_settings.py` pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/openbbq/runtime/__init__.py src/openbbq/runtime/models.py src/openbbq/runtime/settings_parser.py src/openbbq/runtime/settings.py tests/test_runtime_settings.py
git commit -m "feat: add runtime provider defaults"
```

## Task 2: Runtime Defaults And ASR API Routes

**Files:**
- Modify: `src/openbbq/application/runtime.py`
- Modify: `src/openbbq/api/schemas.py`
- Modify: `src/openbbq/api/routes/runtime.py`
- Modify: `src/openbbq/runtime/models_assets.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Write failing API route tests**

Extend `test_runtime_routes` or add a new test in `tests/test_api_projects_plugins_runtime.py`:

```python
def test_runtime_defaults_and_faster_whisper_routes(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project)

    defaults = client.put(
        "/runtime/defaults",
        headers=headers,
        json={"llm_provider": "openai-compatible", "asr_provider": "faster-whisper"},
    )
    asr = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json={
            "cache_dir": str(tmp_path / "fw-cache"),
            "default_model": "small",
            "default_device": "cpu",
            "default_compute_type": "int8",
        },
    )
    settings = client.get("/runtime/settings", headers=headers)
    models = client.get("/runtime/models", headers=headers)

    assert defaults.status_code == 200
    assert defaults.json()["data"]["settings"]["defaults"]["llm_provider"] == "openai-compatible"
    assert asr.status_code == 200
    assert settings.json()["data"]["settings"]["models"]["faster_whisper"]["default_model"] == "small"
    assert models.json()["data"]["models"][0]["model"] == "small"
    assert models.json()["data"]["models"][0]["cache_dir"] == str((tmp_path / "fw-cache").resolve())
```

Update the existing auth route test so it uses `openai-compatible`:

```python
provider = client.put(
    "/runtime/providers/openai-compatible/auth",
    headers=headers,
    json={
        "type": "openai_compatible",
        "api_key_ref": "env:OPENBBQ_LLM_API_KEY",
        "default_chat_model": "gpt-4o-mini",
    },
)
check = client.get("/runtime/providers/openai-compatible/check", headers=headers)
assert provider.json()["data"]["provider"]["name"] == "openai-compatible"
```

- [ ] **Step 2: Run the failing API tests**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_defaults_and_faster_whisper_routes -q
```

Expected: failure for missing routes or request models.

- [ ] **Step 3: Add service-layer request/result models**

In `src/openbbq/application/runtime.py`, import `FasterWhisperSettings`, `RuntimeDefaults`, `with_faster_whisper_settings`, and `with_runtime_defaults`. Add:

```python
class RuntimeDefaultsSetRequest(OpenBBQModel):
    llm_provider: str
    asr_provider: str = "faster-whisper"


class RuntimeSettingsSetResult(OpenBBQModel):
    settings: RuntimeSettings
    config_path: Path


class FasterWhisperSetRequest(OpenBBQModel):
    cache_dir: Path
    default_model: str
    default_device: str
    default_compute_type: str


def defaults_set(request: RuntimeDefaultsSetRequest) -> RuntimeSettingsSetResult:
    defaults = RuntimeDefaults(
        llm_provider=request.llm_provider,
        asr_provider=request.asr_provider,
    )
    settings = load_runtime_settings()
    updated = with_runtime_defaults(settings, defaults)
    write_runtime_settings(updated)
    return RuntimeSettingsSetResult(settings=updated, config_path=updated.config_path)


def faster_whisper_set(request: FasterWhisperSetRequest) -> RuntimeSettingsSetResult:
    settings = load_runtime_settings()
    faster_whisper = FasterWhisperSettings(
        cache_dir=request.cache_dir.expanduser().resolve(),
        default_model=request.default_model,
        default_device=request.default_device,
        default_compute_type=request.default_compute_type,
    )
    updated = with_faster_whisper_settings(settings, faster_whisper)
    write_runtime_settings(updated)
    return RuntimeSettingsSetResult(settings=updated, config_path=updated.config_path)
```

- [ ] **Step 4: Add API schemas**

In `src/openbbq/api/schemas.py`, add:

```python
class RuntimeDefaultsSetRequest(OpenBBQModel):
    llm_provider: str
    asr_provider: str = "faster-whisper"


class RuntimeSettingsSetData(OpenBBQModel):
    settings: RuntimeSettings
    config_path: Path


class FasterWhisperSettingsSetRequest(OpenBBQModel):
    cache_dir: Path
    default_model: str
    default_device: str
    default_compute_type: str
```

- [ ] **Step 5: Add runtime routes**

In `src/openbbq/api/routes/runtime.py`, import the new schema and service names. Add:

```python
@router.put("/runtime/defaults", response_model=ApiSuccess[RuntimeSettingsSetData])
def put_runtime_defaults(
    body: RuntimeDefaultsSetRequest,
) -> ApiSuccess[RuntimeSettingsSetData]:
    result = defaults_set(
        ApplicationRuntimeDefaultsSetRequest(
            llm_provider=body.llm_provider,
            asr_provider=body.asr_provider,
        )
    )
    return ApiSuccess(
        data=RuntimeSettingsSetData(settings=result.settings, config_path=result.config_path)
    )


@router.put("/runtime/models/faster-whisper", response_model=ApiSuccess[RuntimeSettingsSetData])
def put_faster_whisper_settings(
    body: FasterWhisperSettingsSetRequest,
) -> ApiSuccess[RuntimeSettingsSetData]:
    result = faster_whisper_set(
        ApplicationFasterWhisperSetRequest(
            cache_dir=body.cache_dir,
            default_model=body.default_model,
            default_device=body.default_device,
            default_compute_type=body.default_compute_type,
        )
    )
    return ApiSuccess(
        data=RuntimeSettingsSetData(settings=result.settings, config_path=result.config_path)
    )
```

Use import aliases such as `ApplicationRuntimeDefaultsSetRequest` to avoid name collisions with API schema classes.

- [ ] **Step 6: Tighten model status to selected config**

In `src/openbbq/runtime/models_assets.py`, keep `provider="faster_whisper"` but ensure the result uses the configured model and cache directory:

```python
model_settings = (
    settings.models.faster_whisper
    if settings.models is not None
    else FasterWhisperSettings(
        cache_dir=settings.cache.root / "models" / "faster-whisper",
        default_model="base",
        default_device="cpu",
        default_compute_type="int8",
    )
)
cache_dir = model_settings.cache_dir
model = model_settings.default_model
model_path = cache_dir / model
present = model_path.exists() or cache_dir.exists()
```

Use `present = model_path.exists()` if the worker confirms faster-whisper stores each model in a named child directory in the supported version. If not, preserve `cache_dir.exists()` and add a short code comment that the MVP reports cache presence, not verified model integrity.

- [ ] **Step 7: Run API runtime tests**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_routes tests/test_api_projects_plugins_runtime.py::test_runtime_auth_and_secret_routes tests/test_api_projects_plugins_runtime.py::test_runtime_defaults_and_faster_whisper_routes -q
```

Expected: selected API tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/openbbq/application/runtime.py src/openbbq/api/schemas.py src/openbbq/api/routes/runtime.py src/openbbq/runtime/models_assets.py tests/test_api_projects_plugins_runtime.py
git commit -m "feat: expose runtime settings updates"
```

## Task 3: Quickstart Uses Runtime Defaults

**Files:**
- Modify: `src/openbbq/api/schemas.py`
- Modify: `src/openbbq/api/routes/quickstart.py`
- Modify: `src/openbbq/api/task_history.py`
- Modify: `src/openbbq/application/quickstart.py`
- Test: `tests/test_application_quickstart.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Write failing quickstart default tests**

Add to `tests/test_application_quickstart.py`:

```python
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeDefaults,
    RuntimeSettings,
)


def runtime_settings(tmp_path):
    return RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        defaults=RuntimeDefaults(llm_provider="openai-compatible", asr_provider="faster-whisper"),
        providers={
            "openai-compatible": ProviderProfile(
                name="openai-compatible",
                type="openai_compatible",
                api_key="env:OPENBBQ_LLM_API_KEY",
                default_chat_model="gpt-4o-mini",
            )
        },
        models=ModelsSettings(
            faster_whisper=FasterWhisperSettings(
                cache_dir=tmp_path / "fw-cache",
                default_model="small",
                default_device="cpu",
                default_compute_type="int8",
            )
        ),
    )


def test_youtube_subtitle_job_uses_runtime_defaults_when_request_omits_runtime_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        lambda: runtime_settings(tmp_path),
    )
    monkeypatch.setattr(
        "openbbq.application.quickstart.create_run",
        lambda request, execute_inline=False: RunRecord(
            id="run_youtube",
            workflow_id=request.workflow_id,
            mode="start",
            status="queued",
            project_root=request.project_root,
            config_path=request.config_path,
            plugin_paths=request.plugin_paths,
            created_by=request.created_by,
        ),
    )

    result = create_youtube_subtitle_job(
        YouTubeSubtitleJobRequest(
            workspace_root=tmp_path,
            url="https://www.youtube.com/watch?v=demo",
            source_lang="en",
            target_lang="zh",
            provider=None,
            model=None,
            asr_model=None,
            asr_device=None,
            asr_compute_type=None,
            quality="best",
            auth="auto",
        )
    )

    rendered = yaml.safe_load(result.generated_config_path.read_text(encoding="utf-8"))
    steps = _workflow_steps(rendered, "youtube-to-srt")

    assert steps["correct"]["parameters"]["provider"] == "openai-compatible"
    assert steps["correct"]["parameters"]["model"] == "gpt-4o-mini"
    assert steps["translate"]["parameters"]["provider"] == "openai-compatible"
    assert steps["translate"]["parameters"]["model"] == "gpt-4o-mini"
    assert steps["transcribe"]["parameters"]["model"] == "small"
    assert steps["transcribe"]["parameters"]["device"] == "cpu"


def test_quickstart_fails_when_default_llm_provider_is_missing(tmp_path, monkeypatch):
    settings = runtime_settings(tmp_path).model_copy(update={"providers": {}})
    monkeypatch.setattr("openbbq.application.quickstart.load_runtime_settings", lambda: settings)

    with pytest.raises(ValidationError, match="Default LLM provider 'openai-compatible' is not configured"):
        create_youtube_subtitle_job(
            YouTubeSubtitleJobRequest(
                workspace_root=tmp_path,
                url="https://www.youtube.com/watch?v=demo",
                source_lang="en",
                target_lang="zh",
                provider=None,
                model=None,
                asr_model=None,
                asr_device=None,
                asr_compute_type=None,
                quality="best",
                auth="auto",
            )
        )
```

Ensure `pytest` and `ValidationError` are imported in this test module.

- [ ] **Step 2: Run the failing quickstart tests**

Run:

```bash
uv run pytest tests/test_application_quickstart.py::test_youtube_subtitle_job_uses_runtime_defaults_when_request_omits_runtime_fields tests/test_application_quickstart.py::test_quickstart_fails_when_default_llm_provider_is_missing -q
```

Expected: failure because request models still default provider to `"openai"` or default resolution is absent.

- [ ] **Step 3: Make quickstart request runtime fields optional**

In `src/openbbq/application/quickstart.py`, change both request classes:

```python
class LocalSubtitleJobRequest(OpenBBQModel):
    workspace_root: Path
    input_path: Path
    source_lang: str
    target_lang: str
    provider: str | None = None
    model: str | None = None
    asr_model: str | None = None
    asr_device: str | None = None
    asr_compute_type: str | None = None
```

Do the same for `YouTubeSubtitleJobRequest`. In `src/openbbq/api/schemas.py`, change `SubtitleLocalJobRequest.provider` and `SubtitleYouTubeJobRequest.provider` from default `"openai"` to `str | None = None`.

- [ ] **Step 4: Resolve LLM and ASR defaults in the application layer**

In `src/openbbq/application/quickstart.py`, import `ValidationError` and `SecretResolver`. Add:

```python
class _ResolvedQuickstartDefaults(OpenBBQModel):
    provider: str
    model: str | None
    asr_model: str
    asr_device: str
    asr_compute_type: str


def _runtime_defaults_for_request(
    *,
    provider: str | None,
    model: str | None,
    asr_model: str | None,
    asr_device: str | None,
    asr_compute_type: str | None,
) -> _ResolvedQuickstartDefaults:
    settings = load_runtime_settings()
    provider_name = provider or settings.defaults.llm_provider
    profile = settings.providers.get(provider_name)
    if profile is None:
        raise ValidationError(f"Default LLM provider '{provider_name}' is not configured.")
    if profile.api_key is None:
        raise ValidationError(f"Default LLM provider '{provider_name}' does not define an API key.")
    resolved_secret = SecretResolver().resolve(profile.api_key)
    if not resolved_secret.resolved:
        raise ValidationError(
            resolved_secret.public.error
            or f"Default LLM provider '{provider_name}' API key is not resolved."
        )
    if settings.defaults.asr_provider != "faster-whisper":
        raise ValidationError(
            f"Default ASR provider '{settings.defaults.asr_provider}' is not supported by this quickstart."
        )
    faster_whisper = settings.models.faster_whisper
    return _ResolvedQuickstartDefaults(
        provider=provider_name,
        model=model or profile.default_chat_model,
        asr_model=asr_model or faster_whisper.default_model,
        asr_device=asr_device or faster_whisper.default_device,
        asr_compute_type=asr_compute_type or faster_whisper.default_compute_type,
    )
```

At the start of `create_local_subtitle_job` and `create_youtube_subtitle_job`, call this helper and pass the resolved values into `write_*_subtitle_workflow`.

- [ ] **Step 5: Update quickstart API route task history inputs**

In `src/openbbq/api/routes/quickstart.py`, after `result = create_*_subtitle_job(...)`, read the generated workflow config or return resolved runtime fields from the application result before recording task history. Prefer adding these fields to `SubtitleJobResult`:

```python
class SubtitleJobResult(OpenBBQModel):
    generated_project_root: Path
    generated_config_path: Path
    workflow_id: str
    run_id: str
    output_path: Path | None = None
    source_artifact_id: str | None = None
    provider: str
    model: str | None = None
    asr_model: str
    asr_device: str
    asr_compute_type: str
```

Then update `openbbq.api.task_history` helpers to record `result.provider`, `result.model`, `result.asr_model`, `result.asr_device`, and `result.asr_compute_type` when the body omits them. A focused helper keeps this readable:

```python
def _resolved_common_settings(body, result: SubtitleJobResult) -> dict[str, Any]:
    return {
        "source_lang": body.source_lang,
        "target_lang": body.target_lang,
        "provider": result.provider,
        "model": result.model,
        "asr_model": result.asr_model,
        "asr_device": result.asr_device,
        "asr_compute_type": result.asr_compute_type,
    }
```

Use that helper in both local and YouTube task record builders.

- [ ] **Step 6: Run quickstart tests**

Run:

```bash
uv run pytest tests/test_application_quickstart.py tests/test_api_projects_plugins_runtime.py::test_quickstart_subtitle_routes_return_generated_job_metadata -q
```

Expected: selected tests pass after updating test fixtures to include resolved result fields where fake `SubtitleJobResult` values are constructed.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/openbbq/application/quickstart.py src/openbbq/api/schemas.py src/openbbq/api/routes/quickstart.py src/openbbq/api/task_history.py tests/test_application_quickstart.py tests/test_api_projects_plugins_runtime.py
git commit -m "feat: use runtime defaults for quickstart tasks"
```

## Task 4: Electron Runtime Settings Bridge

**Files:**
- Modify: `desktop/electron/apiTypes.ts`
- Modify: `desktop/electron/http.ts`
- Modify: `desktop/electron/ipc.ts`
- Modify: `desktop/electron/preload.cts`
- Modify: `desktop/electron/workflowMapping.ts`
- Modify: `desktop/src/global.d.ts`
- Modify: `desktop/src/lib/apiClient.ts`
- Modify: `desktop/src/lib/desktopClient.ts`
- Modify: `desktop/src/lib/types.ts`
- Test: `desktop/electron/__tests__/ipc.test.ts`
- Test: `desktop/electron/__tests__/workflowMapping.test.ts`
- Test: `desktop/src/lib/desktopClient.test.ts`

- [ ] **Step 1: Write failing workflow mapping tests**

Update `desktop/electron/__tests__/workflowMapping.test.ts` so local and remote quickstart bodies no longer contain runtime defaults:

```ts
expect(request).toEqual({
  route: "/quickstart/subtitle/local",
  body: {
    input_path: "C:/video/sample.mp4",
    source_lang: "en",
    target_lang: "zh"
  }
});
expect(request.body).not.toHaveProperty("provider");
expect(request.body).not.toHaveProperty("model");
expect(request.body).not.toHaveProperty("asr_model");
```

For the remote test:

```ts
expect(request.body).toMatchObject({
  url: "https://example.test/watch",
  source_lang: "en",
  target_lang: "zh",
  quality: "best[ext=mp4][height<=720]/best[height<=720]/best",
  auth: "auto"
});
expect(request.body).not.toHaveProperty("provider");
expect(request.body).not.toHaveProperty("asr_model");
```

- [ ] **Step 2: Write failing IPC tests for runtime settings**

Add to `desktop/electron/__tests__/ipc.test.ts`:

```ts
it("loads runtime settings through the sidecar", async () => {
  const fetchImpl = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        ok: true,
        data: {
          settings: {
            version: 1,
            config_path: "C:/Users/alex/.openbbq/config.toml",
            cache: { root: "C:/Users/alex/.cache/openbbq" },
            defaults: { llm_provider: "openai-compatible", asr_provider: "faster-whisper" },
            providers: {},
            models: {
              faster_whisper: {
                cache_dir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
                default_model: "base",
                default_device: "cpu",
                default_compute_type: "int8"
              }
            }
          }
        }
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    )
  );
  vi.stubGlobal("fetch", fetchImpl);
  const { getRuntimeSettings } = await import("../ipc");

  await expect(getRuntimeSettings(sidecar)).resolves.toMatchObject({
    defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" }
  });
  expect(fetchImpl).toHaveBeenCalledWith(
    "http://127.0.0.1:53124/runtime/settings",
    expect.objectContaining({ method: "GET" })
  );
});

it("saves faster-whisper defaults through the sidecar", async () => {
  const fetchImpl = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ ok: true, data: { settings: {}, config_path: "config.toml" } }), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    })
  );
  vi.stubGlobal("fetch", fetchImpl);
  const { saveFasterWhisperDefaults } = await import("../ipc");

  await saveFasterWhisperDefaults(sidecar, {
    cacheDir: "C:/models/fw",
    defaultModel: "small",
    defaultDevice: "cpu",
    defaultComputeType: "int8"
  });

  expect(fetchImpl).toHaveBeenCalledWith(
    "http://127.0.0.1:53124/runtime/models/faster-whisper",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({
        cache_dir: "C:/models/fw",
        default_model: "small",
        default_device: "cpu",
        default_compute_type: "int8"
      })
    })
  );
});
```

- [ ] **Step 3: Run the failing desktop bridge tests**

Run:

```bash
cd desktop
pnpm test -- workflowMapping.test.ts ipc.test.ts desktopClient.test.ts
```

Expected: failures for missing methods, unsupported `PUT`, and hard-coded runtime fields.

- [ ] **Step 4: Add DTOs and allow PUT**

In `desktop/electron/http.ts`, widen `RequestOptions.method`:

```ts
type RequestOptions = {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
};
```

In `desktop/electron/apiTypes.ts`, add DTOs:

```ts
export type ApiRuntimeSettings = {
  version: number;
  config_path: string;
  cache: { root: string };
  defaults: { llm_provider: string; asr_provider: string };
  providers: Record<string, ApiProviderProfile>;
  models: {
    faster_whisper: {
      cache_dir: string;
      default_model: string;
      default_device: string;
      default_compute_type: string;
    };
  };
};

export type ApiProviderProfile = {
  name: string;
  type: "openai_compatible";
  base_url?: string | null;
  api_key?: string | null;
  default_chat_model?: string | null;
  display_name?: string | null;
};

export type ApiSecretCheck = {
  reference: string;
  resolved: boolean;
  display: string;
  value_preview?: string | null;
  error?: string | null;
};

export type ApiDoctorCheck = {
  id: string;
  status: string;
  severity: string;
  message: string;
};

export type ApiModelAssetStatus = {
  provider: string;
  model: string;
  cache_dir: string;
  present: boolean;
  size_bytes: number;
  error?: string | null;
};
```

- [ ] **Step 5: Add renderer-facing types**

In `desktop/src/lib/types.ts`, add:

```ts
export type RuntimeSettingsModel = {
  configPath: string;
  cacheRoot: string;
  defaults: { llmProvider: string; asrProvider: string };
  llmProviders: LlmProviderModel[];
  fasterWhisper: FasterWhisperSettingsModel;
};

export type LlmProviderModel = {
  name: string;
  type: "openai_compatible";
  baseUrl: string | null;
  apiKeyRef: string | null;
  defaultChatModel: string | null;
  displayName: string | null;
};

export type FasterWhisperSettingsModel = {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
};

export type RuntimeModelStatus = {
  provider: string;
  model: string;
  cacheDir: string;
  present: boolean;
  sizeBytes: number;
  error: string | null;
};

export type SecretStatus = {
  reference: string;
  resolved: boolean;
  display: string;
  valuePreview: string | null;
  error: string | null;
};

export type DiagnosticCheck = {
  id: string;
  status: string;
  severity: string;
  message: string;
};

export type SaveRuntimeDefaultsInput = {
  llmProvider: string;
  asrProvider: string;
};

export type SaveLlmProviderInput = {
  name: string;
  type: "openai_compatible";
  baseUrl: string | null;
  defaultChatModel: string | null;
  secretValue: string | null;
  apiKeyRef: string | null;
  displayName: string | null;
};

export type SaveFasterWhisperDefaultsInput = {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
};
```

- [ ] **Step 6: Implement IPC runtime helpers**

In `desktop/electron/ipc.ts`, export helpers and register handlers:

```ts
["openbbq:get-runtime-settings", async () => getRuntimeSettings(context.getSidecar())],
["openbbq:save-runtime-defaults", async (_event, input) => saveRuntimeDefaults(context.getSidecar(), input as SaveRuntimeDefaultsInput)],
["openbbq:save-llm-provider", async (_event, input) => saveLlmProvider(context.getSidecar(), input as SaveLlmProviderInput)],
["openbbq:check-llm-provider", async (_event, name) => checkLlmProvider(context.getSidecar(), String(name))],
["openbbq:save-faster-whisper-defaults", async (_event, input) => saveFasterWhisperDefaults(context.getSidecar(), input as SaveFasterWhisperDefaultsInput)],
["openbbq:get-runtime-models", async () => getRuntimeModels(context.getSidecar())],
["openbbq:get-diagnostics", async () => getDiagnostics(context.getSidecar())],
```

Add mapping helpers:

```ts
type SaveRuntimeDefaultsInput = {
  llmProvider: string;
  asrProvider: string;
};

type SaveLlmProviderInput = {
  name: string;
  type: "openai_compatible";
  baseUrl: string | null;
  defaultChatModel: string | null;
  secretValue: string | null;
  apiKeyRef: string | null;
  displayName: string | null;
};

type SaveFasterWhisperDefaultsInput = {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
};

function toRuntimeSettingsModel(settings: ApiRuntimeSettings): RuntimeSettingsModel {
  return {
    configPath: settings.config_path,
    cacheRoot: settings.cache.root,
    defaults: {
      llmProvider: settings.defaults.llm_provider,
      asrProvider: settings.defaults.asr_provider
    },
    llmProviders: Object.values(settings.providers).map((provider) => ({
      name: provider.name,
      type: provider.type,
      baseUrl: provider.base_url ?? null,
      apiKeyRef: provider.api_key ?? null,
      defaultChatModel: provider.default_chat_model ?? null,
      displayName: provider.display_name ?? null
    })),
    fasterWhisper: {
      cacheDir: settings.models.faster_whisper.cache_dir,
      defaultModel: settings.models.faster_whisper.default_model,
      defaultDevice: settings.models.faster_whisper.default_device,
      defaultComputeType: settings.models.faster_whisper.default_compute_type
    }
  };
}

function toModelStatusModel(model: ApiModelAssetStatus): RuntimeModelStatus {
  return {
    provider: model.provider,
    model: model.model,
    cacheDir: model.cache_dir,
    present: model.present,
    sizeBytes: model.size_bytes,
    error: model.error ?? null
  };
}

export async function getRuntimeSettings(sidecar: ManagedSidecar) {
  const data = await requestJson<{ settings: ApiRuntimeSettings }>(sidecar.connection, "/runtime/settings");
  return toRuntimeSettingsModel(data.settings);
}

export async function saveRuntimeDefaults(sidecar: ManagedSidecar, input: SaveRuntimeDefaultsInput) {
  const data = await requestJson<{ settings: ApiRuntimeSettings }>(sidecar.connection, "/runtime/defaults", {
    method: "PUT",
    body: { llm_provider: input.llmProvider, asr_provider: input.asrProvider }
  });
  return toRuntimeSettingsModel(data.settings);
}

export async function saveFasterWhisperDefaults(sidecar: ManagedSidecar, input: SaveFasterWhisperDefaultsInput) {
  const data = await requestJson<{ settings: ApiRuntimeSettings }>(
    sidecar.connection,
    "/runtime/models/faster-whisper",
    {
      method: "PUT",
      body: {
        cache_dir: input.cacheDir,
        default_model: input.defaultModel,
        default_device: input.defaultDevice,
        default_compute_type: input.defaultComputeType
      }
    }
  );
  return toRuntimeSettingsModel(data.settings);
}

export async function saveLlmProvider(sidecar: ManagedSidecar, input: SaveLlmProviderInput) {
  const data = await requestJson<{ provider: ApiProviderProfile }>(
    sidecar.connection,
    `/runtime/providers/${encodeURIComponent(input.name)}/auth`,
    {
      method: "PUT",
      body: {
        type: input.type,
        base_url: input.baseUrl,
        default_chat_model: input.defaultChatModel,
        secret_value: input.secretValue,
        api_key_ref: input.apiKeyRef,
        display_name: input.displayName
      }
    }
  );
  return {
    name: data.provider.name,
    type: data.provider.type,
    baseUrl: data.provider.base_url ?? null,
    apiKeyRef: data.provider.api_key ?? null,
    defaultChatModel: data.provider.default_chat_model ?? null,
    displayName: data.provider.display_name ?? null
  };
}

export async function checkLlmProvider(sidecar: ManagedSidecar, name: string): Promise<SecretStatus> {
  const data = await requestJson<{ secret: ApiSecretCheck }>(
    sidecar.connection,
    `/runtime/providers/${encodeURIComponent(name)}/check`
  );
  return {
    reference: data.secret.reference,
    resolved: data.secret.resolved,
    display: data.secret.display,
    valuePreview: data.secret.value_preview ?? null,
    error: data.secret.error ?? null
  };
}

export async function getRuntimeModels(sidecar: ManagedSidecar): Promise<RuntimeModelStatus[]> {
  const data = await requestJson<{ models: ApiModelAssetStatus[] }>(
    sidecar.connection,
    "/runtime/models"
  );
  return data.models.map(toModelStatusModel);
}

export async function getDiagnostics(sidecar: ManagedSidecar): Promise<DiagnosticCheck[]> {
  const data = await requestJson<{ ok: boolean; checks: ApiDoctorCheck[] }>(
    sidecar.connection,
    "/doctor"
  );
  return data.checks.map((check) => ({
    id: check.id,
    status: check.status,
    severity: check.severity,
    message: check.message
  }));
}
```

Use the same snake_case to camelCase mapping style for provider, secret, model status, and diagnostics.

- [ ] **Step 7: Stop hard-coding quickstart runtime fields**

In `desktop/electron/workflowMapping.ts`, remove `provider`, `model`, `asr_model`, `asr_device`, and `asr_compute_type` from the `common` object. Keep `source_lang` and `target_lang`.

The local body should be:

```ts
body: {
  input_path: source.path,
  source_lang: sourceLang,
  target_lang: targetLang
}
```

The remote body should include URL, language, quality, auth, browser, and browser profile only.

- [ ] **Step 8: Expose preload and client methods**

In `desktop/electron/preload.cts`, add methods mirroring the registered IPC channels. In `desktop/src/global.d.ts`, add them to `OpenBBQDesktopApi`.

In `desktop/src/lib/apiClient.ts`, extend `OpenBBQClient` with the runtime methods and add mock implementations backed by in-memory `runtimeSettings`, `runtimeModels`, and diagnostics. In `desktop/src/lib/desktopClient.ts`, forward all new methods to `api`.

- [ ] **Step 9: Run desktop bridge tests**

Run:

```bash
cd desktop
pnpm test -- workflowMapping.test.ts ipc.test.ts desktopClient.test.ts
```

Expected: targeted tests pass.

- [ ] **Step 10: Commit Task 4**

```bash
git add desktop/electron/apiTypes.ts desktop/electron/http.ts desktop/electron/ipc.ts desktop/electron/preload.cts desktop/electron/workflowMapping.ts desktop/src/global.d.ts desktop/src/lib/apiClient.ts desktop/src/lib/desktopClient.ts desktop/src/lib/types.ts desktop/electron/__tests__/ipc.test.ts desktop/electron/__tests__/workflowMapping.test.ts desktop/src/lib/desktopClient.test.ts
git commit -m "feat: add desktop runtime settings bridge"
```

## Task 5: Settings Renderer Component

**Files:**
- Create: `desktop/src/components/Settings.tsx`
- Create: `desktop/src/components/__tests__/Settings.test.tsx`
- Modify: `desktop/src/lib/types.ts`

- [ ] **Step 1: Write failing Settings component tests**

Create `desktop/src/components/__tests__/Settings.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Settings } from "../Settings";
import type { DiagnosticCheck, RuntimeModelStatus, RuntimeSettingsModel, SecretStatus } from "../../lib/types";

const settings: RuntimeSettingsModel = {
  configPath: "C:/Users/alex/.openbbq/config.toml",
  cacheRoot: "C:/Users/alex/.cache/openbbq",
  defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
  llmProviders: [
    {
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: "https://api.openai.com/v1",
      apiKeyRef: "sqlite:openbbq/providers/openai-compatible/api_key",
      defaultChatModel: "gpt-4o-mini",
      displayName: "OpenAI-compatible"
    },
    {
      name: "local-gateway",
      type: "openai_compatible",
      baseUrl: "http://127.0.0.1:8000/v1",
      apiKeyRef: null,
      defaultChatModel: "qwen2.5",
      displayName: "Local gateway"
    }
  ],
  fasterWhisper: {
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    defaultModel: "base",
    defaultDevice: "cpu",
    defaultComputeType: "int8"
  }
};

const modelStatus: RuntimeModelStatus[] = [
  {
    provider: "faster_whisper",
    model: "base",
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    present: false,
    sizeBytes: 0,
    error: null
  }
];

const checks: DiagnosticCheck[] = [
  { id: "cache.root_writable", status: "passed", severity: "error", message: "Runtime cache root is writable." }
];

const secret: SecretStatus = {
  reference: "sqlite:openbbq/providers/openai-compatible/api_key",
  resolved: true,
  display: "sqlite:openbbq/providers/openai-compatible/api_key",
  valuePreview: "sk-...test",
  error: null
};

function renderSettings(overrides = {}) {
  const props = {
    loadSettings: vi.fn().mockResolvedValue(settings),
    loadModels: vi.fn().mockResolvedValue(modelStatus),
    loadDiagnostics: vi.fn().mockResolvedValue(checks),
    saveRuntimeDefaults: vi.fn().mockResolvedValue(settings),
    saveLlmProvider: vi.fn().mockResolvedValue(settings.llmProviders[0]),
    checkLlmProvider: vi.fn().mockResolvedValue(secret),
    saveFasterWhisperDefaults: vi.fn().mockResolvedValue(settings),
    ...overrides
  };
  render(<Settings {...props} />);
  return props;
}

describe("Settings", () => {
  it("loads settings and marks the default LLM provider", async () => {
    renderSettings();

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "LLM provider" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("openai-compatible")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
  });

  it("switches to ASR model and shows faster-whisper defaults", async () => {
    const user = userEvent.setup();
    renderSettings();

    await screen.findByText("openai-compatible");
    await user.click(screen.getByRole("button", { name: "ASR model" }));

    expect(screen.getByRole("heading", { name: "faster-whisper" })).toBeInTheDocument();
    expect(screen.getByLabelText("Default model")).toHaveValue("base");
    expect(screen.getByText("Model cache missing")).toBeInTheDocument();
  });

  it("saves a selected provider as the default LLM provider", async () => {
    const user = userEvent.setup();
    const saveRuntimeDefaults = vi.fn().mockResolvedValue({
      ...settings,
      defaults: { ...settings.defaults, llmProvider: "local-gateway" }
    });
    renderSettings({ saveRuntimeDefaults });

    await screen.findByText("local-gateway");
    await user.click(screen.getByRole("button", { name: "local-gateway" }));
    await user.click(screen.getByRole("button", { name: "Set as default" }));

    expect(saveRuntimeDefaults).toHaveBeenCalledWith({
      llmProvider: "local-gateway",
      asrProvider: "faster-whisper"
    });
  });

  it("edits and saves an LLM provider profile", async () => {
    const user = userEvent.setup();
    const saveLlmProvider = vi.fn().mockResolvedValue({
      ...settings.llmProviders[0],
      baseUrl: "http://127.0.0.1:8000/v1",
      defaultChatModel: "qwen2.5"
    });
    renderSettings({ saveLlmProvider });

    await screen.findByText("openai-compatible");
    await user.clear(screen.getByLabelText("Base URL"));
    await user.type(screen.getByLabelText("Base URL"), "http://127.0.0.1:8000/v1");
    await user.clear(screen.getByLabelText("Default chat model"));
    await user.type(screen.getByLabelText("Default chat model"), "qwen2.5");
    await user.type(screen.getByLabelText("API key"), "sk-local");
    await user.click(screen.getByRole("button", { name: "Save provider" }));

    expect(saveLlmProvider).toHaveBeenCalledWith({
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: "http://127.0.0.1:8000/v1",
      defaultChatModel: "qwen2.5",
      secretValue: "sk-local",
      apiKeyRef: "sqlite:openbbq/providers/openai-compatible/api_key",
      displayName: "OpenAI-compatible"
    });
  });

  it("renders diagnostics and advanced paths", async () => {
    const user = userEvent.setup();
    renderSettings();

    await screen.findByText("openai-compatible");
    await user.click(screen.getByRole("button", { name: "Diagnostics" }));
    expect(screen.getByText("cache.root_writable")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByText("C:/Users/alex/.openbbq/config.toml")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the failing component test**

Run:

```bash
cd desktop
pnpm test -- Settings.test.tsx
```

Expected: failure because `Settings.tsx` does not exist.

- [ ] **Step 3: Implement Settings component shell**

Create `desktop/src/components/Settings.tsx` with prop-driven data loading:

```tsx
import { useEffect, useMemo, useState } from "react";

import type {
  DiagnosticCheck,
  LlmProviderModel,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SecretStatus
} from "../lib/types";
import { Button } from "./Button";

type SettingsSection = "llm" | "asr" | "diagnostics" | "advanced";

export type SettingsProps = {
  loadSettings(): Promise<RuntimeSettingsModel>;
  loadModels(): Promise<RuntimeModelStatus[]>;
  loadDiagnostics(): Promise<DiagnosticCheck[]>;
  saveRuntimeDefaults(input: { llmProvider: string; asrProvider: string }): Promise<RuntimeSettingsModel>;
  saveLlmProvider(input: {
    name: string;
    type: "openai_compatible";
    baseUrl: string | null;
    defaultChatModel: string | null;
    secretValue: string | null;
    apiKeyRef: string | null;
    displayName: string | null;
  }): Promise<LlmProviderModel>;
  checkLlmProvider(name: string): Promise<SecretStatus>;
  saveFasterWhisperDefaults(input: {
    cacheDir: string;
    defaultModel: string;
    defaultDevice: string;
    defaultComputeType: string;
  }): Promise<RuntimeSettingsModel>;
};

export function Settings(props: SettingsProps) {
  const [section, setSection] = useState<SettingsSection>("llm");
  const [settings, setSettings] = useState<RuntimeSettingsModel | null>(null);
  const [models, setModels] = useState<RuntimeModelStatus[]>([]);
  const [diagnostics, setDiagnostics] = useState<DiagnosticCheck[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([props.loadSettings(), props.loadModels(), props.loadDiagnostics()])
      .then(([nextSettings, nextModels, nextDiagnostics]) => {
        if (cancelled) {
          return;
        }
        setSettings(nextSettings);
        setModels(nextModels);
        setDiagnostics(nextDiagnostics);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Settings could not be loaded.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [props]);

  if (error) {
    return <div role="alert" className="rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-[#6b3f27]">{error}</div>;
  }
  if (!settings) {
    return <section aria-label="Settings loading">Loading settings...</section>;
  }

  return (
    <section className="grid min-h-[calc(100vh-84px)] grid-cols-[190px_minmax(0,1fr)] gap-5">
      <aside className="rounded-lg bg-paper-side p-3 shadow-control">
        <h1 className="font-serif text-[36px] leading-none text-ink-brown">Settings</h1>
        <nav className="mt-5 grid gap-2" aria-label="Settings sections">
          <SectionButton active={section === "llm"} onClick={() => setSection("llm")}>LLM provider</SectionButton>
          <SectionButton active={section === "asr"} onClick={() => setSection("asr")}>ASR model</SectionButton>
          <SectionButton active={section === "diagnostics"} onClick={() => setSection("diagnostics")}>Diagnostics</SectionButton>
          <SectionButton active={section === "advanced"} onClick={() => setSection("advanced")}>Advanced</SectionButton>
        </nav>
      </aside>
      <div className="min-w-0">
        {section === "llm" ? <LlmProviderSection settings={settings} onSettingsChange={setSettings} {...props} /> : null}
        {section === "asr" ? <AsrSection settings={settings} models={models} onSettingsChange={setSettings} {...props} /> : null}
        {section === "diagnostics" ? <DiagnosticsSection checks={diagnostics} models={models} /> : null}
        {section === "advanced" ? <AdvancedSection settings={settings} /> : null}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Implement section button and LLM provider section**

Add helper components in the same file:

```tsx
function SectionButton({ active, children, onClick }: { active: boolean; children: string; onClick(): void }) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={active ? "rounded-sm bg-accent px-3 py-2.5 text-left text-sm font-bold text-[#fff8ea]" : "rounded-sm bg-paper px-3 py-2.5 text-left text-sm text-ink-brown shadow-control"}
    >
      {children}
    </button>
  );
}

function LlmProviderSection({
  settings,
  onSettingsChange,
  saveRuntimeDefaults,
  saveLlmProvider,
  checkLlmProvider
}: SettingsProps & { settings: RuntimeSettingsModel; onSettingsChange(settings: RuntimeSettingsModel): void }) {
  const [selectedName, setSelectedName] = useState(settings.defaults.llmProvider);
  const selected = settings.llmProviders.find((provider) => provider.name === selectedName) ?? settings.llmProviders[0];
  const [draft, setDraft] = useState(() => ({
    displayName: selected.displayName ?? selected.name,
    baseUrl: selected.baseUrl ?? "",
    defaultChatModel: selected.defaultChatModel ?? "",
    apiKeyRef: selected.apiKeyRef ?? `sqlite:openbbq/providers/${selected.name}/api_key`,
    secretValue: ""
  }));
  const [secret, setSecret] = useState<SecretStatus | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setDraft({
      displayName: selected.displayName ?? selected.name,
      baseUrl: selected.baseUrl ?? "",
      defaultChatModel: selected.defaultChatModel ?? "",
      apiKeyRef: selected.apiKeyRef ?? `sqlite:openbbq/providers/${selected.name}/api_key`,
      secretValue: ""
    });
    setSecret(null);
    setSaveError(null);
  }, [selected.name, selected.baseUrl, selected.defaultChatModel, selected.apiKeyRef, selected.displayName]);

  async function setDefault() {
    const updated = await saveRuntimeDefaults({
      llmProvider: selected.name,
      asrProvider: settings.defaults.asrProvider
    });
    onSettingsChange(updated);
  }

  async function checkSecret() {
    setSecret(await checkLlmProvider(selected.name));
  }

  async function saveProvider() {
    try {
      setSaveError(null);
      const saved = await saveLlmProvider({
        name: selected.name,
        type: "openai_compatible",
        baseUrl: draft.baseUrl.trim() || null,
        defaultChatModel: draft.defaultChatModel.trim() || null,
        secretValue: draft.secretValue.trim() || null,
        apiKeyRef: draft.apiKeyRef.trim() || null,
        displayName: draft.displayName.trim() || null
      });
      onSettingsChange({
        ...settings,
        llmProviders: settings.llmProviders.map((provider) => (provider.name === saved.name ? saved : provider))
      });
      setDraft((current) => ({ ...current, secretValue: "" }));
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Provider could not be saved.");
    }
  }

  return (
    <section className="grid grid-cols-[220px_minmax(0,1fr)] gap-4" aria-label="LLM provider settings">
      <aside className="rounded-lg bg-paper-muted p-3 shadow-control">
        <p className="text-xs uppercase text-muted">Providers</p>
        <div className="mt-3 grid gap-2">
          {settings.llmProviders.map((provider) => (
            <button key={provider.name} type="button" onClick={() => setSelectedName(provider.name)} className="rounded-md bg-paper px-3 py-2 text-left shadow-control">
              <span className="block font-bold text-ink-brown">{provider.name}</span>
              {settings.defaults.llmProvider === provider.name ? <span className="text-xs text-[#6f7c46]">Default</span> : null}
            </button>
          ))}
        </div>
      </aside>
      <section className="rounded-lg bg-paper-muted p-5 shadow-control">
        <p className="text-xs uppercase text-muted">OpenAI-compatible profile</p>
        <h2 className="mt-2 text-2xl font-extrabold text-ink-brown">{selected.name}</h2>
        <div className="mt-4 grid gap-3">
          <TextInput label="Display name" value={draft.displayName} onChange={(value) => setDraft({ ...draft, displayName: value })} />
          <TextInput label="Base URL" value={draft.baseUrl} onChange={(value) => setDraft({ ...draft, baseUrl: value })} />
          <TextInput label="Default chat model" value={draft.defaultChatModel} onChange={(value) => setDraft({ ...draft, defaultChatModel: value })} />
          <TextInput label="API key reference" value={draft.apiKeyRef} onChange={(value) => setDraft({ ...draft, apiKeyRef: value })} />
          <TextInput label="API key" value={draft.secretValue} onChange={(value) => setDraft({ ...draft, secretValue: value })} />
        </div>
        {secret ? <p className="mt-3 text-sm text-muted">{secret.resolved ? `Secret resolved: ${secret.valuePreview ?? secret.display}` : secret.error}</p> : null}
        {saveError ? <p className="mt-3 text-sm font-semibold text-[#8c4d29]">{saveError}</p> : null}
        <div className="mt-5 flex gap-2">
          <Button variant="primary" onClick={() => void saveProvider()}>Save provider</Button>
          <Button variant="primary" onClick={() => void setDefault()}>Set as default</Button>
          <Button variant="secondary" onClick={() => void checkSecret()}>Check secret</Button>
        </div>
      </section>
    </section>
  );
}
```

The `API key` field should use `type="password"` in `TextInput` when the label is `API key`. Do not render the entered secret anywhere else.

- [ ] **Step 5: Implement ASR, diagnostics, and advanced sections**

Add:

```tsx
function AsrSection({
  settings,
  models,
  onSettingsChange,
  saveFasterWhisperDefaults
}: SettingsProps & {
  settings: RuntimeSettingsModel;
  models: RuntimeModelStatus[];
  onSettingsChange(settings: RuntimeSettingsModel): void;
}) {
  const [draft, setDraft] = useState(settings.fasterWhisper);
  const status = models.find((model) => model.provider === "faster_whisper");

  async function save() {
    const updated = await saveFasterWhisperDefaults({
      cacheDir: draft.cacheDir,
      defaultModel: draft.defaultModel,
      defaultDevice: draft.defaultDevice,
      defaultComputeType: draft.defaultComputeType
    });
    onSettingsChange(updated);
  }

  return (
    <section className="grid grid-cols-[220px_minmax(0,1fr)] gap-4" aria-label="ASR model settings">
      <aside className="rounded-lg bg-paper-muted p-3 shadow-control">
        <p className="text-xs uppercase text-muted">ASR providers</p>
        <div className="mt-3 rounded-md bg-paper px-3 py-2 shadow-control">
          <span className="block font-bold text-ink-brown">faster-whisper</span>
          <span className="text-xs text-[#6f7c46]">Default</span>
        </div>
      </aside>
      <section className="rounded-lg bg-paper-muted p-5 shadow-control">
        <h2 className="text-2xl font-extrabold text-ink-brown">faster-whisper</h2>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <TextInput label="Default model" value={draft.defaultModel} onChange={(value) => setDraft({ ...draft, defaultModel: value })} />
          <TextInput label="Default device" value={draft.defaultDevice} onChange={(value) => setDraft({ ...draft, defaultDevice: value })} />
          <TextInput label="Default compute type" value={draft.defaultComputeType} onChange={(value) => setDraft({ ...draft, defaultComputeType: value })} />
          <TextInput label="Cache directory" value={draft.cacheDir} onChange={(value) => setDraft({ ...draft, cacheDir: value })} wide />
        </div>
        <p className="mt-4 text-sm font-semibold text-[#8c4d29]">{status?.present ? "Model cache present" : "Model cache missing"}</p>
        <Button variant="primary" onClick={() => void save()}>Save ASR defaults</Button>
      </section>
    </section>
  );
}

function DiagnosticsSection({ checks, models }: { checks: DiagnosticCheck[]; models: RuntimeModelStatus[] }) {
  return (
    <section aria-label="Diagnostics" className="rounded-lg bg-paper-muted p-5 shadow-control">
      <h2 className="text-2xl font-extrabold text-ink-brown">Diagnostics</h2>
      <div className="mt-4 grid gap-2">
        {checks.map((check) => (
          <div key={check.id} className="rounded-md bg-paper px-3 py-2 shadow-control">
            <strong>{check.id}</strong>
            <p className="text-sm text-muted">{check.message}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function AdvancedSection({ settings }: { settings: RuntimeSettingsModel }) {
  return (
    <section aria-label="Advanced" className="rounded-lg bg-paper-muted p-5 shadow-control">
      <h2 className="text-2xl font-extrabold text-ink-brown">Advanced</h2>
      <ReadOnlyRow label="Runtime config path" value={settings.configPath} />
      <ReadOnlyRow label="Cache root" value={settings.cacheRoot} />
      <ReadOnlyRow label="faster-whisper cache directory" value={settings.fasterWhisper.cacheDir} />
    </section>
  );
}
```

Also add `TextInput` and `ReadOnlyRow` helpers with visible labels and stable input heights.

- [ ] **Step 6: Run Settings component tests**

Run:

```bash
cd desktop
pnpm test -- Settings.test.tsx
```

Expected: `Settings.test.tsx` passes.

- [ ] **Step 7: Commit Task 5**

```bash
git add desktop/src/components/Settings.tsx desktop/src/components/__tests__/Settings.test.tsx desktop/src/lib/types.ts
git commit -m "feat: add desktop settings screen"
```

## Task 6: App Integration And Final Verification

**Files:**
- Modify: `desktop/src/App.tsx`
- Modify: `desktop/src/__tests__/App.test.tsx`
- Modify: `desktop/src/lib/apiClient.ts`
- Modify: `desktop/src/lib/desktopClient.ts`
- Test: `desktop/src/__tests__/App.test.tsx`
- Test: `desktop/src/components/__tests__/WorkflowEditor.test.tsx`

- [ ] **Step 1: Write failing App navigation test**

Add to `desktop/src/__tests__/App.test.tsx`:

```tsx
it("opens Settings from the global navigation", async () => {
  const user = userEvent.setup();
  const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
    getRuntimeSettings: vi.fn().mockResolvedValue({
      configPath: "C:/Users/alex/.openbbq/config.toml",
      cacheRoot: "C:/Users/alex/.cache/openbbq",
      defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
      llmProviders: [],
      fasterWhisper: {
        cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
        defaultModel: "base",
        defaultDevice: "cpu",
        defaultComputeType: "int8"
      }
    }),
    getRuntimeModels: vi.fn().mockResolvedValue([]),
    getDiagnostics: vi.fn().mockResolvedValue([]),
    saveRuntimeDefaults: vi.fn(),
    saveLlmProvider: vi.fn(),
    checkLlmProvider: vi.fn(),
    saveFasterWhisperDefaults: vi.fn()
  });

  render(<App client={client} />);

  await user.click(screen.getByRole("button", { name: "Settings" }));

  expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("aria-current", "page");
});
```

Keep the existing `WorkflowEditor` test that asserts global settings controls are absent. Update it only if text changes.

- [ ] **Step 2: Run failing App test**

Run:

```bash
cd desktop
pnpm test -- App.test.tsx WorkflowEditor.test.tsx
```

Expected: App test fails because Settings navigation is not wired.

- [ ] **Step 3: Wire Settings into App**

In `desktop/src/App.tsx`, import `Settings`:

```ts
import { Settings } from "./components/Settings";
```

Extend screen type:

```ts
type Screen = "source" | "workflow" | "tasks" | "monitor" | "results" | "settings";
```

Add navigation:

```ts
if (item === "Settings") {
  invalidateTemplateRequest();
  invalidateTaskRequest();
  invalidateTaskListRequest();
  invalidateReviewRequest();
  cancelRetryState();
  setLoadError(null);
  setScreen("settings");
  return;
}
```

Update `activeNav`:

```ts
const activeNav =
  screen === "settings"
    ? "Settings"
    : screen === "tasks" || screen === "monitor"
      ? "Tasks"
      : screen === "results"
        ? "Results"
        : "New";
```

Render Settings:

```tsx
{screen === "settings" ? (
  <Settings
    loadSettings={client.getRuntimeSettings}
    loadModels={client.getRuntimeModels}
    loadDiagnostics={client.getDiagnostics}
    saveRuntimeDefaults={client.saveRuntimeDefaults}
    saveLlmProvider={client.saveLlmProvider}
    checkLlmProvider={client.checkLlmProvider}
    saveFasterWhisperDefaults={client.saveFasterWhisperDefaults}
  />
) : null}
```

- [ ] **Step 4: Ensure test clients include runtime methods**

In `desktop/src/lib/apiClient.ts`, ensure `OpenBBQClient` defines:

```ts
getRuntimeSettings(): Promise<RuntimeSettingsModel>;
saveRuntimeDefaults(input: { llmProvider: string; asrProvider: string }): Promise<RuntimeSettingsModel>;
saveLlmProvider(input: SaveLlmProviderInput): Promise<LlmProviderModel>;
checkLlmProvider(name: string): Promise<SecretStatus>;
saveFasterWhisperDefaults(input: SaveFasterWhisperDefaultsInput): Promise<RuntimeSettingsModel>;
getRuntimeModels(): Promise<RuntimeModelStatus[]>;
getDiagnostics(): Promise<DiagnosticCheck[]>;
```

Define `SaveLlmProviderInput` and `SaveFasterWhisperDefaultsInput` in `desktop/src/lib/types.ts` if not already added in Task 4.

Update `createTestClient` helper in `desktop/src/__tests__/App.test.tsx` with runtime default methods so unrelated App tests do not fail.

- [ ] **Step 5: Run targeted desktop renderer tests**

Run:

```bash
cd desktop
pnpm test -- App.test.tsx Settings.test.tsx WorkflowEditor.test.tsx desktopClient.test.ts
```

Expected: selected renderer tests pass.

- [ ] **Step 6: Run backend targeted tests**

Run:

```bash
uv run pytest tests/test_runtime_settings.py tests/test_api_projects_plugins_runtime.py tests/test_application_quickstart.py -q
```

Expected: selected backend tests pass.

- [ ] **Step 7: Run full verification**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd desktop
pnpm test
pnpm build
```

Expected: all commands pass. If an unrelated pre-existing failure appears, capture the command, failing test name, and error message in the implementation summary before deciding whether to fix it.

- [ ] **Step 8: Commit Task 6**

```bash
git add desktop/src/App.tsx desktop/src/__tests__/App.test.tsx desktop/src/lib/apiClient.ts desktop/src/lib/desktopClient.ts desktop/src/lib/types.ts desktop/src/components/Settings.tsx desktop/src/components/__tests__/Settings.test.tsx
git commit -m "feat: wire desktop settings navigation"
```

## Plan Self-Review

- Spec coverage: tasks cover runtime defaults, runtime write APIs, quickstart default usage, Electron IPC, renderer Settings UI, workflow editor exclusion, diagnostics, advanced read-only paths, and verification.
- Placeholder scan: no placeholder task steps or unresolved work markers are present.
- Type consistency: runtime defaults use `llm_provider` and `asr_provider` in Python/API JSON, `llmProvider` and `asrProvider` in renderer TypeScript, `openai-compatible` as the default LLM profile name, and `faster-whisper` as the default ASR provider name.
- Scope check: ASR downloads, provider presets, plugin-driven workflow editor forms, prompt/glossary sections, and i18n are excluded from the plan.
