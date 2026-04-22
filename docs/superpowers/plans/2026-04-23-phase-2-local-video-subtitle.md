# Phase 2 Local Video Subtitle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 2 Slice 1 so the CLI can import a local video file, run a local ffmpeg plus faster-whisper plus subtitle workflow, and persist large media as file-backed artifacts.

**Architecture:** Extend the existing Phase 1 CLI, storage, binding, and plugin contracts instead of adding an API layer. Large video/audio artifacts become file-backed versions in `ProjectStore`; plugins can emit either `content` or `file_path`; built-in real plugins live under `src/openbbq/builtin_plugins/` and are discovered through the same plugin registry path mechanism. Default tests stay deterministic by faking subprocess and faster-whisper backends; real media smoke tests are optional.

**Tech Stack:** Python 3.11, uv, pytest, Ruff, existing local plugin registry, optional system `ffmpeg`, optional `faster-whisper`.

---

## File Structure

- Modify `src/openbbq/storage/project_store.py`: support file-backed artifact versions, `content_size`, and project-level artifacts with `created_by_step_id=None`.
- Modify `src/openbbq/workflow/bindings.py`: accept plugin outputs with exactly one of `content` or `file_path`; pass file-backed inputs as `file_path` descriptors.
- Modify `src/openbbq/cli/app.py`: add `openbbq artifact import <path> --type <type> --name <name>`.
- Modify `src/openbbq/config/loader.py`: append built-in plugin path after CLI, environment, and project plugin paths.
- Create `src/openbbq/builtin_plugins/__init__.py`: marker for bundled plugin resources.
- Create `src/openbbq/builtin_plugins/ffmpeg/openbbq.plugin.toml`: manifest for `ffmpeg.extract_audio`.
- Create `src/openbbq/builtin_plugins/ffmpeg/plugin.py`: ffmpeg subprocess-backed extraction plugin with injectable runner seam.
- Create `src/openbbq/builtin_plugins/faster_whisper/openbbq.plugin.toml`: manifest for `faster_whisper.transcribe`.
- Create `src/openbbq/builtin_plugins/faster_whisper/plugin.py`: faster-whisper transcription plugin with injectable backend seam.
- Create `src/openbbq/builtin_plugins/subtitle/openbbq.plugin.toml`: manifest for `subtitle.export`.
- Create `src/openbbq/builtin_plugins/subtitle/plugin.py`: SRT subtitle exporter.
- Create `tests/test_file_backed_artifacts.py`: file-backed storage tests.
- Create `tests/test_artifact_import.py`: CLI import tests.
- Modify `tests/test_workflow_bindings.py`: file-backed input and output contract tests.
- Create `tests/test_builtin_plugins.py`: deterministic built-in plugin tests.
- Create `tests/fixtures/projects/local-video-subtitle/openbbq.yaml`: canonical Phase 2 local workflow fixture using built-in plugin names.
- Modify `pyproject.toml`: add optional `media` dependency for `faster-whisper`.
- Modify `README.md`: document Phase 2 local media setup and smoke flow.

## Task 1: File-Backed Artifact Storage

**Files:**
- Modify: `src/openbbq/storage/project_store.py`
- Create: `tests/test_file_backed_artifacts.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_file_backed_artifacts.py`:

```python
from pathlib import Path

import pytest

from openbbq.storage.project_store import ProjectStore


def test_write_file_backed_artifact_version_copies_file_and_returns_descriptor(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"video-bytes")
    store = ProjectStore(tmp_path / ".openbbq")

    artifact, version = store.write_artifact_version(
        artifact_type="video",
        name="source.video",
        content=None,
        file_path=source,
        metadata={"format": "mp4"},
        created_by_step_id=None,
        lineage={"source": "cli_import", "original_path": str(source.resolve())},
    )

    assert artifact.record["created_by_step_id"] is None
    assert artifact.record["name"] == "source.video"
    assert version.record["content_encoding"] == "file"
    assert version.record["content_size"] == len(b"video-bytes")
    assert Path(version.record["content_path"]).read_bytes() == b"video-bytes"
    assert version.content == {
        "file_path": version.record["content_path"],
        "size": len(b"video-bytes"),
        "sha256": version.record["content_hash"],
    }

    reloaded = store.read_artifact_version(version.id)
    assert reloaded.content == version.content


def test_write_artifact_version_requires_exactly_one_payload(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"x")
    store = ProjectStore(tmp_path / ".openbbq")

    with pytest.raises(ValueError, match="exactly one"):
        store.write_artifact_version(
            artifact_type="video",
            name="bad.video",
            content=b"x",
            file_path=source,
            metadata={},
            created_by_step_id=None,
            lineage={},
        )

    with pytest.raises(ValueError, match="exactly one"):
        store.write_artifact_version(
            artifact_type="video",
            name="bad.video",
            content=None,
            file_path=None,
            metadata={},
            created_by_step_id=None,
            lineage={},
        )
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_file_backed_artifacts.py -q
```

Expected: FAIL because `write_artifact_version()` does not accept `file_path`.

- [ ] **Step 3: Implement file-backed storage**

Update `ProjectStore.write_artifact_version()` signature:

```python
def write_artifact_version(
    self,
    *,
    artifact_type: str,
    name: str,
    content: Any = None,
    file_path: Path | None = None,
    metadata: Mapping[str, Any],
    created_by_step_id: str | None,
    lineage: Mapping[str, Any],
    artifact_id: str | None = None,
) -> tuple[StoredArtifact, StoredArtifactVersion]:
```

Add validation:

```python
has_content = content is not None
has_file = file_path is not None
if has_content == has_file:
    raise ValueError("Artifact versions require exactly one of content or file_path.")
```

Add helper:

```python
def _copy_file_durably(self, destination: Path, source: Path) -> tuple[str, bytes, int]:
    source = Path(source)
    if not source.is_file():
        raise ValueError(f"file-backed artifact source does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with NamedTemporaryFile(
        "wb",
        dir=destination.parent,
        delete=False,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    ) as handle:
        with source.open("rb") as source_handle:
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
                handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(destination)
    self._fsync_parent(destination.parent)
    return "file", digest.digest(), size
```

Store `content_hash` as `digest.hex()`, store `content_size`, and return `StoredArtifactVersion.content` as:

```python
{
    "file_path": str(content_path),
    "size": content_size,
    "sha256": content_hash,
}
```

Update `read_artifact_version()`:

```python
if encoding == "file":
    content = {
        "file_path": str(content_path),
        "size": record["content_size"],
        "sha256": record["content_hash"],
    }
```

- [ ] **Step 4: Run storage tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_file_backed_artifacts.py tests/test_storage.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/openbbq/storage/project_store.py tests/test_file_backed_artifacts.py
git commit -m "feat: Add file-backed artifact storage"
```

## Task 2: CLI Artifact Import

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Create: `tests/test_artifact_import.py`

- [ ] **Step 1: Write failing CLI import tests**

Create `tests/test_artifact_import.py`:

```python
import json
from pathlib import Path

from openbbq.cli.app import main
from openbbq.storage.project_store import ProjectStore


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        """
version: 1
project:
  name: Import Demo
workflows:
  demo:
    name: Demo
    steps:
      - id: noop
        name: Noop
        tool_ref: missing.noop
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0
""",
        encoding="utf-8",
    )
    return project


def test_cli_artifact_import_creates_file_backed_project_artifact(tmp_path, capsys):
    project = write_project(tmp_path)
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"fake-video")

    code = main(
        [
            "--project",
            str(project),
            "--json",
            "artifact",
            "import",
            str(video),
            "--type",
            "video",
            "--name",
            "source.video",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["artifact"]["type"] == "video"
    assert payload["artifact"]["created_by_step_id"] is None
    assert payload["version"]["content_encoding"] == "file"
    assert payload["version"]["lineage"]["source"] == "cli_import"

    store = ProjectStore(project / ".openbbq")
    version = store.read_artifact_version(payload["version"]["id"])
    assert Path(version.content["file_path"]).read_bytes() == b"fake-video"


def test_cli_artifact_import_rejects_unknown_type(tmp_path, capsys):
    project = write_project(tmp_path)
    video = tmp_path / "sample.bin"
    video.write_bytes(b"fake")

    code = main(
        [
            "--project",
            str(project),
            "--json",
            "artifact",
            "import",
            str(video),
            "--type",
            "unknown",
            "--name",
            "source.unknown",
        ]
    )

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "validation_error"
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_artifact_import.py -q
```

Expected: FAIL because the `artifact import` subcommand does not exist.

- [ ] **Step 3: Implement CLI parser and handler**

In `_build_parser()`, add:

```python
artifact_import = artifact_sub.add_parser("import", parents=[subcommand_global_options])
artifact_import.add_argument("path")
artifact_import.add_argument("--type", dest="artifact_type", required=True)
artifact_import.add_argument("--name", required=True)
```

In `_dispatch()`:

```python
if args.artifact_command == "import":
    return _artifact_import(args)
```

Implement:

```python
def _artifact_import(args: argparse.Namespace) -> int:
    from openbbq.domain.models import ARTIFACT_TYPES

    source = Path(args.path).expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"Artifact import source is not a file: {source}")
    if args.artifact_type not in ARTIFACT_TYPES:
        raise ValidationError(f"Artifact type '{args.artifact_type}' is not registered.")
    config = _load_config(args)
    artifact, version = _project_store(config).write_artifact_version(
        artifact_type=args.artifact_type,
        name=args.name,
        content=None,
        file_path=source,
        metadata={},
        created_by_step_id=None,
        lineage={"source": "cli_import", "original_path": str(source)},
    )
    payload = {"ok": True, "artifact": artifact.record, "version": version.record}
    _emit(payload, args.json_output, artifact.id)
    return 0
```

- [ ] **Step 4: Run import tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_artifact_import.py tests/test_cli_integration.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/openbbq/cli/app.py tests/test_artifact_import.py
git commit -m "feat: Add artifact import command"
```

## Task 3: File-Backed Plugin IO Contract

**Files:**
- Modify: `src/openbbq/workflow/bindings.py`
- Modify: `tests/test_workflow_bindings.py`

- [ ] **Step 1: Add failing binding tests**

Append to `tests/test_workflow_bindings.py`:

```python
from pathlib import Path

import pytest


def test_build_plugin_inputs_passes_file_path_for_file_backed_artifact(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    source = tmp_path / "audio.wav"
    source.write_bytes(b"audio")
    artifact, version = store.write_artifact_version(
        artifact_type="audio",
        name="audio.source",
        content=None,
        file_path=source,
        metadata={"format": "wav"},
        created_by_step_id=None,
        lineage={"source": "test"},
    )
    step = StepConfig(
        id="transcribe",
        name="Transcribe",
        tool_ref="faster_whisper.transcribe",
        inputs={"audio": f"project.{artifact.id}"},
        outputs=(StepOutput(name="transcript", type="asr_transcript"),),
        parameters={},
        on_error="abort",
        max_retries=0,
    )

    inputs, input_versions = build_plugin_inputs(store, step, {})

    assert inputs["audio"]["file_path"] == version.content["file_path"]
    assert "content" not in inputs["audio"]
    assert input_versions[f"project.{artifact.id}"] == version.id


def test_persist_step_outputs_accepts_file_path_payload(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    step = StepConfig(
        id="extract_audio",
        name="Extract Audio",
        tool_ref="ffmpeg.extract_audio",
        inputs={},
        outputs=(StepOutput(name="audio", type="audio"),),
        parameters={},
        on_error="abort",
        max_retries=0,
    )
    tool = ToolSpec(
        plugin_name="ffmpeg",
        name="extract_audio",
        description="Extract audio",
        input_artifact_types=["video"],
        output_artifact_types=["audio"],
        parameter_schema={},
        effects=["reads_files", "writes_files"],
        manifest_path=tmp_path / "openbbq.plugin.toml",
    )

    bindings = persist_step_outputs(
        store,
        "workflow",
        step,
        tool,
        {"outputs": {"audio": {"type": "audio", "file_path": str(audio), "metadata": {}}}},
        {},
    )

    version = store.read_artifact_version(bindings["audio"]["artifact_version_id"])
    assert version.record["content_encoding"] == "file"
    assert Path(version.content["file_path"]).read_bytes() == b"audio"


def test_persist_step_outputs_rejects_content_and_file_path_together(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    step = StepConfig(
        id="extract_audio",
        name="Extract Audio",
        tool_ref="ffmpeg.extract_audio",
        inputs={},
        outputs=(StepOutput(name="audio", type="audio"),),
        parameters={},
        on_error="abort",
        max_retries=0,
    )
    tool = ToolSpec(
        plugin_name="ffmpeg",
        name="extract_audio",
        description="Extract audio",
        input_artifact_types=["video"],
        output_artifact_types=["audio"],
        parameter_schema={},
        effects=[],
        manifest_path=tmp_path / "openbbq.plugin.toml",
    )

    with pytest.raises(ValidationError, match="exactly one"):
        persist_step_outputs(
            store,
            "workflow",
            step,
            tool,
            {
                "outputs": {
                    "audio": {
                        "type": "audio",
                        "content": b"audio",
                        "file_path": str(audio),
                    }
                }
            },
            {},
        )
```

Ensure imports include `StepConfig`, `StepOutput`, `ToolSpec`, `ValidationError`, and `Path`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_workflow_bindings.py -q
```

Expected: FAIL because file-backed inputs still expose descriptor under `content`, and `persist_step_outputs()` ignores `file_path`.

- [ ] **Step 3: Implement file-backed IO contract**

In `artifact_input()`, detect descriptor content:

```python
content = version.content
payload = {
    "artifact_id": artifact["id"],
    "artifact_version_id": version.id,
    "type": artifact["type"],
    "metadata": version.record.get("metadata", {}),
}
if version.record.get("content_encoding") == "file":
    payload["file_path"] = content["file_path"]
else:
    payload["content"] = content
return payload
```

In `persist_step_outputs()`, validate payload:

```python
has_content = "content" in payload
has_file = "file_path" in payload
if has_content == has_file:
    raise ValidationError(
        f"Plugin response for step '{step.id}' output '{output_name}' must include exactly one of content or file_path."
    )
file_path = payload.get("file_path") if has_file else None
if file_path is not None and not Path(file_path).is_file():
    raise ValidationError(
        f"Plugin response for step '{step.id}' output '{output_name}' file_path does not exist: {file_path}."
    )
```

Call storage with:

```python
content=payload.get("content") if has_content else None,
file_path=Path(file_path) if file_path is not None else None,
```

- [ ] **Step 4: Run binding tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_workflow_bindings.py tests/test_engine_run_text.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/openbbq/workflow/bindings.py tests/test_workflow_bindings.py
git commit -m "feat: Support file-backed plugin artifacts"
```

## Task 4: Built-In Plugin Discovery Path

**Files:**
- Modify: `src/openbbq/config/loader.py`
- Create: `src/openbbq/builtin_plugins/__init__.py`
- Create: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Write failing built-in path test**

Create `tests/test_builtin_plugins.py`:

```python
from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.plugins.registry import discover_plugins


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        """
version: 1
project:
  name: Builtins
workflows:
  demo:
    name: Demo
    steps:
      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: project.art_missing
        outputs:
          - name: audio
            type: audio
        parameters: {}
        on_error: abort
        max_retries: 0
""",
        encoding="utf-8",
    )
    return project


def test_builtin_plugin_path_is_discovered_by_default(tmp_path):
    config = load_project_config(write_project(tmp_path))

    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "subtitle.export" in registry.tools
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_builtin_plugin_path_is_discovered_by_default -q
```

Expected: FAIL because no built-in plugin path or manifests exist.

- [ ] **Step 3: Add built-in plugin package and default path**

Create `src/openbbq/builtin_plugins/__init__.py`.

In `src/openbbq/config/loader.py`, add:

```python
BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "builtin_plugins"
```

When merging plugin paths:

```python
builtin_plugin_paths = [BUILTIN_PLUGIN_ROOT]
plugin_paths = _merge_paths(cli_plugin_paths, _merge_paths(config_plugin_paths, builtin_plugin_paths))
```

This preserves precedence: CLI, env/project config, built-ins.

- [ ] **Step 4: Add minimal built-in manifests**

Create `src/openbbq/builtin_plugins/ffmpeg/openbbq.plugin.toml`:

```toml
name = "ffmpeg"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "extract_audio"
description = "Extract audio from a file-backed video artifact with ffmpeg."
input_artifact_types = ["video"]
output_artifact_types = ["audio"]
effects = ["reads_files", "writes_files"]

[tools.parameter_schema]
type = "object"
additionalProperties = false

[tools.parameter_schema.properties.format]
type = "string"
default = "wav"

[tools.parameter_schema.properties.sample_rate]
type = "integer"
default = 16000

[tools.parameter_schema.properties.channels]
type = "integer"
default = 1
```

Create `src/openbbq/builtin_plugins/faster_whisper/openbbq.plugin.toml`:

```toml
name = "faster_whisper"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "transcribe"
description = "Transcribe a file-backed audio artifact with faster-whisper."
input_artifact_types = ["audio"]
output_artifact_types = ["asr_transcript"]
effects = ["reads_files"]

[tools.parameter_schema]
type = "object"
additionalProperties = false
```

Create `src/openbbq/builtin_plugins/subtitle/openbbq.plugin.toml`:

```toml
name = "subtitle"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "export"
description = "Export transcript or translation segments as subtitle text."
input_artifact_types = ["asr_transcript", "translation"]
output_artifact_types = ["subtitle"]
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false

[tools.parameter_schema.properties.format]
type = "string"
enum = ["srt"]
default = "srt"
```

Create initial plugin files with a real `run()` function that raises clear dependency errors until implemented in later tasks:

```python
def run(request):
    raise RuntimeError("This built-in plugin has not been implemented yet.")
```

- [ ] **Step 5: Run discovery test to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_builtin_plugin_path_is_discovered_by_default tests/test_plugins.py tests/test_config_precedence.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/openbbq/config/loader.py src/openbbq/builtin_plugins tests/test_builtin_plugins.py
git commit -m "feat: Discover built-in real plugins"
```

## Task 5: Subtitle Export Built-In Plugin

**Files:**
- Modify: `src/openbbq/builtin_plugins/subtitle/plugin.py`
- Modify: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Add failing subtitle plugin tests**

Append to `tests/test_builtin_plugins.py`:

```python
from openbbq.builtin_plugins.subtitle import plugin as subtitle_plugin


def test_subtitle_export_writes_srt_from_transcript_segments():
    response = subtitle_plugin.run(
        {
            "tool_name": "export",
            "parameters": {"format": "srt"},
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {"start": 0.0, "end": 1.5, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "OpenBBQ"},
                    ],
                }
            },
        }
    )

    assert response == {
        "outputs": {
            "subtitle": {
                "type": "subtitle",
                "content": "1\n00:00:00,000 --> 00:00:01,500\nHello\n\n"
                "2\n00:00:01,500 --> 00:00:03,000\nOpenBBQ\n",
                "metadata": {"format": "srt", "segment_count": 2, "duration_seconds": 3.0},
            }
        }
    }
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_subtitle_export_writes_srt_from_transcript_segments -q
```

Expected: FAIL because subtitle plugin still raises.

- [ ] **Step 3: Implement subtitle exporter**

Replace `src/openbbq/builtin_plugins/subtitle/plugin.py`:

```python
from __future__ import annotations


def run(request: dict) -> dict:
    if request.get("tool_name") != "export":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    if parameters.get("format", "srt") != "srt":
        raise ValueError("subtitle.export currently supports only srt.")
    segments = _segments(request)
    subtitle = _format_srt(segments)
    duration = float(segments[-1]["end"]) if segments else 0.0
    return {
        "outputs": {
            "subtitle": {
                "type": "subtitle",
                "content": subtitle,
                "metadata": {
                    "format": "srt",
                    "segment_count": len(segments),
                    "duration_seconds": duration,
                },
            }
        }
    }


def _segments(request: dict) -> list[dict]:
    inputs = request.get("inputs", {})
    payload = inputs.get("transcript") or inputs.get("translation")
    if not isinstance(payload, dict) or "content" not in payload:
        raise ValueError("subtitle.export requires transcript or translation content.")
    content = payload["content"]
    if not isinstance(content, list):
        raise ValueError("subtitle.export input content must be a list of segments.")
    return content


def _format_srt(segments: list[dict]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_timestamp(float(segment['start']))} --> {_timestamp(float(segment['end']))}",
                    str(segment["text"]),
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
```

- [ ] **Step 4: Run subtitle tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_subtitle_export_writes_srt_from_transcript_segments -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/openbbq/builtin_plugins/subtitle/plugin.py tests/test_builtin_plugins.py
git commit -m "feat: Add built-in subtitle export plugin"
```

## Task 6: ffmpeg Extract Audio Built-In Plugin

**Files:**
- Modify: `src/openbbq/builtin_plugins/ffmpeg/plugin.py`
- Modify: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Add failing ffmpeg plugin tests**

Append to `tests/test_builtin_plugins.py`:

```python
from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        output_path = command[-1]
        Path(output_path).write_bytes(b"wav")


def test_ffmpeg_extract_audio_builds_command_and_returns_file_output(tmp_path):
    runner = RecordingRunner()
    video = tmp_path / "input.mp4"
    video.write_bytes(b"video")
    work_dir = tmp_path / "work"

    response = ffmpeg_plugin.run(
        {
            "tool_name": "extract_audio",
            "work_dir": str(work_dir),
            "parameters": {"format": "wav", "sample_rate": 16000, "channels": 1},
            "inputs": {"video": {"type": "video", "file_path": str(video)}},
        },
        runner=runner,
    )

    assert runner.commands == [
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(work_dir / "audio.wav"),
        ]
    ]
    assert response["outputs"]["audio"]["type"] == "audio"
    assert response["outputs"]["audio"]["file_path"] == str(work_dir / "audio.wav")
    assert response["outputs"]["audio"]["metadata"] == {
        "format": "wav",
        "sample_rate": 16000,
        "channels": 1,
    }
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_ffmpeg_extract_audio_builds_command_and_returns_file_output -q
```

Expected: FAIL because ffmpeg plugin still raises or does not accept `runner`.

- [ ] **Step 3: Implement ffmpeg plugin with runner seam**

Replace `src/openbbq/builtin_plugins/ffmpeg/plugin.py`:

```python
from __future__ import annotations

from pathlib import Path
import subprocess


def run(request: dict, runner=None) -> dict:
    if request.get("tool_name") != "extract_audio":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    runner = _run_subprocess if runner is None else runner
    video = request.get("inputs", {}).get("video", {})
    video_path = video.get("file_path")
    if not isinstance(video_path, str) or not Path(video_path).is_file():
        raise ValueError("ffmpeg.extract_audio requires a file-backed video input.")
    parameters = request.get("parameters", {})
    audio_format = parameters.get("format", "wav")
    sample_rate = int(parameters.get("sample_rate", 16000))
    channels = int(parameters.get("channels", 1))
    if audio_format != "wav":
        raise ValueError("ffmpeg.extract_audio currently supports wav output only.")
    output_path = Path(request["work_dir"]) / "audio.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        str(output_path),
    ]
    runner(command)
    return {
        "outputs": {
            "audio": {
                "type": "audio",
                "file_path": str(output_path),
                "metadata": {
                    "format": audio_format,
                    "sample_rate": sample_rate,
                    "channels": channels,
                },
            }
        }
    }


def _run_subprocess(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg binary was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed: {exc.stderr.strip()}") from exc
```

- [ ] **Step 4: Run ffmpeg tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_ffmpeg_extract_audio_builds_command_and_returns_file_output -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/openbbq/builtin_plugins/ffmpeg/plugin.py tests/test_builtin_plugins.py
git commit -m "feat: Add built-in ffmpeg audio extraction plugin"
```

## Task 7: faster-whisper Built-In Plugin With Fake Backend Seam

**Files:**
- Modify: `src/openbbq/builtin_plugins/faster_whisper/plugin.py`
- Modify: `tests/test_builtin_plugins.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add failing faster-whisper plugin tests**

Append to `tests/test_builtin_plugins.py`:

```python
from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin


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
    def __init__(self, model, device, compute_type):
        self.model = model
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio_path, language=None, word_timestamps=True, vad_filter=False):
        return [FakeSegment()], FakeInfo()


def test_faster_whisper_transcribe_uses_backend_and_returns_segments(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")

    response = whisper_plugin.run(
        {
            "tool_name": "transcribe",
            "parameters": {
                "model": "base",
                "device": "cpu",
                "compute_type": "int8",
                "word_timestamps": True,
            },
            "inputs": {"audio": {"type": "audio", "file_path": str(audio)}},
        },
        model_factory=FakeWhisperModel,
    )

    assert response["outputs"]["transcript"]["type"] == "asr_transcript"
    assert response["outputs"]["transcript"]["content"] == [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "Hello",
            "confidence": -0.1,
            "words": [
                {"start": 0.0, "end": 0.5, "text": "Hello", "confidence": 0.9}
            ],
        }
    ]
    assert response["outputs"]["transcript"]["metadata"] == {
        "model": "base",
        "device": "cpu",
        "compute_type": "int8",
        "language": "en",
        "duration_seconds": 1.0,
    }
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_faster_whisper_transcribe_uses_backend_and_returns_segments -q
```

Expected: FAIL because faster-whisper plugin still raises or does not accept `model_factory`.

- [ ] **Step 3: Implement faster-whisper plugin**

Replace `src/openbbq/builtin_plugins/faster_whisper/plugin.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def run(request: dict, model_factory=None) -> dict:
    if request.get("tool_name") != "transcribe":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    audio = request.get("inputs", {}).get("audio", {})
    audio_path = audio.get("file_path")
    if not isinstance(audio_path, str) or not Path(audio_path).is_file():
        raise ValueError("faster_whisper.transcribe requires a file-backed audio input.")
    parameters = request.get("parameters", {})
    model_name = parameters.get("model", "base")
    device = parameters.get("device", "cpu")
    compute_type = parameters.get("compute_type", "int8")
    word_timestamps = bool(parameters.get("word_timestamps", True))
    vad_filter = bool(parameters.get("vad_filter", False))
    language = parameters.get("language")
    model_factory = _default_model_factory if model_factory is None else model_factory
    model = model_factory(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=word_timestamps,
        vad_filter=vad_filter,
    )
    content = [_segment_payload(segment, include_words=word_timestamps) for segment in segments]
    return {
        "outputs": {
            "transcript": {
                "type": "asr_transcript",
                "content": content,
                "metadata": {
                    "model": model_name,
                    "device": device,
                    "compute_type": compute_type,
                    "language": getattr(info, "language", language),
                    "duration_seconds": getattr(info, "duration", None),
                },
            }
        }
    }


def _default_model_factory(model_name: str, *, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Install OpenBBQ with the media optional dependencies."
        ) from exc
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _segment_payload(segment: Any, *, include_words: bool) -> dict[str, Any]:
    payload = {
        "start": float(segment.start),
        "end": float(segment.end),
        "text": str(segment.text).strip(),
        "confidence": getattr(segment, "avg_logprob", None),
    }
    if include_words:
        words = getattr(segment, "words", None) or []
        payload["words"] = [
            {
                "start": float(word.start),
                "end": float(word.end),
                "text": str(word.word).strip(),
                "confidence": getattr(word, "probability", None),
            }
            for word in words
        ]
    return payload
```

- [ ] **Step 4: Add optional media dependency**

In `pyproject.toml`, add:

```toml
[project.optional-dependencies]
media = ["faster-whisper>=1.2"]
```

- [ ] **Step 5: Run faster-whisper tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_faster_whisper_transcribe_uses_backend_and_returns_segments -q
```

Expected: PASS without installing faster-whisper, because the test uses a fake backend.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/openbbq/builtin_plugins/faster_whisper/plugin.py tests/test_builtin_plugins.py pyproject.toml
git commit -m "feat: Add built-in faster-whisper transcription plugin"
```

## Task 8: Canonical Local Video Subtitle Workflow And Docs

**Files:**
- Create: `tests/fixtures/projects/local-video-subtitle/openbbq.yaml`
- Modify: `tests/test_fixtures.py`
- Modify: `README.md`

- [ ] **Step 1: Add fixture and failing validation test**

Create `tests/fixtures/projects/local-video-subtitle/openbbq.yaml`:

```yaml
version: 1

project:
  id: local-video-subtitle
  name: Local Video Subtitle

workflows:
  local-video-subtitle:
    name: Local Video Subtitle
    steps:
      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: project.art_imported_video
        outputs:
          - name: audio
            type: audio
        parameters:
          format: wav
          sample_rate: 16000
          channels: 1
        on_error: abort
        max_retries: 0

      - id: transcribe
        name: Transcribe
        tool_ref: faster_whisper.transcribe
        inputs:
          audio: extract_audio.audio
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          model: base
          device: cpu
          compute_type: int8
          word_timestamps: true
        on_error: abort
        max_retries: 0

      - id: subtitle
        name: Export Subtitle
        tool_ref: subtitle.export
        inputs:
          transcript: transcribe.transcript
        outputs:
          - name: subtitle
            type: subtitle
        parameters:
          format: srt
        on_error: abort
        max_retries: 0
```

Append to `tests/test_fixtures.py`:

```python
def test_local_video_subtitle_fixture_uses_builtin_plugins():
    config = load_project_config(FIXTURES / "projects/local-video-subtitle")
    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "subtitle.export" in registry.tools
```

Ensure imports include `load_project_config` and `discover_plugins` if not already present.

- [ ] **Step 2: Run fixture test**

Run:

```bash
uv run pytest tests/test_fixtures.py::test_local_video_subtitle_fixture_uses_builtin_plugins -q
```

Expected: PASS after Task 4; if it fails, fix the fixture path or imports.

- [ ] **Step 3: Update README Phase 2 section**

Add:

```markdown
## Phase 2 Local Media Preview

Phase 2 begins with a local video-to-subtitle workflow driven by the existing CLI. Install optional media dependencies and system ffmpeg before running real local media smoke tests:

```bash
uv sync --extra media
ffmpeg -version
uv run openbbq artifact import ./sample.mp4 --type video --name source.video --project ./demo
uv run openbbq run local-video-subtitle --project ./demo
```

Default CI does not download Whisper models or require ffmpeg.
```

- [ ] **Step 4: Run docs/fixture checks**

Run:

```bash
uv run pytest tests/test_fixtures.py tests/test_package_layout.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/fixtures/projects/local-video-subtitle/openbbq.yaml tests/test_fixtures.py README.md
git commit -m "docs: Add local video subtitle workflow fixture"
```

## Task 9: End-To-End Deterministic CLI Workflow With Fake Built-Ins

**Files:**
- Create: `tests/test_phase2_local_video_subtitle.py`

- [ ] **Step 1: Write failing deterministic E2E test**

Create `tests/test_phase2_local_video_subtitle.py`:

```python
import json
from pathlib import Path

from openbbq.cli.app import main


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/local-video-subtitle/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_cli_imports_video_and_runs_local_video_subtitle_with_fake_media_plugins(
    tmp_path, monkeypatch, capsys
):
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin

    def fake_runner(command):
        Path(command[-1]).write_bytes(b"audio")

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello OpenBBQ"
        avg_logprob = -0.1
        words = []

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeWhisperModel:
        def __init__(self, model, device, compute_type):
            pass

        def transcribe(self, audio_path, language=None, word_timestamps=True, vad_filter=False):
            return [FakeSegment()], FakeInfo()

    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)

    project = write_project(tmp_path)
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")

    assert main(
        [
            "--project",
            str(project),
            "--json",
            "artifact",
            "import",
            str(video),
            "--type",
            "video",
            "--name",
            "source.video",
        ]
    ) == 0
    imported = json.loads(capsys.readouterr().out)
    artifact_id = imported["artifact"]["id"]

    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("project.art_imported_video", f"project.{artifact_id}"),
        encoding="utf-8",
    )

    assert main(["--project", str(project), "--json", "run", "local-video-subtitle"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

    assert main(
        [
            "--project",
            str(project),
            "--json",
            "artifact",
            "list",
            "--workflow",
            "local-video-subtitle",
        ]
    ) == 0
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == [
        "extract_audio.audio",
        "transcribe.transcript",
        "subtitle.subtitle",
    ]
```

- [ ] **Step 2: Run test to verify RED or integration failure**

Run:

```bash
uv run pytest tests/test_phase2_local_video_subtitle.py -q
```

Expected: PASS only after Tasks 1-8 are complete. If it fails, fix the integration path; the fake media seams mean this test must not call real ffmpeg or download Whisper models.

- [ ] **Step 3: Commit**

Run:

```bash
git add tests/test_phase2_local_video_subtitle.py
git commit -m "test: Add deterministic local video subtitle workflow"
```

## Task 10: Full Verification

**Files:**
- All files changed by Tasks 1-9.

- [ ] **Step 1: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: all checks pass.

- [ ] **Step 3: Run format check**

Run:

```bash
uv run ruff format --check .
```

Expected: all files already formatted.

- [ ] **Step 4: Run CLI smoke**

Run:

```bash
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
```

Expected: `Workflow 'text-demo' is valid.`

- [ ] **Step 5: Run optional real media smoke only when dependencies are available**

Run only on a local machine with ffmpeg installed and media dependencies synced:

```bash
uv sync --extra media
ffmpeg -version
uv run openbbq artifact import ./sample.mp4 --type video --name source.video --project ./demo
uv run openbbq run local-video-subtitle --project ./demo
```

Expected: workflow completes and produces `extract_audio.audio`, `transcribe.transcript`, and `subtitle.subtitle`.

- [ ] **Step 6: Confirm git status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes after commits.
