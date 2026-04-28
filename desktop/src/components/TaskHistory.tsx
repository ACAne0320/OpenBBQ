import { RefreshCw } from "lucide-react";

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
    return "bg-ready text-[#fff8ea]";
  }

  if (status === "failed" || status === "aborted") {
    return "bg-accent text-[#fff8ea]";
  }

  if (status === "running" || status === "queued" || status === "paused") {
    return "bg-paper text-accent shadow-[inset_0_0_0_2px_rgba(182,99,47,0.45)]";
  }

  return "bg-[#d8c8ae] text-[#7a6b56]";
}

export function TaskHistory({ error, loading, onOpenTask, onRefresh, tasks }: TaskHistoryProps) {
  return (
    <section className="grid min-h-[calc(100vh-84px)] grid-rows-[auto_minmax(0,1fr)] gap-4">
      <header className="flex items-end justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase text-muted">History</p>
          <h1 className="mt-2 font-serif text-[40px] leading-none text-ink-brown">Tasks</h1>
        </div>
        <Button onClick={onRefresh}>
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
          Refresh
        </Button>
      </header>

      <section className="min-h-0 rounded-lg bg-paper-muted p-4 shadow-control" aria-label="Task history">
        {error ? (
          <div className="mb-3 rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-[#6b3f27]" role="alert">
            {error}
          </div>
        ) : null}

        {loading ? <p className="text-sm font-semibold text-muted">Loading tasks...</p> : null}

        {!loading && tasks.length === 0 ? (
          <div className="grid min-h-[360px] place-items-center rounded-lg bg-paper px-4 text-center shadow-inner">
            <div>
              <h2 className="text-lg font-extrabold text-ink-brown">No tasks yet</h2>
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
                className="grid min-h-[76px] grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-lg bg-paper px-4 py-3 text-left shadow-control transition-transform duration-150 active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [@media(hover:hover)]:hover:bg-[#fffaf0]"
              >
                <span className="min-w-0">
                  <span className="block truncate text-base font-extrabold text-ink-brown">{task.title}</span>
                  <span className="mt-1 block truncate text-sm text-muted">{task.workflowName}</span>
                  <span className="mt-1 block truncate text-xs text-muted">{task.sourceSummary}</span>
                </span>
                <span className="grid justify-items-end gap-2">
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${statusClass(task.status)}`}>
                    {task.status}
                  </span>
                  <span className="text-xs text-muted">{task.updatedAt}</span>
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}
