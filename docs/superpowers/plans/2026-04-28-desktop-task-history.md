# Desktop Task History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist desktop quickstart history in the user SQLite DB and restore old tasks from the Tasks screen.

**Architecture:** Add a `quickstart_tasks` user DB table and repository methods, use it as the run-to-generated-project index for API routes, then expose task listing through Electron IPC and the renderer. Generated project run DBs remain the source of truth for execution state and artifacts.

**Tech Stack:** Python, FastAPI, SQLAlchemy/Alembic, pytest, TypeScript, Electron IPC, React, Vitest.

---

### Task 1: User DB quickstart task storage

**Files:**
- Modify: `src/openbbq/storage/models.py`
- Modify: `src/openbbq/storage/orm.py`
- Modify: `src/openbbq/runtime/user_db.py`
- Modify: `src/openbbq/storage/migration_runner.py`
- Create: `src/openbbq/storage/migrations/versions/0002_user_quickstart_tasks.py`
- Test: `tests/test_runtime_user_db.py`

- [ ] Write failing tests for inserting, reading, listing, and cache-key lookup.
- [ ] Write failing migration test proving an existing providers/credentials user DB receives `quickstart_tasks`.
- [ ] Implement `QuickstartTaskRecord`, ORM row, migration, and `UserRuntimeDatabase` methods.
- [ ] Run targeted storage tests.

### Task 2: API history and run resolution

**Files:**
- Create: `src/openbbq/api/task_history.py`
- Create: `src/openbbq/api/user_database.py`
- Modify: `src/openbbq/api/app.py`
- Modify: `src/openbbq/api/project_refs.py`
- Modify: `src/openbbq/api/routes/quickstart.py`
- Modify: `src/openbbq/api/routes/runs.py`
- Modify: `src/openbbq/api/schemas.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] Write failing API tests for persisted quickstart history, restarted app run lookup, and duplicate request reuse.
- [ ] Implement request-to-task record builders and cache-key lookup.
- [ ] Include user DB task references in run project resolution.
- [ ] Sync task status when listing tasks and when run routes read/update runs.
- [ ] Run targeted API tests.

### Task 3: Electron IPC task listing

**Files:**
- Modify: `desktop/electron/apiTypes.ts`
- Modify: `desktop/electron/ipc.ts`
- Modify: `desktop/electron/preload.cts`
- Modify: `desktop/src/global.d.ts`
- Modify: `desktop/src/lib/desktopClient.ts`
- Modify: `desktop/src/lib/apiClient.ts`
- Test: `desktop/electron/__tests__/ipc.test.ts`

- [ ] Write failing IPC test for `listTasks`.
- [ ] Add preload and client API method.
- [ ] Map API quickstart task records to renderer task summaries.
- [ ] Run targeted Electron tests.

### Task 4: Renderer Tasks screen

**Files:**
- Modify: `desktop/src/lib/types.ts`
- Modify: `desktop/src/lib/mockData.ts`
- Create: `desktop/src/components/TaskHistory.tsx`
- Modify: `desktop/src/App.tsx`
- Test: `desktop/src/__tests__/App.test.tsx`
- Test: `desktop/src/components/__tests__/TaskHistory.test.tsx`

- [ ] Write failing renderer tests for loading task history and opening a task monitor.
- [ ] Implement task history UI and navigation state.
- [ ] Run targeted renderer tests.

### Task 5: Verification

- [ ] Run `uv run pytest tests/test_runtime_user_db.py tests/test_api_projects_plugins_runtime.py tests/test_storage_migration_runner.py`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run ruff format --check .`.
- [ ] Run `pnpm test` in `desktop`.
- [ ] Run `pnpm build` in `desktop`.
