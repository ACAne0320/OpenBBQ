import { dialog, ipcMain, type BrowserWindow, type IpcMainInvokeEvent } from "electron";

import type {
  ApiArtifactPreviewData,
  ApiArtifactRecord,
  ApiQuickstartTaskRecord,
  ApiRunRecord,
  ApiSubtitleJobData,
  ApiWorkflowEvent
} from "./apiTypes.js";
import { requestJson } from "./http.js";
import { toReviewModel } from "./reviewMapping.js";
import type { ManagedSidecar } from "./sidecar.js";
import { toTaskMonitorModel, toTaskSummaryModel } from "./taskMapping.js";
import { buildQuickstartRequest, workflowTemplateForSource } from "./workflowMapping.js";
import type { SourceDraft, StartSubtitleTaskInput } from "../src/lib/types.js";

type IpcContext = {
  getSidecar(): ManagedSidecar;
  window: BrowserWindow;
};

type IpcHandler = (event: IpcMainInvokeEvent, ...args: unknown[]) => Promise<unknown> | unknown;

export function registerOpenBBQIpc(context: IpcContext): () => void {
  const handlers: Array<[string, IpcHandler]> = [
    ["openbbq:choose-local-media", async () => chooseLocalMedia(context.window)],
    ["openbbq:get-workflow-template", async (_event, source) => workflowTemplateForSource(source as SourceDraft)],
    ["openbbq:start-subtitle-task", async (_event, input) => startSubtitleTask(context.getSidecar(), input as StartSubtitleTaskInput)],
    ["openbbq:list-tasks", async () => listTasks(context.getSidecar())],
    ["openbbq:get-task-monitor", async (_event, runId) => getTaskMonitor(context.getSidecar(), String(runId))],
    ["openbbq:get-review", async (_event, runId) => getReview(context.getSidecar(), String(runId))],
    [
      "openbbq:update-segment-text",
      async () => {
        throw new Error("Edited result persistence is not available in the real desktop client yet.");
      }
    ],
    [
      "openbbq:retry-checkpoint",
      async (_event, runId) => retryCheckpoint(context.getSidecar(), String(runId))
    ]
  ];

  for (const [channel, handler] of handlers) {
    ipcMain.handle(channel, handler);
  }

  return () => {
    for (const [channel] of handlers) {
      ipcMain.removeHandler(channel);
    }
  };
}

async function chooseLocalMedia(window: BrowserWindow) {
  const result = await dialog.showOpenDialog(window, {
    properties: ["openFile"],
    filters: [{ name: "Media", extensions: ["mp4", "mov", "mkv", "m4a", "wav"] }]
  });
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  const path = result.filePaths[0];
  return {
    kind: "local_file" as const,
    path,
    displayName: path.split(/[\\/]/).pop() ?? path
  };
}

async function startSubtitleTask(sidecar: ManagedSidecar, input: StartSubtitleTaskInput) {
  const request = buildQuickstartRequest(input.source, input.steps);
  const data = await requestJson<ApiSubtitleJobData>(sidecar.connection, request.route, {
    method: "POST",
    body: request.body
  });
  return { runId: data.run_id };
}

export async function listTasks(sidecar: ManagedSidecar) {
  const data = await requestJson<{ tasks: ApiQuickstartTaskRecord[] }>(
    sidecar.connection,
    "/quickstart/tasks"
  );
  return data.tasks.map(toTaskSummaryModel);
}

async function getTaskMonitor(sidecar: ManagedSidecar, runId: string) {
  const encodedRunId = encodeURIComponent(runId);
  const run = await requestJson<ApiRunRecord>(sidecar.connection, `/runs/${encodedRunId}`);
  const eventData = await requestJson<{ workflow_id: string; events: ApiWorkflowEvent[] }>(
    sidecar.connection,
    `/runs/${encodedRunId}/events`
  );
  return toTaskMonitorModel(run, eventData.events);
}

export async function retryCheckpoint(sidecar: ManagedSidecar, runId: string) {
  await requestJson<ApiRunRecord>(sidecar.connection, `/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST"
  });
}

async function getReview(sidecar: ManagedSidecar, runId: string) {
  const artifactData = await requestJson<{ artifacts: ApiArtifactRecord[] }>(
    sidecar.connection,
    `/runs/${encodeURIComponent(runId)}/artifacts`
  );
  const previewsByVersionId = new Map<string, ApiArtifactPreviewData>();
  for (const artifact of artifactData.artifacts) {
    if (!artifact.current_version_id) {
      continue;
    }
    const preview = await requestJson<ApiArtifactPreviewData>(
      sidecar.connection,
      `/artifact-versions/${encodeURIComponent(artifact.current_version_id)}/preview`
    );
    previewsByVersionId.set(artifact.current_version_id, preview);
  }
  return toReviewModel(runId, artifactData.artifacts, previewsByVersionId);
}
