# Desktop Backend Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing FastAPI sidecar so the first desktop UI can call backend services directly instead of parsing CLI output.

**Architecture:** Keep `openbbq.application` as the shared service layer and make `openbbq.api` a typed adapter. Add focused application helpers for quickstart subtitle jobs and artifact preview/export, while preserving the workflow engine and storage model as the source of truth.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLAlchemy-backed project storage, pytest, Ruff.

---

## Tasks

1. Typed API contracts for workflows and artifacts.
2. API error boundary and run lifecycle hardening.
3. Artifact preview and export services.
4. Generated subtitle quickstart API.
5. Sidecar token enforcement.
6. Final verification with pytest and Ruff.

Each task is executed with test-first changes, focused verification, and then the
full verification suite.

## Task 1: Typed API Contracts For Workflows And Artifacts

**Files:**
- Modify: `src/openbbq/api/schemas.py`
- Modify: `src/openbbq/api/routes/workflows.py`
- Modify: `src/openbbq/api/routes/artifacts.py`
- Test: `tests/test_api_schemas.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`

- [ ] Add failing schema tests for workflow and artifact API data models.
- [ ] Run `uv run pytest tests/test_api_schemas.py -q` and verify RED.
- [ ] Add missing schema models.
- [ ] Update workflow and artifact routes to use typed response models.
- [ ] Run `uv run pytest tests/test_api_schemas.py tests/test_api_workflows_artifacts_runs.py -q` and verify GREEN.

## Task 2: API Error Boundary And Run Lifecycle Hardening

**Files:**
- Modify: `src/openbbq/api/errors.py`
- Modify: `src/openbbq/api/routes/runs.py`
- Modify: `src/openbbq/application/runs.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`
- Test: `tests/test_application_runs.py`

- [ ] Add failing API 404 test for `GET /runs/missing`.
- [ ] Add failing unexpected background exception test.
- [ ] Add failing non-blocking resume test.
- [ ] Run `uv run pytest tests/test_application_runs.py tests/test_api_workflows_artifacts_runs.py -q` and verify RED.
- [ ] Implement FileNotFoundError mapping, unexpected exception recording, and non-blocking resume.
- [ ] Run the focused tests and verify GREEN.

## Task 3: Artifact Preview And Export Services

**Files:**
- Modify: `src/openbbq/api/schemas.py`
- Modify: `src/openbbq/application/artifacts.py`
- Modify: `src/openbbq/api/routes/artifacts.py`
- Test: `tests/test_application_artifacts.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`

- [ ] Add failing application tests for preview truncation and export.
- [ ] Add failing API tests for preview and export routes.
- [ ] Run focused tests and verify RED.
- [ ] Implement preview and export services and routes.
- [ ] Run focused tests and verify GREEN.

## Task 4: Generated Subtitle Quickstart API

**Files:**
- Modify: `src/openbbq/api/schemas.py`
- Modify: `src/openbbq/application/quickstart.py`
- Create: `src/openbbq/api/routes/quickstart.py`
- Modify: `src/openbbq/api/app.py`
- Test: `tests/test_application_quickstart.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] Add failing application tests with monkeypatched run creation.
- [ ] Add failing API route tests with monkeypatched service functions.
- [ ] Run focused tests and verify RED.
- [ ] Implement quickstart services and routes.
- [ ] Run focused tests and verify GREEN.

## Task 5: Sidecar Token Enforcement

**Files:**
- Modify: `src/openbbq/api/server.py`
- Test: `tests/test_api_server.py`

- [ ] Add failing parser tests for required token and `--no-token-dev`.
- [ ] Run focused tests and verify RED.
- [ ] Implement token enforcement.
- [ ] Run focused tests and verify GREEN.

## Task 6: Final Verification

- [ ] Run `uv run ruff format .`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run pytest`.
- [ ] Run `uv run ruff format --check .`.

## Plan self-review

- Spec coverage: every acceptance criterion in the design has a task.
- Placeholder scan: no task contains unresolved requirements.
- Type consistency: route, schema, and service names are consistent across tasks.
