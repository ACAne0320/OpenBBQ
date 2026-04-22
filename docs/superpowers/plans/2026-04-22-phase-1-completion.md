# Phase 1 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining documented Phase 1 backend and CLI behavior for local workflow execution, recovery, reruns, inspection, and launch verification.

**Architecture:** Keep `openbbq.engine` as the public facade while extending focused modules under `openbbq.core.workflow`. Add small helpers for abort request files, rerun preparation, artifact diffs, and lock recovery so the execution loop stays understandable.

**Tech Stack:** Python 3.11, uv, pytest, Ruff, local filesystem storage, argparse CLI.

---

## Task 1: Lock Recovery And Unlock

**Files:**
- Modify: `src/openbbq/core/workflow/locks.py`
- Modify: `src/openbbq/engine.py`
- Modify: `src/openbbq/cli.py`
- Test: `tests/test_workflow_locks.py`
- Test: `tests/test_cli_control_flow.py`

- [ ] **Step 1: Write failing stale-lock and unlock tests**

Add tests that create lock files with dead PIDs, verify `run` reports stale locks, and verify `openbbq unlock --yes <workflow>` removes only the lock.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `uv run pytest tests/test_workflow_locks.py tests/test_cli_control_flow.py -v`

Expected: failures because lock inspection and CLI unlock are not implemented.

- [ ] **Step 3: Implement lock metadata reading, PID liveness, stale lock errors, and unlock facade**

Add lock helpers that parse lock JSON, detect whether the recorded PID is alive, and remove stale locks.

- [ ] **Step 4: Wire `openbbq unlock`**

Dispatch `unlock` to the new engine facade. Support `--yes`; keep interactive confirmation for non-JSON human use.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_workflow_locks.py tests/test_cli_control_flow.py -v`

Commit: `feat: Add workflow unlock recovery`

## Task 2: Running Abort Request Files

**Files:**
- Create: `src/openbbq/core/workflow/aborts.py`
- Modify: `src/openbbq/core/workflow/execution.py`
- Modify: `src/openbbq/engine.py`
- Modify: `src/openbbq/cli.py`
- Test: `tests/test_engine_abort.py`
- Test: `tests/test_cli_control_flow.py`

- [ ] **Step 1: Write failing running-abort tests**

Cover atomic abort request file creation for `running` state and engine-side processing between steps.

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `uv run pytest tests/test_engine_abort.py tests/test_cli_control_flow.py -v`

Expected: failures because running abort is still rejected.

- [ ] **Step 3: Implement abort request helpers**

Add atomic request writes, request detection, and request cleanup.

- [ ] **Step 4: Check abort requests in the execution loop**

After a step completes and before the next step starts, process the request by emitting events, persisting `aborted`, and returning an aborted result.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_engine_abort.py tests/test_cli_control_flow.py -v`

Commit: `feat: Add running workflow abort requests`

## Task 3: Forced Rerun

**Files:**
- Create: `src/openbbq/core/workflow/rerun.py`
- Modify: `src/openbbq/core/workflow/bindings.py`
- Modify: `src/openbbq/core/workflow/execution.py`
- Modify: `src/openbbq/engine.py`
- Modify: `src/openbbq/cli.py`
- Test: `tests/test_engine_rerun.py`
- Test: `tests/test_cli_control_flow.py`

- [ ] **Step 1: Write failing `run --force` tests**

Cover completed rerun, crash-recovered running rerun after unlock, dangling StepRun failure marking, and artifact ID reuse with new version IDs.

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `uv run pytest tests/test_engine_rerun.py tests/test_cli_control_flow.py -v`

Expected: failures because `run --force` is still guarded.

- [ ] **Step 3: Implement force preparation**

Mark dangling running StepRuns failed, reset workflow state, and build a reuse map from previous output bindings.

- [ ] **Step 4: Allow output persistence to reuse artifact IDs**

Pass the reuse map into output persistence so new versions append to existing artifacts.

- [ ] **Step 5: Wire CLI `run --force`**

Reject `--force` combined with `--step`.

- [ ] **Step 6: Verify and commit**

Run: `uv run pytest tests/test_engine_rerun.py tests/test_cli_control_flow.py -v`

Commit: `feat: Add forced workflow rerun`

## Task 4: Single-Step Rerun

**Files:**
- Modify: `src/openbbq/core/workflow/rerun.py`
- Modify: `src/openbbq/core/workflow/execution.py`
- Modify: `src/openbbq/engine.py`
- Modify: `src/openbbq/cli.py`
- Test: `tests/test_engine_rerun.py`
- Test: `tests/test_cli_control_flow.py`

- [ ] **Step 1: Write failing `run --step` tests**

Cover allowed terminal statuses, rejected running/paused/pending/aborted statuses, target output versioning, artifact ID reuse, and no downstream invalidation.

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `uv run pytest tests/test_engine_rerun.py tests/test_cli_control_flow.py -v`

Expected: failures because `run --step` is still guarded.

- [ ] **Step 3: Implement single-step execution path**

Rebuild bindings from completed StepRuns, execute only the requested step, and persist terminal workflow state.

- [ ] **Step 4: Wire CLI `run --step`**

Validate option combinations and return normal run payloads.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_engine_rerun.py tests/test_cli_control_flow.py -v`

Commit: `feat: Add single-step workflow rerun`

## Task 5: Retry, Skip, And Plugin Pause Requests

**Files:**
- Modify: `src/openbbq/core/workflow/execution.py`
- Modify: `src/openbbq/engine.py`
- Modify: `tests/fixtures/plugins/mock-text/plugin.py`
- Modify: `tests/fixtures/plugins/mock-text/openbbq.plugin.toml`
- Test: `tests/test_engine_error_policy.py`
- Test: `tests/test_engine_pause_resume.py`

- [ ] **Step 1: Write failing retry/skip/pause-request tests**

Cover retry success, retry exhaustion, skip continuation, skipped output selector failure, and plugin `pause_requested`.

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `uv run pytest tests/test_engine_error_policy.py tests/test_engine_pause_resume.py -v`

Expected: failures because retry/skip are rejected and plugin pause requests are ignored.

- [ ] **Step 3: Add deterministic fixture plugin failure controls**

Extend the mock text plugin with tools or parameters that can fail for tests without external services.

- [ ] **Step 4: Implement attempt loop and error policy handling**

Create one StepRun per attempt, persist normalized errors, emit retry/skipped/failed events, and continue when policy allows.

- [ ] **Step 5: Implement plugin `pause_requested`**

Treat a successful plugin response with `pause_requested: true` as implicit `pause_after`.

- [ ] **Step 6: Verify and commit**

Run: `uv run pytest tests/test_engine_error_policy.py tests/test_engine_pause_resume.py -v`

Commit: `feat: Add workflow retry and skip policies`

## Task 6: Artifact Diff And Filters

**Files:**
- Create: `src/openbbq/core/workflow/diff.py`
- Modify: `src/openbbq/engine.py`
- Modify: `src/openbbq/cli.py`
- Modify: `src/openbbq/storage.py`
- Test: `tests/test_artifact_diff.py`
- Test: `tests/test_cli_integration.py`

- [ ] **Step 1: Write failing artifact diff and filter tests**

Cover text diff human output, JSON output, missing versions, binary rejection, workflow filter, and composed filters.

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `uv run pytest tests/test_artifact_diff.py tests/test_cli_integration.py -v`

Expected: failures because `artifact diff` is guarded and workflow filtering is incomplete.

- [ ] **Step 3: Implement diff helper**

Use `difflib.unified_diff` with stable version headers.

- [ ] **Step 4: Wire artifact diff and workflow filters**

Filter artifacts by current version lineage workflow ID.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_artifact_diff.py tests/test_cli_integration.py -v`

Commit: `feat: Add artifact diff inspection`

## Task 7: Configuration Precedence

**Files:**
- Modify: `src/openbbq/config.py`
- Modify: `src/openbbq/cli.py`
- Test: `tests/test_config_precedence.py`

- [ ] **Step 1: Write failing precedence tests**

Cover `OPENBBQ_PROJECT`, `OPENBBQ_CONFIG`, `OPENBBQ_PLUGIN_PATH`, CLI `--plugins`, and `OPENBBQ_LOG_LEVEL` interactions.

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `uv run pytest tests/test_config_precedence.py -v`

Expected: failures for missing project/config environment defaults and log-level behavior.

- [ ] **Step 3: Implement environment defaults**

Let CLI default project/config values come from environment variables while preserving CLI flag precedence.

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest tests/test_config_precedence.py -v`

Commit: `feat: Complete configuration precedence`

## Task 8: Docs, CI, And Final Acceptance

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `tests/test_cli_integration.py`
- Test: full suite

- [ ] **Step 1: Add final CLI acceptance tests**

Cover Scenario A, Scenario B across separate CLI calls, and Scenario C paused abort.

- [ ] **Step 2: Update README and AGENTS**

Document implemented Phase 1 commands and remove obsolete Slice 2 guardrail language.

- [ ] **Step 3: Add CI workflow**

Run `uv sync`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`.

- [ ] **Step 4: Run final verification**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 5: Commit**

Commit: `docs: Finalize phase 1 launch docs`
