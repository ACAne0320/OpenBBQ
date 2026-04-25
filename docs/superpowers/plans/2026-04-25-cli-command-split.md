# CLI Command Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the large CLI entry module into focused command group modules while preserving the existing CLI contract.

**Architecture:** Keep `openbbq.cli.app` as the console entry point, global option owner, logging owner, top-level parser orchestrator, and dispatch orchestrator. Add command modules under `openbbq.cli` that each expose `register(subparsers, parents)` and `dispatch(args)`, plus shared `cli.output` and `cli.context` helpers used by command modules.

**Tech Stack:** Python 3.11, argparse, pytest, Ruff.

---

## File Structure

- Modify: `src/openbbq/cli/app.py`
  - Keep `main()`, `_build_parser()`, `_global_options()`, `_configure_logging()`, `_effective_log_level()`, and `_dispatch()`.
  - Import and orchestrate command modules.
  - Keep direct handling of the `version` command.
- Create: `src/openbbq/cli/output.py`
  - Owns `emit()`, `emit_error()`, and `jsonable_content()`.
- Create: `src/openbbq/cli/context.py`
  - Owns `load_config()`, `load_registry()`, `load_config_and_plugins()`, and `project_store()`.
- Create: `src/openbbq/cli/projects.py`
  - Registers and handles `init`, `project list`, and `project info`.
- Create: `src/openbbq/cli/plugins.py`
  - Registers and handles `plugin list` and `plugin info`.
- Create: `src/openbbq/cli/api.py`
  - Registers and handles `api serve`.
- Create: `src/openbbq/cli/workflows.py`
  - Registers and handles `validate`, `run`, `resume`, `abort`, `unlock`, `status`, and `logs`.
- Create: `src/openbbq/cli/artifacts.py`
  - Registers and handles `artifact list`, `artifact show`, `artifact diff`, and `artifact import`.
- Create: `src/openbbq/cli/runtime.py`
  - Registers and handles `settings`, `auth`, `secret`, `models`, and `doctor`.
- Create: `src/openbbq/cli/quickstart.py`
  - Registers and handles `subtitle local` and `subtitle youtube`.
- Create: `tests/test_cli_module_split.py`
  - Covers importability of the new modules and representative parser contracts.
- Modify: `tests/test_cli_quickstart.py`
  - Update the interactive auth monkeypatch to patch `openbbq.cli.runtime.getpass` after runtime commands move.
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  - Mark the CLI split item as done after implementation verification.

Do not change command names, arguments, defaults, exit codes, JSON payloads, text output, application services, storage behavior, workflow behavior, plugin contracts, or the `openbbq = "openbbq.cli.app:main"` console script target.

---

### Task 1: Add CLI split characterization tests

**Files:**
- Create: `tests/test_cli_module_split.py`

- [ ] **Step 1: Create the new test file**

Create `tests/test_cli_module_split.py` with this content:

```python
import importlib

from openbbq.cli.app import _build_parser


CLI_MODULES = (
    "openbbq.cli.output",
    "openbbq.cli.context",
    "openbbq.cli.projects",
    "openbbq.cli.plugins",
    "openbbq.cli.api",
    "openbbq.cli.workflows",
    "openbbq.cli.artifacts",
    "openbbq.cli.runtime",
    "openbbq.cli.quickstart",
)


def test_cli_split_modules_are_importable():
    for module_name in CLI_MODULES:
        importlib.import_module(module_name)


def test_parser_accepts_representative_command_groups():
    parser = _build_parser()

    cases = [
        (["version"], ("version", None)),
        (["init"], ("init", None)),
        (["project", "info"], ("project", "info")),
        (["validate", "text-demo"], ("validate", None)),
        (["run", "text-demo", "--force"], ("run", None)),
        (["resume", "text-demo"], ("resume", None)),
        (["abort", "text-demo"], ("abort", None)),
        (["unlock", "text-demo", "--yes"], ("unlock", None)),
        (["status", "text-demo"], ("status", None)),
        (["logs", "text-demo"], ("logs", None)),
        (["artifact", "list"], ("artifact", "list")),
        (
            ["artifact", "import", "sample.mp4", "--type", "video", "--name", "source.video"],
            ("artifact", "import"),
        ),
        (["plugin", "info", "mock_text"], ("plugin", "info")),
        (["settings", "show"], ("settings", "show")),
        (["auth", "check", "openai"], ("auth", "check")),
        (["secret", "check", "env:OPENBBQ_LLM_API_KEY"], ("secret", "check")),
        (["models", "list"], ("models", "list")),
        (["doctor", "--workflow", "text-demo"], ("doctor", None)),
        (["api", "serve", "--host", "127.0.0.1", "--port", "0"], ("api", "serve")),
        (
            [
                "subtitle",
                "local",
                "--input",
                "sample.mp4",
                "--source",
                "en",
                "--target",
                "zh",
                "--output",
                "subtitle.srt",
            ],
            ("subtitle", "local"),
        ),
        (
            [
                "subtitle",
                "youtube",
                "--url",
                "https://www.youtube.com/watch?v=test",
                "--source",
                "en",
                "--target",
                "zh",
                "--output",
                "subtitle.srt",
            ],
            ("subtitle", "youtube"),
        ),
    ]

    for argv, expected in cases:
        args = parser.parse_args(argv)
        assert (args.command, _subcommand(args)) == expected


def _subcommand(args):
    for name in (
        "project_command",
        "artifact_command",
        "plugin_command",
        "settings_command",
        "auth_command",
        "secret_command",
        "models_command",
        "api_command",
        "subtitle_command",
    ):
        if hasattr(args, name):
            return getattr(args, name)
    return None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli_module_split.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `openbbq.cli.output`.

- [ ] **Step 3: Commit the failing tests**

Run:

```bash
git add tests/test_cli_module_split.py
git commit -m "test: Cover CLI split module boundaries"
```

---

### Task 2: Add shared CLI modules and empty command modules

**Files:**
- Create: `src/openbbq/cli/output.py`
- Create: `src/openbbq/cli/context.py`
- Create: `src/openbbq/cli/projects.py`
- Create: `src/openbbq/cli/plugins.py`
- Create: `src/openbbq/cli/api.py`
- Create: `src/openbbq/cli/workflows.py`
- Create: `src/openbbq/cli/artifacts.py`
- Create: `src/openbbq/cli/runtime.py`
- Create: `src/openbbq/cli/quickstart.py`
- Test: `tests/test_cli_module_split.py`

- [ ] **Step 1: Add `src/openbbq/cli/output.py`**

Create `src/openbbq/cli/output.py`:

```python
from __future__ import annotations

import json
import sys
from typing import Any

from openbbq.domain.base import JsonObject, dump_jsonable
from openbbq.errors import OpenBBQError


def emit(payload: JsonObject, json_output: bool, text: Any) -> None:
    payload = dump_jsonable(payload)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
        return
    if text is not None:
        print(text)


def emit_error(error: OpenBBQError, json_output: bool) -> None:
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(error.message, file=sys.stderr)


def jsonable_content(content: Any) -> Any:
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content
```

- [ ] **Step 2: Add `src/openbbq/cli/context.py`**

Create `src/openbbq/cli/context.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.models import ProjectConfig
from openbbq.plugins.registry import PluginRegistry, discover_plugins
from openbbq.storage.project_store import ProjectStore


def load_config(args: argparse.Namespace):
    return load_project_config(
        Path(args.project),
        config_path=args.config,
        extra_plugin_paths=args.plugins,
    )


def load_registry(args: argparse.Namespace) -> PluginRegistry:
    config = load_config(args)
    return discover_plugins(config.plugin_paths)


def load_config_and_plugins(args: argparse.Namespace):
    config = load_config(args)
    return config, discover_plugins(config.plugin_paths)


def project_store(config: ProjectConfig) -> ProjectStore:
    return ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
```

- [ ] **Step 3: Add empty command modules**

Create each file below with the same content:

- `src/openbbq/cli/projects.py`
- `src/openbbq/cli/plugins.py`
- `src/openbbq/cli/api.py`
- `src/openbbq/cli/workflows.py`
- `src/openbbq/cli/artifacts.py`
- `src/openbbq/cli/runtime.py`
- `src/openbbq/cli/quickstart.py`

Content:

```python
from __future__ import annotations


def register(subparsers, parents) -> None:
    return None


def dispatch(args) -> int | None:
    return None
```

- [ ] **Step 4: Run the new module tests**

Run:

```bash
uv run pytest tests/test_cli_module_split.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_module_split.py
uv run ruff format --check src/openbbq/cli tests/test_cli_module_split.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit shared CLI module scaffolding**

Run:

```bash
git add src/openbbq/cli tests/test_cli_module_split.py
git commit -m "refactor: Add CLI command module scaffolding"
```

---

### Task 3: Move shared output and context helpers out of `app.py`

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Test: `tests/test_cli_smoke.py`
- Test: `tests/test_config_precedence.py`

- [ ] **Step 1: Replace helper imports in `app.py`**

In `src/openbbq/cli/app.py`, remove these imports:

```python
import json
import sys

from openbbq.config.loader import load_project_config
from openbbq.domain.base import JsonObject, dump_jsonable
from openbbq.domain.models import ProjectConfig
from openbbq.plugins.registry import PluginRegistry, discover_plugins
```

Add these imports:

```python
from openbbq.cli.context import (
    load_config as _load_config,
    load_config_and_plugins as _load_config_and_plugins,
    load_registry as _load_registry,
    project_store as _project_store,
)
from openbbq.cli.output import (
    emit as _emit,
    emit_error as _emit_error,
    jsonable_content as _jsonable_content,
)
```

Keep imports such as `Path`, `Any`, `ArtifactRecord`, and `ProjectStore` in
`app.py` until the command handlers that still use them are moved in subsequent
tasks.

- [ ] **Step 2: Remove moved helper definitions from `app.py`**

Delete these private helpers from `src/openbbq/cli/app.py`:

- `_load_config`
- `_load_registry`
- `_load_config_and_plugins`
- `_project_store`
- `_jsonable_content`
- `_emit`
- `_emit_error`

Leave command handlers in `app.py` unchanged in this task. Their calls to
`_emit`, `_load_config`, and related names should resolve to the imported
aliases.

- [ ] **Step 3: Remove unused private helpers**

Run:

```bash
rg -n "_read_events|_runtime_context|_artifact_workflow_id" src/openbbq/cli/app.py
```

Expected before deletion: matches for private helper definitions only.

Delete these unused private helpers from `src/openbbq/cli/app.py`:

- `_read_events`
- `_runtime_context`
- `_artifact_workflow_id`

After deletion, run the same `rg` command again.

Expected after deletion: no matches.

- [ ] **Step 4: Run smoke and config precedence tests**

Run:

```bash
uv run pytest tests/test_cli_smoke.py tests/test_config_precedence.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_smoke.py tests/test_config_precedence.py
uv run ruff format --check src/openbbq/cli tests/test_cli_smoke.py tests/test_config_precedence.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit shared helper extraction**

Run:

```bash
git add src/openbbq/cli tests/test_cli_smoke.py tests/test_config_precedence.py
git commit -m "refactor: Extract shared CLI helpers"
```

---

### Task 4: Move project, plugin, and API command groups

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/cli/projects.py`
- Modify: `src/openbbq/cli/plugins.py`
- Modify: `src/openbbq/cli/api.py`
- Test: `tests/test_cli_integration.py`
- Test: `tests/test_config_precedence.py`
- Test: `tests/test_api_server.py`

- [ ] **Step 1: Implement `projects.py`**

Replace `src/openbbq/cli/projects.py` with:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.application.projects import (
    ProjectInitRequest,
    init_project as init_project_command,
    project_info as project_info_command,
)
from openbbq.cli.context import load_config
from openbbq.cli.output import emit


def register(subparsers, parents) -> None:
    subparsers.add_parser("init", parents=[parents])

    project = subparsers.add_parser("project", parents=[parents])
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_sub.add_parser("list", parents=[parents])
    project_sub.add_parser("info", parents=[parents])


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command == "init":
        return _init_project(args)
    if args.command == "project":
        if args.project_command == "list":
            return _project_list(args)
        if args.project_command == "info":
            return _project_info(args)
        return 2
    return None


def _init_project(args: argparse.Namespace) -> int:
    result = init_project_command(
        ProjectInitRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
        )
    )
    emit(
        {"ok": True, "config_path": str(result.config_path)},
        args.json_output,
        f"Initialized {result.config_path}",
    )
    return 0


def _project_list(args: argparse.Namespace) -> int:
    config = load_config(args)
    payload = {
        "ok": True,
        "projects": [
            {
                "id": config.project.id,
                "name": config.project.name,
                "root_path": str(config.root_path),
            }
        ],
    }
    emit(payload, args.json_output, config.project.name)
    return 0


def _project_info(args: argparse.Namespace) -> int:
    info = project_info_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
    )
    payload = {
        "ok": True,
        "project": {"id": info.id, "name": info.name},
        "root_path": str(info.root_path),
        "config_path": str(info.config_path),
        "workflow_count": info.workflow_count,
        "plugin_paths": [str(path) for path in info.plugin_paths],
        "artifact_storage_path": str(info.artifact_storage_path),
    }
    emit(payload, args.json_output, f"{info.name}: {info.workflow_count} workflow(s)")
    return 0
```

- [ ] **Step 2: Implement `plugins.py`**

Replace `src/openbbq/cli/plugins.py` with:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.application.plugins import plugin_info as plugin_info_command
from openbbq.application.plugins import plugin_list as plugin_list_command
from openbbq.cli.output import emit


def register(subparsers, parents) -> None:
    plugin = subparsers.add_parser("plugin", parents=[parents])
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    plugin_sub.add_parser("list", parents=[parents])
    plugin_info = plugin_sub.add_parser("info", parents=[parents])
    plugin_info.add_argument("name")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command != "plugin":
        return None
    if args.plugin_command == "list":
        return _plugin_list(args)
    if args.plugin_command == "info":
        return _plugin_info(args)
    return 2


def _plugin_list(args: argparse.Namespace) -> int:
    result = plugin_list_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
    )
    payload = {
        "ok": True,
        "plugins": list(result.plugins),
        "invalid_plugins": list(result.invalid_plugins),
        "warnings": list(result.warnings),
    }
    emit(payload, args.json_output, "\n".join(plugin["name"] for plugin in result.plugins))
    return 0


def _plugin_info(args: argparse.Namespace) -> int:
    result = plugin_info_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        plugin_name=args.name,
    )
    payload = {"ok": True, "plugin": result.plugin}
    emit(payload, args.json_output, result.plugin["name"])
    return 0
```

- [ ] **Step 3: Implement `api.py`**

Replace `src/openbbq/cli/api.py` with:

```python
from __future__ import annotations

import argparse


def register(subparsers, parents) -> None:
    api = subparsers.add_parser("api", parents=[parents])
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_serve = api_sub.add_parser("serve", parents=[parents])
    api_serve.add_argument("--host", default="127.0.0.1")
    api_serve.add_argument("--port", type=int, default=0)
    api_serve.add_argument("--token")
    api_serve.add_argument("--allow-dev-cors", action="store_true")
    api_serve.add_argument("--no-token-dev", action="store_true")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command != "api":
        return None
    if args.api_command == "serve":
        from openbbq.api.server import main as api_server_main

        argv = [
            "--project",
            str(args.project),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        if args.config:
            argv.extend(["--config", str(args.config)])
        for plugin_path in args.plugins:
            argv.extend(["--plugins", str(plugin_path)])
        if args.token:
            argv.extend(["--token", args.token])
        if args.allow_dev_cors:
            argv.append("--allow-dev-cors")
        if args.no_token_dev:
            argv.append("--no-token-dev")
        return api_server_main(argv)
    return 2
```

- [ ] **Step 4: Wire these modules in `app.py`**

In `src/openbbq/cli/app.py`, import the modules:

```python
from openbbq.cli import api, plugins, projects
```

In `_build_parser()`, replace the existing parser setup for `init`, `project`,
`plugin`, and `api` with:

```python
    projects.register(subparsers, subcommand_global_options)
    plugins.register(subparsers, subcommand_global_options)
    api.register(subparsers, subcommand_global_options)
```

In `_dispatch()`, after the `version` branch and before the existing command
branches, add:

```python
    for command_module in (projects, plugins, api):
        result = command_module.dispatch(args)
        if result is not None:
            return result
```

Delete the old `_init_project`, `_project_list`, `_project_info`,
`_plugin_list`, and `_plugin_info` definitions from `app.py`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli_module_split.py tests/test_config_precedence.py tests/test_cli_integration.py tests/test_api_server.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_module_split.py tests/test_config_precedence.py tests/test_cli_integration.py tests/test_api_server.py
uv run ruff format --check src/openbbq/cli tests/test_cli_module_split.py tests/test_config_precedence.py tests/test_cli_integration.py tests/test_api_server.py
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit project, plugin, and API module migration**

Run:

```bash
git add src/openbbq/cli tests/test_cli_module_split.py tests/test_config_precedence.py tests/test_cli_integration.py tests/test_api_server.py
git commit -m "refactor: Split project plugin and API CLI commands"
```

---

### Task 5: Move workflow command group

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/cli/workflows.py`
- Test: `tests/test_cli_integration.py`
- Test: `tests/test_cli_control_flow.py`

- [ ] **Step 1: Implement `workflows.py`**

Replace `src/openbbq/cli/workflows.py` by moving these functions from
`src/openbbq/cli/app.py` into the module with unchanged behavior:

- `_validate`
- `_run`
- `_resume`
- `_abort`
- `_unlock`
- `_status`
- `_logs`
- `_format_event`

Use these imports at the top:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.application.workflows import (
    WorkflowCommandRequest,
    WorkflowRunRequest,
    abort_workflow_command,
    resume_workflow_command,
    run_workflow_command,
    unlock_workflow_command,
    workflow_logs,
    workflow_status,
)
from openbbq.cli.context import load_config_and_plugins
from openbbq.cli.output import emit
from openbbq.engine.validation import validate_workflow
from openbbq.errors import OpenBBQError
from openbbq.storage.models import WorkflowEvent
```

Add this parser registration and dispatch code above the moved handlers:

```python
def register(subparsers, parents) -> None:
    resume = subparsers.add_parser("resume", parents=[parents])
    resume.add_argument("workflow")

    abort = subparsers.add_parser("abort", parents=[parents])
    abort.add_argument("workflow")

    unlock = subparsers.add_parser("unlock", parents=[parents])
    unlock.add_argument("workflow")
    unlock.add_argument("--yes", action="store_true")

    validate = subparsers.add_parser("validate", parents=[parents])
    validate.add_argument("workflow")

    run = subparsers.add_parser("run", parents=[parents])
    run.add_argument("workflow")
    run.add_argument("--force", action="store_true")
    run.add_argument("--step")

    status = subparsers.add_parser("status", parents=[parents])
    status.add_argument("workflow")

    logs = subparsers.add_parser("logs", parents=[parents])
    logs.add_argument("workflow")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command == "resume":
        return _resume(args)
    if args.command == "abort":
        return _abort(args)
    if args.command == "unlock":
        return _unlock(args)
    if args.command == "validate":
        return _validate(args)
    if args.command == "run":
        if args.force and args.step:
            raise OpenBBQError(
                "invalid_command_usage",
                "run --force cannot be combined with --step.",
                2,
            )
        return _run(args)
    if args.command == "status":
        return _status(args)
    if args.command == "logs":
        return _logs(args)
    return None
```

When moving the handlers, replace calls to `_load_config_and_plugins` with
`load_config_and_plugins`, and replace `_emit` with `emit`.

- [ ] **Step 2: Wire `workflows.py` in `app.py`**

In `src/openbbq/cli/app.py`, add `workflows` to the CLI module import:

```python
from openbbq.cli import api, plugins, projects, workflows
```

In `_build_parser()`, replace the existing parser setup for `resume`, `abort`,
`unlock`, `validate`, `run`, `status`, and `logs` with:

```python
    workflows.register(subparsers, subcommand_global_options)
```

In `_dispatch()`, add `workflows` to the command module tuple:

```python
    for command_module in (projects, plugins, api, workflows):
```

Delete the moved workflow handlers from `app.py`.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_cli_control_flow.py tests/test_phase1_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 4: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_cli_control_flow.py tests/test_phase1_acceptance.py
uv run ruff format --check src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_cli_control_flow.py tests/test_phase1_acceptance.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit workflow module migration**

Run:

```bash
git add src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_cli_control_flow.py tests/test_phase1_acceptance.py
git commit -m "refactor: Split workflow CLI commands"
```

---

### Task 6: Move artifact command group

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/cli/artifacts.py`
- Test: `tests/test_cli_integration.py`
- Test: `tests/test_artifact_import.py`
- Test: `tests/test_artifact_diff.py`

- [ ] **Step 1: Implement `artifacts.py`**

Replace `src/openbbq/cli/artifacts.py` by moving these functions from
`src/openbbq/cli/app.py` into the module with unchanged behavior:

- `_artifact_list`
- `_artifact_diff`
- `_artifact_import`
- `_artifact_show`

Use these imports at the top:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.application.artifacts import (
    ArtifactImportRequest,
    diff_artifact_versions as diff_artifact_versions_command,
    import_artifact,
    list_artifacts as list_artifacts_command,
    show_artifact,
)
from openbbq.cli.output import emit, jsonable_content
```

Add this parser registration and dispatch code above the moved handlers:

```python
def register(subparsers, parents) -> None:
    artifact = subparsers.add_parser("artifact", parents=[parents])
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_sub.add_parser("list", parents=[parents])
    artifact_list.add_argument("--workflow")
    artifact_list.add_argument("--step")
    artifact_list.add_argument("--type", dest="artifact_type")
    artifact_show = artifact_sub.add_parser("show", parents=[parents])
    artifact_show.add_argument("artifact_id")
    artifact_diff = artifact_sub.add_parser("diff", parents=[parents])
    artifact_diff.add_argument("from_version")
    artifact_diff.add_argument("to_version")
    artifact_import = artifact_sub.add_parser("import", parents=[parents])
    artifact_import.add_argument("path")
    artifact_import.add_argument("--type", dest="artifact_type", required=True)
    artifact_import.add_argument("--name", required=True)


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command != "artifact":
        return None
    if args.artifact_command == "diff":
        return _artifact_diff(args)
    if args.artifact_command == "import":
        return _artifact_import(args)
    if args.artifact_command == "list":
        return _artifact_list(args)
    if args.artifact_command == "show":
        return _artifact_show(args)
    return 2
```

When moving the handlers, replace `_emit` with `emit` and replace
`_jsonable_content` with `jsonable_content`.

- [ ] **Step 2: Wire `artifacts.py` in `app.py`**

In `src/openbbq/cli/app.py`, add `artifacts` to the CLI module import:

```python
from openbbq.cli import api, artifacts, plugins, projects, workflows
```

In `_build_parser()`, replace the existing parser setup for `artifact` with:

```python
    artifacts.register(subparsers, subcommand_global_options)
```

In `_dispatch()`, add `artifacts` to the command module tuple:

```python
    for command_module in (projects, plugins, api, workflows, artifacts):
```

Delete the moved artifact handlers from `app.py`.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_artifact_import.py tests/test_artifact_diff.py tests/test_phase1_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 4: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_artifact_import.py tests/test_artifact_diff.py tests/test_phase1_acceptance.py
uv run ruff format --check src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_artifact_import.py tests/test_artifact_diff.py tests/test_phase1_acceptance.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit artifact module migration**

Run:

```bash
git add src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_integration.py tests/test_artifact_import.py tests/test_artifact_diff.py tests/test_phase1_acceptance.py
git commit -m "refactor: Split artifact CLI commands"
```

---

### Task 7: Move runtime command group

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/cli/runtime.py`
- Modify: `tests/test_cli_quickstart.py`
- Test: `tests/test_runtime_cli.py`
- Test: `tests/test_cli_quickstart.py`

- [ ] **Step 1: Implement `runtime.py`**

Replace `src/openbbq/cli/runtime.py` by moving these functions from
`src/openbbq/cli/app.py` into the module with unchanged behavior:

- `_settings_show`
- `_settings_set_provider`
- `_auth_set`
- `_auth_check`
- `_secret_check`
- `_secret_set`
- `_models_list`
- `_doctor`
- `_secret_payload`

Use these imports at the top:

```python
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from openbbq.application.diagnostics import doctor as doctor_command
from openbbq.application.runtime import (
    AuthSetRequest,
    ProviderSetRequest,
    SecretSetRequest,
    auth_check as auth_check_command,
    auth_set as auth_set_command,
    model_list as model_list_command,
    provider_set as provider_set_command,
    secret_check as secret_check_command,
    secret_set as secret_set_command,
    settings_show as settings_show_command,
)
from openbbq.cli.output import emit
from openbbq.errors import ValidationError
```

Add this parser registration and dispatch code above the moved handlers:

```python
def register(subparsers, parents) -> None:
    settings = subparsers.add_parser("settings", parents=[parents])
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("show", parents=[parents])
    settings_provider = settings_sub.add_parser("set-provider", parents=[parents])
    settings_provider.add_argument("name")
    settings_provider.add_argument("--type", required=True)
    settings_provider.add_argument("--base-url")
    settings_provider.add_argument("--api-key")
    settings_provider.add_argument("--default-chat-model")
    settings_provider.add_argument("--display-name")

    auth = subparsers.add_parser("auth", parents=[parents])
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_set = auth_sub.add_parser("set", parents=[parents])
    auth_set.add_argument("name")
    auth_set.add_argument("--type", default="openai_compatible")
    auth_set.add_argument("--base-url")
    auth_set.add_argument("--api-key-ref")
    auth_set.add_argument("--default-chat-model")
    auth_set.add_argument("--display-name")
    auth_check = auth_sub.add_parser("check", parents=[parents])
    auth_check.add_argument("name")

    secret = subparsers.add_parser("secret", parents=[parents])
    secret_sub = secret.add_subparsers(dest="secret_command", required=True)
    secret_check = secret_sub.add_parser("check", parents=[parents])
    secret_check.add_argument("reference")
    secret_set = secret_sub.add_parser("set", parents=[parents])
    secret_set.add_argument("reference")

    models = subparsers.add_parser("models", parents=[parents])
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("list", parents=[parents])

    doctor = subparsers.add_parser("doctor", parents=[parents])
    doctor.add_argument("--workflow")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command == "settings":
        if args.settings_command == "show":
            return _settings_show(args)
        if args.settings_command == "set-provider":
            return _settings_set_provider(args)
        return 2
    if args.command == "auth":
        if args.auth_command == "set":
            return _auth_set(args)
        if args.auth_command == "check":
            return _auth_check(args)
        return 2
    if args.command == "secret":
        if args.secret_command == "check":
            return _secret_check(args)
        if args.secret_command == "set":
            return _secret_set(args)
        return 2
    if args.command == "models":
        if args.models_command == "list":
            return _models_list(args)
        return 2
    if args.command == "doctor":
        return _doctor(args)
    return None
```

When moving the handlers, replace `_emit` with `emit`.

- [ ] **Step 2: Wire `runtime.py` in `app.py`**

In `src/openbbq/cli/app.py`, add `runtime` to the CLI module import:

```python
from openbbq.cli import api, artifacts, plugins, projects, runtime, workflows
```

In `_build_parser()`, replace the existing parser setup for `settings`, `auth`,
`secret`, `models`, and `doctor` with:

```python
    runtime.register(subparsers, subcommand_global_options)
```

In `_dispatch()`, add `runtime` to the command module tuple:

```python
    for command_module in (projects, plugins, api, workflows, artifacts, runtime):
```

Delete the moved runtime handlers from `app.py`.

- [ ] **Step 3: Update the interactive auth monkeypatch test**

In `tests/test_cli_quickstart.py`, replace this import block inside
`test_auth_set_without_secret_reference_prompts_and_uses_sqlite_default`:

```python
    from openbbq.cli import app
    from openbbq.application import runtime as runtime_app
```

with:

```python
    from openbbq.application import runtime as runtime_app
    from openbbq.cli import runtime as runtime_cli
```

Replace this monkeypatch:

```python
    monkeypatch.setattr(app.getpass, "getpass", lambda prompt: "sk-prompt")
```

with:

```python
    monkeypatch.setattr(runtime_cli.getpass, "getpass", lambda prompt: "sk-prompt")
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli_module_split.py tests/test_runtime_cli.py tests/test_cli_quickstart.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_module_split.py tests/test_runtime_cli.py tests/test_cli_quickstart.py
uv run ruff format --check src/openbbq/cli tests/test_cli_module_split.py tests/test_runtime_cli.py tests/test_cli_quickstart.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit runtime module migration**

Run:

```bash
git add src/openbbq/cli tests/test_cli_module_split.py tests/test_runtime_cli.py tests/test_cli_quickstart.py
git commit -m "refactor: Split runtime CLI commands"
```

---

### Task 8: Move subtitle quickstart command group

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/cli/quickstart.py`
- Test: `tests/test_cli_quickstart.py`

- [ ] **Step 1: Implement `quickstart.py`**

Replace `src/openbbq/cli/quickstart.py` by moving these functions from
`src/openbbq/cli/app.py` into the module with unchanged behavior:

- `_subtitle_local`
- `_subtitle_youtube`
- `_latest_workflow_artifact_content`

Use these imports at the top:

```python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from openbbq.application.artifacts import ArtifactImportRequest, import_artifact
from openbbq.application.quickstart import (
    DEFAULT_YOUTUBE_QUALITY,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.application.workflows import WorkflowRunRequest, run_workflow_command, workflow_status
from openbbq.cli.context import project_store
from openbbq.cli.output import emit
from openbbq.config.loader import load_project_config
from openbbq.errors import OpenBBQError
from openbbq.runtime.settings import load_runtime_settings
from openbbq.storage.models import ArtifactRecord
from openbbq.storage.project_store import ProjectStore
```

Add this parser registration and dispatch code above the moved handlers:

```python
def register(subparsers, parents) -> None:
    subtitle = subparsers.add_parser("subtitle", parents=[parents])
    subtitle_sub = subtitle.add_subparsers(dest="subtitle_command", required=True)
    subtitle_local = subtitle_sub.add_parser("local", parents=[parents])
    subtitle_local.add_argument("--input", required=True)
    subtitle_local.add_argument("--source", required=True)
    subtitle_local.add_argument("--target", required=True)
    subtitle_local.add_argument("--output", required=True)
    subtitle_local.add_argument("--provider", default="openai")
    subtitle_local.add_argument("--model")
    subtitle_local.add_argument("--asr-model")
    subtitle_local.add_argument("--asr-device")
    subtitle_local.add_argument("--asr-compute-type")
    subtitle_local.add_argument("--force", action="store_true")

    subtitle_youtube = subtitle_sub.add_parser("youtube", parents=[parents])
    subtitle_youtube.add_argument("--url", required=True)
    subtitle_youtube.add_argument("--source", required=True)
    subtitle_youtube.add_argument("--target", required=True)
    subtitle_youtube.add_argument("--output", required=True)
    subtitle_youtube.add_argument("--provider", default="openai")
    subtitle_youtube.add_argument("--model")
    subtitle_youtube.add_argument("--asr-model")
    subtitle_youtube.add_argument("--asr-device")
    subtitle_youtube.add_argument("--asr-compute-type")
    subtitle_youtube.add_argument("--quality", default=DEFAULT_YOUTUBE_QUALITY)
    subtitle_youtube.add_argument(
        "--auth",
        choices=("auto", "anonymous", "browser_cookies"),
        default="auto",
    )
    subtitle_youtube.add_argument("--browser")
    subtitle_youtube.add_argument("--browser-profile")
    subtitle_youtube.add_argument("--force", action="store_true")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command != "subtitle":
        return None
    if args.subtitle_command == "local":
        return _subtitle_local(args)
    if args.subtitle_command == "youtube":
        return _subtitle_youtube(args)
    return 2
```

When moving the handlers, replace `_project_store` with `project_store` and
replace `_emit` with `emit`.

- [ ] **Step 2: Wire `quickstart.py` in `app.py`**

In `src/openbbq/cli/app.py`, add `quickstart` to the CLI module import:

```python
from openbbq.cli import api, artifacts, plugins, projects, quickstart, runtime, workflows
```

In `_build_parser()`, replace the existing parser setup for `subtitle` with:

```python
    quickstart.register(subparsers, subcommand_global_options)
```

In `_dispatch()`, add `quickstart` to the command module tuple:

```python
    for command_module in (projects, plugins, api, workflows, artifacts, runtime, quickstart):
```

Delete the moved subtitle quickstart handlers and `_latest_workflow_artifact_content`
from `app.py`.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli_module_split.py tests/test_cli_quickstart.py tests/test_phase2_remote_video_slice.py -q
```

Expected: PASS.

- [ ] **Step 4: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_quickstart.py tests/test_phase2_remote_video_slice.py
uv run ruff format --check src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_quickstart.py tests/test_phase2_remote_video_slice.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit quickstart module migration**

Run:

```bash
git add src/openbbq/cli tests/test_cli_module_split.py tests/test_cli_quickstart.py tests/test_phase2_remote_video_slice.py
git commit -m "refactor: Split quickstart CLI commands"
```

---

### Task 9: Finalize `app.py` as thin orchestrator and update audit tracking

**Files:**
- Modify: `src/openbbq/cli/app.py`
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
- Test: `tests/test_cli_module_split.py`
- Test: `tests/test_package_layout.py`

- [ ] **Step 1: Convert `app._dispatch()` to a module loop**

In `src/openbbq/cli/app.py`, define the command module tuple near the imports:

```python
_COMMAND_MODULES = (
    projects,
    plugins,
    api,
    workflows,
    artifacts,
    runtime,
    quickstart,
)
```

Update `_dispatch()` to this shape:

```python
def _dispatch(args: argparse.Namespace) -> int:
    _configure_logging(args)
    if args.command == "version":
        _emit({"ok": True, "version": __version__}, args.json_output, __version__)
        return 0
    for command_module in _COMMAND_MODULES:
        result = command_module.dispatch(args)
        if result is not None:
            return result
    return 2
```

- [ ] **Step 2: Convert `_build_parser()` to command module registration**

Inside `_build_parser()`, after adding the `version` parser, register command
modules with:

```python
    for command_module in _COMMAND_MODULES:
        command_module.register(subparsers, subcommand_global_options)
```

After this step, `_build_parser()` should not contain command-specific parser
setup for project, workflow, artifact, plugin, runtime, API, or subtitle
commands.

- [ ] **Step 3: Remove unused imports from `app.py`**

Run:

```bash
uv run ruff check src/openbbq/cli/app.py
```

Remove every import reported as unused. After cleanup, the import section should
only need:

```python
from __future__ import annotations

import argparse
import logging
import os

from openbbq import __version__
from openbbq.cli import api, artifacts, plugins, projects, quickstart, runtime, workflows
from openbbq.cli.output import emit as _emit
from openbbq.cli.output import emit_error as _emit_error
from openbbq.errors import OpenBBQError
```

Also remove `FILE_BACKED_IMPORT_TYPES` from `app.py` if it is still present.

- [ ] **Step 4: Add new CLI modules to package layout import coverage**

In `tests/test_package_layout.py`, add these module names to the `modules` list
in `test_new_package_modules_are_importable`:

```python
        "openbbq.cli.api",
        "openbbq.cli.artifacts",
        "openbbq.cli.context",
        "openbbq.cli.output",
        "openbbq.cli.plugins",
        "openbbq.cli.projects",
        "openbbq.cli.quickstart",
        "openbbq.cli.runtime",
        "openbbq.cli.workflows",
```

- [ ] **Step 5: Update the audit closure tracking spec**

In `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`,
move **P1: CLI module mixes too many responsibilities** from the Remaining
section to the Done section. Add this bullet under `### Done`:

```markdown
- **P1: CLI module mixes too many responsibilities**
  - Completed by the CLI command split into focused modules under
    `src/openbbq/cli/`, with `src/openbbq/cli/app.py` retained as the thin entry
    point and parser/dispatch orchestrator.
```

Remove this bullet from `### Remaining`:

```markdown
- **P1: CLI module mixes too many responsibilities**
```

In the `## Next slice` section, replace the current text with:

```markdown
The next implementation slice should be **Plugin registry boundary split**. It
is the highest-priority remaining P2 audit item and should preserve
`discover_plugins()` and the current registry API.
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli_module_split.py tests/test_package_layout.py tests/test_cli_smoke.py tests/test_config_precedence.py -q
```

Expected: PASS.

- [ ] **Step 7: Run focused lint and format checks**

Run:

```bash
uv run ruff check src/openbbq/cli tests/test_cli_module_split.py tests/test_package_layout.py
uv run ruff format --check src/openbbq/cli tests/test_cli_module_split.py tests/test_package_layout.py
```

Expected: both commands exit 0.

- [ ] **Step 8: Commit final app cleanup and tracking update**

Run:

```bash
git add src/openbbq/cli tests/test_cli_module_split.py tests/test_package_layout.py docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
git commit -m "refactor: Finalize CLI command split"
```

---

### Task 10: Full CLI contract verification

**Files:**
- No planned file changes.

- [ ] **Step 1: Run CLI contract test groups**

Run:

```bash
uv run pytest tests/test_cli_smoke.py tests/test_config_precedence.py -q
uv run pytest tests/test_cli_integration.py tests/test_cli_control_flow.py -q
uv run pytest tests/test_artifact_import.py tests/test_artifact_diff.py -q
uv run pytest tests/test_cli_quickstart.py tests/test_runtime_cli.py -q
uv run pytest tests/test_phase1_acceptance.py -q
uv run pytest tests/test_phase2_local_video_subtitle.py tests/test_phase2_remote_video_slice.py tests/test_phase2_translation_slice.py tests/test_phase2_asr_correction_segmentation.py -q
```

Expected: every command exits 0.

- [ ] **Step 2: Check the CLI module size reduction**

Run:

```bash
wc -l src/openbbq/cli/app.py src/openbbq/cli/*.py
```

Expected: `src/openbbq/cli/app.py` is much smaller than its starting size of
about 970 lines, and command-specific code now lives in command modules.

- [ ] **Step 3: Verify no command handlers remain in `app.py`**

Run:

```bash
rg -n "^def _(init_project|project_|validate|run|resume|abort|unlock|status|logs|artifact_|plugin_|settings_|auth_|secret_|models_|doctor|subtitle_)" src/openbbq/cli/app.py
```

Expected: no matches.

- [ ] **Step 4: Check git status**

Run:

```bash
git status -sb
```

Expected: no uncommitted changes.

---

### Task 11: Final verification

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

- [ ] **Step 4: Inspect final branch state**

Run:

```bash
git status -sb
git log --oneline --decorate -12
```

Expected: clean working tree on the feature branch with the CLI split commits
on top of the CLI split plan commit.

---

## Self-Review

- Spec coverage: The plan splits `app.py` into command modules, preserves
  `openbbq.cli.app:main`, keeps `_build_parser()` and `_effective_log_level()`
  available, adds shared output/context helpers, preserves CLI behavior through
  existing contract tests, and updates the audit closure tracking spec.
- Placeholder scan: The plan contains concrete file paths, code blocks, command
  snippets, and expected results.
- Type consistency: Every command module uses the same `register(subparsers,
  parents)` and `dispatch(args) -> int | None` interface. `app.py` uses one
  `_COMMAND_MODULES` tuple for both parser registration and dispatch.
