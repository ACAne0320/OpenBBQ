# CLI Spec

## Goals

The CLI is the primary Phase 1 interface. It must support local development, workflow debugging, artifact inspection, and future automation.

The command name is `openbbq`.

## Global Options

- `--project <path>`: project root. Defaults to current directory.
- `--config <path>`: explicit project config path.
- `--plugins <path>`: additional plugin search path. May be repeated.
- `--json`: emit machine-readable JSON when supported.
- `--verbose`: include more diagnostic output.
- `--debug`: include debug output and stack traces for OpenBBQ errors.

## Exit Codes

- `0`: success.
- `1`: general runtime failure.
- `2`: invalid command usage.
- `3`: validation failure.
- `4`: plugin discovery or manifest failure.
- `5`: workflow execution failure.
- `6`: artifact lookup failure.

## Output Rules

Human-readable output should be concise and stable enough for documentation examples.

JSON output should:

- emit one JSON object.
- include `ok: true` or `ok: false`.
- include `error.code` and `error.message` on failure.
- avoid stack traces unless `--debug` is set.

## Project Commands

### `openbbq init`

Scaffold a project in the current directory unless `--project` is provided.

Creates:

- project config file.
- artifact storage directory.
- workflow state directory.
- optional plugin directory.

### `openbbq project list`

List known projects in the current workspace when workspace discovery exists. For Phase 1, this may return only the current project.

### `openbbq project info`

Show project ID, name, root path, config path, workflow count, plugin search paths, and artifact storage path.

## Workflow Commands

### `openbbq run <workflow>`

Validate and execute a workflow end to end.

Rejects with exit code `1` if the workflow is `running` (lock file held by a live process), `paused`, or `completed`. Use `--force` to override the completed check and force a full rerun.

Options:

- `--step <step-id>`: rerun a single step by its ID. Allowed when the workflow status is `completed` or `failed`; rejected if `running` or `paused`. Creates a new `StepRun` and new artifact versions for that step's outputs. Downstream artifacts are **not** invalidated in Phase 1. Does not require `--force` and cannot be combined with it.
- `--force`: allow rerunning a `completed` or crash-recovered `running` workflow (no lock file present). Resets the workflow state to `pending`, marks any dangling `running` StepRuns as `failed`, and starts a fresh execution from the beginning. New `ArtifactVersion` records are created; existing `Artifact` IDs are reused where prior output bindings exist. Cannot be combined with `--step`.

### `openbbq resume <workflow>`

Resume a `paused` workflow from persisted state. Rebuilds the output binding map from the recorded `StepRun` history and continues from `current_step_id`.

Rejects with exit code `1` if the workflow is not in `paused` status.

### `openbbq status <workflow>`

Show workflow status, current step, last event, produced artifacts, and failure summary when applicable.

### `openbbq abort <workflow>`

Request a workflow to stop and transition to `aborted`.

- For `paused` workflows: synchronous. Transitions immediately to `aborted`, persists state, removes the lock file, and returns exit code `0`.
- For `running` workflows: returns immediately after writing an abort request file at `<workflow-state-dir>/<workflow-id>.abort_requested` (atomic rename). The CLI does **not** write to the event log — the running engine emits `workflow.abort_requested` and `workflow.aborted` when it observes the file between steps. Prints a message that the abort will take effect between steps and returns exit code `0`. Use `openbbq status <workflow>` to confirm when the status reaches `aborted`.

Returns exit code `1` if the workflow is not in an abortable state (`completed`, `aborted`, `failed`, or `pending`).

### `openbbq unlock <workflow>`

Remove a stale lock file left by a crashed process. Prints the PID recorded in the lock file and requires confirmation before removing it unless `--yes` is passed.

This command **only** clears the lock file. It does not modify workflow status, StepRun records, or artifacts. After clearing a stale lock, the workflow status may be `pending` if the process crashed before status persistence, or `running` if it crashed after execution state changed.

Recommended recovery:

```
openbbq unlock <workflow>          # clear the stale lock
openbbq run <workflow>             # if status is still pending
openbbq run <workflow> --force     # if status is running after crash
```

`run --force` handles the `running` status left by the crash: it marks dangling `running` StepRuns as `failed` and resets the workflow to `pending` before starting fresh.

Should only be used when `openbbq run` or `openbbq resume` reports a stale lock and the recorded PID is no longer running. Using this command while the workflow is genuinely running will corrupt workflow state.

## Artifact Commands

### `openbbq artifact list`

List artifacts for a project or workflow.

Useful filters:

- `--workflow <workflow>`
- `--step <step-id>`
- `--type <artifact-type>`

### `openbbq artifact show <id>`

Display artifact metadata and content preview. With `--json`, include version metadata and lineage.

### `openbbq artifact diff <v1> <v2>`

Compare two artifact versions.

Phase 1 supports text diff only:

- Both IDs must resolve to `ArtifactVersion` records.
- Both versions must belong to artifacts of type `text`, `subtitle`, or another artifact type whose stored content is plain text.
- If either version is missing, return exit code `6`.
- If either version is binary or an unsupported structured type, return exit code `3` with a validation error.
- Human-readable output should use unified diff format with stable headers:

```text
--- <v1>
+++ <v2>
```

- JSON output should emit one object:

```json
{
  "ok": true,
  "from": "<v1>",
  "to": "<v2>",
  "format": "unified",
  "diff": "--- <v1>\n+++ <v2>\n..."
}
```

## Plugin Commands

### `openbbq plugin list`

List discovered plugins and mark invalid plugins with validation errors.

### `openbbq plugin info <name>`

Show plugin manifest, tool declarations, parameter schemas, and declared effects.

## Diagnostics Commands

### `openbbq logs <workflow>`

Print workflow events in chronological order. Phase 1 can implement this as event log output instead of live streaming.

### `openbbq validate <workflow>`

Validate workflow config, plugin references, parameters, artifact type compatibility, and output declarations without executing plugin code.

## Configuration Precedence

When the same setting appears in multiple places, use this order:

1. CLI flags.
2. Environment variables.
3. Project config.
4. Built-in defaults.

Initial environment variables:

- `OPENBBQ_PROJECT`
- `OPENBBQ_CONFIG`
- `OPENBBQ_PLUGIN_PATH`
- `OPENBBQ_LOG_LEVEL`

For scalar settings such as project root, config path, and log level, the highest-precedence source wins. For plugin search paths, the final list is concatenated in precedence order: repeated `--plugins` flags, then `OPENBBQ_PLUGIN_PATH` entries, then project config paths, then built-in defaults. Duplicate paths are removed after normalization while preserving first occurrence. If the same plugin name is found in multiple paths, the first discovered plugin wins and later duplicates are reported as warnings.

The required precedence test matrix is defined in [Project Config](./Project-Config.md).

## Meta Commands

### `openbbq version`

Print the installed OpenBBQ version and exit with code `0`. With `--json`, emit `{"ok": true, "version": "<semver>"}`.
