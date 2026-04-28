# Desktop task history design

## Context

The desktop quickstart flow currently creates generated projects under the active
workspace and keeps run-to-project references only in sidecar memory. After the
Electron sidecar restarts, old generated runs remain on disk, but the API no
longer knows which project owns each run. The renderer also has no persistent
task list, so real testing forces users to re-enter the source URL and create a
new generated project.

## Goals

- Persist desktop quickstart task history in the user SQLite database, not in a
  scanned directory index.
- Restore old quickstart runs across sidecar restarts.
- Let the desktop Tasks screen list recent tasks and open a task monitor without
  re-entering the source.
- Reuse an existing quickstart task for the same source and settings so duplicate
  tests do not create a fresh run by default.
- Preserve the existing project-local run, event, and artifact stores.

## Non-goals

- Store video, audio, transcript, or subtitle artifact content in the user DB.
- Change the workflow executor to skip individual completed steps in a new run.
- Add a force-new-copy UI. A later design can add that once task duplication is
  explicit.

## Architecture

Add a user-level `quickstart_tasks` table to `~/.openbbq/openbbq.db`. Each row is
an index record for one generated quickstart task. It stores the run ID, generated
project paths, source summary, workflow settings, latest known status, and a
deterministic cache key.

The generated project remains the source of truth for execution state. API run
routes use the user DB index to resolve `run_id -> generated_project_root` before
falling back to in-memory references or the active project.

## Backend behavior

- `POST /quickstart/subtitle/local` and `POST /quickstart/subtitle/youtube`
  compute a cache key from source and workflow settings.
- If a non-aborted task with the same cache key still resolves to a readable run,
  the route returns that existing task instead of creating another generated
  project.
- Otherwise the route creates the generated project and run, then upserts a
  `quickstart_tasks` row.
- `GET /quickstart/tasks` returns recent quickstart task records from the user DB
  after syncing each readable row from its project-local run record.
- `/runs/{run_id}`, `/runs/{run_id}/events`, `/runs/{run_id}/artifacts`,
  `/runs/{run_id}/resume`, and `/runs/{run_id}/abort` can resolve generated
  quickstart runs from the user DB after a sidecar restart.

## Desktop behavior

- The preload API exposes `listTasks()`.
- Electron maps `GET /quickstart/tasks` to renderer task summaries.
- The renderer Tasks navigation loads the persistent task list. Selecting a task
  opens the live task monitor for that run.
- Starting the same quickstart source/settings can return an existing run ID.

## Testing

- Storage tests cover user DB migration and quickstart task CRUD.
- API tests cover creating quickstart task history, resolving a run after a new
  app instance starts, and cache-key reuse.
- Electron tests cover `listTasks` IPC and mapping.
- React tests cover loading persistent tasks and opening a selected monitor.
