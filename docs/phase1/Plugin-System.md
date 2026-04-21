# Plugin System

## Goal

Plugins let OpenBBQ run workflow steps without baking every media operation into the core backend.

Phase 1 supports local plugins only. Plugin discovery, validation, and execution must be deterministic enough for tests and debugging.

## Plugin Directory

A plugin directory contains:

```text
example-plugin/
  openbbq.plugin.toml
  plugin.py
```

The manifest file is required. The Python module path may vary, but the manifest must declare the runtime entrypoint.

## Manifest

Required manifest fields:

```toml
name = "example-text"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "uppercase"
description = "Convert text input to uppercase."
input_artifact_types = ["text"]
output_artifact_types = ["text"]
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false
properties = {}
```

Manifest validation must reject:

- missing name, version, runtime, or entrypoint.
- invalid semantic version.
- duplicate tool names.
- tools missing `input_artifact_types` or `output_artifact_types`.
- tools with an empty `output_artifact_types` list. `input_artifact_types` may be empty for tools that consume only literal inputs.
- invalid parameter schemas.
- unsupported runtime values.

## Discovery

Plugin search paths come from project config, environment variables, and CLI flags in the precedence defined by [CLI Spec](./CLI-Spec.md).

Discovery should:

- scan configured plugin directories.
- load manifests without executing plugin code.
- validate manifests.
- register plugin tools by `<plugin_name>.<tool_name>`.
- report invalid plugins without hiding valid ones.

## Execution Contract

The Phase 1 Python execution contract should pass a single request object to the plugin entrypoint and expect a single response object.

For `runtime = "python"` and `entrypoint = "plugin:run"`, the loader imports `plugin.py` from the plugin directory as an isolated module and calls:

```python
response = run(request)
```

`request` and `response` are JSON-compatible dictionaries, except artifact `content` may be bytes for file-like artifacts. The engine validates the response shape before persisting artifacts. Plugin code may raise exceptions; the engine catches them and normalizes them into workflow engine errors.

Request fields:

- `project_root`
- `workflow_id`
- `step_id`
- `tool_name`
- `parameters`
- `inputs`
- `work_dir`

Input object rules:

- Artifact selector inputs are passed as objects containing `artifact_id`, `artifact_version_id`, `type`, `content`, and `metadata`.
- Literal inputs are passed as objects containing `literal`.
- A single input value must not contain both `literal` and artifact fields.
- Plugin requests must be JSON serializable except that `content` may be bytes for file-like artifacts; the engine is responsible for adapting bytes to storage.

Response fields:

- `outputs`: produced artifact payloads keyed by the output name declared in the step's `outputs` list. Each value is an object with:
  - `type`: the artifact type string (must match a type allowed by the tool manifest declaration).
  - `content`: the artifact content — a string, bytes, or a JSON-serializable object, depending on the artifact type.
  - `metadata`: artifact-type-specific metadata object (see the Artifact Type Registry in [Domain Model](./Domain-Model.md)). May be an empty object if the type requires no metadata.
- `metadata`: optional structured metadata about the execution as a whole (e.g., processing duration, model version used).
- `events`: optional list of plugin-level event objects for inclusion in the workflow event log.
- `pause_requested`: optional boolean. When `true`, the engine pauses after writing this step's outputs, equivalent to `pause_after: true` on the step config. Defaults to `false`. Useful for plugins that detect human review is needed (e.g., low ASR confidence).

The engine owns artifact ID assignment, artifact version creation, lineage metadata, and persistence. Plugins return content; they do not directly mutate the OpenBBQ artifact index.

### Request Example

```json
{
  "project_root": "/tmp/openbbq-project",
  "workflow_id": "text-demo",
  "step_id": "uppercase",
  "tool_name": "uppercase",
  "parameters": {},
  "inputs": {
    "text": {
      "artifact_id": "art_00000000000000000000000000000001",
      "artifact_version_id": "av_00000000000000000000000000000001",
      "type": "text",
      "content": "hello openbbq",
      "metadata": {}
    }
  },
  "work_dir": "/tmp/openbbq-project/.openbbq/work/text-demo/uppercase"
}
```

Literal inputs use the same key space but carry a `literal` value:

```json
{
  "inputs": {
    "text": {
      "literal": "hello openbbq"
    }
  }
}
```

### Response Example

```json
{
  "outputs": {
    "text": {
      "type": "text",
      "content": "HELLO OPENBBQ",
      "metadata": {}
    }
  },
  "metadata": {
    "duration_ms": 3
  },
  "events": [
    {
      "level": "info",
      "message": "Uppercase transform completed",
      "data": {
        "input_chars": 12,
        "output_chars": 12
      }
    }
  ],
  "pause_requested": false
}
```

Plugin event objects are not persisted directly as workflow events. The engine wraps each plugin event in a workflow event with generated ID, sequence, workflow ID, step ID, timestamp, and event type `plugin.event`.

### Error Normalization

If the plugin raises an exception, the engine records a `step.failed` event and a failed `StepRun.error` object:

```json
{
  "code": "plugin.execution_failed",
  "message": "Mock plugin failed",
  "details": {
    "exception_type": "RuntimeError"
  }
}
```

With `--debug`, CLI output may include stack traces for OpenBBQ errors. JSON output must still use the standard `ok: false` envelope from [CLI Spec](./CLI-Spec.md).

## Artifact Type Validation

Before execution:

- every input artifact type must match the tool declaration.
- every required parameter must be present.
- no unknown parameter is accepted when the schema disallows it.

After execution:

- every output name declared in the step's `outputs` list must be present as a key in `response.outputs`.
- every output's `type` field must be a value listed in the tool's `output_artifact_types` allowlist.
- output content must be serializable or storable by the artifact storage layer.

Note: `output_artifact_types` in the manifest is a **type allowlist** — it declares which artifact types the tool is permitted to produce. The per-output names (`name` fields) that determine how outputs are wired between steps are declared in the workflow step definition, not in the plugin manifest.

**Phase 1 input validation is deliberately shallow.** Tools declare a flat `input_artifact_types` allowlist; the engine verifies each input artifact's type is in that list. There is no support for named input declarations or cardinality constraints (e.g., "requires exactly one `video` and an optional `glossary`"). This is accepted as a Phase 1 limitation. Named input schema for tools is out of scope until the workflow contracts are stable.

## Security Boundary

Phase 1 local plugins are trusted code. The docs and CLI should state this clearly.

The manifest `effects` field is still required so future phases can enforce policy. Phase 1 should record declared effects but does not need sandbox enforcement.
