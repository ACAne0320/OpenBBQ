import { Clock3, FileVideo, Link2, RefreshCw } from "lucide-react";

import type { TaskSummary } from "../lib/types";
import { Button } from "./Button";

type TaskHistoryProps = {
  tasks: TaskSummary[];
  loading: boolean;
  error: string | null;
  onRefresh: () => Promise<void> | void;
  onOpenTask: (runId: string) => Promise<void> | void;
};

function statusClass(status: TaskSummary["status"]): string {
  if (status === "completed") {
    return "bg-accent text-paper";
  }

  if (status === "failed" || status === "aborted") {
    return "bg-accent text-paper";
  }

  if (status === "running" || status === "queued" || status === "paused") {
    return "bg-state-running text-accent shadow-running";
  }

  return "bg-paper-side text-muted";
}

function sourceLabel(task: TaskSummary): string {
  return task.sourceKind === "local_file" ? "File path" : "Video URL";
}

function formatTaskTimestamp(timestamp: string): string {
  const match = timestamp.trim().match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}` : timestamp;
}

export function TaskHistory({ error, loading, onOpenTask, onRefresh, tasks }: TaskHistoryProps) {
  return (
    <section className="grid min-h-[calc(100vh-84px)] grid-rows-[auto_minmax(0,1fr)] gap-4">
      <header className="flex items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase text-muted">History</p>
          <h1 className="mt-2 text-[32px] font-semibold leading-tight tracking-[-0.022em] text-ink-brown">Tasks</h1>
        </div>
        <Button onClick={onRefresh}>
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
          Refresh
        </Button>
      </header>

      <section className="min-h-0 rounded-lg bg-paper-muted p-4 shadow-control" aria-label="Task history">
        {error ? (
          <div className="mb-3 rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-ink" role="alert">
            {error}
          </div>
        ) : null}

        {loading ? <p className="text-sm font-semibold text-muted">Loading tasks...</p> : null}

        {!loading && tasks.length === 0 ? (
          <div className="grid min-h-[360px] place-items-center rounded-lg bg-paper px-4 text-center shadow-inner">
            <div>
              <h2 className="text-lg font-semibold text-ink-brown">No tasks yet</h2>
              <p className="mt-1 text-sm text-muted">Created subtitle tasks will appear here.</p>
            </div>
          </div>
        ) : null}

        {!loading && tasks.length > 0 ? (
          <div className="grid gap-2">
            {tasks.map((task) => (
              <button
                key={task.id}
                type="button"
                aria-label={`Open ${task.title}`}
                onClick={() => onOpenTask(task.id)}
                className="grid min-h-[108px] grid-cols-1 gap-4 rounded-lg bg-paper px-4 py-3 text-left shadow-control transition-transform duration-150 active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center [@media(hover:hover)]:hover:bg-paper-muted"
              >
                <span className="grid min-w-0 gap-2">
                  <span className="block truncate text-base font-semibold text-ink-brown">{task.title}</span>
                  <span className="block truncate text-sm font-medium text-muted">{task.workflowName}</span>
                  <span className="grid min-w-0 gap-1.5 text-xs text-muted">
                    <span className="flex min-w-0 items-center gap-2">
                      {task.sourceKind === "local_file" ? (
                        <FileVideo className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
                      ) : (
                        <Link2 className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
                      )}
                      <span className="shrink-0 font-semibold text-ink-brown">{sourceLabel(task)}</span>
                      <span className="truncate" title={task.sourceUri}>
                        {task.sourceUri}
                      </span>
                    </span>
                    <span className="flex min-w-0 items-center gap-2">
                      <Clock3 className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
                      <span className="shrink-0 font-semibold text-ink-brown">Created</span>
                      <time className="truncate tabular-nums" dateTime={task.createdAt}>
                        {formatTaskTimestamp(task.createdAt)}
                      </time>
                    </span>
                  </span>
                </span>
                <span className="flex items-center justify-start sm:justify-end">
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${statusClass(task.status)}`}>
                    {task.status}
                  </span>
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}
