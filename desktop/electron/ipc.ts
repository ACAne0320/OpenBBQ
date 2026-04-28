import { dialog, ipcMain, type BrowserWindow, type IpcMainInvokeEvent } from "electron";

import type {
  ApiArtifactPreviewData,
  ApiArtifactRecord,
  ApiDoctorCheck,
  ApiModelAssetStatus,
  ApiModelDownloadData,
  ApiProviderProfile,
  ApiQuickstartTaskRecord,
  ApiRunRecord,
  ApiRuntimeSettings,
  ApiSecretCheck,
  ApiSubtitleJobData,
  ApiWorkflowEvent
} from "./apiTypes.js";
import { requestJson } from "./http.js";
import { toReviewModel } from "./reviewMapping.js";
import type { ManagedSidecar } from "./sidecar.js";
import { toTaskMonitorModel, toTaskSummaryModel } from "./taskMapping.js";
import { buildQuickstartRequest, workflowTemplateForSource } from "./workflowMapping.js";
import type {
  DiagnosticCheck,
  DownloadFasterWhisperModelInput,
  LlmProviderModel,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SaveFasterWhisperDefaultsInput,
  SaveLlmProviderInput,
  SaveRuntimeDefaultsInput,
  SecretStatus,
  SourceDraft,
  StartSubtitleTaskInput
} from "../src/lib/types.js";

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
    ["openbbq:get-runtime-settings", async () => getRuntimeSettings(context.getSidecar())],
    [
      "openbbq:save-runtime-defaults",
      async (_event, input) => saveRuntimeDefaults(context.getSidecar(), input as SaveRuntimeDefaultsInput)
    ],
    [
      "openbbq:save-llm-provider",
      async (_event, input) => saveLlmProvider(context.getSidecar(), input as SaveLlmProviderInput)
    ],
    ["openbbq:check-llm-provider", async (_event, name) => checkLlmProvider(context.getSidecar(), String(name))],
    [
      "openbbq:save-faster-whisper-defaults",
      async (_event, input) => saveFasterWhisperDefaults(context.getSidecar(), input as SaveFasterWhisperDefaultsInput)
    ],
    ["openbbq:get-runtime-models", async () => getRuntimeModels(context.getSidecar())],
    [
      "openbbq:download-faster-whisper-model",
      async (_event, input) => downloadFasterWhisperModel(context.getSidecar(), input as DownloadFasterWhisperModelInput)
    ],
    ["openbbq:get-diagnostics", async () => getDiagnostics(context.getSidecar())],
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

function toLlmProviderModel(provider: ApiProviderProfile): LlmProviderModel {
  return {
    name: provider.name,
    type: provider.type,
    baseUrl: provider.base_url ?? null,
    apiKeyRef: provider.api_key ?? null,
    defaultChatModel: provider.default_chat_model ?? null,
    displayName: provider.display_name ?? null
  };
}

function toRuntimeSettingsModel(settings: ApiRuntimeSettings): RuntimeSettingsModel {
  return {
    configPath: settings.config_path,
    cacheRoot: settings.cache.root,
    defaults: {
      llmProvider: settings.defaults.llm_provider,
      asrProvider: settings.defaults.asr_provider
    },
    llmProviders: Object.values(settings.providers).map(toLlmProviderModel),
    fasterWhisper: {
      cacheDir: settings.models.faster_whisper.cache_dir,
      defaultModel: settings.models.faster_whisper.default_model,
      defaultDevice: settings.models.faster_whisper.default_device,
      defaultComputeType: settings.models.faster_whisper.default_compute_type
    }
  };
}

function toModelStatusModel(model: ApiModelAssetStatus): RuntimeModelStatus {
  return {
    provider: model.provider,
    model: model.model,
    cacheDir: model.cache_dir,
    present: model.present,
    sizeBytes: model.size_bytes,
    error: model.error ?? null
  };
}

function toSecretStatus(secret: ApiSecretCheck): SecretStatus {
  return {
    reference: secret.reference,
    resolved: secret.resolved,
    display: secret.display,
    valuePreview: secret.value_preview ?? null,
    error: secret.error ?? null
  };
}

export async function getRuntimeSettings(sidecar: ManagedSidecar): Promise<RuntimeSettingsModel> {
  const data = await requestJson<{ settings: ApiRuntimeSettings }>(sidecar.connection, "/runtime/settings");
  return toRuntimeSettingsModel(data.settings);
}

export async function saveRuntimeDefaults(
  sidecar: ManagedSidecar,
  input: SaveRuntimeDefaultsInput
): Promise<RuntimeSettingsModel> {
  const data = await requestJson<{ settings: ApiRuntimeSettings }>(sidecar.connection, "/runtime/defaults", {
    method: "PUT",
    body: { llm_provider: input.llmProvider, asr_provider: input.asrProvider }
  });
  return toRuntimeSettingsModel(data.settings);
}

export async function saveLlmProvider(
  sidecar: ManagedSidecar,
  input: SaveLlmProviderInput
): Promise<LlmProviderModel> {
  const data = await requestJson<{ provider: ApiProviderProfile }>(
    sidecar.connection,
    `/runtime/providers/${encodeURIComponent(input.name)}/auth`,
    {
      method: "PUT",
      body: {
        type: input.type,
        base_url: input.baseUrl,
        default_chat_model: input.defaultChatModel,
        secret_value: input.secretValue,
        api_key_ref: input.apiKeyRef,
        display_name: input.displayName
      }
    }
  );
  return toLlmProviderModel(data.provider);
}

export async function checkLlmProvider(sidecar: ManagedSidecar, name: string): Promise<SecretStatus> {
  const data = await requestJson<{ secret: ApiSecretCheck }>(
    sidecar.connection,
    `/runtime/providers/${encodeURIComponent(name)}/check`
  );
  return toSecretStatus(data.secret);
}

export async function saveFasterWhisperDefaults(
  sidecar: ManagedSidecar,
  input: SaveFasterWhisperDefaultsInput
): Promise<RuntimeSettingsModel> {
  const data = await requestJson<{ settings: ApiRuntimeSettings }>(
    sidecar.connection,
    "/runtime/models/faster-whisper",
    {
      method: "PUT",
      body: {
        cache_dir: input.cacheDir,
        default_model: input.defaultModel,
        default_device: input.defaultDevice,
        default_compute_type: input.defaultComputeType
      }
    }
  );
  return toRuntimeSettingsModel(data.settings);
}

export async function getRuntimeModels(sidecar: ManagedSidecar): Promise<RuntimeModelStatus[]> {
  const data = await requestJson<{ models: ApiModelAssetStatus[] }>(sidecar.connection, "/runtime/models");
  return data.models.map(toModelStatusModel);
}

export async function downloadFasterWhisperModel(
  sidecar: ManagedSidecar,
  input: DownloadFasterWhisperModelInput
): Promise<RuntimeModelStatus> {
  const data = await requestJson<ApiModelDownloadData>(sidecar.connection, "/runtime/models/faster-whisper/download", {
    method: "POST",
    body: { model: input.model }
  });
  return toModelStatusModel(data.model);
}

export async function getDiagnostics(sidecar: ManagedSidecar): Promise<DiagnosticCheck[]> {
  const data = await requestJson<{ ok: boolean; checks: ApiDoctorCheck[] }>(sidecar.connection, "/doctor");
  return data.checks.map((check) => ({
    id: check.id,
    status: check.status,
    severity: check.severity,
    message: check.message
  }));
}
