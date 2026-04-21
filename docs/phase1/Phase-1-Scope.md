# Phase 1 Scope

## Goal

Launch the smallest useful headless OpenBBQ backend: a local project can define a workflow, discover local plugins, execute steps in order, persist versioned artifacts, and inspect results through a CLI.

Phase 1 is not the full platform. It is the backend foundation needed to validate the core workflow model before adding agent APIs or a desktop UI.

## MVP Acceptance Scenarios

Phase 1 has three acceptance scenarios that together cover the core workflow contracts. Each uses a separate project fixture; they are not sequential steps in a single run.

### Scenario A — Run to Completion

The baseline scenario proves execution, artifact persistence, and inspection.

1. Create a project with `openbbq init`.
2. Configure one workflow in the project config (YAML).
3. Validate the workflow config with `openbbq validate <workflow>`. Confirm exit code `0`.
4. Discover at least one local mock plugin with `openbbq plugin list`.
5. Run the workflow with `openbbq run <workflow>`. Confirm it completes and exits `0`.
6. Inspect workflow state with `openbbq status <workflow>`. Confirm `completed`.
7. Inspect artifact metadata and content with `openbbq artifact show <id>`.
8. Confirm `openbbq run <workflow>` on an already-`completed` workflow is rejected with a clear error.

### Scenario B — Pause and Resume

Proves persisted pause state survives a process restart.

1. Configure a workflow with `pause_before: true` on a middle step.
2. Run the workflow. Confirm it stops before the marked step and status is `paused`.
3. Exit the process entirely.
4. In a new process, run `openbbq status <workflow>`. Confirm `paused` and the correct next step.
5. Run `openbbq resume <workflow>`. Confirm the workflow completes from the paused step.
6. Confirm artifacts produced before and after the pause are all present.

### Scenario C — Abort

Proves abort from a paused state persists correctly. The MVP acceptance scenario exercises paused abort; running workflow abort is covered by the cooperative request-file contract in the workflow engine spec.

1. Configure a workflow with `pause_before: true` on a step. Run it until it pauses.
2. Run `openbbq abort <workflow>`. Confirm exit code `0`.
3. Confirm status is `aborted` and artifacts produced before the abort are still present.
4. Confirm `openbbq resume <workflow>` on an `aborted` workflow is rejected.

---

The mock plugin may transform text instead of processing real media. The goal is to prove the contracts, not media quality.

The production target is the [YouTube → Subtitle pipeline](../Target-Workflows.md). Phase 1 must be able to load its full workflow config, validate all step references and artifact types, and execute it end-to-end using mock plugins that emit correct artifact types without performing real media operations.

## In Scope

- Python backend package managed with `uv`.
- Code quality enforced with `Ruff` (lint and format).
- Project config format: **YAML**. The project config schema and canonical fixture configs are defined in [Project Config](./Project-Config.md).
- Abort command: synchronous transition for `paused` workflows; writes atomic abort request file and returns immediately for `running` workflows (see [Workflow Engine](./Workflow-Engine.md)).
- `openbbq unlock <workflow>` command to clear stale lock files left by crashed processes.
- Rerun support:
  - `run --force`: allowed for `completed` workflows and for crash-recovered `running` workflows (no lock file). Marks dangling `running` StepRuns as `failed`, resets workflow to `pending`, and reruns from the beginning. Creates new `ArtifactVersion` records; reuses existing `Artifact` IDs where prior output bindings exist so version history is preserved.
  - `run --step <step-id>`: allowed for `completed` and `failed` workflows; rejected for `running` and `paused`. Reruns a single step; produces a new `StepRun` and new artifact versions for that step's outputs only. Downstream artifacts are **not** invalidated — that is out of scope for Phase 1. Cannot combine with `--force`.
- Local filesystem project layout.
- Local plugin discovery from configured search paths.
- Plugin manifest validation.
- Synchronous plugin execution.
- Project, workflow, step run, tool, plugin, artifact, artifact version, and event models.
- Ordered workflow execution.
- Pause/resume state persistence triggered by step configuration (`pause_before` / `pause_after`).
- Basic retry, skip, and abort behavior. The three MVP acceptance scenarios cover run, pause/resume, and paused abort; retry/skip are Slice 2 Phase 1 requirements and must be covered before Phase 1 launch.
- Local artifact persistence with metadata and lineage.
- CLI commands required by [CLI Spec](./CLI-Spec.md).
- Unit and integration tests covering all three MVP acceptance scenarios, retry/skip policies, configuration precedence, lock crash recovery, and artifact diff behavior.

## Out Of Scope

- Desktop UI.
- HTTP or gRPC API.
- Authentication and authorization.
- Multi-user collaboration.
- Remote plugin registries.
- Plugin marketplace.
- Distributed execution.
- Long-running worker queues.
- Real transcription, translation, or subtitle rendering integrations.
- Cloud storage backends.
- Downstream artifact invalidation on single-step rerun (`run --step`). Users are responsible for understanding which downstream artifacts are stale after a partial rerun.
- Named input declarations in tool manifests (e.g., "requires one video input"). Phase 1 validates only that input artifact types are in the tool's allowlist.

## Definition Of Done

Phase 1 is ready to launch when:

- A new project can be initialized from the CLI.
- A workflow can be configured (YAML), validated, run, paused, resumed, and inspected locally.
- Plugins are discovered from configured paths and rejected when manifests are invalid.
- Plugin execution uses the documented contract in [Plugin System](./Plugin-System.md).
- Artifacts are written to local storage with stable IDs, metadata, versions, and lineage.
- The CLI returns documented exit codes and useful human-readable errors.
- A machine-readable JSON output mode exists for status, validation, plugin, and artifact inspection commands.
- Tests cover domain validation, plugin loading, workflow execution, artifact versioning, and CLI behavior.
- All three MVP acceptance scenarios are implemented as test fixtures and pass in CI.
- Slice 2 retry/skip, artifact diff, configuration precedence, paused config drift, and lock crash-recovery test cases pass in CI.

## Recommended Implementation Order

Build in two vertical slices to avoid integrating all concerns at once.

**Slice 1 — Core Execution Loop:**
`init` → config load (YAML) → manifest discovery → `validate` → `run` to completion → artifact persistence → event log → `status` → `artifact show` → `logs` → JSON output mode.
Do not proceed to Slice 2 until Slice 1 passes in CI.

**Slice 2 — Control Flow and Inspection:**
Pause/resume (`pause_before` / `pause_after` step config, process-restart survival), abort (from paused state; cooperative cancellation between steps for running state), retry/skip policies, `--step` single-step execution, `artifact diff`.

## Recommended Repository Layout

```text
openbbq/
  pyproject.toml
  .github/
    workflows/
  src/openbbq/
    cli/
    config/
    domain/
    engine/
    plugins/
    storage/
  tests/
    fixtures/
      projects/
      plugins/
```

## Launch Risks

- Overbuilding real media integrations before the workflow contracts are stable.
- Letting plugin execution define implicit artifact formats instead of validating types.
- Treating pause/resume as an in-memory concern instead of persisted workflow state.
- Omitting JSON output from CLI commands, which would make Phase 2 agent integration harder.
