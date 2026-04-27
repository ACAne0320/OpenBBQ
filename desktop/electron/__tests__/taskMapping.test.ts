// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { ApiRunRecord, ApiWorkflowEvent } from "../apiTypes";
import { toTaskMonitorModel } from "../taskMapping";

const baseRun: ApiRunRecord = {
  id: "run_1",
  workflow_id: "local-to-srt",
  mode: "start",
  status: "running",
  project_root: "H:/workspace",
  config_path: "H:/workspace/openbbq.yaml",
  plugin_paths: [],
  latest_event_sequence: 3,
  error: null,
  created_by: "desktop"
};

function event(sequence: number, type: string, stepId: string | null, message: string, level: ApiWorkflowEvent["level"] = "info"): ApiWorkflowEvent {
  return {
    id: `evt_${sequence}`,
    workflow_id: "local-to-srt",
    sequence,
    type,
    level,
    message,
    data: {},
    created_at: `2026-04-27T03:15:1${sequence}.000Z`,
    step_id: stepId,
    attempt: null
  };
}

describe("toTaskMonitorModel", () => {
  it("maps running events into progress and logs", () => {
    const model = toTaskMonitorModel(baseRun, [
      event(1, "workflow.started", null, "Workflow started."),
      event(2, "step.completed", "extract_audio", "Audio extraction completed."),
      event(3, "step.started", "transcribe", "Transcription started.")
    ]);

    expect(model).toMatchObject({
      id: "run_1",
      title: "local-to-srt",
      workflowName: "Local video -> translated SRT",
      status: "running"
    });
    expect(model.progress).toEqual([
      { id: "extract_audio", label: "Extract", status: "done" },
      { id: "transcribe", label: "Transcribe", status: "running" },
      { id: "correct", label: "Correct", status: "blocked" },
      { id: "segment", label: "Segment", status: "blocked" },
      { id: "translate", label: "Translate", status: "blocked" },
      { id: "subtitle", label: "Export", status: "blocked" }
    ]);
    expect(model.logs[0]).toMatchObject({ sequence: 1, level: "info", message: "Workflow started." });
  });

  it("shows failed step and error message", () => {
    const model = toTaskMonitorModel(
      { ...baseRun, status: "failed", error: { code: "provider_error", message: "Provider returned rate limit." } },
      [
        event(1, "step.completed", "extract_audio", "Audio extraction completed."),
        event(2, "step.completed", "transcribe", "Transcription completed."),
        event(3, "step.failed", "translate", "Translation provider failed.", "error")
      ]
    );

    expect(model.status).toBe("failed");
    expect(model.errorMessage).toBe("Provider returned rate limit.");
    expect(model.progress.find((step) => step.id === "translate")).toMatchObject({ status: "failed" });
    expect(model.progress.find((step) => step.id === "subtitle")).toMatchObject({ status: "blocked" });
  });

  it("marks all known steps done for completed runs", () => {
    const model = toTaskMonitorModel({ ...baseRun, status: "completed" }, [event(1, "workflow.completed", null, "Workflow completed.")]);

    expect(model.progress.every((step) => step.status === "done")).toBe(true);
  });
});
