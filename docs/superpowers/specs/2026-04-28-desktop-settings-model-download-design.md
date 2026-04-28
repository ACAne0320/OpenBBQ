# Desktop Settings Model Download Design

## Goal

Improve the Desktop Settings page so users can enter an LLM API key directly and manage faster-whisper ASR model downloads from the same screen.

The change should keep the runtime settings model as the source of truth. The Desktop UI should not invent a separate model registry or store credentials outside the existing runtime secret system.

## Current baseline

The current implementation already has:

- `desktop/src/components/Settings.tsx`, which renders LLM provider settings, faster-whisper defaults, diagnostics, and advanced paths.
- `PUT /runtime/providers/{name}/auth`, which can receive a raw `secret_value` and store it behind a secret reference.
- `PUT /runtime/models/faster-whisper`, which saves faster-whisper defaults.
- `GET /runtime/models`, which returns model cache status for the configured faster-whisper default.
- Electron IPC and renderer client methods for reading runtime settings, saving providers, checking provider credentials, saving ASR defaults, and loading model cache status.

The current implementation does not have:

- a backend route that downloads an ASR model on demand;
- a Desktop IPC method for model download;
- a Settings UI that lists downloadable ASR model sizes;
- an API-key visibility toggle;
- a Settings UI that hides the implementation detail of `api_key_ref`.

## Scope

This design includes:

- removing the visible API key reference field from the Settings LLM form;
- adding an eye icon button that toggles the API key field between hidden and visible text;
- preserving the existing backend secret-reference contract by using the provider's current `apiKeyRef`, or the default sqlite reference, when saving a typed API key;
- exposing supported faster-whisper model sizes as selectable ASR defaults;
- listing downloadable faster-whisper model sizes below the ASR defaults form;
- adding a backend route and Electron bridge method that downloads one faster-whisper model size on demand;
- refreshing model cache status after a download completes;
- deterministic tests that do not require network access or real model downloads.

This design excludes:

- progress percentages, pause, resume, and cancel for model downloads;
- background job persistence for downloads;
- automatic downloads when a user saves defaults;
- support for ASR providers other than faster-whisper;
- `.en` faster-whisper model variants;
- GPU auto-detection or compute-type recommendation logic.

## User experience

### LLM provider

The LLM provider form should show:

- Display name
- Base URL
- Default chat model
- API key

The API key field should:

- be hidden by default using an input type of `password`;
- include an icon-only button on the right side;
- use `Eye` when clicking will reveal the key;
- use `EyeOff` when clicking will hide the key;
- expose an accessible label such as `Show API key` or `Hide API key`;
- never echo the typed API key in status messages or secret-check output.

The form should not show `API key reference`. When the user saves a typed API key, the renderer should still submit an `apiKeyRef`:

1. use the selected provider's existing reference when present;
2. otherwise use `sqlite:openbbq/providers/<provider-name>/api_key`.

This keeps direct key entry simple while preserving the backend's current secret storage boundary.

### ASR model

The ASR section should keep the current provider panel for `faster-whisper`.

The runtime defaults form should replace the free-text `Default model` input with a model-size selector. Supported sizes for this slice are:

- `tiny`
- `base`
- `small`
- `medium`
- `large-v3`

The section below the defaults form should list those model sizes. Each row should show:

- model size;
- cache state: `Downloaded`, `Not downloaded`, or `Status unavailable`;
- cached size when available;
- a `Download` button when the model is not cached;
- a disabled busy button while that model is downloading.

Saving defaults and downloading a model are separate actions. A user can download `medium` without making it the default, and can make `small` the default without forcing a download.

## Backend architecture

Add a focused runtime model-download operation in `openbbq.application.runtime`.

```text
Settings UI
  -> Electron IPC
  -> POST /runtime/models/faster-whisper/download
  -> openbbq.application.runtime.faster_whisper_download
  -> faster-whisper download adapter
  -> runtime model status
```

### Supported model sizes

The backend should own the canonical supported sizes so the Desktop UI and CLI cannot drift. The list should live near the faster-whisper asset helpers, for example in `openbbq.runtime.models_assets`.

The supported sizes are `tiny`, `base`, `small`, `medium`, and `large-v3`.

Requests for any other model should fail with the existing validation-error response shape.

### Download route

Add:

```http
POST /runtime/models/faster-whisper/download
```

Request:

```json
{
  "model": "base"
}
```

Response:

```json
{
  "ok": true,
  "data": {
    "model": {
      "provider": "faster-whisper",
      "model": "base",
      "cache_dir": "/home/user/.cache/openbbq/models/faster-whisper",
      "present": true,
      "size_bytes": 123456,
      "error": null
    }
  }
}
```

The route may be synchronous in this slice. The renderer will show a busy state for the selected row until the request resolves. This avoids introducing a download job subsystem before there is a real need for resumable or cancellable downloads.

### Model status

`GET /runtime/models` should return one faster-whisper status per supported model size instead of only the current default model. This lets the Settings page render the downloadable list from backend status rather than hardcoding status client-side.

The status calculation should remain deterministic and filesystem-based. It should not make network calls. If the exact faster-whisper cache layout cannot be identified for a model, the status should return `present: false` instead of raising.

### Download adapter

The application layer should call a small adapter function rather than importing download behavior directly into the route. Tests can inject or monkeypatch that adapter.

The adapter should use the configured `models.faster_whisper.cache_dir` as the download root and request the selected model size from faster-whisper. If the optional `media` dependency is missing, the application should return a clear validation/runtime error that the UI can display.

## Desktop bridge

Add renderer-facing types:

- `DownloadFasterWhisperModelInput`
- `RuntimeModelDownloadResult`

Add client methods:

- `downloadFasterWhisperModel(input: { model: string }): Promise<RuntimeModelStatus>`

Add Electron IPC:

- channel: `openbbq:download-faster-whisper-model`
- implementation: `POST /runtime/models/faster-whisper/download`
- response mapping: API model status DTO to renderer `RuntimeModelStatus`

The mock client should simulate a successful download by marking the selected faster-whisper model as present and assigning a non-zero `sizeBytes`.

## Settings implementation

### API key field

`TextInput` can stay generic for normal fields. The API key field should use a dedicated component so the icon button can sit inside the input frame without changing all text fields.

The dedicated component should keep stable height and width on desktop and mobile. The icon button should not resize the input or overlap typed text.

### ASR model selector

The ASR section should derive available model sizes from `models` where `provider === "faster-whisper"`. If the backend returns no faster-whisper rows, the UI should still render the supported selector using a local fallback list and show `Status unavailable` for each row.

The selector should update `draft.defaultModel`. `Save ASR defaults` should continue to call `saveFasterWhisperDefaults` with the current cache directory, selected default model, device, and compute type.

### Download list

Each download button should call `downloadFasterWhisperModel({ model })`. On success, the UI should refresh `loadModels()` and replace the local model status list. On failure, it should show an inline ASR error.

While one model is downloading, only that row's button needs to be disabled. The rest of the Settings page can remain usable.

## Error handling

Backend validation errors should use the existing API error handling.

The Settings page should display:

- provider-save failures under the LLM form;
- secret-check failures under the LLM form;
- ASR default-save failures under the ASR form;
- ASR download failures under the model list.

The UI must not display a typed API key after save, check, failure, or visibility-toggle operations, except inside the input field while the user has chosen to reveal it.

## Testing

Backend tests should cover:

- `GET /runtime/models` returns one faster-whisper status per supported model size;
- `POST /runtime/models/faster-whisper/download` accepts a supported model and returns updated status;
- unsupported model names are rejected;
- download behavior can be tested with a fake adapter and no network access.

Electron tests should cover:

- the IPC handler posts to the download route and maps the response to `RuntimeModelStatus`;
- the desktop client forwards `downloadFasterWhisperModel`.

Renderer tests should cover:

- API key reference is not rendered;
- API key input is hidden by default;
- clicking the eye button reveals and hides the API key field;
- saving a provider still sends the current or default sqlite API key reference;
- ASR default model uses a selector;
- the model list renders downloadable faster-whisper sizes;
- clicking `Download` calls the new client prop and refreshes model status;
- download errors render inline.

## Documentation

Update repository documentation only where behavior changes are user-visible:

- mention that Desktop stores typed API keys through the local runtime secret reference;
- mention that ASR model downloads can be triggered from Settings;
- document the new runtime API route if API routes are documented nearby.

## Risks and tradeoffs

Synchronous downloads can keep an HTTP request open for a long time. That is acceptable for this first Desktop settings slice because it keeps state management simple and avoids a job system. If downloads prove unreliable over long requests, the next step should be a runtime asset-job API with progress events.

Model cache detection may not perfectly match every faster-whisper or Hugging Face cache layout. The implementation should prefer conservative `present: false` results over false positives. Running a download for an already-present model should be harmless because the underlying downloader should reuse cached files.

Removing the visible API key reference reduces advanced control in the Desktop MVP. The Advanced section can keep read-only paths, and CLI/API users can still manage references directly.

## Acceptance criteria

- Users can enter an API key directly in Settings without seeing or editing `apiKeyRef`.
- API key input is hidden by default and can be toggled visible with an icon button.
- Saving a typed API key still stores it through the existing secret-reference mechanism.
- Users can choose a faster-whisper model size from a selector.
- Users can see supported faster-whisper model sizes below the ASR defaults form.
- Users can download a selected model size on demand.
- Model status refreshes after a successful download.
- Unit tests cover backend, Electron bridge, and renderer behavior without real network downloads.
