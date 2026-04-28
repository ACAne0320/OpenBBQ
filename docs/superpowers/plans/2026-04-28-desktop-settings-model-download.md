# Desktop Settings Model Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Desktop users enter API keys directly, choose a faster-whisper model size, and download faster-whisper models on demand from Settings.

**Architecture:** The backend owns supported faster-whisper model sizes, model cache status, and the model download endpoint. Electron IPC forwards that backend contract to the renderer. The Settings UI hides secret-reference mechanics, keeps the typed API key behind the existing runtime secret store, and renders ASR model status/download controls from runtime model status data.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, TypeScript, Electron IPC, React, Vitest, Testing Library, Tailwind CSS, lucide-react.

---

## File Structure

Backend:

- Modify `src/openbbq/runtime/models_assets.py`: own supported faster-whisper model sizes, per-size status helpers, and a testable download adapter.
- Modify `src/openbbq/application/runtime.py`: add service request/result models and `faster_whisper_download`.
- Modify `src/openbbq/api/schemas.py`: add request/response schemas for faster-whisper downloads.
- Modify `src/openbbq/api/routes/runtime.py`: add `POST /runtime/models/faster-whisper/download`.
- Modify `tests/test_api_projects_plugins_runtime.py`: cover multi-model status, download success, and unsupported model rejection.

Desktop bridge:

- Modify `desktop/electron/apiTypes.ts`: add API response typing for model download.
- Modify `desktop/electron/ipc.ts`: add mapper/handler/export for model download.
- Modify `desktop/electron/preload.cts`: expose preload method.
- Modify `desktop/src/global.d.ts`: type preload method.
- Modify `desktop/src/lib/types.ts`: add renderer input type.
- Modify `desktop/src/lib/apiClient.ts`: add client method and mock download behavior.
- Modify `desktop/src/lib/desktopClient.ts`: forward preload method.
- Modify `desktop/electron/__tests__/ipc.test.ts`: cover sidecar download route.
- Modify `desktop/src/lib/desktopClient.test.ts`: cover preload forwarding.

Renderer:

- Modify `desktop/src/components/Settings.tsx`: hide API key reference, add API key visibility toggle, replace ASR model text input with a selector, and add per-model download controls.
- Modify `desktop/src/components/__tests__/Settings.test.tsx`: cover API key visibility, hidden reference field, ASR selector, model list, download success refresh, and download failure.

Verification:

- Run focused backend tests.
- Run focused desktop component/client/IPC tests.
- Run full backend and desktop test commands if focused tests pass.

---

## Task 1: Backend Faster-Whisper Status And Download Service

**Files:**
- Modify: `src/openbbq/runtime/models_assets.py`
- Modify: `src/openbbq/application/runtime.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Write failing backend tests for supported statuses and download**

Add these tests near the existing runtime settings/model route tests in `tests/test_api_projects_plugins_runtime.py`:

```python
def test_runtime_models_lists_supported_faster_whisper_sizes(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / "models" / "faster-whisper"
    (cache_dir / "models--Systran--faster-whisper-base").mkdir(parents=True)
    (cache_dir / "models--Systran--faster-whisper-base" / "model.bin").write_bytes(b"base")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project)

    response = client.get("/runtime/models", headers=headers)

    assert response.status_code == 200
    models = response.json()["data"]["models"]
    assert [model["model"] for model in models] == ["base", "tiny", "small", "medium", "large-v3"]
    base = models[0]
    assert base["provider"] == "faster-whisper"
    assert base["cache_dir"] == str(cache_dir.resolve())
    assert base["present"] is True
    assert base["size_bytes"] == 4
    assert all(model["provider"] == "faster-whisper" for model in models)


def test_runtime_downloads_faster_whisper_model_with_fake_adapter(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / "models" / "faster-whisper"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    calls = []

    def fake_download(model, *, cache_dir, device, compute_type):
        calls.append(
            {
                "model": model,
                "cache_dir": cache_dir,
                "device": device,
                "compute_type": compute_type,
            }
        )
        model_dir = cache_dir / f"models--Systran--faster-whisper-{model}"
        model_dir.mkdir(parents=True)
        (model_dir / "model.bin").write_bytes(b"downloaded")

    monkeypatch.setattr("openbbq.application.runtime.download_faster_whisper_model", fake_download)
    client, headers = authed_client(project)

    response = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "small"},
    )

    assert response.status_code == 200
    assert calls == [
        {
            "model": "small",
            "cache_dir": cache_dir.resolve(),
            "device": "cpu",
            "compute_type": "int8",
        }
    ]
    assert response.json()["data"]["model"] == {
        "provider": "faster-whisper",
        "model": "small",
        "cache_dir": str(cache_dir.resolve()),
        "present": True,
        "size_bytes": 10,
        "error": None,
    }


def test_runtime_download_rejects_unsupported_faster_whisper_model(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project, raise_server_exceptions=False)

    response = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "unknown-size"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "unknown-size" in response.json()["error"]["message"]
```

- [ ] **Step 2: Run backend tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_models_lists_supported_faster_whisper_sizes tests/test_api_projects_plugins_runtime.py::test_runtime_downloads_faster_whisper_model_with_fake_adapter tests/test_api_projects_plugins_runtime.py::test_runtime_download_rejects_unsupported_faster_whisper_model -q
```

Expected: fail because `/runtime/models` returns one model and `/runtime/models/faster-whisper/download` does not exist.

- [ ] **Step 3: Implement model-size constants, status helpers, and download adapter**

Replace `src/openbbq/runtime/models_assets.py` with:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.errors import ExecutionError, ValidationError
from openbbq.runtime.models import FasterWhisperSettings, ModelAssetStatus, RuntimeSettings

SUPPORTED_FASTER_WHISPER_MODELS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
)


def faster_whisper_model_status(settings: RuntimeSettings, model: str | None = None) -> ModelAssetStatus:
    model_settings = _faster_whisper_settings(settings)
    selected_model = model or model_settings.default_model
    _require_supported_faster_whisper_model(selected_model)
    cache_dir = model_settings.cache_dir
    present = _faster_whisper_model_present(cache_dir, selected_model)
    return ModelAssetStatus(
        provider="faster-whisper",
        model=selected_model,
        cache_dir=cache_dir,
        present=present,
        size_bytes=_faster_whisper_model_size(cache_dir, selected_model) if present else 0,
    )


def faster_whisper_model_statuses(settings: RuntimeSettings) -> tuple[ModelAssetStatus, ...]:
    model_settings = _faster_whisper_settings(settings)
    models = _ordered_supported_models(model_settings.default_model)
    return tuple(faster_whisper_model_status(settings, model) for model in models)


def download_faster_whisper_model(
    model: str,
    *,
    cache_dir: Path,
    device: str,
    compute_type: str,
) -> None:
    _require_supported_faster_whisper_model(model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ExecutionError(
            "faster-whisper is not installed. Install OpenBBQ with the media optional dependencies."
        ) from exc
    try:
        WhisperModel(model, device=device, compute_type=compute_type, download_root=str(cache_dir))
    except Exception as exc:
        raise ExecutionError(f"faster-whisper model '{model}' could not be downloaded: {exc}") from exc


def _faster_whisper_settings(settings: RuntimeSettings) -> FasterWhisperSettings:
    return (
        settings.models.faster_whisper
        if settings.models is not None
        else FasterWhisperSettings(
            cache_dir=settings.cache.root / "models" / "faster-whisper",
            default_model="base",
            default_device="cpu",
            default_compute_type="int8",
        )
    )


def _ordered_supported_models(default_model: str) -> tuple[str, ...]:
    if default_model not in SUPPORTED_FASTER_WHISPER_MODELS:
        return SUPPORTED_FASTER_WHISPER_MODELS
    return (default_model,) + tuple(
        model for model in SUPPORTED_FASTER_WHISPER_MODELS if model != default_model
    )


def _require_supported_faster_whisper_model(model: str) -> None:
    if model not in SUPPORTED_FASTER_WHISPER_MODELS:
        supported = ", ".join(SUPPORTED_FASTER_WHISPER_MODELS)
        raise ValidationError(f"Unsupported faster-whisper model '{model}'. Supported models: {supported}.")


def _faster_whisper_model_present(cache_dir: Path, model: str) -> bool:
    return any(candidate.exists() for candidate in _model_cache_candidates(cache_dir, model))


def _faster_whisper_model_size(cache_dir: Path, model: str) -> int:
    return sum(_path_size(candidate) for candidate in _model_cache_candidates(cache_dir, model) if candidate.exists())


def _model_cache_candidates(cache_dir: Path, model: str) -> tuple[Path, ...]:
    return (
        cache_dir / model,
        cache_dir / f"faster-whisper-{model}",
        cache_dir / f"models--Systran--faster-whisper-{model}",
    )


def _path_size(path: Path) -> int:
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

- [ ] **Step 4: Add application service request/result and update `model_list`**

In `src/openbbq/application/runtime.py`, update imports:

```python
from openbbq.runtime.models_assets import (
    download_faster_whisper_model,
    faster_whisper_model_status,
    faster_whisper_model_statuses,
)
```

Add these classes after `FasterWhisperSetRequest`:

```python
class FasterWhisperDownloadRequest(OpenBBQModel):
    model: str


class ModelDownloadResult(OpenBBQModel):
    model: ModelAssetStatus
```

Replace `model_list` with:

```python
def model_list() -> ModelListResult:
    return ModelListResult(models=faster_whisper_model_statuses(load_runtime_settings()))
```

Add this service function after `faster_whisper_set`:

```python
def faster_whisper_download(request: FasterWhisperDownloadRequest) -> ModelDownloadResult:
    settings = load_runtime_settings()
    faster_whisper = (
        settings.models.faster_whisper
        if settings.models is not None
        else FasterWhisperSettings(
            cache_dir=settings.cache.root / "models" / "faster-whisper",
            default_model="base",
            default_device="cpu",
            default_compute_type="int8",
        )
    )
    download_faster_whisper_model(
        request.model,
        cache_dir=faster_whisper.cache_dir,
        device=faster_whisper.default_device,
        compute_type=faster_whisper.default_compute_type,
    )
    return ModelDownloadResult(model=faster_whisper_model_status(settings, request.model))
```

- [ ] **Step 5: Run backend tests to verify service work is still blocked only by missing route**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_models_lists_supported_faster_whisper_sizes tests/test_api_projects_plugins_runtime.py::test_runtime_downloads_faster_whisper_model_with_fake_adapter tests/test_api_projects_plugins_runtime.py::test_runtime_download_rejects_unsupported_faster_whisper_model -q
```

Expected: status-list test passes; download route tests fail with HTTP 404 or method-not-found behavior.

---

## Task 2: Backend Download API Route

**Files:**
- Modify: `src/openbbq/api/schemas.py`
- Modify: `src/openbbq/api/routes/runtime.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Add API schemas**

In `src/openbbq/api/schemas.py`, add these classes after `FasterWhisperSettingsSetRequest`:

```python
class FasterWhisperDownloadRequest(OpenBBQModel):
    model: str


class ModelDownloadData(OpenBBQModel):
    model: ModelAssetStatus
```

- [ ] **Step 2: Add route imports**

In `src/openbbq/api/routes/runtime.py`, include these schema imports:

```python
    FasterWhisperDownloadRequest,
    ModelDownloadData,
```

Include these application imports:

```python
    FasterWhisperDownloadRequest as ApplicationFasterWhisperDownloadRequest,
    faster_whisper_download,
```

- [ ] **Step 3: Add the download route**

In `src/openbbq/api/routes/runtime.py`, add this route after `put_faster_whisper_settings`:

```python
@router.post("/runtime/models/faster-whisper/download", response_model=ApiSuccess[ModelDownloadData])
def post_faster_whisper_download(
    body: FasterWhisperDownloadRequest,
) -> ApiSuccess[ModelDownloadData]:
    result = faster_whisper_download(
        ApplicationFasterWhisperDownloadRequest(model=body.model)
    )
    return ApiSuccess(data=ModelDownloadData(model=result.model))
```

- [ ] **Step 4: Run backend route tests**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_models_lists_supported_faster_whisper_sizes tests/test_api_projects_plugins_runtime.py::test_runtime_downloads_faster_whisper_model_with_fake_adapter tests/test_api_projects_plugins_runtime.py::test_runtime_download_rejects_unsupported_faster_whisper_model -q
```

Expected: all three tests pass.

- [ ] **Step 5: Run existing runtime route regression tests**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_defaults_and_faster_whisper_routes tests/test_runtime_cli.py::test_models_list_json_reports_faster_whisper_cache -q
```

Expected: both pass. The model-list order keeps the configured default first, preserving existing callers that inspect `models[0]`.

- [ ] **Step 6: Commit backend API work**

Run:

```bash
git add src/openbbq/runtime/models_assets.py src/openbbq/application/runtime.py src/openbbq/api/schemas.py src/openbbq/api/routes/runtime.py tests/test_api_projects_plugins_runtime.py
git commit -m "feat: Add faster-whisper model download API"
```

Expected: commit succeeds with only backend files staged.

---

## Task 3: Electron And Renderer Client Contract

**Files:**
- Modify: `desktop/electron/apiTypes.ts`
- Modify: `desktop/electron/ipc.ts`
- Modify: `desktop/electron/preload.cts`
- Modify: `desktop/src/global.d.ts`
- Modify: `desktop/src/lib/types.ts`
- Modify: `desktop/src/lib/apiClient.ts`
- Modify: `desktop/src/lib/desktopClient.ts`
- Test: `desktop/electron/__tests__/ipc.test.ts`
- Test: `desktop/src/lib/desktopClient.test.ts`

- [ ] **Step 1: Write failing Electron IPC test**

Add this test to `desktop/electron/__tests__/ipc.test.ts` after the faster-whisper defaults test:

```typescript
  it("downloads a faster-whisper model through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            model: {
              provider: "faster-whisper",
              model: "small",
              cache_dir: "C:/models/fw",
              present: true,
              size_bytes: 10,
              error: null
            }
          }
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { downloadFasterWhisperModel } = await import("../ipc");

    await expect(downloadFasterWhisperModel(sidecar, { model: "small" })).resolves.toEqual({
      provider: "faster-whisper",
      model: "small",
      cacheDir: "C:/models/fw",
      present: true,
      sizeBytes: 10,
      error: null
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/models/faster-whisper/download",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ model: "small" })
      })
    );
  });
```

- [ ] **Step 2: Write failing desktop client forwarding test**

In `desktop/src/lib/desktopClient.test.ts`, add this mock API method:

```typescript
      downloadFasterWhisperModel: vi.fn().mockResolvedValue({
        provider: "faster-whisper",
        model: "small",
        cacheDir: "cache/models/faster-whisper",
        present: true,
        sizeBytes: 10,
        error: null
      }),
```

Then add these assertions before `await client.getDiagnostics();`:

```typescript
    await client.downloadFasterWhisperModel({ model: "small" });
```

And after the existing runtime expectations:

```typescript
    expect(api.downloadFasterWhisperModel).toHaveBeenCalledWith({ model: "small" });
```

- [ ] **Step 3: Run desktop bridge tests to verify they fail**

Run:

```bash
cd desktop && pnpm test electron/__tests__/ipc.test.ts src/lib/desktopClient.test.ts
```

Expected: fail because `downloadFasterWhisperModel` is not defined on the IPC module/client type.

- [ ] **Step 4: Add renderer types**

In `desktop/src/lib/types.ts`, add:

```typescript
export type DownloadFasterWhisperModelInput = {
  model: string;
};
```

- [ ] **Step 5: Extend `OpenBBQClient` and mock client**

In `desktop/src/lib/apiClient.ts`, import the new type:

```typescript
  DownloadFasterWhisperModelInput,
```

Add this method to `OpenBBQClient` after `saveFasterWhisperDefaults`:

```typescript
  downloadFasterWhisperModel(input: DownloadFasterWhisperModelInput): Promise<RuntimeModelStatus>;
```

Change the initial `runtimeModels` to include supported sizes:

```typescript
  let runtimeModels: RuntimeModelStatus[] = ["base", "tiny", "small", "medium", "large-v3"].map((model) => ({
    provider: "faster-whisper",
    model,
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    present: false,
    sizeBytes: 0,
    error: null
  }));
```

Add this mock method before `getRuntimeModels`:

```typescript
    async downloadFasterWhisperModel(input) {
      const downloaded: RuntimeModelStatus = {
        provider: "faster-whisper",
        model: input.model,
        cacheDir: runtimeSettings.fasterWhisper.cacheDir,
        present: true,
        sizeBytes: 10,
        error: null
      };
      runtimeModels = runtimeModels.some((model) => model.provider === "faster-whisper" && model.model === input.model)
        ? runtimeModels.map((model) =>
            model.provider === "faster-whisper" && model.model === input.model ? downloaded : model
          )
        : [downloaded, ...runtimeModels];
      return cloneModel(downloaded);
    },
```

- [ ] **Step 6: Add preload and global API typing**

In `desktop/electron/preload.cts`, add:

```typescript
  downloadFasterWhisperModel: (input: unknown) => ipcRenderer.invoke("openbbq:download-faster-whisper-model", input),
```

Place it after `saveFasterWhisperDefaults`.

In `desktop/src/global.d.ts`, import `DownloadFasterWhisperModelInput` and add:

```typescript
  downloadFasterWhisperModel(input: DownloadFasterWhisperModelInput): Promise<RuntimeModelStatus>;
```

Place it after `saveFasterWhisperDefaults`.

- [ ] **Step 7: Add Electron API typing and IPC implementation**

In `desktop/electron/apiTypes.ts`, add:

```typescript
export type ApiModelDownloadData = {
  model: ApiModelAssetStatus;
};
```

In `desktop/electron/ipc.ts`, import `DownloadFasterWhisperModelInput` from renderer types.

Add this handler after `openbbq:save-faster-whisper-defaults`:

```typescript
    [
      "openbbq:download-faster-whisper-model",
      async (_event, input) =>
        downloadFasterWhisperModel(context.getSidecar(), input as DownloadFasterWhisperModelInput)
    ],
```

Add this exported function after `saveFasterWhisperDefaults`:

```typescript
export async function downloadFasterWhisperModel(
  sidecar: ManagedSidecar,
  input: DownloadFasterWhisperModelInput
): Promise<RuntimeModelStatus> {
  const data = await requestJson<{ model: ApiModelAssetStatus }>(
    sidecar.connection,
    "/runtime/models/faster-whisper/download",
    {
      method: "POST",
      body: { model: input.model }
    }
  );
  return toModelStatusModel(data.model);
}
```

- [ ] **Step 8: Forward desktop client method**

In `desktop/src/lib/desktopClient.ts`, add:

```typescript
    downloadFasterWhisperModel: (input) => api.downloadFasterWhisperModel(input),
```

Place it after `saveFasterWhisperDefaults`.

- [ ] **Step 9: Run desktop bridge tests**

Run:

```bash
cd desktop && pnpm test electron/__tests__/ipc.test.ts src/lib/desktopClient.test.ts
```

Expected: both test files pass.

- [ ] **Step 10: Commit desktop bridge work**

Run:

```bash
git add desktop/electron/apiTypes.ts desktop/electron/ipc.ts desktop/electron/preload.cts desktop/src/global.d.ts desktop/src/lib/types.ts desktop/src/lib/apiClient.ts desktop/src/lib/desktopClient.ts desktop/electron/__tests__/ipc.test.ts desktop/src/lib/desktopClient.test.ts
git commit -m "feat: Add desktop ASR model download client"
```

Expected: commit succeeds with only desktop bridge files staged.

---

## Task 4: Settings UI Tests

**Files:**
- Modify: `desktop/src/components/__tests__/Settings.test.tsx`

- [ ] **Step 1: Extend test fixture model statuses**

Replace the `models` constant in `desktop/src/components/__tests__/Settings.test.tsx` with:

```typescript
const models: RuntimeModelStatus[] = [
  {
    provider: "faster-whisper",
    model: "base",
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    present: false,
    sizeBytes: 0,
    error: null
  },
  {
    provider: "faster-whisper",
    model: "small",
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    present: true,
    sizeBytes: 10,
    error: null
  }
];
```

- [ ] **Step 2: Add required default prop**

In `renderSettings`, add this default prop after `saveFasterWhisperDefaults`:

```typescript
    downloadFasterWhisperModel: vi.fn().mockImplementation(async (input: { model: string }) => ({
      provider: "faster-whisper",
      model: input.model,
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      present: true,
      sizeBytes: 10,
      error: null
    })),
```

- [ ] **Step 3: Update LLM provider edit test for hidden API key reference and visibility toggle**

Replace the test named `"edits and saves an LLM provider including secret value and API key reference"` with:

```typescript
  it("edits and saves an LLM provider with a direct API key and hidden reference", async () => {
    const user = userEvent.setup();
    const saveLlmProvider = vi.fn().mockImplementation(async (input) => ({
      name: input.name,
      type: input.type,
      baseUrl: input.baseUrl,
      apiKeyRef: input.apiKeyRef,
      defaultChatModel: input.defaultChatModel,
      displayName: input.displayName
    }));
    renderSettings({ saveLlmProvider });

    await screen.findByRole("heading", { name: "Settings" });

    expect(screen.queryByLabelText("API key reference")).not.toBeInTheDocument();
    const secretInput = screen.getByLabelText("API key");
    expect(secretInput).toHaveAttribute("type", "password");

    await user.type(secretInput, "sk-test-secret");
    await user.click(screen.getByRole("button", { name: "Show API key" }));
    expect(secretInput).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Hide API key" }));
    expect(secretInput).toHaveAttribute("type", "password");

    await user.clear(screen.getByLabelText("Display name"));
    await user.type(screen.getByLabelText("Display name"), "Production LLM");
    await user.clear(screen.getByLabelText("Base URL"));
    await user.type(screen.getByLabelText("Base URL"), "https://llm.example.test/v1");
    await user.clear(screen.getByLabelText("Default chat model"));
    await user.type(screen.getByLabelText("Default chat model"), "gpt-4.1-mini");
    await user.click(screen.getByRole("button", { name: "Save provider" }));

    expect(saveLlmProvider).toHaveBeenCalledWith({
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: "https://llm.example.test/v1",
      defaultChatModel: "gpt-4.1-mini",
      secretValue: "sk-test-secret",
      apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
      displayName: "Production LLM"
    });
    expect(secretInput).toHaveValue("");
  });
```

- [ ] **Step 4: Add fallback sqlite reference assertion for bootstrapped provider**

Keep the existing bootstrapped-provider test. Its final `expect(saveLlmProvider).toHaveBeenCalledWith(...)` should still assert:

```typescript
      apiKeyRef: "sqlite:openbbq/providers/openai-compatible/api_key",
```

No API key reference input should be used in this test.

- [ ] **Step 5: Update ASR section test for selector and download rows**

In `"switches to ASR and shows faster-whisper defaults and status"`, keep the existing navigation and replace the ASR assertions with:

```typescript
    const modelSelect = screen.getByLabelText("Default model");
    expect(modelSelect).toHaveValue("base");
    expect(screen.getByRole("option", { name: "tiny" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "base" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "small" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "medium" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "large-v3" })).toBeInTheDocument();
    expect(screen.getByLabelText("Default device")).toHaveValue("cpu");
    expect(screen.getByLabelText("Default compute type")).toHaveValue("int8");
    expect(screen.getByLabelText("Cache directory")).toHaveValue("C:/Users/alex/.cache/openbbq/models/faster-whisper");
    expect(screen.getByText("base")).toBeInTheDocument();
    expect(screen.getByText("Not downloaded")).toBeInTheDocument();
    expect(screen.getByText("small")).toBeInTheDocument();
    expect(screen.getByText("Downloaded")).toBeInTheDocument();
```

- [ ] **Step 6: Update faster-whisper save test to use select options**

In `"saves faster-whisper defaults"`, replace:

```typescript
    await user.clear(screen.getByLabelText("Default model"));
    await user.type(screen.getByLabelText("Default model"), "small");
```

With:

```typescript
    await user.selectOptions(screen.getByLabelText("Default model"), "small");
```

In `"syncs ASR inputs to canonical saved settings"`, replace the same clear/type pair with `selectOptions`.

- [ ] **Step 7: Add ASR download success test**

Add this test after the ASR save tests:

```typescript
  it("downloads a selected faster-whisper model and refreshes model status", async () => {
    const user = userEvent.setup();
    const downloadedModels: RuntimeModelStatus[] = [
      {
        provider: "faster-whisper",
        model: "base",
        cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
        present: true,
        sizeBytes: 10,
        error: null
      },
      models[1]
    ];
    const loadModels = vi.fn().mockResolvedValueOnce(clone(models)).mockResolvedValueOnce(clone(downloadedModels));
    const downloadFasterWhisperModel = vi.fn().mockResolvedValue(downloadedModels[0]);
    renderSettings({ loadModels, downloadFasterWhisperModel });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.click(screen.getByRole("button", { name: "Download base" }));

    expect(downloadFasterWhisperModel).toHaveBeenCalledWith({ model: "base" });
    expect(loadModels).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Model downloaded.")).toBeInTheDocument();
    expect(screen.getAllByText("Downloaded").length).toBeGreaterThanOrEqual(2);
  });
```

- [ ] **Step 8: Add ASR download failure test**

Add this test after the download success test:

```typescript
  it("renders ASR download failures", async () => {
    const user = userEvent.setup();
    renderSettings({
      downloadFasterWhisperModel: vi.fn().mockRejectedValue(new Error("Model download failed."))
    });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.click(screen.getByRole("button", { name: "Download base" }));

    expect(await screen.findByText("Model download failed.")).toBeInTheDocument();
  });
```

- [ ] **Step 9: Update unavailable ASR status test**

Replace the assertions in `"renders unavailable model status when faster-whisper status is absent"` with:

```typescript
    expect(screen.getAllByText("Status unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText("Model cache missing")).not.toBeInTheDocument();
```

- [ ] **Step 10: Run Settings tests to verify they fail**

Run:

```bash
cd desktop && pnpm test src/components/__tests__/Settings.test.tsx
```

Expected: fail because `SettingsProps` does not include `downloadFasterWhisperModel`, the API key reference still renders, the API key toggle does not exist, and ASR still uses a text input.

---

## Task 5: Settings UI Implementation

**Files:**
- Modify: `desktop/src/components/Settings.tsx`
- Test: `desktop/src/components/__tests__/Settings.test.tsx`

- [ ] **Step 1: Update imports and props**

In `desktop/src/components/Settings.tsx`, change the React import and add lucide icons:

```typescript
import { useEffect, useId, useMemo, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
```

Add `downloadFasterWhisperModel` to `SettingsProps`:

```typescript
  downloadFasterWhisperModel(input: { model: string }): Promise<RuntimeModelStatus>;
```

Destructure it in `Settings(...)` and pass it to `AsrSection` along with model refresh helpers:

```tsx
          <AsrSection
            downloadFasterWhisperModel={downloadFasterWhisperModel}
            loadModels={loadModels}
            models={models}
            saveFasterWhisperDefaults={saveFasterWhisperDefaults}
            settings={settings}
            onModelsChange={setModels}
            onSettingsChange={setSettings}
          />
```

- [ ] **Step 2: Add shared helpers**

Add these constants/helpers near `emptyToNull`:

```typescript
const fallbackFasterWhisperModels = ["tiny", "base", "small", "medium", "large-v3"];

function defaultApiKeyRef(name: string): string {
  return `sqlite:openbbq/providers/${name}/api_key`;
}

function fasterWhisperStatuses(models: RuntimeModelStatus[], defaultModel: string): RuntimeModelStatus[] {
  const statuses = models.filter((model) => model.provider === "faster-whisper");
  const byName = new Map(statuses.map((status) => [status.model, status]));
  const names = Array.from(
    new Set([...fallbackFasterWhisperModels, ...statuses.map((status) => status.model)])
  );
  const orderedNames = orderModelNames(Array.from(new Set(names)), defaultModel);
  return orderedNames.map(
    (model) =>
      byName.get(model) ?? {
        provider: "faster-whisper",
        model,
        cacheDir: "",
        present: false,
        sizeBytes: 0,
        error: "Status unavailable"
      }
  );
}

function orderModelNames(models: string[], defaultModel: string): string[] {
  if (!models.includes(defaultModel)) {
    return models;
  }
  return [defaultModel, ...models.filter((model) => model !== defaultModel)];
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) {
    return "";
  }
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}
```

- [ ] **Step 3: Hide API key reference and keep default reference on save**

In `providerDraft`, change:

```typescript
    apiKeyRef: provider.apiKeyRef ?? `sqlite:openbbq/providers/${provider.name}/api_key`,
```

To:

```typescript
    apiKeyRef: provider.apiKeyRef ?? defaultApiKeyRef(provider.name),
```

In `defaultLlmProvider`, change the `apiKeyRef` expression to:

```typescript
    apiKeyRef: defaultApiKeyRef(name),
```

In `saveProvider`, change:

```typescript
        apiKeyRef: emptyToNull(draft.apiKeyRef),
```

To:

```typescript
        apiKeyRef: emptyToNull(draft.apiKeyRef) ?? defaultApiKeyRef(selected.name),
```

Remove the rendered `TextInput` with label `"API key reference"`.

- [ ] **Step 4: Add API key visibility state and reset it on provider change**

In `LlmProviderSection`, add state after `draft`:

```typescript
  const [secretVisible, setSecretVisible] = useState(false);
```

Inside the `useEffect` that resets selected provider draft, add:

```typescript
    setSecretVisible(false);
```

Replace the API key `TextInput` with:

```tsx
          <SecretInput
            label="API key"
            visible={secretVisible}
            value={draft.secretValue}
            onChange={(secretValue) => setDraft((current) => ({ ...current, secretValue }))}
            onToggleVisible={() => setSecretVisible((current) => !current)}
          />
```

- [ ] **Step 5: Add `SecretInput` and `SelectInput` components**

Add these components above `TextInput`:

```tsx
function SecretInput({
  label,
  onChange,
  onToggleVisible,
  value,
  visible
}: {
  label: string;
  value: string;
  visible: boolean;
  onChange(value: string): void;
  onToggleVisible(): void;
}) {
  const inputId = useId();
  return (
    <div className="grid gap-2">
      <label htmlFor={inputId} className="text-xs font-bold uppercase text-muted">
        {label}
      </label>
      <span className="grid min-h-11 grid-cols-[minmax(0,1fr)_44px] overflow-hidden rounded-md bg-paper shadow-control focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent">
        <input
          id={inputId}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="min-w-0 bg-transparent px-3 text-sm font-normal normal-case text-ink outline-none"
        />
        <button
          type="button"
          aria-label={visible ? "Hide API key" : "Show API key"}
          onClick={onToggleVisible}
          className="grid min-h-11 place-items-center text-muted transition-colors [@media(hover:hover)]:hover:text-ink-brown"
        >
          {visible ? <EyeOff aria-hidden="true" size={18} /> : <Eye aria-hidden="true" size={18} />}
        </button>
      </span>
    </div>
  );
}

function SelectInput({
  label,
  onChange,
  options,
  value
}: {
  label: string;
  value: string;
  options: string[];
  onChange(value: string): void;
}) {
  return (
    <label className="grid gap-2 text-xs font-bold uppercase text-muted">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-11 min-w-0 rounded-md bg-paper px-3 text-sm font-normal normal-case text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
```

- [ ] **Step 6: Extend ASR section props and state**

Change the `AsrSection` signature to include:

```typescript
  downloadFasterWhisperModel,
  loadModels,
  models,
  onModelsChange,
```

Change the prop type block to include:

```typescript
  downloadFasterWhisperModel: SettingsProps["downloadFasterWhisperModel"];
  loadModels: SettingsProps["loadModels"];
  models: RuntimeModelStatus[];
  onModelsChange(models: RuntimeModelStatus[]): void;
```

Replace:

```typescript
  const status = models.find((model) => model.provider === "faster-whisper");
```

With:

```typescript
  const statuses = useMemo(() => fasterWhisperStatuses(models, draft.defaultModel), [models, draft.defaultModel]);
  const modelOptions = useMemo(() => statuses.map((model) => model.model), [statuses]);
  const status = statuses.find((model) => model.model === draft.defaultModel) ?? statuses[0];
  const [downloadingModel, setDownloadingModel] = useState<string | null>(null);
```

- [ ] **Step 7: Add ASR download action**

Inside `AsrSection`, add:

```typescript
  async function downloadModel(model: string) {
    setFeedback(null);
    setMutationError(null);
    setDownloadingModel(model);

    try {
      await downloadFasterWhisperModel({ model });
      const refreshed = await loadModels();
      onModelsChange(refreshed);
      setFeedback("Model downloaded.");
    } catch (error) {
      setMutationError(errorMessage(error, "ASR model could not be downloaded."));
    } finally {
      setDownloadingModel(null);
    }
  }
```

- [ ] **Step 8: Replace ASR default model input with selector**

Replace the `TextInput` labeled `"Default model"` with:

```tsx
          <SelectInput
            label="Default model"
            options={modelOptions}
            value={draft.defaultModel}
            onChange={(defaultModel) => setDraft((current) => ({ ...current, defaultModel }))}
          />
```

- [ ] **Step 9: Replace single status card with model list**

Replace the single rounded status `<div>` after the defaults inputs with:

```tsx
        <div className="mt-4 grid gap-2" aria-label="Downloadable ASR models">
          {statuses.map((model) => {
            const unavailable = model.error === "Status unavailable";
            const statusLabel = unavailable ? "Status unavailable" : model.present ? "Downloaded" : "Not downloaded";
            const busy = downloadingModel === model.model;
            return (
              <div
                key={`${model.provider}-${model.model}`}
                className="grid gap-3 rounded-md bg-paper px-3 py-3 text-sm shadow-control md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
              >
                <div className="min-w-0">
                  <span className="font-bold text-ink-brown">{model.model}</span>
                  <span className={model.present ? "ml-2 font-bold text-ready" : "ml-2 font-bold text-[#8c4d29]"}>
                    {statusLabel}
                  </span>
                  {model.sizeBytes > 0 ? <span className="ml-2 text-muted">{formatBytes(model.sizeBytes)}</span> : null}
                  <p className="mt-1 break-all text-xs text-muted">{model.cacheDir || draft.cacheDir}</p>
                </div>
                <Button
                  variant="secondary"
                  disabled={model.present || unavailable || busy}
                  aria-label={`Download ${model.model}`}
                  onClick={() => void downloadModel(model.model)}
                >
                  {busy ? "Downloading..." : model.present ? "Downloaded" : "Download"}
                </Button>
              </div>
            );
          })}
        </div>
```

- [ ] **Step 10: Run Settings tests**

Run:

```bash
cd desktop && pnpm test src/components/__tests__/Settings.test.tsx
```

Expected: Settings tests pass.

- [ ] **Step 11: Commit Settings UI work**

Run:

```bash
git add desktop/src/components/Settings.tsx desktop/src/components/__tests__/Settings.test.tsx
git commit -m "feat: Add settings ASR model controls"
```

Expected: commit succeeds with only Settings files staged.

---

## Task 6: Final Verification

**Files:**
- Read: `docs/superpowers/specs/2026-04-28-desktop-settings-model-download-design.md`
- Verify: backend and desktop test suites

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_models_lists_supported_faster_whisper_sizes tests/test_api_projects_plugins_runtime.py::test_runtime_downloads_faster_whisper_model_with_fake_adapter tests/test_api_projects_plugins_runtime.py::test_runtime_download_rejects_unsupported_faster_whisper_model tests/test_api_projects_plugins_runtime.py::test_runtime_defaults_and_faster_whisper_routes tests/test_runtime_cli.py::test_models_list_json_reports_faster_whisper_cache -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run focused desktop tests**

Run:

```bash
cd desktop && pnpm test src/components/__tests__/Settings.test.tsx electron/__tests__/ipc.test.ts src/lib/desktopClient.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 3: Run full backend tests**

Run:

```bash
uv run pytest
```

Expected: full backend test suite passes.

- [ ] **Step 4: Run full desktop tests**

Run:

```bash
cd desktop && pnpm test
```

Expected: full desktop Vitest suite passes.

- [ ] **Step 5: Run desktop build**

Run:

```bash
cd desktop && pnpm build
```

Expected: TypeScript, Vite, and Electron build complete successfully.

- [ ] **Step 6: Inspect final diff**

Run:

```bash
git status --short
git diff --stat HEAD
```

Expected: only intentional implementation files are modified since the last commit. If Task 2, Task 3, and Task 5 commits were created, `git status --short` should be clean.

- [ ] **Step 7: Final response**

Report:

- commits created;
- focused tests run;
- full tests/build run;
- any command that could not be run and why.
