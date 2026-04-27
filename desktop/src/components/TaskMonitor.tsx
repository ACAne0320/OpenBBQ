import { AlertTriangle, Check, Copy, Minus, X } from "lucide-react";

import type { ProgressStep, TaskMonitorModel } from "../lib/types";
import { Button } from "./Button";

type TaskMonitorProps = {
  task: TaskMonitorModel;
  onRetry: () => void;
};

function stepSummary(task: TaskMonitorModel): string {
  const failedStep = task.progress.find((step) => step.status === "failed");
  if (failedStep) {
    return `${failedStep.label} failed`;
  }

  const runningStep = task.progress.find((step) => step.status === "running");
  if (runningStep) {
    return `${runningStep.label} running`;
  }

  const completedStep = [...task.progress].reverse().find((step) => step.status === "done");
  if (completedStep && task.status === "completed") {
    return `${completedStep.label} completed`;
  }

  return task.status === "queued" ? "Waiting to start" : "No active step";
}

function progressCounts(progress: ProgressStep[]) {
  const done = progress.filter((step) => step.status === "done").length;
  const failed = progress.filter((step) => step.status === "failed").length;
  const running = progress.filter((step) => step.status === "running").length;

  return { done, failed, running };
}

function statusTone(status: ProgressStep["status"]): string {
  if (status === "done") {
    return "bg-ready text-[#fff8ea]";
  }

  if (status === "failed") {
    return "bg-accent text-[#fff8ea]";
  }

  if (status === "running") {
    return "bg-paper text-accent shadow-[inset_0_0_0_2px_rgba(182,99,47,0.45)]";
  }

  return "bg-[#d8c8ae] text-[#7a6b56]";
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
    return "bg-[#5b2e22] text-[#ffbd96]";
  }

  if (level === "warning") {
    return "bg-[#5a4627] text-[#ffd08f]";
  }

  return "bg-[#403329] text-[#d9c4a2]";
}

export function TaskMonitor({ task, onRetry }: TaskMonitorProps) {
  const failed = task.status === "failed" && Boolean(task.errorMessage);
  const counts = progressCounts(task.progress);
  const logText = task.logs.map((line) => `${line.timestamp} ${line.level} ${line.message}`).join("\n");

  function copyLog() {
    if (!navigator.clipboard) {
      return;
    }

    void navigator.clipboard.writeText(logText).catch(() => undefined);
  }

  return (
    <section className="grid min-h-[calc(100vh-84px)] grid-rows-[auto_auto_minmax(0,1fr)] gap-3.5">
      <header className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] uppercase text-muted">Task monitor</p>
          <h1 className="mt-2 truncate font-serif text-[38px] leading-none text-ink-brown">{task.title}</h1>
          <p className="mt-1.5 text-sm text-muted">{task.workflowName}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button>Diagnostics</Button>
          <Button variant="ink">Request cancel</Button>
        </div>
      </header>

      <section aria-label="Task progress" className="rounded-lg bg-paper-muted px-4 py-3 shadow-control">
        <div className="grid grid-cols-[minmax(136px,180px)_minmax(220px,1fr)_minmax(120px,auto)] items-center gap-4">
          <div className="min-w-0">
            <p className="text-[11px] uppercase text-muted">Progress</p>
            <h2 className="mt-1 truncate text-base font-extrabold leading-tight text-ink-brown">{stepSummary(task)}</h2>
          </div>

          <ol className="flex min-w-0 items-center gap-2">
            {task.progress.map((step, index) => (
              <li key={step.id} className="flex min-w-0 flex-1 items-center gap-2 last:flex-none">
                <span
                  data-testid="progress-step"
                  title={`${step.label}: ${step.status}`}
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${statusTone(step.status)}`}
                >
                  {statusIcon(step.status)}
                </span>
                {index < task.progress.length - 1 ? <span className="h-[3px] flex-1 rounded-full bg-[#d8c8ae]" /> : null}
              </li>
            ))}
          </ol>

          <p className="text-right text-xs text-muted">
            {counts.done} done
            {counts.running > 0 ? ` - ${counts.running} running` : ""}
            {counts.failed > 0 ? ` - ${counts.failed} failed` : ""}
          </p>
        </div>
      </section>

      <section aria-label="Runtime log" className="grid min-h-[520px] grid-rows-[auto_auto_minmax(0,1fr)] rounded-lg bg-paper-muted p-4 shadow-control">
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
            className="mb-3 flex items-center justify-between gap-3 rounded-lg bg-accent-soft px-3.5 py-3 text-[#6b3f27] shadow-control"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p className="text-sm font-semibold leading-snug">{task.errorMessage}</p>
            </div>
            <Button className="shrink-0" variant="primary" onClick={onRetry}>
              Retry checkpoint
            </Button>
          </div>
        ) : null}

        <div className="min-h-0 overflow-auto rounded-lg bg-log-bg p-3.5 font-mono text-xs leading-relaxed text-[#f8ead2] shadow-inner">
          {task.logs.map((line) => (
            <div key={line.sequence} className="grid grid-cols-[176px_72px_minmax(0,1fr)] gap-2 py-0.5">
              <span className="text-[#c7aa7a]">{line.timestamp}</span>
              <span className={`rounded-sm px-1.5 text-center text-[10px] uppercase leading-5 ${logLevelClass(line.level)}`}>
                {line.level}
              </span>
              <span className={line.level === "error" ? "text-[#ffbd96]" : line.level === "warning" ? "text-[#ffd08f]" : ""}>
                {line.message}
              </span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
