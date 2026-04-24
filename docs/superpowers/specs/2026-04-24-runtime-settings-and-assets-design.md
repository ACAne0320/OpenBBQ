# Runtime Settings and Assets Design

## Goal

Add a runtime settings layer that lets OpenBBQ run real media workflows with user-editable provider profiles, credential references, and model cache settings. The layer must work from the CLI first and remain reusable by the future Desktop UI.

The target is not a Desktop screen in this slice. The target is a backend configuration domain that a Desktop screen can edit later without inventing a second settings model.

## Problem Statement

Phase 2 can validate and run real media workflows, but real users still need to configure machine-specific runtime state outside `openbbq.yaml`:

- LLM translation and transcript correction need API credentials.
- OpenAI-compatible providers need editable base URLs and model defaults.
- `faster-whisper` downloads and caches models through third-party defaults that OpenBBQ does not inspect or manage.
- ffmpeg, yt-dlp, optional Python dependencies, browser cookies, and model downloads can fail only after a workflow has started.
- The future Desktop UI needs settings it can read, validate, and edit without writing secrets into project workflow files.

The current implementation reads `OPENBBQ_LLM_API_KEY` and `OPENBBQ_LLM_BASE_URL` inside the LLM-backed plugins. That works for early CLI smoke tests, but it does not give users a durable settings surface or a clear place to manage model assets.

## Current Baseline

Current code facts:

- [`src/openbbq/config/loader.py`](../../../src/openbbq/config/loader.py) loads project-scoped `openbbq.yaml`. It supports project metadata, storage roots, plugin paths, and workflow definitions.
- [`src/openbbq/domain/models.py`](../../../src/openbbq/domain/models.py) has `StorageConfig` for project artifacts and state, but no runtime settings, provider, secret, or cache model.
- [`src/openbbq/builtin_plugins/translation/plugin.py`](../../../src/openbbq/builtin_plugins/translation/plugin.py) and [`src/openbbq/builtin_plugins/transcript/plugin.py`](../../../src/openbbq/builtin_plugins/transcript/plugin.py) read `OPENBBQ_LLM_API_KEY` and `OPENBBQ_LLM_BASE_URL` directly.
- [`src/openbbq/builtin_plugins/faster_whisper/plugin.py`](../../../src/openbbq/builtin_plugins/faster_whisper/plugin.py) calls `WhisperModel(model_name, device=device, compute_type=compute_type)` without an OpenBBQ-managed cache path.
- [`src/openbbq/workflow/execution.py`](../../../src/openbbq/workflow/execution.py) builds the plugin request in memory. Step run records store input artifact version IDs and output bindings, not the full request payload.
- [`docs/Target-Workflows.md`](../../../docs/Target-Workflows.md) documents real workflows that depend on LLM API access, faster-whisper model availability, ffmpeg, and yt-dlp.

There is no `docs/solutions/` directory with prior decisions for this topic. The GitHub CLI is not available in the current environment, so related remote issues or pull requests could not be checked through `gh`. A web search did not surface existing public issue or PR discussions for this repository.

## Scope

This design includes:

- a user-level runtime settings file;
- provider profiles for OpenAI-compatible LLM use;
- secret references that keep API keys out of project configs, workflow state, artifact metadata, event logs, and lineage;
- a secret resolver with environment-variable and keyring-backed references;
- an OpenBBQ cache root and faster-whisper model cache settings;
- a runtime context object passed to built-in plugins;
- CLI commands that the future Desktop UI can mirror or call through the backend;
- preflight checks for credentials, binaries, optional dependencies, network endpoints, and model availability;
- deterministic tests that do not require real credentials, network access, ffmpeg, yt-dlp, or model downloads.

This design excludes:

- Desktop UI implementation;
- HTTP API routes;
- multi-user accounts, cloud sync, and team credential sharing;
- encrypted project-local vault files;
- provider-specific SDK abstractions beyond the existing OpenAI-compatible chat completions path;
- managed model registries or plugin marketplace features;
- automatic paid API calls during normal validation.

## Design Principles

Keep `openbbq.yaml` project-reproducible. Project configs should describe workflows and artifact storage, not local account credentials or machine cache paths.

Keep user runtime settings editable. The settings file should be plain structured data so the CLI and future Desktop UI can present the same provider and cache fields.

Keep secret values out of persisted workflow data. Runtime code may resolve a secret into memory, but persisted state must store only secret references or redacted labels.

Prefer explicit preflight failures. Users should be able to learn that a model is missing, a key is unresolved, or ffmpeg is unavailable before a long workflow starts.

Preserve current environment-variable workflows. Existing smoke-test instructions using `OPENBBQ_LLM_API_KEY` should keep working while the new settings layer lands.

## Architecture

```text
CLI commands or future Desktop UI
        |
        v
Runtime settings service
        |
        +-- user settings file
        +-- secret resolver
        +-- model asset registry
        +-- preflight checks
        |
        v
Workflow execution builds an in-memory plugin request
        |
        v
Built-in plugins consume runtime context
        |
        +-- translation.translate
        +-- transcript.correct
        +-- faster_whisper.transcribe
        +-- remote_video.download
```

The runtime settings service is a Python backend module, not a daemon. The CLI imports it directly. A later Desktop API can import the same service and expose it through UI endpoints.

## User Settings File

OpenBBQ should load a user-level TOML file from:

```text
~/.openbbq/config.toml
```

The location can be overridden by:

```text
OPENBBQ_USER_CONFIG
```

The file should use a versioned schema:

```toml
version = 1

[cache]
root = "~/.cache/openbbq"

[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "keyring:openbbq/providers/openai/api_key"
default_chat_model = "gpt-4o-mini"

[providers.local_gateway]
type = "openai_compatible"
base_url = "http://127.0.0.1:8000/v1"
api_key = "env:OPENBBQ_LOCAL_LLM_API_KEY"
default_chat_model = "qwen2.5-14b-instruct"

[models.faster_whisper]
cache_dir = "~/.cache/openbbq/models/faster-whisper"
default_model = "base"
default_device = "cpu"
default_compute_type = "int8"
```

Project config may refer to a provider by name:

```yaml
parameters:
  provider: openai
  source_lang: en
  target_lang: zh-Hans
  model: gpt-4o-mini
```

If a workflow omits `provider`, built-in LLM-backed tools should use `openai_compatible` compatibility behavior for one transition period:

- `OPENBBQ_LLM_API_KEY` remains accepted;
- `OPENBBQ_LLM_BASE_URL` remains accepted;
- `base_url` in workflow parameters continues to override the environment default.

After the transition, docs can steer users toward named provider profiles while leaving environment variables as a supported advanced path.

## Secret References

Secrets should be represented as references, not values:

```text
env:OPENBBQ_LLM_API_KEY
keyring:openbbq/providers/openai/api_key
```

Supported reference schemes:

- `env:<NAME>` reads the current process environment.
- `keyring:<SERVICE>/<USERNAME>` reads from the OS keychain through Python `keyring`.

The `keyring` dependency should be optional:

```toml
[project.optional-dependencies]
secrets = ["keyring>=25"]
```

When `keyring` is missing or unsupported on the host, OpenBBQ should report a clear preflight error and continue to support `env:` references. It should not silently write secret values to disk as a fallback.

The secret resolver returns a redacted descriptor for display:

```json
{
  "reference": "keyring:openbbq/providers/openai/api_key",
  "resolved": true,
  "display": "keyring:openbbq/providers/openai/api_key",
  "value_preview": "sk-...abcd"
}
```

Only in-memory plugin runtime context receives the full value. Logs, events, exceptions, state records, and artifact metadata must not include resolved secret values.

## Runtime Context

Workflow execution should build a runtime context once per run and include it in plugin requests:

```json
{
  "runtime": {
    "providers": {
      "openai": {
        "type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "api_key": "<resolved in memory>",
        "default_chat_model": "gpt-4o-mini"
      }
    },
    "cache": {
      "root": "/Users/alex/.cache/openbbq",
      "faster_whisper": "/Users/alex/.cache/openbbq/models/faster-whisper"
    }
  }
}
```

This object is part of the in-memory request only. `ProjectStore` should not persist it.

Built-in plugins should prefer runtime context and fall back to existing environment variables during the compatibility period:

1. explicit provider profile from `parameters.provider`;
2. default provider profile from user settings when one exists;
3. legacy `OPENBBQ_LLM_API_KEY` and `OPENBBQ_LLM_BASE_URL`.

Plugin metadata may include the provider name and base URL host, but not the API key reference or resolved value.

## Provider Profiles

The first provider type is:

```text
openai_compatible
```

A provider profile contains:

- `type`: required, currently `openai_compatible`;
- `base_url`: optional for OpenAI SDK defaults, required for local gateways;
- `api_key`: optional secret reference;
- `default_chat_model`: optional model name used by tools when workflow parameters omit `model`;
- `display_name`: optional Desktop-friendly label.

The current built-in tools should use provider profiles as follows:

- `translation.translate` uses the selected provider for translation.
- `llm.translate` remains a compatibility alias and uses the same provider resolution.
- `transcript.correct` uses the selected provider for source-language correction.

Provider validation must reject unknown provider names at workflow validation or preflight time. It should not wait until the plugin starts if the settings file is available.

## Model Assets and Cache

OpenBBQ should own a cache root:

```text
~/.cache/openbbq
```

The cache root can be configured through:

1. `OPENBBQ_CACHE_DIR`;
2. `[cache].root` in user settings;
3. default `~/.cache/openbbq`.

The faster-whisper cache defaults to:

```text
<cache.root>/models/faster-whisper
```

`faster_whisper.transcribe` should pass the configured cache path to `WhisperModel` when the upstream API supports it. If the exact parameter differs by faster-whisper version, the plugin should use a small adapter with tests against fake model factories. The plugin must not depend on a real model download in default tests.

OpenBBQ should track model assets as local filesystem facts, not as artifact versions:

- provider: `faster_whisper`;
- model name;
- cache directory;
- present or missing;
- total size when present;
- last checked timestamp;
- optional error from the last check.

Model assets are runtime dependencies. They are not workflow artifacts because they are not produced by a workflow step and should not be copied into project storage.

## CLI Surface

The CLI should expose runtime settings through commands that map cleanly to future Desktop actions.

Suggested commands:

```bash
openbbq settings show --json
openbbq settings set-provider openai --type openai_compatible --base-url https://api.openai.com/v1 --default-chat-model gpt-4o-mini
openbbq secret set keyring:openbbq/providers/openai/api_key
openbbq secret check keyring:openbbq/providers/openai/api_key --json
openbbq models list --json
openbbq models check faster_whisper base --json
openbbq doctor --workflow local-video-translate-subtitle --project ./demo --json
```

`secret set` should read the value interactively when not in JSON mode. In JSON mode it should require a safer non-echo input mechanism or return a clear error. The CLI should not accept secret values as normal command arguments because shell history can capture them.

`doctor` should return structured checks:

```json
{
  "ok": false,
  "checks": [
    {
      "id": "provider.openai.api_key",
      "status": "failed",
      "severity": "error",
      "message": "Provider 'openai' API key reference is not resolved."
    },
    {
      "id": "binary.ffmpeg",
      "status": "passed",
      "severity": "error",
      "message": "ffmpeg is available."
    }
  ]
}
```

The Desktop UI can render this same JSON as settings status, setup checklist, or run preflight output.

## Preflight Checks

Preflight should support two levels:

- `settings` checks user-level configuration without a project workflow.
- `workflow` checks only the dependencies needed by a selected workflow.

Checks should cover:

- selected provider exists;
- secret reference resolves;
- optional keyring dependency is installed when a `keyring:` reference is used;
- OpenAI-compatible base URL is syntactically valid;
- optional network probe for provider reachability when the user requests it;
- ffmpeg binary exists when `ffmpeg.extract_audio` is used;
- yt-dlp import succeeds when `remote_video.download` is used;
- browser cookie strategy has enough local support to attempt download when configured;
- faster-whisper import succeeds when `faster_whisper.transcribe` is used;
- configured model cache directory is writable;
- requested faster-whisper model is present or will require download;
- project artifact and state directories are writable.

Network probes must be opt-in for normal validation. Default validation should not call paid APIs or download models.

## Desktop Reuse

The Desktop UI should not write workflow YAML to store user secrets. It should use the runtime settings service for these screens:

- provider profile list and editor;
- secret status and secret setup prompts;
- model cache location and disk usage;
- model availability checks;
- preflight checklist before a run;
- workflow step parameter editor that can offer provider names and default models.

The UI can write the user settings file through backend calls. It should store secret values through the secret resolver, not by editing TOML directly.

## Security and Privacy

The settings file may store provider names, base URLs, model names, and secret references. It must not store resolved secret values.

OpenBBQ should redact these patterns from plugin errors before writing events or step run errors:

- values resolved from secret references;
- strings matching known API key prefixes from configured providers;
- authorization headers if future plugins expose raw HTTP errors.

Artifact metadata should not include:

- API keys;
- secret references;
- browser cookie paths;
- full local model cache paths unless the user explicitly asks for local diagnostic output.

Step metadata may include:

- provider name;
- provider type;
- model name;
- cache provider name;
- whether a model was already cached.

## Migration and Compatibility

The first implementation should preserve current workflows:

- `OPENBBQ_LLM_API_KEY` still works.
- `OPENBBQ_LLM_BASE_URL` still works.
- workflow-level `base_url` still works.
- existing fixtures that specify `model` continue to validate.

New provider profiles add a clearer path:

```yaml
parameters:
  provider: openai
  model: gpt-4o-mini
```

If both a provider profile and legacy environment variables are present, the provider profile wins for steps that name it. Legacy variables apply only when no provider profile is selected.

## Error Handling

Settings loading errors should fail with `ValidationError` and point to the bad field path.

Secret resolution errors should not reveal secret values. They should include the unresolved reference and the dependency that failed, such as missing `keyring`.

Plugin execution should continue to use existing step error policies. Runtime settings errors that can be detected before the plugin starts should be reported by `doctor` and, when possible, by workflow validation.

Model cache errors should distinguish:

- cache directory is not writable;
- model is missing but can be downloaded later;
- model download failed during an explicit download operation;
- model load failed even though files are present.

## Testing Strategy

Default tests should stay deterministic and offline.

Unit tests:

- load default user settings when the file is absent;
- load valid TOML user settings;
- reject unsupported config versions;
- reject provider profiles with unknown types;
- resolve `env:` secrets with fake environments;
- report missing `env:` secrets without leaking values;
- resolve `keyring:` secrets with a fake keyring backend;
- report missing keyring dependency;
- compute cache roots from env, user config, and defaults;
- build runtime context without persisting it in step run records;
- redact resolved secrets from error messages.

Plugin tests:

- `translation.translate` uses provider profile credentials when present;
- `translation.translate` falls back to legacy environment variables;
- `transcript.correct` uses the same provider resolution path;
- `faster_whisper.transcribe` receives the configured cache directory through a fake model factory;
- plugin metadata excludes secret values and secret references.

CLI tests:

- `settings show --json` returns redacted provider data;
- `secret check --json` reports resolved and unresolved references;
- `models list --json` reports configured faster-whisper cache state without downloading;
- `doctor --json` reports workflow-specific missing dependencies;
- JSON mode does not prompt for secret values.

Integration tests:

- a translated subtitle fixture validates with provider names and fake secrets;
- a workflow preflight catches missing LLM credentials before execution;
- a local video workflow preflight catches missing ffmpeg or missing faster-whisper optional dependency through fake probes.

Optional local smoke tests:

- real ffmpeg check;
- real faster-whisper import;
- cached `tiny` or `base` model check;
- opt-in provider reachability probe using a user-provided API key.

## Rollback

This layer is additive. If the direction changes, OpenBBQ can keep legacy environment-variable support and ignore user settings. Project configs and artifact state remain compatible because the runtime context is not persisted.

Existing workflows should not require migration. New provider-profile workflows can be converted back by replacing `provider: <name>` with legacy `base_url` plus environment variables.

## External Dependencies

This design depends on:

- Python `keyring` for OS keychain access when users choose `keyring:` secret references;
- environment variables for the no-extra-dependency secret path;
- OpenAI-compatible chat completions endpoints for LLM translation and transcript correction;
- ffmpeg for local audio extraction;
- yt-dlp for remote video download;
- faster-whisper and its model download behavior for ASR;
- browser cookie stores when users choose browser-cookie video download.

Default tests should fake or skip all external systems.

## Acceptance Criteria

The design is ready to implement when OpenBBQ provides:

- a versioned user runtime settings loader;
- provider profile models for OpenAI-compatible LLM use;
- secret reference resolution for `env:` and `keyring:`;
- redacted settings display suitable for CLI and Desktop UI;
- a runtime context path from workflow execution to built-in plugins;
- model cache settings for faster-whisper;
- `doctor` or equivalent preflight output with structured checks;
- deterministic tests proving credential resolution, cache selection, plugin integration, and redaction;
- documentation that explains where API keys and model files should live.
