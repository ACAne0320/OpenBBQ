# Slice 1 Backend CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Slice 1 OpenBBQ Python backend and CLI: init, validate, plugin discovery, run-to-completion, artifact persistence, events, and inspection commands.

**Architecture:** Create a small `src/openbbq/` package with clear boundaries for CLI, config, domain, plugins, storage, and engine. The CLI delegates to application services; persisted state follows the `.openbbq/` layout documented in `docs/phase1/Domain-Model.md`. Slice 1 keeps production plugin contracts aligned with `yt-dlp`, local Whisper, and OpenAI-compatible translation, while tests use deterministic mock plugins.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `ruff`, `PyYAML`, `jsonschema`, stdlib `argparse`, `tomllib`, `dataclasses`, `importlib`, and `pathlib`.

---

## File Structure

- Create `pyproject.toml`: package metadata, dependencies, console script, pytest and Ruff settings.
- Create `src/openbbq/__init__.py`: version export.
- Create `src/openbbq/cli.py`: argument parsing, output envelopes, exit-code mapping.
- Create `src/openbbq/errors.py`: typed application exceptions.
- Create `src/openbbq/domain.py`: dataclasses, constants, artifact types, ID/clock helpers.
- Create `src/openbbq/config.py`: YAML load, defaults, path resolution, config hash, validation.
- Create `src/openbbq/plugins.py`: manifest discovery, registry, validation, Python entrypoint execution.
- Create `src/openbbq/storage.py`: atomic JSON, JSONL events, artifact and workflow state persistence.
- Create `src/openbbq/engine.py`: workflow validation, run-to-completion orchestration, inspection services.
- Create `tests/fixtures/projects/...`: canonical project configs.
- Create `tests/fixtures/plugins/...`: deterministic mock plugin manifests and implementations.
- Create focused tests under `tests/`.

## Task 1: Package Scaffold And CLI Version

**Files:**
- Create: `pyproject.toml`
- Create: `src/openbbq/__init__.py`
- Create: `src/openbbq/cli.py`
- Create: `tests/test_cli_smoke.py`

- [ ] **Step 1: Write the failing CLI version test**

```python
# tests/test_cli_smoke.py
from openbbq.cli import main


def test_version_json(capsys):
    code = main(["--json", "version"])
    assert code == 0
    assert capsys.readouterr().out.strip() == '{"ok": true, "version": "0.1.0"}'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_smoke.py::test_version_json -v`
Expected: FAIL because `openbbq` cannot be imported.

- [ ] **Step 3: Implement minimal package scaffold**

```toml
# pyproject.toml
[project]
name = "openbbq"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6.0", "jsonschema>=4.0"]

[project.scripts]
openbbq = "openbbq.cli:main"

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.6"]

[tool.pytest.ini_options]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

```python
# src/openbbq/__init__.py
__version__ = "0.1.0"
```

```python
# src/openbbq/cli.py
import argparse
import json

from openbbq import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openbbq")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("command", choices=["version"])
    args = parser.parse_args(argv)
    if args.command == "version":
        payload = {"ok": True, "version": __version__}
        print(json.dumps(payload) if args.json_output else __version__)
        return 0
    return 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_smoke.py::test_version_json -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/openbbq tests/test_cli_smoke.py
git commit -m "feat: scaffold openbbq package"
```

## Task 2: Canonical Fixtures And Mock Plugin Contracts

**Files:**
- Create: `tests/fixtures/projects/text-basic/openbbq.yaml`
- Create: `tests/fixtures/projects/youtube-subtitle-mock/openbbq.yaml`
- Create: `tests/fixtures/plugins/mock-text/openbbq.plugin.toml`
- Create: `tests/fixtures/plugins/mock-text/plugin.py`
- Create: `tests/fixtures/plugins/mock-media/openbbq.plugin.toml`
- Create: `tests/fixtures/plugins/mock-media/plugin.py`
- Create: `tests/test_fixtures.py`

- [ ] **Step 1: Write failing fixture contract tests**

```python
# tests/test_fixtures.py
from pathlib import Path

import yaml


FIXTURES = Path(__file__).parent / "fixtures"


def test_text_basic_fixture_exists():
    config = yaml.safe_load((FIXTURES / "projects/text-basic/openbbq.yaml").read_text())
    assert config["workflows"]["text-demo"]["steps"][1]["tool_ref"] == "mock_text.uppercase"


def test_mock_media_roles_match_phase_1_targets():
    manifest = (FIXTURES / "plugins/mock-media/openbbq.plugin.toml").read_text()
    assert 'name = "youtube_download"' in manifest
    assert 'name = "transcribe"' in manifest
    assert "yt-dlp" in manifest
    assert "local Whisper" in manifest
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fixtures.py -v`
Expected: FAIL because fixture files do not exist.

- [ ] **Step 3: Add fixtures**

Use the YAML workflows from `docs/phase1/Project-Config.md`. In `mock-media` manifest, declare tools `youtube_download`, `extract_audio`, and `transcribe`; descriptions must mention `yt-dlp` and local Whisper. In `mock-text` manifest, declare `echo`, `uppercase`, `glossary_replace`, `translate`, and `subtitle_export`; translation description must mention OpenAI-compatible APIs. Plugin implementations return deterministic dictionaries matching the Phase 1 execution contract.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fixtures.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures tests/test_fixtures.py
git commit -m "test: add phase 1 mock fixtures"
```

## Task 3: Errors, Domain Types, And Config Loader

**Files:**
- Create: `src/openbbq/errors.py`
- Create: `src/openbbq/domain.py`
- Create: `src/openbbq/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

```python
# tests/test_config.py
from pathlib import Path

import pytest

from openbbq.config import load_project_config
from openbbq.errors import ValidationError


def test_load_text_basic_defaults():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    assert config.project.name == "Text Basic"
    assert config.storage.root.name == ".openbbq"
    assert config.workflows["text-demo"].steps[0].id == "seed"


def test_rejects_invalid_step_id(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\nproject: {name: Bad}\nworkflows:\n  demo:\n    name: Demo\n"
        "    steps:\n      - id: Bad ID\n        name: Bad\n        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
    )
    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)
    assert "step id" in str(exc.value).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL because `openbbq.config` does not exist.

- [ ] **Step 3: Implement config and domain dataclasses**

Implement dataclasses for `ProjectConfig`, `StorageConfig`, `WorkflowConfig`, `StepConfig`, and `StepOutput`. Add `OpenBBQError`, `ValidationError`, `PluginError`, `ExecutionError`, and `ArtifactNotFoundError` with `code`, `message`, and `exit_code`. `load_project_config(project_root, config_path=None, extra_plugin_paths=None, env=None)` loads YAML, applies defaults, validates IDs, validates output declarations, normalizes paths, and returns dataclasses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/errors.py src/openbbq/domain.py src/openbbq/config.py tests/test_config.py
git commit -m "feat: load and validate project config"
```

## Task 4: Plugin Discovery Without Execution

**Files:**
- Create: `src/openbbq/plugins.py`
- Create: `tests/test_plugins.py`

- [ ] **Step 1: Write failing plugin discovery tests**

```python
# tests/test_plugins.py
from pathlib import Path

from openbbq.config import load_project_config
from openbbq.plugins import discover_plugins


def test_discovers_mock_text_tools_without_importing_plugin_code():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)
    assert "mock_text.uppercase" in registry.tools
    assert registry.tools["mock_text.uppercase"].output_artifact_types == ["text"]


def test_reports_invalid_manifest_without_hiding_valid_plugins(tmp_path):
    bad = tmp_path / "bad-plugin"
    bad.mkdir()
    (bad / "openbbq.plugin.toml").write_text('name = "bad"\n')
    registry = discover_plugins([Path("tests/fixtures/plugins/mock-text"), bad])
    assert "mock_text.echo" in registry.tools
    assert registry.invalid_plugins[0].path == bad / "openbbq.plugin.toml"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v`
Expected: FAIL because plugin discovery is missing.

- [ ] **Step 3: Implement manifest discovery**

Use stdlib `tomllib`. Scan each configured plugin path; if the path itself contains `openbbq.plugin.toml`, treat it as one plugin, otherwise scan immediate child directories. Validate required manifest fields, semantic version shape, supported runtime `python`, entrypoint shape `module:function`, duplicate tool names, non-empty output types, and JSON Schema validity.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/plugins.py tests/test_plugins.py
git commit -m "feat: discover local plugin manifests"
```

## Task 5: Storage Layer

**Files:**
- Create: `src/openbbq/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

```python
# tests/test_storage.py
from openbbq.storage import ProjectStore


def test_write_artifact_version_round_trip(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )
    loaded = store.read_artifact_version(version.id)
    assert loaded.content == "hello openbbq"
    assert loaded.record["artifact_id"] == artifact.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL because storage is missing.

- [ ] **Step 3: Implement atomic persistence**

Implement `ProjectStore` with `write_json_atomic`, `append_event`, `write_workflow_state`, `read_workflow_state`, `write_step_run`, `list_artifacts`, `read_artifact`, `read_artifact_version`, and `write_artifact_version`. Store content as UTF-8 text for strings and JSON text for dict/list content. Generate IDs with injectable `IdGenerator` so later tests can be deterministic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/storage.py tests/test_storage.py
git commit -m "feat: persist local artifacts and state"
```

## Task 6: Workflow Validation Service

**Files:**
- Modify: `src/openbbq/engine.py`
- Create: `tests/test_engine_validate.py`

- [ ] **Step 1: Write failing workflow validation tests**

```python
# tests/test_engine_validate.py
from pathlib import Path

import pytest

from openbbq.config import load_project_config
from openbbq.engine import validate_workflow
from openbbq.errors import ValidationError
from openbbq.plugins import discover_plugins


def test_validate_text_workflow_success():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)
    result = validate_workflow(config, registry, "text-demo")
    assert result.workflow_id == "text-demo"
    assert result.step_count == 2


def test_validate_rejects_unknown_workflow():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)
    with pytest.raises(ValidationError):
        validate_workflow(config, registry, "missing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine_validate.py -v`
Expected: FAIL because engine validation is missing.

- [ ] **Step 3: Implement validation**

Implement tool resolution, parameter JSON Schema validation, selector order validation, output artifact type registry validation, input artifact type compatibility for selectors, duplicate output name checks per step, and Slice 1 rejection for `pause_before`/`pause_after: true`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine_validate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/engine.py tests/test_engine_validate.py
git commit -m "feat: validate workflows against plugins"
```

## Task 7: Run Text Workflow To Completion

**Files:**
- Modify: `src/openbbq/plugins.py`
- Modify: `src/openbbq/storage.py`
- Modify: `src/openbbq/engine.py`
- Create: `tests/test_engine_run_text.py`

- [ ] **Step 1: Write failing text run test**

```python
# tests/test_engine_run_text.py
from pathlib import Path

from openbbq.config import load_project_config
from openbbq.engine import run_workflow
from openbbq.plugins import discover_plugins
from openbbq.storage import ProjectStore


def test_run_text_workflow_to_completion(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/text-basic/openbbq.yaml").read_text()
    (project / "openbbq.yaml").write_text(source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")))
    config = load_project_config(project)
    result = run_workflow(config, discover_plugins(config.plugin_paths), "text-demo")
    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    artifacts = store.list_artifacts()
    assert [a["name"] for a in artifacts] == ["seed.text", "uppercase.text"]
    latest = store.read_artifact_version(artifacts[-1]["current_version_id"])
    assert latest.content == "HELLO OPENBBQ"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine_run_text.py -v`
Expected: FAIL because workflow execution is missing.

- [ ] **Step 3: Implement plugin execution and ordered engine run**

Implement `execute_plugin_tool(plugin, tool, request)` using isolated module import by file path. In `run_workflow`, reject existing completed state, emit events, create `StepRun` records, pass literal inputs as `{"literal": value}`, pass artifact inputs with content and metadata, validate response outputs, persist artifacts, and mark workflow completed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_engine_run_text.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/plugins.py src/openbbq/storage.py src/openbbq/engine.py tests/test_engine_run_text.py
git commit -m "feat: run text workflow to completion"
```

## Task 8: Run Mock Media Workflow To Completion

**Files:**
- Modify: `tests/fixtures/plugins/mock-media/plugin.py`
- Modify: `tests/fixtures/plugins/mock-text/plugin.py`
- Create: `tests/test_engine_run_media.py`

- [ ] **Step 1: Write failing mock media run test**

```python
# tests/test_engine_run_media.py
from pathlib import Path

from openbbq.config import load_project_config
from openbbq.engine import run_workflow
from openbbq.plugins import discover_plugins
from openbbq.storage import ProjectStore


def test_run_mock_youtube_subtitle_workflow(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/youtube-subtitle-mock/openbbq.yaml").read_text()
    (project / "openbbq.yaml").write_text(source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")))
    config = load_project_config(project)
    result = run_workflow(config, discover_plugins(config.plugin_paths), "youtube-subtitle")
    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    subtitle = [a for a in store.list_artifacts() if a["type"] == "subtitle"][0]
    version = store.read_artifact_version(subtitle["current_version_id"])
    assert "OpenBBQ" in version.content
    assert version.record["metadata"]["format"] == "srt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine_run_media.py -v`
Expected: FAIL until mock plugin outputs and engine JSON content handling are complete.

- [ ] **Step 3: Complete deterministic mock outputs**

`mock_media.youtube_download` returns `video` metadata, `extract_audio` returns `audio`, and `transcribe` returns an `asr_transcript` with "Open BBQ" text. `mock_text.glossary_replace` replaces "Open BBQ" with "OpenBBQ"; `translate` preserves timing and emits deterministic Chinese text; `subtitle_export` emits SRT.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_engine_run_media.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/plugins tests/test_engine_run_media.py
git commit -m "feat: run mock media workflow"
```

## Task 9: CLI Commands And JSON Envelopes

**Files:**
- Modify: `src/openbbq/cli.py`
- Create: `tests/test_cli_integration.py`

- [ ] **Step 1: Write failing CLI integration tests**

```python
# tests/test_cli_integration.py
import json
from pathlib import Path

from openbbq.cli import main


def write_project(tmp_path, fixture_name):
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text()
    (project / "openbbq.yaml").write_text(source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")))
    return project


def test_validate_json_success(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")
    code = main(["--project", str(project), "--json", "validate", "text-demo"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_run_status_logs_and_artifact_show(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")
    assert main(["--project", str(project), "run", "text-demo"]) == 0
    assert main(["--project", str(project), "--json", "status", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_integration.py -v`
Expected: FAIL because CLI commands are missing.

- [ ] **Step 3: Implement CLI command surface**

Support global `--project`, `--config`, repeated `--plugins`, `--json`, `--verbose`, and `--debug`. Implement `init`, `project list`, `project info`, `validate`, `run`, `status`, `logs`, `artifact list`, `artifact show`, `plugin list`, `plugin info`, and `version`. Map exceptions to documented exit codes and JSON error envelopes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_integration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/cli.py tests/test_cli_integration.py
git commit -m "feat: expose slice 1 cli commands"
```

## Task 10: Slice 2 Command Guardrails

**Files:**
- Modify: `src/openbbq/cli.py`
- Create: `tests/test_slice2_guardrails.py`

- [ ] **Step 1: Write failing guardrail tests**

```python
# tests/test_slice2_guardrails.py
from openbbq.cli import main


def test_resume_is_clear_slice_2_error(capsys):
    code = main(["resume", "demo"])
    assert code == 1
    assert "not implemented in Slice 1" in capsys.readouterr().err


def test_artifact_diff_is_clear_slice_2_error(capsys):
    code = main(["artifact", "diff", "a", "b"])
    assert code == 1
    assert "not implemented in Slice 1" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_slice2_guardrails.py -v`
Expected: FAIL until guardrails are implemented.

- [ ] **Step 3: Implement guardrails**

Add command handlers for `resume`, `abort`, `unlock`, `run --force`, `run --step`, and `artifact diff` that return exit code `1` with a stable Slice 1 unsupported message.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_slice2_guardrails.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/cli.py tests/test_slice2_guardrails.py
git commit -m "feat: add slice 2 command guardrails"
```

## Task 11: Final Verification And Documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` if commands changed materially

- [ ] **Step 1: Run full verification**

Run: `uv run pytest`
Expected: all tests PASS.

Run: `uv run ruff check .`
Expected: no lint errors.

Run: `uv run ruff format --check .`
Expected: no formatting changes required.

- [ ] **Step 2: Update usage docs**

Add a short README section showing:

```bash
uv sync
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
uv run openbbq run text-demo --project tests/fixtures/projects/text-basic
uv run openbbq status text-demo --project tests/fixtures/projects/text-basic
```

- [ ] **Step 3: Re-run verification**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: all commands exit `0`.

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md pyproject.toml src tests
git commit -m "docs: document slice 1 cli usage"
```

## Self-Review

- Spec coverage: Tasks cover scaffolding, config, plugin discovery, plugin execution, storage, engine run, CLI inspection, JSON envelopes, deterministic fixtures, and Slice 2 guardrails.
- Explicit exclusions: pause/resume, abort, retry/skip, lock recovery, reruns, and artifact diff are guarded but not implemented.
- Plugin targets: mock media/text roles map to `yt-dlp`, local Whisper ASR, and OpenAI-compatible translation while avoiding network, GPU, and media binary requirements in tests.
- Type consistency: config, plugin, storage, and engine modules share dataclass boundaries through `domain.py`; CLI only calls public service functions.
