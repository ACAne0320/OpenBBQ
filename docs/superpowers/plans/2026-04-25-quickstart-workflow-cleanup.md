# Quickstart Workflow Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract generated subtitle workflow rendering and persistence from the quickstart job orchestration module while preserving CLI and API behavior.

**Architecture:** Add `openbbq.application.quickstart_workflows` as the owner of workflow template loading, mutation, generated run ids, YAML writing, and `GeneratedWorkflow`. Keep `openbbq.application.quickstart` as the public orchestration facade for API job creation and compatibility re-exports used by the CLI.

**Tech Stack:** Python 3.11, Pydantic v2 through `OpenBBQModel`, PyYAML, importlib resources, pytest, Ruff.

---

## File Structure

- Create: `src/openbbq/application/quickstart_workflows.py`
  - Owns workflow generation constants, `GeneratedWorkflow`, YAML template rendering, generated project writing, and private rendering helpers.
- Modify: `src/openbbq/application/quickstart.py`
  - Keeps subtitle job request/result models and job orchestration.
  - Imports and re-exports generated workflow helpers from `quickstart_workflows`.
  - Removes direct imports of `datetime`, `importlib.resources`, `uuid4`, `yaml`, `JsonObject`, and `TypeAlias`.
- Modify: `tests/test_application_quickstart.py`
  - Adds direct tests for the new workflow generation module.
  - Keeps existing imports through `openbbq.application.quickstart` as compatibility coverage.

Do not modify API route schemas, CLI subtitle behavior, workflow template YAML files, storage schema, or run execution behavior.

---

### Task 1: Add direct workflow generation tests

**Files:**
- Modify: `tests/test_application_quickstart.py`

- [ ] **Step 1: Add test imports**

Update the top of `tests/test_application_quickstart.py` so it imports `yaml` and direct workflow helpers from the new module:

```python
from importlib import resources

import yaml

from openbbq.application.quickstart import (
    LocalSubtitleJobRequest,
    YouTubeSubtitleJobRequest,
    create_local_subtitle_job,
    create_youtube_subtitle_job,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.application.quickstart_workflows import (
    write_local_subtitle_workflow as write_local_subtitle_workflow_direct,
    write_youtube_subtitle_workflow as write_youtube_subtitle_workflow_direct,
)
from openbbq.storage.models import RunRecord
```

- [ ] **Step 2: Add direct module tests and a local test helper**

Add these tests after `test_youtube_workflow_template_is_packaged_as_workflow_dsl()`:

```python
def test_direct_youtube_workflow_generation_renders_expected_config(tmp_path):
    generated = write_youtube_subtitle_workflow_direct(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=direct",
        source_lang="en",
        target_lang="zh-Hans",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="youtube-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    steps = _workflow_steps(config, "youtube-to-srt")

    assert generated.project_root == (
        tmp_path / ".openbbq" / "generated" / "youtube-subtitle" / "youtube-direct"
    )
    assert generated.config_path == generated.project_root / "openbbq.yaml"
    assert generated.workflow_id == "youtube-to-srt"
    assert generated.run_id == "youtube-direct"
    assert config["storage"] == {"root": ".openbbq"}

    download = steps["download"]["parameters"]
    assert download["url"] == "https://www.youtube.com/watch?v=direct"
    assert download["quality"] == "best"
    assert download["auth"] == "auto"
    assert "browser" not in download
    assert "browser_profile" not in download

    transcribe = steps["transcribe"]["parameters"]
    assert transcribe["model"] == "tiny"
    assert transcribe["device"] == "cpu"
    assert transcribe["compute_type"] == "int8"
    assert transcribe["language"] == "en"

    correction = steps["correct"]["parameters"]
    assert correction["provider"] == "openai"
    assert correction["source_lang"] == "en"
    assert "model" not in correction

    translation = steps["translate"]["parameters"]
    assert translation["provider"] == "openai"
    assert translation["source_lang"] == "en"
    assert translation["target_lang"] == "zh-Hans"
    assert "model" not in translation


def test_direct_local_workflow_generation_renders_expected_config(tmp_path):
    generated = write_local_subtitle_workflow_direct(
        workspace_root=tmp_path,
        video_selector="project.art_source_video",
        source_lang="ja",
        target_lang="en",
        provider="openai",
        model="gpt-4.1-mini",
        asr_model="small",
        asr_device="cuda",
        asr_compute_type="float16",
        run_id="local-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    steps = _workflow_steps(config, "local-to-srt")

    assert generated.project_root == (
        tmp_path / ".openbbq" / "generated" / "local-subtitle" / "local-direct"
    )
    assert generated.config_path == generated.project_root / "openbbq.yaml"
    assert generated.workflow_id == "local-to-srt"
    assert generated.run_id == "local-direct"
    assert config["storage"] == {"root": ".openbbq"}
    assert steps["extract_audio"]["inputs"]["video"] == "project.art_source_video"

    transcribe = steps["transcribe"]["parameters"]
    assert transcribe["model"] == "small"
    assert transcribe["device"] == "cuda"
    assert transcribe["compute_type"] == "float16"
    assert transcribe["language"] == "ja"

    correction = steps["correct"]["parameters"]
    assert correction["provider"] == "openai"
    assert correction["source_lang"] == "ja"
    assert correction["model"] == "gpt-4.1-mini"

    translation = steps["translate"]["parameters"]
    assert translation["provider"] == "openai"
    assert translation["source_lang"] == "ja"
    assert translation["target_lang"] == "en"
    assert translation["model"] == "gpt-4.1-mini"


def _workflow_steps(config, workflow_id):
    return {step["id"]: step for step in config["workflows"][workflow_id]["steps"]}
```

- [ ] **Step 3: Run the new direct tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_application_quickstart.py::test_direct_youtube_workflow_generation_renders_expected_config \
  tests/test_application_quickstart.py::test_direct_local_workflow_generation_renders_expected_config \
  -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'openbbq.application.quickstart_workflows'`.

- [ ] **Step 4: Commit the failing tests**

Run:

```bash
git add tests/test_application_quickstart.py
git commit -m "test: Cover quickstart workflow generation module"
```

---

### Task 2: Extract workflow generation into `quickstart_workflows`

**Files:**
- Create: `src/openbbq/application/quickstart_workflows.py`
- Modify: `src/openbbq/application/quickstart.py`
- Test: `tests/test_application_quickstart.py`

- [ ] **Step 1: Create the workflow generation module**

Create `src/openbbq/application/quickstart_workflows.py` with this content:

```python
from __future__ import annotations

from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TypeAlias
from uuid import uuid4

import yaml

from openbbq.domain.base import JsonObject, OpenBBQModel

YOUTUBE_SUBTITLE_TEMPLATE_ID = "youtube-subtitle"
YOUTUBE_SUBTITLE_WORKFLOW_ID = "youtube-to-srt"
DEFAULT_YOUTUBE_QUALITY = "best[ext=mp4][height<=720]/best[height<=720]/best"
YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE = "openbbq.workflow_templates.youtube_subtitle"
YOUTUBE_SUBTITLE_TEMPLATE_NAME = "openbbq.yaml"
LOCAL_SUBTITLE_TEMPLATE_ID = "local-subtitle"
LOCAL_SUBTITLE_WORKFLOW_ID = "local-to-srt"
LOCAL_SUBTITLE_TEMPLATE_PACKAGE = "openbbq.workflow_templates.local_subtitle"
LOCAL_SUBTITLE_TEMPLATE_NAME = "openbbq.yaml"
WorkflowTemplate: TypeAlias = JsonObject


class GeneratedWorkflow(OpenBBQModel):
    project_root: Path
    config_path: Path
    workflow_id: str
    run_id: str


def write_youtube_subtitle_workflow(
    *,
    workspace_root: Path,
    url: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    quality: str,
    auth: str,
    browser: str | None,
    browser_profile: str | None,
    run_id: str | None = None,
) -> GeneratedWorkflow:
    run_id = run_id or _new_run_id()
    generated_root = (
        workspace_root / ".openbbq" / "generated" / YOUTUBE_SUBTITLE_TEMPLATE_ID / run_id
    )
    generated_root.mkdir(parents=True, exist_ok=True)
    config_path = generated_root / "openbbq.yaml"
    config = _youtube_subtitle_config(
        url=url,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
        quality=quality,
        auth=auth,
        browser=browser,
        browser_profile=browser_profile,
    )
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return GeneratedWorkflow(
        project_root=generated_root,
        config_path=config_path,
        workflow_id=YOUTUBE_SUBTITLE_WORKFLOW_ID,
        run_id=run_id,
    )


def write_local_subtitle_workflow(
    *,
    workspace_root: Path,
    video_selector: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    run_id: str | None = None,
) -> GeneratedWorkflow:
    run_id = run_id or _new_run_id()
    generated_root = workspace_root / ".openbbq" / "generated" / LOCAL_SUBTITLE_TEMPLATE_ID / run_id
    generated_root.mkdir(parents=True, exist_ok=True)
    config_path = generated_root / "openbbq.yaml"
    config = _local_subtitle_config(
        video_selector=video_selector,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
    )
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return GeneratedWorkflow(
        project_root=generated_root,
        config_path=config_path,
        workflow_id=LOCAL_SUBTITLE_WORKFLOW_ID,
        run_id=run_id,
    )


def _youtube_subtitle_config(
    *,
    url: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
    quality: str,
    auth: str,
    browser: str | None,
    browser_profile: str | None,
) -> WorkflowTemplate:
    config = _load_youtube_subtitle_template()
    config["storage"] = {"root": ".openbbq"}
    steps = _steps_by_id(config, YOUTUBE_SUBTITLE_WORKFLOW_ID)

    download_parameters = steps["download"]["parameters"]
    download_parameters["url"] = url
    download_parameters["quality"] = quality
    download_parameters["auth"] = auth
    _set_optional(download_parameters, "browser", browser)
    _set_optional(download_parameters, "browser_profile", browser_profile)

    transcribe_parameters = steps["transcribe"]["parameters"]
    transcribe_parameters["model"] = asr_model
    transcribe_parameters["device"] = asr_device
    transcribe_parameters["compute_type"] = asr_compute_type
    transcribe_parameters["language"] = source_lang

    correction_parameters = steps["correct"]["parameters"]
    correction_parameters["provider"] = provider
    correction_parameters["source_lang"] = source_lang
    _set_optional(correction_parameters, "model", model)

    translation_parameters = steps["translate"]["parameters"]
    translation_parameters["provider"] = provider
    translation_parameters["source_lang"] = source_lang
    translation_parameters["target_lang"] = target_lang
    _set_optional(translation_parameters, "model", model)

    return config


def _local_subtitle_config(
    *,
    video_selector: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str,
    asr_device: str,
    asr_compute_type: str,
) -> WorkflowTemplate:
    config = _load_local_subtitle_template()
    config["storage"] = {"root": ".openbbq"}
    steps = _steps_by_id(config, LOCAL_SUBTITLE_WORKFLOW_ID)

    extract_audio_inputs = steps["extract_audio"]["inputs"]
    extract_audio_inputs["video"] = video_selector

    transcribe_parameters = steps["transcribe"]["parameters"]
    transcribe_parameters["model"] = asr_model
    transcribe_parameters["device"] = asr_device
    transcribe_parameters["compute_type"] = asr_compute_type
    transcribe_parameters["language"] = source_lang

    correction_parameters = steps["correct"]["parameters"]
    correction_parameters["provider"] = provider
    correction_parameters["source_lang"] = source_lang
    _set_optional(correction_parameters, "model", model)

    translation_parameters = steps["translate"]["parameters"]
    translation_parameters["provider"] = provider
    translation_parameters["source_lang"] = source_lang
    translation_parameters["target_lang"] = target_lang
    _set_optional(translation_parameters, "model", model)

    return config


def _load_youtube_subtitle_template() -> WorkflowTemplate:
    return _load_template(
        package=YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE,
        name=YOUTUBE_SUBTITLE_TEMPLATE_NAME,
        description="YouTube subtitle workflow template",
    )


def _load_local_subtitle_template() -> WorkflowTemplate:
    return _load_template(
        package=LOCAL_SUBTITLE_TEMPLATE_PACKAGE,
        name=LOCAL_SUBTITLE_TEMPLATE_NAME,
        description="Local subtitle workflow template",
    )


def _load_template(*, package: str, name: str, description: str) -> WorkflowTemplate:
    raw = resources.files(package).joinpath(name).read_text(encoding="utf-8")
    config = yaml.safe_load(raw)
    if not isinstance(config, dict):
        raise ValueError(f"{description} must be a YAML mapping.")
    return config


def _steps_by_id(config: WorkflowTemplate, workflow_id: str) -> dict[str, WorkflowTemplate]:
    workflow = config["workflows"][workflow_id]
    return {step["id"]: step for step in workflow["steps"]}


def _set_optional(parameters: WorkflowTemplate, name: str, value: str | None) -> None:
    if value is None:
        parameters.pop(name, None)
        return
    parameters[name] = value


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"
```

- [ ] **Step 2: Replace `quickstart.py` imports and add compatibility re-exports**

In `src/openbbq/application/quickstart.py`, replace the current import section and constants/model definitions through `GeneratedWorkflow` with:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.application.artifacts import ArtifactImportRequest, import_artifact
from openbbq.application.quickstart_workflows import (
    DEFAULT_YOUTUBE_QUALITY,
    GeneratedWorkflow,
    LOCAL_SUBTITLE_TEMPLATE_ID,
    LOCAL_SUBTITLE_WORKFLOW_ID,
    YOUTUBE_SUBTITLE_TEMPLATE_ID,
    YOUTUBE_SUBTITLE_WORKFLOW_ID,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.application.runs import RunCreateRequest, create_run
from openbbq.domain.base import OpenBBQModel
from openbbq.runtime.settings import load_runtime_settings

__all__ = (
    "DEFAULT_YOUTUBE_QUALITY",
    "GeneratedWorkflow",
    "LOCAL_SUBTITLE_TEMPLATE_ID",
    "LOCAL_SUBTITLE_WORKFLOW_ID",
    "LocalSubtitleJobRequest",
    "SubtitleJobResult",
    "YOUTUBE_SUBTITLE_TEMPLATE_ID",
    "YOUTUBE_SUBTITLE_WORKFLOW_ID",
    "YouTubeSubtitleJobRequest",
    "create_local_subtitle_job",
    "create_youtube_subtitle_job",
    "write_local_subtitle_workflow",
    "write_youtube_subtitle_workflow",
)
```

After this replacement, `SubtitleJobResult` should be the first class defined in the file.

- [ ] **Step 3: Remove moved workflow generation code from `quickstart.py`**

Delete these definitions from `src/openbbq/application/quickstart.py` because they now live in `quickstart_workflows.py`:

```python
YOUTUBE_SUBTITLE_TEMPLATE_ID = "youtube-subtitle"
YOUTUBE_SUBTITLE_WORKFLOW_ID = "youtube-to-srt"
DEFAULT_YOUTUBE_QUALITY = "best[ext=mp4][height<=720]/best[height<=720]/best"
YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE = "openbbq.workflow_templates.youtube_subtitle"
YOUTUBE_SUBTITLE_TEMPLATE_NAME = "openbbq.yaml"
LOCAL_SUBTITLE_TEMPLATE_ID = "local-subtitle"
LOCAL_SUBTITLE_WORKFLOW_ID = "local-to-srt"
LOCAL_SUBTITLE_TEMPLATE_PACKAGE = "openbbq.workflow_templates.local_subtitle"
LOCAL_SUBTITLE_TEMPLATE_NAME = "openbbq.yaml"
WorkflowTemplate: TypeAlias = JsonObject
```

Also delete these moved definitions from `quickstart.py`:

- `class GeneratedWorkflow(OpenBBQModel)`
- `def write_youtube_subtitle_workflow`
- `def write_local_subtitle_workflow`
- `def _youtube_subtitle_config`
- `def _local_subtitle_config`
- `def _load_youtube_subtitle_template`
- `def _load_local_subtitle_template`
- `def _load_template`
- `def _steps_by_id`
- `def _set_optional`
- `def _new_run_id`

Keep `_faster_whisper_defaults()` in `quickstart.py` because job orchestration still owns runtime defaults.

- [ ] **Step 4: Verify moved imports are gone from `quickstart.py`**

Run:

```bash
rg -n "datetime|resources|uuid4|yaml|JsonObject|TypeAlias|WorkflowTemplate" src/openbbq/application/quickstart.py
```

Expected: no matches.

- [ ] **Step 5: Run focused quickstart application tests**

Run:

```bash
uv run pytest tests/test_application_quickstart.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/application/quickstart.py src/openbbq/application/quickstart_workflows.py tests/test_application_quickstart.py
uv run ruff format --check src/openbbq/application/quickstart.py src/openbbq/application/quickstart_workflows.py tests/test_application_quickstart.py
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit the extraction**

Run:

```bash
git add src/openbbq/application/quickstart.py src/openbbq/application/quickstart_workflows.py tests/test_application_quickstart.py
git commit -m "refactor: Extract quickstart workflow generation"
```

---

### Task 3: Prove CLI and API behavior preservation

**Files:**
- Test: `tests/test_application_quickstart.py`
- Test: `tests/test_cli_quickstart.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Run API quickstart-adjacent tests**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py -q
```

Expected: PASS.

- [ ] **Step 2: Run CLI quickstart tests**

Run:

```bash
uv run pytest tests/test_cli_quickstart.py -q
```

Expected: PASS.

- [ ] **Step 3: Run all quickstart-focused tests together**

Run:

```bash
uv run pytest tests/test_application_quickstart.py tests/test_cli_quickstart.py tests/test_api_projects_plugins_runtime.py -q
```

Expected: PASS.

- [ ] **Step 4: Confirm the preservation checks did not create new changes**

Run:

```bash
git status -sb
```

Expected: no uncommitted changes after the Task 2 extraction commit.

---

### Task 4: Final verification

**Files:**
- No planned file changes.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 2: Run full lint**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run full format check**

Run:

```bash
uv run ruff format --check .
```

Expected: PASS with all files already formatted.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status -sb
git diff --stat
```

Expected: only intentional quickstart workflow cleanup files are changed, unless the implementation tasks already committed all changes.

---

## Self-Review

- Spec coverage: The plan creates `quickstart_workflows.py`, keeps `quickstart.py` as the orchestration facade, preserves public imports, and verifies CLI/API behavior.
- Placeholder scan: The plan has concrete file paths, code snippets, exact commands, and expected results. There are no TODO/TBD placeholders.
- Type consistency: `GeneratedWorkflow`, workflow constants, and `write_*_subtitle_workflow()` keep their existing names and signatures. Tests import the new module with aliases while existing compatibility imports remain unchanged.
