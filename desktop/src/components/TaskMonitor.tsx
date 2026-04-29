import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowDown, Check, Copy, Minus, X } from "lucide-react";

import type { ProgressStep, TaskMonitorModel, TaskProgressLogLine } from "../lib/types";
import { Button } from "./Button";

type TaskMonitorProps = {
  task: TaskMonitorModel;
  onRetry: () => Promise<void> | void;
  onCancel?: () => void;
  retryError?: string | null;
  retryPending?: boolean;
};

const fallbackFailureMessage = "Task failed before OpenBBQ received detailed error information.";
const cancelableStatuses = new Set<TaskMonitorModel["status"]>(["queued", "running", "paused"]);
const logPinThresholdPx = 32;
const jumpToLatestThresholdPx = 120;

type RuntimeTextLogLine = TaskMonitorModel["logs"][number];
type RuntimeLogRow =
  | { kind: "progress"; sequence: number; line: TaskProgressLogLine }
  | { kind: "text"; sequence: number; line: RuntimeTextLogLine };

function stepSummary(task: TaskMonitorModel, progress: ProgressStep[]): string {
  if (task.status === "failed") {
    const failedStep = progress.find((step) => step.status === "failed");
    return failedStep ? `${failedStep.label} failed` : "Task failed";
  }

  if (task.status === "running") {
    const runningStep = progress.find((step) => step.status === "running");
    return runningStep ? `${runningStep.label} running` : "Task running";
  }

  if (task.status === "completed") {
    const completedStep = [...progress].reverse().find((step) => step.status === "done");
    const rawHasUnfinishedStep = task.progress.some((step) => step.status === "failed" || step.status === "blocked");
    return completedStep && !rawHasUnfinishedStep ? `${completedStep.label} completed` : "Task completed";
  }

  if (task.status === "paused") {
    return "Task paused";
  }

  if (task.status === "aborted") {
    return "Task aborted";
  }

  return task.status === "queued" ? "Waiting to start" : "No active step";
}

function normalizedProgress(task: TaskMonitorModel): ProgressStep[] {
  if (task.status === "failed") {
    return task.progress;
  }

  return task.progress.map((step) => {
    if (step.status !== "failed") {
      if (task.status === "completed" && step.status === "blocked") {
        return { ...step, status: "done" };
      }

      return step;
    }

    if (task.status === "running") {
      return { ...step, status: "running" };
    }

    if (task.status === "completed") {
      return { ...step, status: "done" };
    }

    return { ...step, status: "blocked" };
  });
}

function progressCounts(progress: ProgressStep[]) {
  const done = progress.filter((step) => step.status === "done").length;
  const failed = progress.filter((step) => step.status === "failed").length;
  const running = progress.filter((step) => step.status === "running").length;

  return { done, failed, running };
}

function progressPercent(progress: ProgressStep[]): number {
  if (progress.length === 0) {
    return 0;
  }

  return Math.round((progress.filter((step) => step.status === "done").length / progress.length) * 100);
}

function statusTone(status: ProgressStep["status"]): string {
  if (status === "done") {
    return "bg-accent text-paper";
  }

  if (status === "failed") {
    return "bg-accent text-paper";
  }

  if (status === "running") {
    return "bg-state-running text-accent shadow-running";
  }

  return "bg-paper-side text-muted";
}

function statusIcon(status: ProgressStep["status"]) {
  if (status === "done") {
    return <Check className="h-3.5 w-3.5" aria-hidden="true" />;
  }

  if (status === "failed") {
    return <X className="h-3.5 w-3.5" aria-hidden="true" />;
  }

  if (status === "running") {
    return <span className="h-2 w-2 rounded-full bg-accent" aria-hidden="true" />;
  }

  return <Minus className="h-3.5 w-3.5" aria-hidden="true" />;
}

function logLevelClass(level: TaskMonitorModel["logs"][number]["level"]): string {
  if (level === "error") {
    return "bg-log-panel text-log-error";
  }

  if (level === "warning") {
    return "bg-log-panel text-log-warning";
  }

  return "bg-log-panel text-log-muted";
}

function progressDetail(line: TaskProgressLogLine): string | null {
  if (line.current == null || line.total == null || !line.unit) {
    return null;
  }

  return `${Math.round(line.current)} / ${Math.round(line.total)} ${line.unit}`;
}

function roundedPercent(percent: number): number {
  return Number.isFinite(percent) ? Math.round(percent) : 0;
}

function clampedPercent(percent: number): number {
  if (!Number.isFinite(percent)) {
    return 0;
  }

  return Math.min(100, Math.max(0, percent));
}

function runtimeLogRows(task: TaskMonitorModel): RuntimeLogRow[] {
  const progressSequences = new Set(task.progressLogs.map((line) => line.sequence));
  return [
    ...task.progressLogs.map((line) => ({ kind: "progress" as const, sequence: line.sequence, line })),
    ...task.logs
      .filter((line) => !progressSequences.has(line.sequence))
      .map((line) => ({ kind: "text" as const, sequence: line.sequence, line }))
  ].sort((left, right) => left.sequence - right.sequence);
}

function runtimeLogRowText(row: RuntimeLogRow): string {
  if (row.kind === "text") {
    return `${row.line.timestamp} ${row.line.level} ${row.line.message}`;
  }

  const percent = roundedPercent(clampedPercent(row.line.percent));
  const detail = progressDetail(row.line);
  return `${row.line.timestamp} progress ${row.line.label} ${percent}%${detail ? ` ${detail}` : ""}`;
}

export function TaskMonitor({ onCancel, onRetry, retryError, retryPending = false, task }: TaskMonitorProps) {
  const failed = task.status === "failed";
  const progress = normalizedProgress(task);
  const counts = progressCounts(progress);
  const percentDone = progressPercent(progress);
  const runtimeRows = useMemo(() => runtimeLogRows(task), [task]);
  const runtimeLogRef = useRef<HTMLDivElement>(null);
  const logPinnedRef = useRef(true);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const logText = runtimeRows.map(runtimeLogRowText).join("\n");
  const showCancel = Boolean(onCancel) && cancelableStatuses.has(task.status);

  function distanceFromLogBottom(viewport: HTMLDivElement): number {
    return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
  }

  function updateLogPinState(viewport: HTMLDivElement) {
    const distanceFromBottom = distanceFromLogBottom(viewport);
    logPinnedRef.current = distanceFromBottom <= logPinThresholdPx;
    setShowJumpToLatest(distanceFromBottom > jumpToLatestThresholdPx);
  }

  useEffect(() => {
    const viewport = runtimeLogRef.current;
    if (!viewport) {
      return;
    }

    if (logPinnedRef.current) {
      viewport.scrollTop = viewport.scrollHeight;
    }

    updateLogPinState(viewport);
  }, [runtimeRows]);

  function handleRuntimeLogScroll() {
    const viewport = runtimeLogRef.current;
    if (!viewport) {
      return;
    }

    updateLogPinState(viewport);
  }

  function jumpToLatestLog() {
    const viewport = runtimeLogRef.current;
    if (!viewport) {
      return;
    }

    logPinnedRef.current = true;
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    setShowJumpToLatest(false);
  }

  function copyLog() {
    if (!navigator.clipboard) {
      return;
    }

    void navigator.clipboard.writeText(logText).catch(() => undefined);
  }

  return (
    <section className="grid min-h-[calc(100vh-76px)] grid-rows-[auto_auto_minmax(0,1fr)] gap-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase text-muted">Task monitor</p>
          <h1 className="mt-2 truncate text-[32px] font-semibold leading-tight tracking-[-0.022em] text-ink-brown">{task.title}</h1>
          <p className="mt-1.5 text-sm text-muted">{task.workflowName}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button>Diagnostics</Button>
          {showCancel ? (
            <Button variant="ink" onClick={onCancel}>
              Request cancel
            </Button>
          ) : null}
        </div>
      </header>

      <section aria-label="Task progress" className="grid gap-4 rounded-xl bg-paper-muted p-4 shadow-control">
        <div className="grid gap-4 xl:grid-cols-[220px_minmax(0,1fr)_140px] xl:items-center">
          <div className="min-w-0">
            <p className="text-[11px] uppercase text-muted">Progress</p>
            <h2 className="mt-1 truncate text-base font-semibold leading-tight text-ink-brown">{stepSummary(task, progress)}</h2>
          </div>

          <ol className="flex min-w-0 items-center gap-2 rounded-lg bg-paper px-3 py-3 shadow-control">
            {progress.map((step, index) => (
              <li key={step.id} className="flex min-w-0 flex-1 items-center gap-2 last:flex-none">
                <span
                  aria-label={`${step.label}: ${step.status}`}
                  data-testid="progress-step"
                  title={`${step.label}: ${step.status}`}
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${statusTone(step.status)}`}
                >
                  {statusIcon(step.status)}
                </span>
                {index < task.progress.length - 1 ? <span className="h-[3px] flex-1 rounded-full bg-paper-side" /> : null}
              </li>
            ))}
          </ol>

          <div className="grid gap-1.5 text-xs text-muted">
            <div className="flex items-center justify-between">
              <span>{counts.done} done</span>
              <span>{percentDone}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-paper-side">
              <div className="h-full rounded-full bg-accent" style={{ width: `${percentDone}%` }} />
            </div>
            <p className="text-right">
              {counts.running > 0 ? `${counts.running} running` : ""}
              {counts.failed > 0 ? `${counts.running > 0 ? " - " : ""}${counts.failed} failed` : ""}
            </p>
          </div>
        </div>
      </section>

      <section aria-label="Runtime log" className="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-xl bg-paper-muted p-4 shadow-control">
        <div className="mb-3 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase text-muted">Runtime log</p>
            <p className="mt-1 text-sm text-muted">Backend events for this task.</p>
          </div>
          <Button onClick={copyLog}>
            <Copy className="mr-2 h-4 w-4" aria-hidden="true" />
            Copy log
          </Button>
        </div>

        {failed ? (
          <div
            role="alert"
            className="mb-3 flex items-center justify-between gap-3 rounded-lg bg-accent-soft px-3.5 py-3 text-ink shadow-control"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div className="grid gap-1">
                <p className="text-sm font-semibold leading-snug">{task.errorMessage ?? fallbackFailureMessage}</p>
                {retryError ? <p className="text-xs font-semibold leading-snug text-accent">{retryError}</p> : null}
                {retryPending ? <p className="text-xs font-semibold leading-snug text-accent">Retrying checkpoint...</p> : null}
              </div>
            </div>
            <Button className="shrink-0" disabled={retryPending} variant="primary" onClick={onRetry}>
              Retry checkpoint
            </Button>
          </div>
        ) : null}

        <div className="relative min-h-0">
          <div
            ref={runtimeLogRef}
            data-testid="runtime-log-scroll"
            onScroll={handleRuntimeLogScroll}
            className="scrollbar-log h-[420px] min-h-0 overflow-y-auto overflow-x-hidden rounded-lg bg-log-bg p-3.5 font-mono text-xs leading-relaxed text-log-text shadow-inner xl:h-[520px]"
          >
            {runtimeRows.map((row) => {
              if (row.kind === "text") {
                const line = row.line;
                return (
                  <div key={`text-${line.sequence}`} className="grid grid-cols-[132px_72px_minmax(0,1fr)] gap-2 py-0.5 md:grid-cols-[176px_72px_minmax(0,1fr)]">
                    <span className="min-w-0 truncate text-log-muted">{line.timestamp}</span>
                    <span className={`rounded-sm px-1.5 text-center text-[10px] uppercase leading-5 ${logLevelClass(line.level)}`}>
                      {line.level}
                    </span>
                    <span
                      className={`min-w-0 whitespace-pre-wrap break-words ${line.level === "error" ? "text-log-error" : line.level === "warning" ? "text-log-warning" : ""}`}
                    >
                      {line.message}
                    </span>
                  </div>
                );
              }

              const line = row.line;
              const detail = progressDetail(line);
              const visualPercent = clampedPercent(line.percent);
              const percentText = roundedPercent(visualPercent);

              return (
                <div key={`progress-${line.sequence}`} className="grid grid-cols-[132px_88px_minmax(0,1fr)] gap-2 py-1.5 md:grid-cols-[176px_112px_minmax(0,1fr)]">
                  <span className="min-w-0 truncate text-log-muted">{line.timestamp}</span>
                  <span className="rounded-sm bg-log-panel px-1.5 text-center text-[10px] uppercase leading-5 text-log-muted">
                    progress
                  </span>
                  <div aria-label={`${line.label} progress`} className="min-w-0">
                    <p className="min-w-0 truncate font-semibold text-log-text">{line.label}</p>
                    <div className="mt-1 flex items-center gap-2">
                      <div
                        aria-hidden="true"
                        className="h-2 flex-1 overflow-hidden rounded-full bg-log-panel"
                      >
                        <div className="h-full rounded-full bg-log-accent" style={{ width: `${visualPercent}%` }} />
                      </div>
                      <span className="w-10 text-right font-bold text-log-accent">{percentText}%</span>
                    </div>
                    {detail ? <p className="mt-1 text-log-muted">{detail}</p> : null}
                  </div>
                </div>
              );
            })}
          </div>
          <button
            type="button"
            aria-hidden={!showJumpToLatest}
            aria-label="Jump to latest log"
            tabIndex={showJumpToLatest ? 0 : -1}
            onClick={jumpToLatestLog}
            className={`absolute bottom-4 right-4 flex h-10 w-10 items-center justify-center rounded-full bg-paper text-log-bg shadow-control outline-none transition-[opacity,transform] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-log-bg active:scale-95 motion-reduce:transition-none ${showJumpToLatest ? "pointer-events-auto translate-y-0 opacity-100" : "pointer-events-none translate-y-1 opacity-0"}`}
          >
            <ArrowDown className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </section>
    </section>
  );
}
