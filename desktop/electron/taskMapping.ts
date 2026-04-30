import type { ProgressStep, RuntimeLogLine, TaskMonitorModel, TaskProgressLogLine, TaskSummary } from "../src/lib/types.js";
import type { ApiProgressPayload, ApiQuickstartTaskRecord, ApiRunRecord, ApiWorkflowEvent } from "./apiTypes.js";

const knownSteps: Array<{ id: string; label: string }> = [
  { id: "extract_audio", label: "Extract" },
  { id: "download", label: "Download" },
  { id: "transcribe", label: "Transcribe" },
  { id: "correct", label: "Correct" },
  { id: "segment", label: "Segment" },
  { id: "translate", label: "Translate" },
  { id: "subtitle", label: "Export" }
];

const workflowNames: Record<string, string> = {
  "local-to-srt": "Local video -> translated SRT",
  "youtube-to-srt": "Remote video -> translated SRT"
};

function workflowDisplayName(workflowId: string): string {
  return workflowNames[workflowId] ?? workflowId;
}

function stepsForWorkflow(workflowId: string): Array<{ id: string; label: string }> {
  if (workflowId === "youtube-to-srt") {
    return knownSteps.filter((step) => step.id !== "extract_audio");
  }

  return knownSteps.filter((step) => step.id !== "download");
}

function eventMessage(event: ApiWorkflowEvent): string {
  return event.message ?? event.type;
}

function logLevel(level: ApiWorkflowEvent["level"]): RuntimeLogLine["level"] {
  if (level === "debug") {
    return "info";
  }

  return level;
}

function toLogs(events: ApiWorkflowEvent[]): RuntimeLogLine[] {
  return events.map((event) => ({
    sequence: event.sequence,
    timestamp: event.created_at,
    level: logLevel(event.level),
    message: eventMessage(event)
  }));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isOptionalNumber(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || (typeof value === "number" && Number.isFinite(value));
}

function isOptionalString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

function isProgressPayload(value: unknown): value is ApiProgressPayload {
  if (!isRecord(value)) {
    return false;
  }

  return (
    typeof value.phase === "string" &&
    typeof value.label === "string" &&
    typeof value.percent === "number" &&
    Number.isFinite(value.percent) &&
    isOptionalNumber(value.current) &&
    isOptionalNumber(value.total) &&
    isOptionalString(value.unit)
  );
}

function clampPercent(percent: number): number {
  return Math.min(100, Math.max(0, percent));
}

function toProgressLogs(events: ApiWorkflowEvent[]): TaskProgressLogLine[] {
  return events.flatMap((event) => {
    if (event.type !== "step.progress" || !event.step_id || !isProgressPayload(event.data.progress)) {
      return [];
    }

    const progress = event.data.progress;
    return [
      {
        sequence: event.sequence,
        timestamp: event.created_at,
        stepId: event.step_id,
        attempt: event.attempt ?? null,
        phase: progress.phase,
        label: progress.label,
        percent: clampPercent(progress.percent),
        current: progress.current ?? null,
        total: progress.total ?? null,
        unit: progress.unit ?? null
      }
    ];
  });
}

function computeProgress(run: ApiRunRecord, events: ApiWorkflowEvent[]): ProgressStep[] {
  const steps = stepsForWorkflow(run.workflow_id);
  if (run.status === "completed") {
    return steps.map((step) => ({ ...step, status: "done" as const }));
  }

  const completed = new Set(events.filter((event) => event.type === "step.completed" && event.step_id).map((event) => event.step_id as string));
  const failed = [...events].reverse().find((event) => event.type === "step.failed" && event.step_id)?.step_id ?? null;
  const running =
    [...events].reverse().find((event) => (event.type === "step.started" || event.type === "workflow.step_rerun_started") && event.step_id)?.step_id ??
    null;

  return steps.map((step) => {
    if (failed === step.id) {
      return { ...step, status: "failed" as const };
    }

    if (completed.has(step.id)) {
      return { ...step, status: "done" as const };
    }

    if (run.status === "running" && running === step.id) {
      return { ...step, status: "running" as const };
    }

    if (run.status === "queued" && step.id === steps[0]?.id) {
      return { ...step, status: "running" as const };
    }

    return { ...step, status: "blocked" as const };
  });
}

export function toTaskMonitorModel(run: ApiRunRecord, events: ApiWorkflowEvent[]): TaskMonitorModel {
  const progress = computeProgress(run, events);
  return {
    id: run.id,
    title: run.workflow_id,
    workflowName: workflowDisplayName(run.workflow_id),
    status: run.status,
    progress,
    progressLogs: toProgressLogs(events),
    logs: toLogs(events),
    errorMessage: run.status === "failed" ? run.error?.message ?? undefined : undefined
  };
}

export function toTaskSummaryModel(task: ApiQuickstartTaskRecord): TaskSummary {
  const sourceSummary = task.source_summary ?? task.source_uri;
  return {
    id: task.run_id,
    title: sourceSummary,
    workflowName: workflowDisplayName(task.workflow_id),
    sourceKind: task.source_kind,
    sourceUri: task.source_uri,
    sourceSummary,
    status: task.status,
    createdAt: task.created_at,
    updatedAt: task.updated_at
  };
}
