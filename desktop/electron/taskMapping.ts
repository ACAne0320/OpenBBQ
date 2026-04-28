import type { ProgressStep, RuntimeLogLine, TaskMonitorModel, TaskSummary } from "../src/lib/types.js";
import type { ApiQuickstartTaskRecord, ApiRunRecord, ApiWorkflowEvent } from "./apiTypes.js";

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
    sourceSummary,
    status: task.status,
    updatedAt: task.updated_at
  };
}
