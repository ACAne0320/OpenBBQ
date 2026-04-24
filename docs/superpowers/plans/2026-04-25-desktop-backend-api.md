# Desktop Backend API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Pydantic-validated FastAPI sidecar backend that the future Electron desktop can call without depending on CLI internals.

**Architecture:** Keep `openbbq.application` as the shared business-service layer and add `openbbq.api` as a thin HTTP/SSE adapter. Introduce a minimal `RunRecord` layer so desktop calls receive stable run handles while the existing workflow engine and `.openbbq/` storage remain the execution source of truth.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, Uvicorn, pytest, Ruff, filesystem-backed `.openbbq/` storage.

---

## Scope And Sequencing

This plan implements the approved spec in one sequential backend milestone. The slices are dependent: API routes need application services, run routes need run storage, and SSE needs event read helpers. Do not start desktop UI work in this plan.

Do not migrate CLI JSON output to the new `{"ok": true, "data": ...}` envelope in this milestone. Keep current CLI command payloads stable while adding API envelopes.

## File Structure

Create:

- `src/openbbq/api/__init__.py` - exports the API app factory.
- `src/openbbq/api/app.py` - FastAPI app factory, route registration, app settings.
- `src/openbbq/api/auth.py` - local bearer-token middleware.
- `src/openbbq/api/errors.py` - exception handlers and HTTP status mapping.
- `src/openbbq/api/schemas.py` - Pydantic API request, response, and SSE models.
- `src/openbbq/api/server.py` - sidecar CLI entry point with machine-readable startup output.
- `src/openbbq/api/routes/__init__.py` - route package marker.
- `src/openbbq/api/routes/health.py` - `GET /health`.
- `src/openbbq/api/routes/projects.py` - current project and initialization routes.
- `src/openbbq/api/routes/plugins.py` - plugin list and detail routes.
- `src/openbbq/api/routes/runtime.py` - settings, provider, model, and doctor routes.
- `src/openbbq/api/routes/workflows.py` - workflow list, detail, validate, status, and event history routes.
- `src/openbbq/api/routes/runs.py` - run create/status/resume/abort routes.
- `src/openbbq/api/routes/artifacts.py` - artifact list/show/version/import/diff routes.
- `src/openbbq/api/routes/events.py` - SSE formatting and streaming helpers.
- `src/openbbq/application/projects.py` - project init and project info services.
- `src/openbbq/application/plugins.py` - plugin list/detail services.
- `src/openbbq/application/runtime.py` - runtime settings, providers, auth, secrets, and model status services.
- `src/openbbq/application/diagnostics.py` - doctor service wrapper.
- `src/openbbq/application/quickstart.py` - generated subtitle workflow helpers moved from CLI.
- `src/openbbq/application/runs.py` - run records, run creation, background execution, resume, abort, and status.
- `src/openbbq/storage/runs.py` - persisted run JSON helpers.
- `tests/test_api_schemas.py`
- `tests/test_api_health.py`
- `tests/test_application_projects_plugins.py`
- `tests/test_application_runtime_diagnostics.py`
- `tests/test_application_quickstart.py`
- `tests/test_storage_runs.py`
- `tests/test_application_runs.py`
- `tests/test_api_projects_plugins_runtime.py`
- `tests/test_api_workflows_artifacts_runs.py`
- `tests/test_api_events.py`
- `tests/test_api_server.py`

Modify:

- `pyproject.toml` - add API optional dependency, dev test dependency, and `openbbq-api` script.
- `src/openbbq/cli/app.py` - call application services for project, plugin, runtime, doctor, and quickstart behavior.
- `src/openbbq/storage/models.py` - add `RunRecord`, `RunStatus`, `RunMode`, and `RunErrorRecord`.
- `src/openbbq/storage/project_store.py` - retain `state_base` so runs can live under `.openbbq/state/runs`.
- `src/openbbq/storage/events.py` - add typed event read helpers.
- `src/openbbq/application/workflows.py` - use storage event readers and expose workflow summaries/events.
- `src/openbbq/application/artifacts.py` - expose artifact version lookup as an application service.
- `tests/test_cli_quickstart.py` - import generated workflow helpers from `openbbq.application.quickstart`.
- Existing CLI tests - update imports only where behavior was moved; keep payload assertions unchanged.

Delete:

- `src/openbbq/cli/quickstart.py` after imports move to `openbbq.application.quickstart`.

---

## Task 1: API Dependencies And Shared Schemas

**Files:**
- Modify: `pyproject.toml`
- Create: `src/openbbq/api/__init__.py`
- Create: `src/openbbq/api/schemas.py`
- Test: `tests/test_api_schemas.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_api_schemas.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.api.schemas import (
    ApiError,
    ApiErrorResponse,
    ApiSuccess,
    HealthData,
    RunCreateRequest,
    RunRecord,
)


def test_api_success_envelope_validates_payload():
    response = ApiSuccess[HealthData](
        data=HealthData(version="0.1.0", pid=123, project_root=Path("/tmp/project"))
    )

    assert response.model_dump(mode="json") == {
        "ok": True,
        "data": {
            "version": "0.1.0",
            "pid": 123,
            "project_root": "/tmp/project",
        },
    }


def test_api_error_response_includes_details():
    response = ApiErrorResponse(
        error=ApiError(
            code="validation_error",
            message="Project config is invalid.",
            details={"field": "project.name"},
        )
    )

    assert response.ok is False
    assert response.error.details == {"field": "project.name"}


def test_run_create_request_rejects_force_with_step_id():
    with pytest.raises(PydanticValidationError, match="force cannot be combined"):
        RunCreateRequest(
            project_root=Path("/tmp/project"),
            workflow_id="demo",
            force=True,
            step_id="translate",
        )


def test_run_record_uses_known_statuses():
    record = RunRecord(
        id="run_abc",
        workflow_id="demo",
        mode="start",
        status="queued",
        project_root=Path("/tmp/project"),
        latest_event_sequence=0,
        created_by="api",
    )

    assert record.status == "queued"
```

- [ ] **Step 2: Run the schema test to verify it fails**

Run:

```bash
uv run pytest tests/test_api_schemas.py -v
```

Expected: FAIL because `openbbq.api.schemas` does not exist.

- [ ] **Step 3: Add API dependencies and script metadata**

Modify `pyproject.toml` so the relevant sections contain these entries:

```toml
[project]
dependencies = ["PyYAML>=6.0", "jsonschema>=4.0", "pydantic>=2.0"]

[project.optional-dependencies]
api = ["fastapi>=0.115", "uvicorn>=0.30"]
media = ["faster-whisper>=1.2"]
llm = ["openai>=1.0"]
download = ["yt-dlp>=2024.12.0"]
secrets = ["keyring>=25"]

[project.scripts]
openbbq = "openbbq.cli.app:main"
openbbq-api = "openbbq.api.server:main"

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.6", "httpx>=0.27", "fastapi>=0.115", "uvicorn>=0.30"]
```

Keep any package-data entries currently present in the file.

- [ ] **Step 4: Add the API package marker**

Create `src/openbbq/api/__init__.py`:

```python
from __future__ import annotations
```

Task 2 will export `create_app` from this package after `openbbq.api.app` exists.

- [ ] **Step 5: Add shared API schema models**

Create `src/openbbq/api/schemas.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeAlias, TypeVar

from pydantic import Field, model_validator

from openbbq.domain.base import JsonObject, JsonValue, OpenBBQModel
from openbbq.runtime.models import DoctorCheck, ModelAssetStatus, ProviderProfile, RuntimeSettings
from openbbq.storage.models import ArtifactRecord, ArtifactVersionRecord, WorkflowEvent, WorkflowState

T = TypeVar("T")

RunMode: TypeAlias = Literal["start", "resume", "step_rerun", "force_rerun"]
RunStatus: TypeAlias = Literal["queued", "running", "paused", "completed", "failed", "aborted"]
RunCreator: TypeAlias = Literal["api", "cli", "desktop"]


class ApiSuccess(OpenBBQModel, Generic[T]):
    ok: Literal[True] = True
    data: T


class ApiError(OpenBBQModel):
    code: str
    message: str
    details: JsonObject = Field(default_factory=dict)


class ApiErrorResponse(OpenBBQModel):
    ok: Literal[False] = False
    error: ApiError


class HealthData(OpenBBQModel):
    version: str
    pid: int
    project_root: Path | None = None


class ProjectInfoData(OpenBBQModel):
    id: str | None
    name: str
    root_path: Path
    config_path: Path
    workflow_count: int
    plugin_paths: tuple[Path, ...]
    artifact_storage_path: Path
    state_storage_path: Path


class WorkflowStepSummary(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    outputs: tuple[JsonObject, ...]


class WorkflowSummary(OpenBBQModel):
    id: str
    name: str
    steps: tuple[WorkflowStepSummary, ...]
    state: WorkflowState
    latest_event_sequence: int


class RunCreateRequest(OpenBBQModel):
    project_root: Path
    workflow_id: str
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    force: bool = False
    step_id: str | None = None
    created_by: RunCreator = "api"

    @model_validator(mode="after")
    def force_without_step_id(self) -> RunCreateRequest:
        if self.force and self.step_id is not None:
            raise ValueError("force cannot be combined with step_id")
        return self


class RunError(OpenBBQModel):
    code: str
    message: str


class RunRecord(OpenBBQModel):
    id: str
    workflow_id: str
    mode: RunMode
    status: RunStatus
    project_root: Path
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    started_at: str | None = None
    completed_at: str | None = None
    latest_event_sequence: int = 0
    error: RunError | None = None
    created_by: RunCreator = "api"


class ArtifactVersionData(OpenBBQModel):
    record: ArtifactVersionRecord
    content: JsonValue | bytes


class ArtifactShowData(OpenBBQModel):
    artifact: ArtifactRecord
    current_version: ArtifactVersionData


class PluginListData(OpenBBQModel):
    plugins: tuple[JsonObject, ...]
    invalid_plugins: tuple[JsonObject, ...]
    warnings: tuple[str, ...]


class RuntimeSettingsData(OpenBBQModel):
    settings: RuntimeSettings


class ProviderData(OpenBBQModel):
    provider: ProviderProfile
    config_path: Path


class ModelListData(OpenBBQModel):
    models: tuple[ModelAssetStatus, ...]


class DoctorData(OpenBBQModel):
    ok: bool
    checks: tuple[DoctorCheck, ...]


class EventStreamItem(OpenBBQModel):
    event: WorkflowEvent
```

- [ ] **Step 6: Run the schema test to verify it passes**

Run:

```bash
uv run pytest tests/test_api_schemas.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/openbbq/api/__init__.py src/openbbq/api/schemas.py tests/test_api_schemas.py
git commit -m "feat: add API schema contracts"
```

---

## Task 2: FastAPI App, Auth, Error Handling, And Health

**Files:**
- Create: `src/openbbq/api/app.py`
- Create: `src/openbbq/api/auth.py`
- Create: `src/openbbq/api/errors.py`
- Create: `src/openbbq/api/routes/__init__.py`
- Create: `src/openbbq/api/routes/health.py`
- Test: `tests/test_api_health.py`

- [ ] **Step 1: Write failing API health tests**

Create `tests/test_api_health.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app


def test_health_is_available_without_token(tmp_path):
    app = create_app(ApiAppSettings(project_root=tmp_path, token="secret-token"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["project_root"] == str(tmp_path)


def test_authorized_route_requires_bearer_token(tmp_path):
    app = create_app(ApiAppSettings(project_root=tmp_path, token="secret-token"))
    client = TestClient(app)

    response = client.get("/projects/current")

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "unauthorized",
            "message": "Missing or invalid bearer token.",
            "details": {},
        },
    }


def test_authorized_route_accepts_bearer_token(tmp_path):
    app = create_app(ApiAppSettings(project_root=tmp_path, token="secret-token"))
    client = TestClient(app)
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n\nproject:\n  name: Demo\n\nworkflows: {}\n",
        encoding="utf-8",
    )

    response = client.get(
        "/projects/current",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code != 401
```

The last test will still fail until the projects route exists in Task 8. Keep it marked with the expected non-401 assertion so it verifies middleware behavior once routes are registered.

- [ ] **Step 2: Run the health tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api_health.py -v
```

Expected: FAIL because `openbbq.api.app` does not exist.

- [ ] **Step 3: Add API app settings and route registration**

Create `src/openbbq/api/app.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from openbbq import __version__
from openbbq.api.auth import install_auth_middleware
from openbbq.api.errors import install_error_handlers
from openbbq.api.routes import health
from openbbq.domain.base import OpenBBQModel


class ApiAppSettings(OpenBBQModel):
    project_root: Path | None = None
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    token: str | None = None
    allow_dev_cors: bool = False
    execute_runs_inline: bool = False


def create_app(settings: ApiAppSettings | None = None) -> FastAPI:
    app_settings = settings or ApiAppSettings()
    app = FastAPI(title="OpenBBQ API", version=__version__)
    app.state.openbbq_settings = app_settings
    install_error_handlers(app)
    install_auth_middleware(app, app_settings)
    app.include_router(health.router)
    return app


def app_settings(app: FastAPI) -> ApiAppSettings:
    return app.state.openbbq_settings
```

Update `src/openbbq/api/__init__.py`:

```python
from __future__ import annotations

from openbbq.api.app import ApiAppSettings, create_app

__all__ = ["ApiAppSettings", "create_app"]
```

- [ ] **Step 4: Add bearer token middleware**

Create `src/openbbq/api/auth.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from openbbq.api.schemas import ApiError, ApiErrorResponse

AUTH_EXEMPT_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/redoc"})


def install_auth_middleware(app: FastAPI, settings) -> None:
    @app.middleware("http")
    async def require_bearer_token(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        token = settings.token
        if token is None or request.url.path in AUTH_EXEMPT_PATHS:
            return await call_next(request)
        expected = f"Bearer {token}"
        if request.headers.get("Authorization") != expected:
            payload = ApiErrorResponse(
                error=ApiError(
                    code="unauthorized",
                    message="Missing or invalid bearer token.",
                )
            )
            return JSONResponse(
                status_code=401,
                content=payload.model_dump(mode="json"),
            )
        return await call_next(request)
```

- [ ] **Step 5: Add OpenBBQ error conversion**

Create `src/openbbq/api/errors.py`:

```python
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from openbbq.api.schemas import ApiError, ApiErrorResponse
from openbbq.errors import OpenBBQError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OpenBBQError)
    async def openbbq_error_handler(request: Request, exc: OpenBBQError) -> JSONResponse:
        payload = ApiErrorResponse(error=ApiError(code=exc.code, message=exc.message))
        return JSONResponse(
            status_code=_status_code(exc),
            content=payload.model_dump(mode="json"),
        )


def _status_code(error: OpenBBQError) -> int:
    if error.code == "validation_error":
        return 422
    if error.code == "artifact_not_found":
        return 404
    if error.code in {"invalid_workflow_state", "invalid_command_usage"}:
        return 409
    return 500 if error.exit_code >= 5 else 400
```

- [ ] **Step 6: Add health route**

Create `src/openbbq/api/routes/__init__.py`:

```python
from __future__ import annotations
```

Create `src/openbbq/api/routes/health.py`:

```python
from __future__ import annotations

import os

from fastapi import APIRouter, Request

from openbbq import __version__
from openbbq.api.schemas import ApiSuccess, HealthData

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiSuccess[HealthData])
def health(request: Request) -> ApiSuccess[HealthData]:
    settings = request.app.state.openbbq_settings
    return ApiSuccess(
        data=HealthData(
            version=__version__,
            pid=os.getpid(),
            project_root=settings.project_root,
        )
    )
```

- [ ] **Step 7: Run the focused health tests**

Run:

```bash
uv run pytest tests/test_api_schemas.py tests/test_api_health.py -v
```

Expected: the first two health tests PASS. The third test may return 404 until Task 8 registers `/projects/current`, but it must not return 401.

- [ ] **Step 8: Commit**

```bash
git add src/openbbq/api/app.py src/openbbq/api/auth.py src/openbbq/api/errors.py src/openbbq/api/routes/__init__.py src/openbbq/api/routes/health.py tests/test_api_health.py
git commit -m "feat: add FastAPI sidecar foundation"
```

---

## Task 3: Project And Plugin Application Services

**Files:**
- Create: `src/openbbq/application/projects.py`
- Create: `src/openbbq/application/plugins.py`
- Modify: `src/openbbq/cli/app.py`
- Test: `tests/test_application_projects_plugins.py`
- Test: `tests/test_cli_integration.py`

- [ ] **Step 1: Write failing project and plugin service tests**

Create `tests/test_application_projects_plugins.py`:

```python
from pathlib import Path

import pytest

from openbbq.application.plugins import plugin_info, plugin_list
from openbbq.application.projects import ProjectInitRequest, init_project, project_info
from openbbq.errors import ValidationError


def test_project_service_initializes_and_reports_project(tmp_path):
    result = init_project(ProjectInitRequest(project_root=tmp_path))
    info = project_info(project_root=tmp_path)

    assert result.config_path == tmp_path / "openbbq.yaml"
    assert info.name == "OpenBBQ Project"
    assert info.workflow_count == 0
    assert info.artifact_storage_path == tmp_path / ".openbbq" / "artifacts"


def test_project_service_rejects_existing_config(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n\nproject:\n  name: Demo\n\nworkflows: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="already exists"):
        init_project(ProjectInitRequest(project_root=tmp_path))


def test_plugin_service_lists_and_describes_fixture_plugin(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/text-basic/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )

    listed = plugin_list(project_root=project)
    info = plugin_info(project_root=project, plugin_name="mock_text")

    assert [plugin["name"] for plugin in listed.plugins] == ["mock_text"]
    assert info.plugin["name"] == "mock_text"
    assert any(tool["name"] == "uppercase" for tool in info.plugin["tools"])
```

- [ ] **Step 2: Run the service tests to verify they fail**

Run:

```bash
uv run pytest tests/test_application_projects_plugins.py -v
```

Expected: FAIL because the new application modules do not exist.

- [ ] **Step 3: Add project application service**

Create `src/openbbq/application/projects.py`:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.errors import ValidationError


class ProjectInitRequest(OpenBBQModel):
    project_root: Path
    config_path: Path | None = None


class ProjectInitResult(OpenBBQModel):
    config_path: Path


class ProjectInfoResult(OpenBBQModel):
    id: str | None
    name: str
    root_path: Path
    config_path: Path
    workflow_count: int
    plugin_paths: tuple[Path, ...]
    artifact_storage_path: Path
    state_storage_path: Path


def init_project(request: ProjectInitRequest) -> ProjectInitResult:
    project_root = request.project_root.expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = (
        request.config_path.expanduser().resolve()
        if request.config_path is not None
        else project_root / "openbbq.yaml"
    )
    if config_path.exists():
        raise ValidationError(f"Project config already exists: {config_path}", exit_code=1)
    config_path.write_text(
        "version: 1\n\nproject:\n  name: OpenBBQ Project\n\nworkflows: {}\n",
        encoding="utf-8",
    )
    (project_root / ".openbbq" / "artifacts").mkdir(parents=True, exist_ok=True)
    (project_root / ".openbbq" / "state").mkdir(parents=True, exist_ok=True)
    return ProjectInitResult(config_path=config_path)


def project_info(
    *,
    project_root: Path,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> ProjectInfoResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    return ProjectInfoResult(
        id=config.project.id,
        name=config.project.name,
        root_path=config.root_path,
        config_path=config.config_path,
        workflow_count=len(config.workflows),
        plugin_paths=config.plugin_paths,
        artifact_storage_path=config.storage.artifacts,
        state_storage_path=config.storage.state,
    )
```

- [ ] **Step 4: Add plugin application service**

Create `src/openbbq/application/plugins.py`:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.errors import ValidationError
from openbbq.plugins.registry import discover_plugins


class PluginListResult(OpenBBQModel):
    plugins: tuple[JsonObject, ...]
    invalid_plugins: tuple[JsonObject, ...]
    warnings: tuple[str, ...]


class PluginInfoResult(OpenBBQModel):
    plugin: JsonObject


def plugin_list(
    *,
    project_root: Path,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> PluginListResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    return PluginListResult(
        plugins=tuple(
            {
                "name": plugin.name,
                "version": plugin.version,
                "runtime": plugin.runtime,
                "manifest_path": str(plugin.manifest_path),
            }
            for plugin in registry.plugins.values()
        ),
        invalid_plugins=tuple(
            {"path": str(invalid.path), "error": invalid.error}
            for invalid in registry.invalid_plugins
        ),
        warnings=tuple(registry.warnings),
    )


def plugin_info(
    *,
    project_root: Path,
    plugin_name: str,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> PluginInfoResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    plugin = registry.plugins.get(plugin_name)
    if plugin is None:
        raise ValidationError(f"Plugin '{plugin_name}' was not found.", exit_code=4)
    return PluginInfoResult(
        plugin={
            "name": plugin.name,
            "version": plugin.version,
            "runtime": plugin.runtime,
            "entrypoint": plugin.entrypoint,
            "manifest_path": str(plugin.manifest_path),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_artifact_types": tool.input_artifact_types,
                    "output_artifact_types": tool.output_artifact_types,
                    "inputs": {
                        name: spec.model_dump(mode="json")
                        for name, spec in tool.inputs.items()
                    },
                    "outputs": {
                        name: spec.model_dump(mode="json")
                        for name, spec in tool.outputs.items()
                    },
                    "runtime_requirements": tool.runtime_requirements.model_dump(mode="json"),
                    "ui": tool.ui.model_dump(mode="json"),
                    "parameter_schema": tool.parameter_schema,
                    "effects": tool.effects,
                }
                for tool in plugin.tools
            ],
        }
    )
```

- [ ] **Step 5: Update CLI project and plugin commands**

In `src/openbbq/cli/app.py`, add imports:

```python
from openbbq.application.plugins import plugin_info as plugin_info_command
from openbbq.application.plugins import plugin_list as plugin_list_command
from openbbq.application.projects import (
    ProjectInitRequest,
    init_project as init_project_command,
    project_info as project_info_command,
)
```

Replace `_init_project()` with:

```python
def _init_project(args: argparse.Namespace) -> int:
    result = init_project_command(
        ProjectInitRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
        )
    )
    _emit(
        {"ok": True, "config_path": str(result.config_path)},
        args.json_output,
        f"Initialized {result.config_path}",
    )
    return 0
```

Replace `_project_info()` with:

```python
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
    _emit(payload, args.json_output, f"{info.name}: {info.workflow_count} workflow(s)")
    return 0
```

Replace `_plugin_list()` with:

```python
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
    _emit(payload, args.json_output, "\n".join(plugin["name"] for plugin in result.plugins))
    return 0
```

Replace `_plugin_info()` with:

```python
def _plugin_info(args: argparse.Namespace) -> int:
    result = plugin_info_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        plugin_name=args.name,
    )
    payload = {"ok": True, "plugin": result.plugin}
    _emit(payload, args.json_output, result.plugin["name"])
    return 0
```

- [ ] **Step 6: Run service and CLI regression tests**

Run:

```bash
uv run pytest tests/test_application_projects_plugins.py tests/test_cli_integration.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openbbq/application/projects.py src/openbbq/application/plugins.py src/openbbq/cli/app.py tests/test_application_projects_plugins.py
git commit -m "refactor: extract project and plugin services"
```

---

## Task 4: Runtime, Auth, Secret, Model, And Doctor Services

**Files:**
- Create: `src/openbbq/application/runtime.py`
- Create: `src/openbbq/application/diagnostics.py`
- Modify: `src/openbbq/cli/app.py`
- Test: `tests/test_application_runtime_diagnostics.py`
- Test: `tests/test_runtime_cli.py`

- [ ] **Step 1: Write failing runtime service tests**

Create `tests/test_application_runtime_diagnostics.py`:

```python
from pathlib import Path

import pytest

from openbbq.application.diagnostics import doctor
from openbbq.application.runtime import (
    AuthSetRequest,
    ProviderSetRequest,
    auth_check,
    auth_set,
    model_list,
    provider_set,
    secret_check,
    settings_show,
)
from openbbq.errors import ValidationError


def test_provider_set_and_settings_show_use_runtime_config(tmp_path, monkeypatch):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    provider = provider_set(
        ProviderSetRequest(
            name="openai",
            type="openai_compatible",
            base_url="https://api.openai.com/v1",
            api_key="env:OPENBBQ_LLM_API_KEY",
            default_chat_model="gpt-4o-mini",
        )
    )
    settings = settings_show()

    assert provider.provider.name == "openai"
    assert settings.settings.providers["openai"].api_key == "env:OPENBBQ_LLM_API_KEY"


def test_auth_set_requires_secret_reference_in_noninteractive_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))

    with pytest.raises(ValidationError, match="api-key-ref"):
        auth_set(AuthSetRequest(name="openai", type="openai_compatible"))


def test_auth_check_reports_unresolved_env_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)
    auth_set(
        AuthSetRequest(
            name="openai",
            type="openai_compatible",
            api_key_ref="env:OPENBBQ_LLM_API_KEY",
        )
    )

    result = auth_check("openai")

    assert result.secret.resolved is False
    assert "OPENBBQ_LLM_API_KEY" in str(result.secret.error)


def test_secret_check_and_model_list_return_pydantic_results(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))
    result = secret_check("env:OPENBBQ_MISSING_SECRET")
    models = model_list()

    assert result.secret.resolved is False
    assert models.models[0].provider == "faster_whisper"


def test_doctor_service_reports_setting_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)

    result = doctor(project_root=tmp_path)

    assert isinstance(result.ok, bool)
    assert result.checks
```

- [ ] **Step 2: Run runtime service tests to verify they fail**

Run:

```bash
uv run pytest tests/test_application_runtime_diagnostics.py -v
```

Expected: FAIL because the new application modules do not exist.

- [ ] **Step 3: Add runtime application service**

Create `src/openbbq/application/runtime.py`:

```python
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import OpenBBQModel, format_pydantic_error
from openbbq.errors import ValidationError
from openbbq.runtime.models import ModelAssetStatus, ProviderProfile, RuntimeSettings, SecretCheck
from openbbq.runtime.models_assets import faster_whisper_model_status
from openbbq.runtime.secrets import SecretResolver
from openbbq.runtime.settings import load_runtime_settings, with_provider_profile, write_runtime_settings


class SettingsShowResult(OpenBBQModel):
    settings: RuntimeSettings


class ProviderSetRequest(OpenBBQModel):
    name: str
    type: str
    base_url: str | None = None
    api_key: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None


class ProviderSetResult(OpenBBQModel):
    provider: ProviderProfile
    config_path: Path


class AuthSetRequest(OpenBBQModel):
    name: str
    type: str = "openai_compatible"
    base_url: str | None = None
    api_key_ref: str | None = None
    secret_value: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None


class AuthSetResult(OpenBBQModel):
    provider: ProviderProfile
    secret_stored: bool
    config_path: Path


class AuthCheckResult(OpenBBQModel):
    provider: ProviderProfile
    secret: SecretCheck


class SecretCheckResult(OpenBBQModel):
    secret: SecretCheck


class SecretSetRequest(OpenBBQModel):
    reference: str
    value: str


class ModelListResult(OpenBBQModel):
    models: tuple[ModelAssetStatus, ...]


def settings_show() -> SettingsShowResult:
    return SettingsShowResult(settings=load_runtime_settings())


def provider_set(request: ProviderSetRequest) -> ProviderSetResult:
    try:
        provider = ProviderProfile(
            name=request.name,
            type=request.type,
            base_url=request.base_url,
            api_key=request.api_key,
            default_chat_model=request.default_chat_model,
            display_name=request.display_name,
        )
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error(f"providers.{request.name}", exc)) from exc
    settings = load_runtime_settings()
    updated = with_provider_profile(settings, provider)
    write_runtime_settings(updated)
    return ProviderSetResult(provider=provider, config_path=updated.config_path)


def auth_set(request: AuthSetRequest) -> AuthSetResult:
    api_key_ref = request.api_key_ref
    stored_secret = False
    if api_key_ref is None:
        if request.secret_value is None:
            raise ValidationError("auth set requires --api-key-ref when non-interactive.")
        api_key_ref = _default_provider_keyring_reference(request.name)
        SecretResolver().set_secret(api_key_ref, request.secret_value)
        stored_secret = True
    provider = ProviderProfile(
        name=request.name,
        type=request.type,
        base_url=request.base_url,
        api_key=api_key_ref,
        default_chat_model=request.default_chat_model,
        display_name=request.display_name,
    )
    settings = load_runtime_settings()
    updated = with_provider_profile(settings, provider)
    write_runtime_settings(updated)
    return AuthSetResult(provider=provider, secret_stored=stored_secret, config_path=updated.config_path)


def auth_check(name: str) -> AuthCheckResult:
    settings = load_runtime_settings()
    provider = settings.providers.get(name)
    if provider is None:
        raise ValidationError(f"Provider '{name}' is not configured.")
    if provider.api_key is None:
        secret = SecretCheck(
            reference="",
            resolved=False,
            display="",
            value_preview=None,
            error=f"Provider '{name}' does not define an API key reference.",
        )
    else:
        secret = SecretResolver().resolve(provider.api_key).public
    return AuthCheckResult(provider=provider, secret=secret)


def secret_check(reference: str) -> SecretCheckResult:
    return SecretCheckResult(secret=SecretResolver().resolve(reference).public)


def secret_set(request: SecretSetRequest) -> SecretCheckResult:
    SecretResolver().set_secret(request.reference, request.value)
    return SecretCheckResult(secret=SecretResolver().resolve(request.reference).public)


def model_list() -> ModelListResult:
    return ModelListResult(models=(faster_whisper_model_status(load_runtime_settings()),))


def _default_provider_keyring_reference(name: str) -> str:
    return f"keyring:openbbq/providers/{name}/api_key"
```

- [ ] **Step 4: Add diagnostics application service**

Create `src/openbbq/application/diagnostics.py`:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.doctor import check_settings, check_workflow
from openbbq.runtime.models import DoctorCheck
from openbbq.runtime.settings import load_runtime_settings


class DoctorResult(OpenBBQModel):
    ok: bool
    checks: tuple[DoctorCheck, ...]


def doctor(
    *,
    project_root: Path,
    workflow_id: str | None = None,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> DoctorResult:
    settings = load_runtime_settings()
    if workflow_id is None:
        checks = tuple(check_settings(settings=settings))
    else:
        config = load_project_config(
            project_root,
            config_path=config_path,
            extra_plugin_paths=plugin_paths,
        )
        registry = discover_plugins(config.plugin_paths)
        checks = tuple(
            check_workflow(
                config=config,
                registry=registry,
                workflow_id=workflow_id,
                settings=settings,
            )
        )
    return DoctorResult(ok=all(check.status != "failed" for check in checks), checks=checks)
```

- [ ] **Step 5: Update CLI runtime and doctor commands**

In `src/openbbq/cli/app.py`, add imports:

```python
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
```

Replace `_settings_show()`, `_settings_set_provider()`, `_auth_set()`, `_auth_check()`, `_secret_check()`, `_secret_set()`, `_models_list()`, and `_doctor()` with service calls that preserve current JSON payloads. For `_auth_set()`, keep the CLI prompt in `cli/app.py`:

```python
def _auth_set(args: argparse.Namespace) -> int:
    secret_value = None
    api_key_ref = args.api_key_ref
    if api_key_ref is None:
        if args.json_output:
            raise ValidationError("auth set requires --api-key-ref when --json is used.")
        secret_value = getpass.getpass("API key: ")
    result = auth_set_command(
        AuthSetRequest(
            name=args.name,
            type=args.type,
            base_url=args.base_url,
            api_key_ref=api_key_ref,
            secret_value=secret_value,
            default_chat_model=args.default_chat_model,
            display_name=args.display_name,
        )
    )
    payload = {
        "ok": True,
        "provider": result.provider.public_dict(),
        "secret_stored": result.secret_stored,
        "config_path": str(result.config_path),
    }
    _emit(payload, args.json_output, f"Configured provider '{result.provider.name}'.")
    return 0
```

- [ ] **Step 6: Run runtime service and CLI tests**

Run:

```bash
uv run pytest tests/test_application_runtime_diagnostics.py tests/test_runtime_cli.py tests/test_cli_quickstart.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openbbq/application/runtime.py src/openbbq/application/diagnostics.py src/openbbq/cli/app.py tests/test_application_runtime_diagnostics.py
git commit -m "refactor: extract runtime and diagnostic services"
```

---

## Task 5: Move Quickstart Generation To Application Layer

**Files:**
- Create: `src/openbbq/application/quickstart.py`
- Modify: `src/openbbq/cli/app.py`
- Modify: `tests/test_cli_quickstart.py`
- Delete: `src/openbbq/cli/quickstart.py`
- Test: `tests/test_application_quickstart.py`

- [ ] **Step 1: Write application quickstart test**

Create `tests/test_application_quickstart.py` by moving the pure generation assertions from `tests/test_cli_quickstart.py`:

```python
from importlib import resources

from openbbq.application.quickstart import (
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)


def test_youtube_workflow_template_is_packaged_as_workflow_dsl():
    template = (
        resources.files("openbbq.workflow_templates.youtube_subtitle")
        .joinpath("openbbq.yaml")
        .read_text(encoding="utf-8")
    )

    assert "workflows:" in template
    assert "youtube-to-srt:" in template
    assert "tool_ref: remote_video.download" in template
    assert "tool_ref: translation.translate" in template


def test_youtube_workflow_generation_can_create_isolated_jobs(tmp_path):
    first = write_youtube_subtitle_workflow(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=one",
        source_lang="en",
        target_lang="zh",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="job-one",
    )
    second = write_youtube_subtitle_workflow(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=two",
        source_lang="en",
        target_lang="ja",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="job-two",
    )

    assert first.project_root != second.project_root
    assert "watch?v=one" in first.config_path.read_text(encoding="utf-8")
    assert "watch?v=two" in second.config_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the quickstart test to verify it fails**

Run:

```bash
uv run pytest tests/test_application_quickstart.py -v
```

Expected: FAIL because `openbbq.application.quickstart` does not exist.

- [ ] **Step 3: Move quickstart implementation**

Move the full content of `src/openbbq/cli/quickstart.py` into `src/openbbq/application/quickstart.py`, preserving:

```python
YOUTUBE_SUBTITLE_TEMPLATE_ID = "youtube-subtitle"
YOUTUBE_SUBTITLE_WORKFLOW_ID = "youtube-to-srt"
DEFAULT_YOUTUBE_QUALITY = "best[ext=mp4][height<=720]/best[height<=720]/best"
LOCAL_SUBTITLE_TEMPLATE_ID = "local-subtitle"
LOCAL_SUBTITLE_WORKFLOW_ID = "local-to-srt"

class GeneratedWorkflow(OpenBBQModel):
    project_root: Path
    config_path: Path
    workflow_id: str
    run_id: str
```

Do not keep a compatibility re-export in `openbbq.cli.quickstart`; delete the file after imports are updated.

- [ ] **Step 4: Update imports**

In `src/openbbq/cli/app.py`, replace:

```python
from openbbq.cli.quickstart import (
```

with:

```python
from openbbq.application.quickstart import (
```

In `tests/test_cli_quickstart.py`, remove imports of generation helpers from `openbbq.cli.quickstart`; keep CLI behavior tests in that file and import pure helpers from `openbbq.application.quickstart` only in `tests/test_application_quickstart.py`.

- [ ] **Step 5: Run quickstart and package layout tests**

Run:

```bash
uv run pytest tests/test_application_quickstart.py tests/test_cli_quickstart.py tests/test_package_layout.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/application/quickstart.py src/openbbq/cli/app.py tests/test_application_quickstart.py tests/test_cli_quickstart.py tests/test_package_layout.py
git rm src/openbbq/cli/quickstart.py
git commit -m "refactor: move quickstart generation to application layer"
```

---

## Task 6: Event Read Helpers

**Files:**
- Modify: `src/openbbq/storage/events.py`
- Modify: `src/openbbq/application/workflows.py`
- Test: `tests/test_storage.py`
- Test: `tests/test_application_workflows.py`

- [ ] **Step 1: Add failing event reader tests**

Add to `tests/test_storage.py`:

```python
from openbbq.storage.events import latest_event_sequence, read_events, read_events_after


def test_event_readers_return_typed_events_after_sequence(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    first = store.append_event("demo", {"type": "workflow.started"})
    second = store.append_event("demo", {"type": "workflow.completed"})

    assert [event.id for event in read_events(store.state_root, "demo")] == [
        first.id,
        second.id,
    ]
    assert [event.id for event in read_events_after(store.state_root, "demo", 1)] == [second.id]
    assert latest_event_sequence(store.state_root, "demo") == 2
```

Add to `tests/test_application_workflows.py`:

```python
from openbbq.application.workflows import workflow_events


def test_workflow_events_returns_events_after_sequence(tmp_path):
    project = write_project(tmp_path, "text-basic")
    run_workflow_command(WorkflowRunRequest(project_root=project, workflow_id="text-demo"))

    result = workflow_events(project_root=project, workflow_id="text-demo", after_sequence=1)

    assert result.workflow_id == "text-demo"
    assert all(event.sequence > 1 for event in result.events)
```

- [ ] **Step 2: Run event tests to verify they fail**

Run:

```bash
uv run pytest tests/test_storage.py::test_event_readers_return_typed_events_after_sequence tests/test_application_workflows.py::test_workflow_events_returns_events_after_sequence -v
```

Expected: FAIL because the read helper functions do not exist.

- [ ] **Step 3: Add storage event readers**

Add to `src/openbbq/storage/events.py`:

```python
def read_events(state_root: Path, workflow_id: str) -> tuple[WorkflowEvent, ...]:
    path = events_path(state_root, workflow_id)
    if not path.exists():
        return ()
    events: list[WorkflowEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(WorkflowEvent.model_validate(json.loads(line)))
        except json.JSONDecodeError:
            break
    return tuple(events)


def read_events_after(
    state_root: Path,
    workflow_id: str,
    sequence: int,
) -> tuple[WorkflowEvent, ...]:
    return tuple(event for event in read_events(state_root, workflow_id) if event.sequence > sequence)


def latest_event_sequence(state_root: Path, workflow_id: str) -> int:
    events = read_events(state_root, workflow_id)
    return events[-1].sequence if events else 0
```

- [ ] **Step 4: Add application workflow event service**

In `src/openbbq/application/workflows.py`, import:

```python
from openbbq.storage.events import read_events_after
```

Add:

```python
def workflow_events(
    *,
    project_root: Path,
    workflow_id: str,
    after_sequence: int = 0,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> WorkflowLogsResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    return WorkflowLogsResult(
        workflow_id=workflow_id,
        events=read_events_after(store.state_root, workflow_id, after_sequence),
    )
```

Change `workflow_logs()` to return `workflow_events(..., after_sequence=0)` instead of manually parsing JSONL.

- [ ] **Step 5: Run event tests**

Run:

```bash
uv run pytest tests/test_storage.py tests/test_application_workflows.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/storage/events.py src/openbbq/application/workflows.py tests/test_storage.py tests/test_application_workflows.py
git commit -m "feat: add workflow event readers"
```

---

## Task 7: Run Storage And Application Run Manager

**Files:**
- Modify: `src/openbbq/storage/models.py`
- Modify: `src/openbbq/storage/project_store.py`
- Create: `src/openbbq/storage/runs.py`
- Create: `src/openbbq/application/runs.py`
- Test: `tests/test_storage_runs.py`
- Test: `tests/test_application_runs.py`

- [ ] **Step 1: Write failing run storage tests**

Create `tests/test_storage_runs.py`:

```python
from pathlib import Path

from openbbq.storage.models import RunRecord
from openbbq.storage.runs import list_active_runs, read_run, write_run


def test_write_read_and_list_active_runs(tmp_path):
    state_root = tmp_path / ".openbbq" / "state"
    record = RunRecord(
        id="run_1",
        workflow_id="demo",
        mode="start",
        status="queued",
        project_root=tmp_path,
        latest_event_sequence=0,
        created_by="api",
    )

    written = write_run(state_root, record)
    loaded = read_run(state_root, "run_1")
    active = list_active_runs(state_root, workflow_id="demo")

    assert written == record
    assert loaded == record
    assert [run.id for run in active] == ["run_1"]
```

Create `tests/test_application_runs.py`:

```python
from pathlib import Path

from openbbq.application.runs import RunCreateRequest, create_run, get_run


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def test_create_run_executes_workflow_with_sync_executor(tmp_path):
    project = write_project(tmp_path, "text-basic")

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    loaded = get_run(project_root=project, run_id=created.id)

    assert created.workflow_id == "text-demo"
    assert loaded.status == "completed"
    assert loaded.latest_event_sequence > 0
```

- [ ] **Step 2: Run run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_storage_runs.py tests/test_application_runs.py -v
```

Expected: FAIL because run models and helpers do not exist.

- [ ] **Step 3: Add persisted run models**

In `src/openbbq/storage/models.py`, add:

```python
RunStatus: TypeAlias = Literal["queued", "running", "paused", "completed", "failed", "aborted"]
RunMode: TypeAlias = Literal["start", "resume", "step_rerun", "force_rerun"]
RunCreator: TypeAlias = Literal["api", "cli", "desktop"]


class RunErrorRecord(RecordModel):
    code: str
    message: str


class RunRecord(RecordModel):
    id: str
    workflow_id: str
    mode: RunMode
    status: RunStatus
    project_root: Path
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    started_at: str | None = None
    completed_at: str | None = None
    latest_event_sequence: int = 0
    error: RunErrorRecord | None = None
    created_by: RunCreator = "api"
```

- [ ] **Step 4: Preserve `state_base` in ProjectStore**

In `src/openbbq/storage/project_store.py`, change initialization from:

```python
state_base = Path(state_root) if state_root is not None else self.root / "state"
self.state_root = state_base / "workflows"
```

to:

```python
self.state_base = Path(state_root) if state_root is not None else self.root / "state"
self.state_root = self.state_base / "workflows"
```

- [ ] **Step 5: Add run storage helpers**

Create `src/openbbq/storage/runs.py`:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.storage.json_files import read_json_object, write_json_atomic
from openbbq.storage.models import RunRecord

ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})


def runs_dir(state_base: Path) -> Path:
    return state_base / "runs"


def run_path(state_base: Path, run_id: str) -> Path:
    return runs_dir(state_base) / f"{run_id}.json"


def write_run(state_base: Path, run: RunRecord) -> RunRecord:
    write_json_atomic(run_path(state_base, run.id), run.model_dump(mode="json"))
    return run


def read_run(state_base: Path, run_id: str) -> RunRecord:
    path = run_path(state_base, run_id)
    if not path.exists():
        raise FileNotFoundError(path)
    return RunRecord.model_validate(read_json_object(path))


def list_runs(state_base: Path) -> tuple[RunRecord, ...]:
    directory = runs_dir(state_base)
    if not directory.exists():
        return ()
    runs = [
        RunRecord.model_validate(read_json_object(path))
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name)
    ]
    return tuple(sorted(runs, key=lambda run: (run.started_at or "", run.id)))


def list_active_runs(state_base: Path, *, workflow_id: str) -> tuple[RunRecord, ...]:
    return tuple(
        run
        for run in list_runs(state_base)
        if run.workflow_id == workflow_id and run.status in ACTIVE_RUN_STATUSES
    )
```

- [ ] **Step 6: Add run application service**

Create `src/openbbq/application/runs.py`:

```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import model_validator

from openbbq.application.workflows import WorkflowCommandRequest, WorkflowRunRequest, abort_workflow_command, resume_workflow_command, run_workflow_command
from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.errors import ExecutionError, OpenBBQError, ValidationError
from openbbq.storage import events as event_storage
from openbbq.storage.models import RunErrorRecord, RunRecord
from openbbq.storage.project_store import ProjectStore
from openbbq.storage.runs import list_active_runs, read_run, write_run


class RunCreateRequest(OpenBBQModel):
    project_root: Path
    workflow_id: str
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    force: bool = False
    step_id: str | None = None
    created_by: str = "api"

    @model_validator(mode="after")
    def force_without_step_id(self) -> RunCreateRequest:
        if self.force and self.step_id is not None:
            raise ValueError("force cannot be combined with step_id")
        return self


_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="openbbq-run")


def create_run(request: RunCreateRequest, *, execute_inline: bool = False) -> RunRecord:
    config = load_project_config(
        request.project_root,
        config_path=request.config_path,
        extra_plugin_paths=request.plugin_paths,
    )
    workflow = config.workflows.get(request.workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{request.workflow_id}' is not defined.")
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    active = list_active_runs(store.state_base, workflow_id=request.workflow_id)
    if active:
        raise ExecutionError(
            f"Workflow '{request.workflow_id}' already has an active run.",
            code="active_run_exists",
            exit_code=1,
        )
    mode = "force_rerun" if request.force else ("step_rerun" if request.step_id else "start")
    run = RunRecord(
        id=_new_run_id(),
        workflow_id=request.workflow_id,
        mode=mode,
        status="queued",
        project_root=request.project_root.expanduser().resolve(),
        config_path=request.config_path,
        plugin_paths=request.plugin_paths,
        latest_event_sequence=event_storage.latest_event_sequence(store.state_root, request.workflow_id),
        created_by=request.created_by,
    )
    write_run(store.state_base, run)
    if execute_inline:
        _execute_run(run.id, request)
    else:
        _EXECUTOR.submit(_execute_run, run.id, request)
    return read_run(store.state_base, run.id)


def get_run(*, project_root: Path, run_id: str, config_path: Path | None = None) -> RunRecord:
    config = load_project_config(project_root, config_path=config_path)
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    return read_run(store.state_base, run_id)


def abort_run(*, project_root: Path, run_id: str, config_path: Path | None = None) -> RunRecord:
    run = get_run(project_root=project_root, run_id=run_id, config_path=config_path)
    abort_workflow_command(
        WorkflowCommandRequest(
            project_root=project_root,
            config_path=run.config_path,
            plugin_paths=run.plugin_paths,
            workflow_id=run.workflow_id,
        )
    )
    return get_run(project_root=project_root, run_id=run_id, config_path=config_path)


def resume_run(*, project_root: Path, run_id: str, config_path: Path | None = None) -> RunRecord:
    run = get_run(project_root=project_root, run_id=run_id, config_path=config_path)
    request = RunCreateRequest(
        project_root=project_root,
        config_path=run.config_path,
        plugin_paths=run.plugin_paths,
        workflow_id=run.workflow_id,
        created_by=run.created_by,
    )
    _execute_resume(run.id, request)
    return get_run(project_root=project_root, run_id=run_id, config_path=config_path)


def _execute_run(run_id: str, request: RunCreateRequest) -> None:
    config = load_project_config(
        request.project_root,
        config_path=request.config_path,
        extra_plugin_paths=request.plugin_paths,
    )
    store = ProjectStore(config.storage.root, artifacts_root=config.storage.artifacts, state_root=config.storage.state)
    run = read_run(store.state_base, run_id)
    write_run(store.state_base, run.model_copy(update={"status": "running", "started_at": _now()}))
    try:
        result = run_workflow_command(
            WorkflowRunRequest(
                project_root=request.project_root,
                config_path=request.config_path,
                plugin_paths=request.plugin_paths,
                workflow_id=request.workflow_id,
                force=request.force,
                step_id=request.step_id,
            )
        )
    except OpenBBQError as exc:
        latest = event_storage.latest_event_sequence(store.state_root, request.workflow_id)
        failed = read_run(store.state_base, run_id).model_copy(
            update={
                "status": "failed",
                "completed_at": _now(),
                "latest_event_sequence": latest,
                "error": RunErrorRecord(code=exc.code, message=exc.message),
            }
        )
        write_run(store.state_base, failed)
        return
    latest = event_storage.latest_event_sequence(store.state_root, request.workflow_id)
    completed = read_run(store.state_base, run_id).model_copy(
        update={
            "status": result.status,
            "completed_at": _now() if result.status in {"completed", "failed", "aborted"} else None,
            "latest_event_sequence": latest,
        }
    )
    write_run(store.state_base, completed)


def _execute_resume(run_id: str, request: RunCreateRequest) -> None:
    resume_workflow_command(
        WorkflowCommandRequest(
            project_root=request.project_root,
            config_path=request.config_path,
            plugin_paths=request.plugin_paths,
            workflow_id=request.workflow_id,
        )
    )


def _new_run_id() -> str:
    return f"run_{uuid4().hex}"


def _now() -> str:
    return datetime.now(UTC).isoformat()
```

- [ ] **Step 7: Run run tests**

Run:

```bash
uv run pytest tests/test_storage_runs.py tests/test_application_runs.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/openbbq/storage/models.py src/openbbq/storage/project_store.py src/openbbq/storage/runs.py src/openbbq/application/runs.py tests/test_storage_runs.py tests/test_application_runs.py
git commit -m "feat: add workflow run records"
```

---

## Task 8: Project, Plugin, Runtime, Workflow, Run, And Artifact API Routes

**Files:**
- Modify: `src/openbbq/api/app.py`
- Create: `src/openbbq/api/routes/projects.py`
- Create: `src/openbbq/api/routes/plugins.py`
- Create: `src/openbbq/api/routes/runtime.py`
- Create: `src/openbbq/api/routes/workflows.py`
- Create: `src/openbbq/api/routes/runs.py`
- Create: `src/openbbq/api/routes/artifacts.py`
- Modify: `src/openbbq/application/artifacts.py`
- Test: `tests/test_api_projects_plugins_runtime.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`

- [ ] **Step 1: Add API route tests**

Create `tests/test_api_projects_plugins_runtime.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def authed_client(project):
    client = TestClient(
        create_app(
            ApiAppSettings(project_root=project, token="token", execute_runs_inline=True)
        )
    )
    return client, {"Authorization": "Bearer token"}


def test_project_and_plugin_routes(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client, headers = authed_client(project)

    project_response = client.get("/projects/current", headers=headers)
    plugins_response = client.get("/plugins", headers=headers)
    plugin_response = client.get("/plugins/mock_text", headers=headers)

    assert project_response.status_code == 200
    assert project_response.json()["data"]["name"] == "Text Basic"
    assert plugins_response.json()["data"]["plugins"][0]["name"] == "mock_text"
    assert plugin_response.json()["data"]["plugin"]["name"] == "mock_text"


def test_runtime_routes(tmp_path, monkeypatch):
    project = write_project(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project)

    settings_response = client.get("/runtime/settings", headers=headers)
    models_response = client.get("/runtime/models", headers=headers)
    doctor_response = client.get("/doctor", headers=headers)

    assert settings_response.status_code == 200
    assert "settings" in settings_response.json()["data"]
    assert models_response.json()["data"]["models"][0]["provider"] == "faster_whisper"
    assert isinstance(doctor_response.json()["data"]["checks"], list)
```

Create `tests/test_api_workflows_artifacts_runs.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def test_workflow_run_and_artifact_routes(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client = TestClient(
        create_app(
            ApiAppSettings(project_root=project, token="token", execute_runs_inline=True)
        )
    )
    headers = {"Authorization": "Bearer token"}

    workflows = client.get("/workflows", headers=headers)
    validate = client.post("/workflows/text-demo/validate", headers=headers)
    run = client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"project_root": str(project), "workflow_id": "text-demo"},
    )

    assert workflows.status_code == 200
    assert workflows.json()["data"]["workflows"][0]["id"] == "text-demo"
    assert validate.json()["data"]["workflow_id"] == "text-demo"
    assert run.status_code == 200
    run_id = run.json()["data"]["id"]

    run_status = client.get(f"/runs/{run_id}", headers=headers)
    artifacts = client.get("/artifacts", headers=headers)

    assert run_status.json()["data"]["workflow_id"] == "text-demo"
    assert artifacts.status_code == 200
```

- [ ] **Step 2: Run API route tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py tests/test_api_workflows_artifacts_runs.py -v
```

Expected: FAIL because the route modules are not registered.

- [ ] **Step 3: Add route registration**

In `src/openbbq/api/app.py`, import route modules:

```python
from openbbq.api.routes import artifacts, health, plugins, projects, runtime, runs, workflows
```

In `create_app()`, after `app.include_router(health.router)`, add:

```python
    app.include_router(projects.router)
    app.include_router(plugins.router)
    app.include_router(runtime.router)
    app.include_router(workflows.router)
    app.include_router(runs.router)
    app.include_router(artifacts.router)
```

- [ ] **Step 4: Add route settings helper pattern**

Each route module should use this helper pattern:

```python
def _settings(request: Request):
    return request.app.state.openbbq_settings
```

Use `_settings(request).project_root` for the active project. If it is `None`, raise:

```python
ValidationError("API sidecar does not have an active project root.")
```

- [ ] **Step 5: Add project route**

Create `src/openbbq/api/routes/projects.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess, ProjectInfoData
from openbbq.application.projects import project_info
from openbbq.errors import ValidationError

router = APIRouter(tags=["projects"])


@router.get("/projects/current", response_model=ApiSuccess[ProjectInfoData])
def current_project(request: Request) -> ApiSuccess[ProjectInfoData]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    info = project_info(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=ProjectInfoData(**info.model_dump()))
```

- [ ] **Step 6: Add plugin and runtime routes**

Create `src/openbbq/api/routes/plugins.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess, PluginListData
from openbbq.application.plugins import PluginInfoResult, plugin_info, plugin_list
from openbbq.errors import ValidationError

router = APIRouter(tags=["plugins"])


@router.get("/plugins", response_model=ApiSuccess[PluginListData])
def list_plugins(request: Request) -> ApiSuccess[PluginListData]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    result = plugin_list(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=PluginListData(**result.model_dump()))


@router.get("/plugins/{plugin_name}", response_model=ApiSuccess[PluginInfoResult])
def get_plugin(plugin_name: str, request: Request) -> ApiSuccess[PluginInfoResult]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return ApiSuccess(
        data=plugin_info(
            project_root=settings.project_root,
            config_path=settings.config_path,
            plugin_paths=settings.plugin_paths,
            plugin_name=plugin_name,
        )
    )
```

Create `src/openbbq/api/routes/runtime.py` with routes that wrap `settings_show()`, `provider_set()`, `auth_check()`, `model_list()`, and `doctor()`. Use `ApiSuccess[...]` and the Pydantic result models from the application services.

- [ ] **Step 7: Add workflow and run routes**

Create `src/openbbq/api/routes/workflows.py` with:

```python
@router.get("/workflows")
def list_workflows(request: Request) -> ApiSuccess[dict[str, object]]:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    config = load_project_config(
        settings.project_root,
        config_path=settings.config_path,
        extra_plugin_paths=settings.plugin_paths,
    )
    workflows = [
        {"id": workflow.id, "name": workflow.name, "step_count": len(workflow.steps)}
        for workflow in config.workflows.values()
    ]
    return ApiSuccess(data={"workflows": workflows})
```

Also add:

- `GET /workflows/{workflow_id}` returning workflow ID, name, and steps.
- `POST /workflows/{workflow_id}/validate` wrapping `validate_workflow`.
- `GET /workflows/{workflow_id}/status` wrapping `workflow_status`.
- `GET /workflows/{workflow_id}/events` wrapping `workflow_events`.

Create `src/openbbq/api/routes/runs.py` with:

```python
@router.post("/workflows/{workflow_id}/runs")
def create_workflow_run(
    workflow_id: str,
    body: RunCreateRequest,
    request: Request,
) -> ApiSuccess[RunRecord]:
    settings = request.app.state.openbbq_settings
    run = create_run(
        ApplicationRunCreateRequest(
            project_root=body.project_root,
            config_path=body.config_path or settings.config_path,
            plugin_paths=body.plugin_paths or settings.plugin_paths,
            workflow_id=workflow_id,
            force=body.force,
            step_id=body.step_id,
            created_by=body.created_by,
        ),
        execute_inline=settings.execute_runs_inline,
    )
    return ApiSuccess(data=RunRecord(**run.model_dump()))
```

Use import aliases to avoid name conflict:

```python
from openbbq.api.schemas import RunCreateRequest, RunRecord
from openbbq.application.runs import RunCreateRequest as ApplicationRunCreateRequest
```

- [ ] **Step 8: Add artifact version application service and routes**

In `src/openbbq/application/artifacts.py`, add:

```python
def show_artifact_version(
    *,
    project_root: Path,
    version_id: str,
    config_path: Path | None = None,
) -> StoredArtifactVersion:
    config = load_project_config(project_root, config_path=config_path)
    return _store(config).read_artifact_version(version_id)
```

Create `src/openbbq/api/routes/artifacts.py` with:

- `GET /artifacts` wrapping `list_artifacts`.
- `GET /artifacts/{artifact_id}` wrapping `show_artifact`.
- `GET /artifact-versions/{version_id}` wrapping `show_artifact_version`.
- `POST /artifacts/import` wrapping `import_artifact`.
- `GET /artifact-versions/{from_version_id}/diff/{to_version_id}` wrapping `diff_artifact_versions`.

- [ ] **Step 9: Run route tests**

Run:

```bash
uv run pytest tests/test_api_health.py tests/test_api_projects_plugins_runtime.py tests/test_api_workflows_artifacts_runs.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/openbbq/api/app.py src/openbbq/api/routes src/openbbq/application/artifacts.py tests/test_api_projects_plugins_runtime.py tests/test_api_workflows_artifacts_runs.py
git commit -m "feat: expose desktop backend API routes"
```

---

## Task 9: SSE Event Streaming

**Files:**
- Create: `src/openbbq/api/routes/events.py`
- Modify: `src/openbbq/api/app.py`
- Modify: `src/openbbq/api/routes/workflows.py`
- Test: `tests/test_api_events.py`

- [ ] **Step 1: Write failing SSE formatting and replay tests**

Create `tests/test_api_events.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app
from openbbq.api.routes.events import format_sse
from openbbq.storage.models import WorkflowEvent


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def test_format_sse_serializes_pydantic_event():
    event = WorkflowEvent(
        id="evt_1",
        workflow_id="demo",
        sequence=1,
        type="workflow.started",
        created_at="2026-04-25T00:00:00+00:00",
    )

    rendered = format_sse(event)

    assert rendered.startswith("id: 1\n")
    assert "event: workflow.started\n" in rendered
    assert '"workflow_id":"demo"' in rendered


def test_events_history_route_replays_after_sequence(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client = TestClient(
        create_app(
            ApiAppSettings(project_root=project, token="token", execute_runs_inline=True)
        )
    )
    headers = {"Authorization": "Bearer token"}
    client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"project_root": str(project), "workflow_id": "text-demo"},
    )

    response = client.get("/workflows/text-demo/events?after_sequence=1", headers=headers)

    assert response.status_code == 200
    assert all(event["sequence"] > 1 for event in response.json()["data"]["events"])
```

- [ ] **Step 2: Run event API tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api_events.py -v
```

Expected: FAIL because `openbbq.api.routes.events` does not exist.

- [ ] **Step 3: Add SSE formatting helpers**

Create `src/openbbq/api/routes/events.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

from openbbq.api.schemas import EventStreamItem
from openbbq.application.workflows import workflow_events
from openbbq.storage.models import WorkflowEvent


def format_sse(event: WorkflowEvent) -> str:
    item = EventStreamItem(event=event)
    return f"id: {event.sequence}\nevent: {event.type}\ndata: {item.model_dump_json()}\n\n"


async def event_stream(
    *,
    request: Request,
    project_root,
    workflow_id: str,
    after_sequence: int,
    config_path=None,
    plugin_paths=(),
    poll_interval_seconds: float = 0.25,
) -> AsyncIterator[str]:
    last_sequence = after_sequence
    while True:
        result = workflow_events(
            project_root=project_root,
            config_path=config_path,
            plugin_paths=plugin_paths,
            workflow_id=workflow_id,
            after_sequence=last_sequence,
        )
        for event in result.events:
            last_sequence = event.sequence
            yield format_sse(event)
        if await request.is_disconnected():
            return
        yield ": heartbeat\n\n"
        await asyncio.sleep(poll_interval_seconds)


def streaming_response(iterator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(iterator, media_type="text/event-stream")
```

- [ ] **Step 4: Add stream route to workflows**

In `src/openbbq/api/routes/workflows.py`, add:

```python
from openbbq.api.routes.events import event_stream, streaming_response
```

Add route:

```python
@router.get("/workflows/{workflow_id}/events/stream")
def stream_workflow_events(
    workflow_id: str,
    request: Request,
    after_sequence: int = 0,
):
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return streaming_response(
        event_stream(
            request=request,
            project_root=settings.project_root,
            workflow_id=workflow_id,
            after_sequence=after_sequence,
            config_path=settings.config_path,
            plugin_paths=settings.plugin_paths,
        )
    )
```

- [ ] **Step 5: Run event API tests**

Run:

```bash
uv run pytest tests/test_api_events.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/api/routes/events.py src/openbbq/api/routes/workflows.py tests/test_api_events.py
git commit -m "feat: stream workflow events over SSE"
```

---

## Task 10: Sidecar Server Entry Point

**Files:**
- Create: `src/openbbq/api/server.py`
- Modify: `src/openbbq/cli/app.py`
- Test: `tests/test_api_server.py`

- [ ] **Step 1: Write server argument and startup payload tests**

Create `tests/test_api_server.py`:

```python
from pathlib import Path

from openbbq.api.server import ServerArgs, build_startup_payload, parse_args


def test_parse_args_accepts_sidecar_options():
    args = parse_args(
        [
            "--project",
            "/tmp/project",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--token",
            "secret",
        ]
    )

    assert args == ServerArgs(
        project=Path("/tmp/project"),
        config=None,
        plugins=(),
        host="127.0.0.1",
        port=0,
        token="secret",
    )


def test_build_startup_payload_is_machine_readable():
    payload = build_startup_payload(host="127.0.0.1", port=53124, pid=123)

    assert payload == {"ok": True, "host": "127.0.0.1", "port": 53124, "pid": 123}
```

- [ ] **Step 2: Run server tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api_server.py -v
```

Expected: FAIL because `openbbq.api.server` does not exist.

- [ ] **Step 3: Add sidecar server module**

Create `src/openbbq/api/server.py`:

```python
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket

import uvicorn

from openbbq.api.app import ApiAppSettings, create_app
from openbbq.domain.base import OpenBBQModel


class ServerArgs(OpenBBQModel):
    project: Path | None = None
    config: Path | None = None
    plugins: tuple[Path, ...] = ()
    host: str = "127.0.0.1"
    port: int = 0
    token: str | None = None


def parse_args(argv: list[str] | None = None) -> ServerArgs:
    parser = argparse.ArgumentParser(prog="openbbq-api")
    parser.add_argument("--project")
    parser.add_argument("--config")
    parser.add_argument("--plugins", action="append", default=[])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token")
    parsed = parser.parse_args(argv)
    return ServerArgs(
        project=Path(parsed.project).expanduser().resolve() if parsed.project else None,
        config=Path(parsed.config).expanduser().resolve() if parsed.config else None,
        plugins=tuple(Path(path).expanduser().resolve() for path in parsed.plugins),
        host=parsed.host,
        port=parsed.port,
        token=parsed.token,
    )


def build_startup_payload(*, host: str, port: int, pid: int) -> dict[str, object]:
    return {"ok": True, "host": host, "port": port, "pid": pid}


def bind_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(2048)
    return sock


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = create_app(
        ApiAppSettings(
            project_root=args.project,
            config_path=args.config,
            plugin_paths=args.plugins,
            token=args.token,
        )
    )
    sock = bind_socket(args.host, args.port)
    selected_port = sock.getsockname()[1]
    config = uvicorn.Config(app, host=args.host, port=selected_port, log_level="info")
    server = uvicorn.Server(config)
    print(
        json.dumps(
            build_startup_payload(host=args.host, port=selected_port, pid=os.getpid()),
            ensure_ascii=False,
        ),
        flush=True,
    )
    server.run(sockets=[sock])
    return 0
```

- [ ] **Step 4: Add optional CLI subcommand for discoverability**

In `src/openbbq/cli/app.py`, add an `api` command with a `serve` subcommand that delegates to `openbbq.api.server.main()`:

```python
api = subparsers.add_parser("api", parents=[subcommand_global_options])
api_sub = api.add_subparsers(dest="api_command", required=True)
api_serve = api_sub.add_parser("serve", parents=[subcommand_global_options])
api_serve.add_argument("--host", default="127.0.0.1")
api_serve.add_argument("--port", type=int, default=0)
api_serve.add_argument("--token")
```

In `_dispatch()`:

```python
if args.command == "api":
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
        return api_server_main(argv)
```

- [ ] **Step 5: Run server tests**

Run:

```bash
uv run pytest tests/test_api_server.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/api/server.py src/openbbq/cli/app.py tests/test_api_server.py pyproject.toml
git commit -m "feat: add API sidecar launcher"
```

---

## Task 11: Final Verification And Documentation Alignment

**Files:**
- Modify: `docs/Architecture.md`
- Modify: `docs/Roadmap.md`
- Modify: `docs/phase2/Phase-2-Exit.md`

- [ ] **Step 1: Update architecture docs**

In `docs/Architecture.md`, add an "API sidecar" paragraph under "Backend Layers":

```markdown
The desktop backend adapter is a local FastAPI sidecar managed by Electron main.
It exposes Pydantic-validated REST responses for commands and queries, and SSE
for workflow event streaming. The API layer calls `openbbq.application` services
and does not import CLI parser internals.
```

- [ ] **Step 2: Update roadmap Phase 3 handoff**

In `docs/Roadmap.md`, under Phase 3, add:

```markdown
The desktop communicates with a local Python sidecar over authenticated
loopback HTTP. Electron main owns the token and process lifecycle; the renderer
uses preload IPC rather than owning backend credentials directly.
```

- [ ] **Step 3: Update Phase 2 exit handoff**

In `docs/phase2/Phase-2-Exit.md`, add the new API verification command:

```bash
uv sync --extra api
uv run pytest tests/test_api_health.py tests/test_api_workflows_artifacts_runs.py
```

- [ ] **Step 4: Run full verification**

Run:

```bash
uv sync --extra api
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build --wheel --out-dir /tmp/openbbq-wheel-check
```

Expected: all commands PASS.

- [ ] **Step 5: Search for stale CLI quickstart imports**

Run:

```bash
rg -n "openbbq\\.cli\\.quickstart|from openbbq.cli import quickstart" src tests docs --glob '!docs/superpowers/plans/**'
```

Expected: no matches.

- [ ] **Step 6: Commit documentation and verification updates**

```bash
git add docs/Architecture.md docs/Roadmap.md docs/phase2/Phase-2-Exit.md
git commit -m "docs: document desktop API sidecar"
```

---

## Self-Review Checklist

- [ ] Spec coverage: API sidecar, Pydantic contracts, bearer token auth, application service extraction, run records, event readers, SSE, and sidecar launcher each have implementation tasks.
- [ ] Red-flag scan: run the plan-quality search from the writing-plans skill and confirm it returns no matches outside this checklist.
- [ ] Type consistency: `RunCreateRequest`, `RunRecord`, `ApiSuccess`, `ApiErrorResponse`, `WorkflowEvent`, and `ProjectInfoData` names are consistent across tests and implementation snippets.
- [ ] CLI safety: current CLI JSON payload shapes remain stable in this milestone.
- [ ] Dirty worktree safety: implementation commits must stage only files touched by the active task and must not stage unrelated user changes.
