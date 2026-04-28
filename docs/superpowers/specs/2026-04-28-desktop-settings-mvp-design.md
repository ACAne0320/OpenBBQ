# Desktop Settings MVP design

> Status: design approved. Implementation has not started.

## Goal

Add a first real desktop Settings surface for runtime configuration used by the
subtitle quickstart flows. The MVP lets a user configure the default LLM
provider, configure faster-whisper ASR defaults, inspect runtime readiness, and
view advanced paths without exposing provider credentials in workflow files.

Settings becomes the source of truth for runtime provider and model choices in
the desktop quickstart flow. The workflow editor remains focused on task
parameters, not credential or runtime model management.

## Current baseline

The backend already has the core runtime foundation:

- runtime settings models for provider profiles and faster-whisper settings;
- local secret references through environment, SQLite, and keyring schemes;
- provider auth write routes;
- runtime settings, model status, and doctor routes;
- quickstart job creation that can use faster-whisper runtime defaults when ASR
  request fields are omitted.

The desktop renderer does not yet expose Settings:

- the global nav contains `Settings`, but `App` has no settings screen;
- the renderer client and preload API have no runtime settings methods;
- Electron quickstart mapping currently fills hard-coded provider and ASR
  fallbacks, which prevents backend runtime defaults from being the single source
  of truth;
- workflow steps are still frontend/Electron templates, not plugin-driven forms.

## Product decisions

The first Settings MVP includes:

- LLM provider setup for OpenAI-compatible endpoints;
- API key entry and redacted secret status;
- default LLM provider selection;
- ASR provider defaults for faster-whisper;
- faster-whisper model/cache status;
- runtime diagnostics;
- read-only advanced paths.

The first Settings MVP excludes:

- ASR model download management;
- provider presets for named vendors;
- provider types other than `openai_compatible`;
- plugin-driven workflow editing;
- interface language settings and i18n resource migration;
- editable advanced runtime paths outside the specific ASR cache setting;
- future sections such as general settings, glossary, and system prompts.

Because the project is still in development, this design does not preserve old
runtime settings compatibility. The implementation can update the config schema
directly and adjust tests and fixtures with the new defaults.

## Settings information architecture

The desktop Settings page uses section navigation:

- `LLM provider`
- `ASR model`
- `Diagnostics`
- `Advanced`

Only implemented sections appear in the first release. Future sections such as
`General`, `Prompts`, and `Glossary` should be added later using the same
section pattern rather than appearing as disabled placeholders now.

`LLM provider` and `ASR model` each have one more level of navigation inside the
section:

- the section selects the capability area;
- a provider/profile list selects the concrete profile;
- the details panel edits or displays that provider;
- the selected default provider is explicit.

This keeps the MVP simple while leaving room for multiple LLM profiles and future
ASR providers.

## Runtime settings model

Runtime settings should explicitly store default runtime providers:

```toml
[defaults]
llm_provider = "openai-compatible"
asr_provider = "faster-whisper"

[providers.openai-compatible]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "sqlite:openbbq/providers/openai-compatible/api_key"
default_chat_model = "gpt-4o-mini"

[models.faster_whisper]
cache_dir = "~/.cache/openbbq/models/faster-whisper"
default_model = "base"
default_device = "cpu"
default_compute_type = "int8"
```

Naming rules:

- UI copy uses `LLM provider`, not `AI provider`.
- The default LLM profile name is `openai-compatible`.
- The provider type remains `openai_compatible`.
- The default ASR provider is `faster-whisper`.

Backend models should add a defaults object:

```python
class RuntimeDefaults(OpenBBQModel):
    llm_provider: str = "openai-compatible"
    asr_provider: str = "faster-whisper"
```

`RuntimeSettings` should include `defaults: RuntimeDefaults`.

The first implementation can keep the ASR provider data under
`models.faster_whisper`, because faster-whisper is the only ASR provider in this
slice. API and UI naming should still treat it as an ASR provider so future ASR
providers do not require a Settings page redesign.

## Backend API design

Reuse the existing provider and secret routes where they already fit:

```text
GET /runtime/settings
PUT /runtime/providers/{name}/auth
GET /runtime/providers/{name}/check
GET /runtime/models
GET /doctor
```

Add focused write contracts:

```text
PUT /runtime/defaults
PUT /runtime/models/faster-whisper
```

`PUT /runtime/defaults` stores:

```json
{
  "llm_provider": "openai-compatible",
  "asr_provider": "faster-whisper"
}
```

`PUT /runtime/models/faster-whisper` stores:

```json
{
  "cache_dir": "~/.cache/openbbq/models/faster-whisper",
  "default_model": "base",
  "default_device": "cpu",
  "default_compute_type": "int8"
}
```

`GET /runtime/models` should report the selected faster-whisper model status
using the configured model and cache directory. The MVP reports local status only
and never starts a download.

## Quickstart defaults

Desktop quickstart task creation should stop sending hard-coded runtime
fallbacks. In real desktop mode, if the workflow editor does not expose a runtime
field, the Electron request mapper should omit it so the backend resolves
runtime defaults.

When a quickstart request omits fields, backend job creation should use:

- provider: `settings.defaults.llm_provider`;
- LLM model: selected provider's `default_chat_model`;
- ASR provider: `settings.defaults.asr_provider`;
- ASR model/device/compute type: configured faster-whisper defaults.

Explicit API request values still win over runtime defaults, but the desktop UI
does not expose those overrides in this MVP.

If the configured default LLM provider does not exist or its secret is
unresolved, preflight or task creation should fail clearly. The implementation
must not silently fall back to another provider.

## Desktop client contract

Extend the renderer client and Electron preload API with runtime settings
methods:

```ts
getRuntimeSettings(): Promise<RuntimeSettingsModel>;
saveRuntimeDefaults(input: {
  llmProvider: string;
  asrProvider: string;
}): Promise<RuntimeSettingsModel>;
saveLlmProvider(input: {
  name: string;
  type: "openai_compatible";
  baseUrl?: string | null;
  defaultChatModel?: string | null;
  secretValue?: string | null;
  apiKeyRef?: string | null;
  displayName?: string | null;
}): Promise<LlmProviderModel>;
checkLlmProvider(name: string): Promise<ProviderCheckModel>;
saveFasterWhisperDefaults(input: {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
}): Promise<RuntimeSettingsModel>;
getRuntimeModels(): Promise<ModelStatusModel[]>;
getDiagnostics(): Promise<DoctorModel>;
```

The renderer should not call arbitrary HTTP routes directly. Electron main owns
HTTP calls to the FastAPI sidecar and returns typed UI-oriented data.

## Section behavior

### LLM provider

The section shows a provider/profile list and details for the selected profile.
The default profile is marked in the list. The details panel supports:

- provider name;
- provider type, fixed to OpenAI-compatible in this MVP;
- base URL;
- default chat model;
- API key entry;
- save;
- check secret;
- set as default.

Saving a provider with a secret value should store the secret through the backend
secret resolver and store only a secret reference in runtime settings.

### ASR model

The section shows an ASR provider list. The first provider is `faster-whisper`,
marked as default. The details panel supports:

- default model;
- default device;
- default compute type;
- cache directory;
- model/cache status.

The MVP should clearly report missing model/cache status. It must not show a
download progress UI or imply that OpenBBQ manages downloads in this slice.

### Diagnostics

Diagnostics aggregates:

- runtime settings load status;
- provider secret checks;
- model/cache status;
- doctor checks.

Raw backend messages can appear here. Primary task creation screens should show
only actionable summaries.

### Advanced

Advanced is read-only in this MVP. It can show:

- runtime config path;
- cache root;
- faster-whisper cache directory;
- active project path;
- sidecar status;
- safe diagnostic metadata.

Advanced must not expose or edit resolved secret values.

## Workflow editor impact

Workflow editor should continue to show task-specific parameters only. It should
not render LLM provider, LLM model, ASR model, ASR device, or ASR compute controls
in this MVP.

The existing hard-coded workflow templates can remain. Plugin-driven parameter
generation and workflow template metadata are separate follow-up work.

## Error handling

Settings page load failure:

- show a page-level error and retry action;
- avoid falling back to mock runtime settings in real desktop mode.

Provider save failure:

- keep the user's entered values in the form;
- show the backend validation or secret storage error;
- do not write partial UI state as saved.

Secret check failure:

- display unresolved status and backend error;
- never reveal the API key value.

ASR model status:

- missing model is a warning/blocking setup status depending on context;
- no download action is promised in this MVP.

Task creation:

- fail clearly when the default provider is missing or unresolved;
- avoid silent fallback to `openai` or `base`.

## Testing strategy

Backend tests:

- parse and write runtime defaults;
- save provider auth for `openai-compatible`;
- save faster-whisper defaults;
- report faster-whisper status for the configured model/cache;
- quickstart local and YouTube jobs use runtime defaults when request fields are
  omitted;
- missing default provider produces a clear validation/runtime error.

Electron tests:

- runtime settings IPC maps to the expected sidecar routes;
- Settings errors are normalized consistently;
- quickstart request mapping no longer injects hard-coded provider or ASR
  fallback values for real desktop task creation.

Renderer tests:

- Settings opens from global nav;
- section navigation switches between LLM provider, ASR model, Diagnostics, and
  Advanced;
- LLM provider list marks the default provider;
- saving provider and setting default update the view;
- ASR defaults save and model status render;
- Diagnostics and Advanced render safe status/path data;
- workflow editor does not show runtime provider/model controls.

Verification should include the existing desktop and backend suites once
implemented:

```bash
cd desktop
pnpm test
pnpm build

cd ..
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Follow-up work

Keep these outside the MVP:

- ASR model download and progress management;
- vendor presets for OpenAI-compatible providers;
- additional LLM provider types;
- additional ASR providers;
- plugin-driven workflow editor forms;
- workflow template metadata from the backend;
- glossary and system prompt Settings sections;
- interface language settings and renderer i18n migration;
- request-specific quickstart preflight endpoints.

## Acceptance criteria

- Settings is reachable from the desktop global nav.
- Settings uses section navigation with only implemented MVP sections visible.
- LLM provider section supports OpenAI-compatible provider setup.
- The default LLM provider is explicit and defaults to `openai-compatible`.
- API keys are stored as secret references and displayed only as redacted status.
- ASR model section supports faster-whisper default model/device/compute/cache
  configuration.
- The default ASR provider is explicit and defaults to `faster-whisper`.
- Runtime model status reports the configured faster-whisper model/cache state.
- New desktop quickstart tasks use runtime defaults rather than hard-coded
  provider or ASR fallbacks.
- Workflow editor does not expose runtime provider/model controls in the MVP.
- Diagnostics and Advanced expose troubleshooting data without leaking secrets.

## Self-review

- Placeholder scan: no placeholder sections or unresolved work markers remain.
- Internal consistency: Settings is the runtime source of truth, while workflow
  edit remains task-parameter focused.
- Scope check: the MVP is focused on runtime provider/default configuration and
  excludes model downloads, plugin-driven workflow editing, and i18n.
- Ambiguity check: provider naming, default provider behavior, and ASR download
  exclusion are explicit.
