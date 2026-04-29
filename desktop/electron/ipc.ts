import { dialog, ipcMain, type BrowserWindow, type IpcMainInvokeEvent } from "electron";

import type {
  ApiArtifactPreviewData,
  ApiArtifactRecord,
  ApiDoctorCheck,
  ApiModelDownloadJob,
  ApiModelAssetStatus,
  ApiModelDownloadData,
  ApiProviderProfile,
  ApiProviderModel,
  ApiProviderConnectionTestData,
  ApiQuickstartTaskRecord,
  ApiRunRecord,
  ApiRuntimeSettings,
  ApiSecretCheck,
  ApiSubtitleJobData,
  ApiSubtitleWorkflowTemplateData,
  ApiWorkflowToolCatalogData,
  ApiWorkflowEvent
} from "./apiTypes.js";
import { requestJson } from "./http.js";
import { toReviewModel } from "./reviewMapping.js";
import type { ManagedSidecar } from "./sidecar.js";
import { toTaskMonitorModel, toTaskSummaryModel } from "./taskMapping.js";
import { buildQuickstartRequest } from "./workflowMapping.js";
import type {
  DiagnosticCheck,
  DownloadFasterWhisperModelInput,
  LlmProviderModel,
  ProviderConnectionTestInput,
  ProviderConnectionTestResult,
  ProviderModelOption,
  RuntimeModelDownloadJob,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SaveFasterWhisperDefaultsInput,
  SaveLlmProviderInput,
  SaveRuntimeDefaultsInput,
  SecretStatus,
  SourceDraft,
  StartSubtitleTaskInput,
  WorkflowTool,
  WorkflowStep
} from "../src/lib/types.js";

type IpcContext = {
  getSidecar(): ManagedSidecar;
  window: BrowserWindow;
};

type IpcHandler = (event: IpcMainInvokeEvent, ...args: unknown[]) => Promise<unknown> | unknown;

export function registerOpenBBQIpc(context: IpcContext): () => void {
  const handlers: Array<[string, IpcHandler]> = [
    ["openbbq:choose-local-media", async () => chooseLocalMedia(context.window)],
    ["openbbq:get-workflow-template", async (_event, source) => getWorkflowTemplate(context.getSidecar(), source as SourceDraft)],
    ["openbbq:get-workflow-tools", async () => getWorkflowTools(context.getSidecar())],
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
      "openbbq:get-llm-provider-secret",
      async (_event, name) => getLlmProviderSecret(context.getSidecar(), String(name))
    ],
    [
      "openbbq:get-llm-provider-models",
      async (_event, name) => getLlmProviderModels(context.getSidecar(), String(name))
    ],
    [
      "openbbq:test-llm-provider-connection",
      async (_event, input) => testLlmProviderConnection(context.getSidecar(), input as ProviderConnectionTestInput)
    ],
    [
      "openbbq:save-faster-whisper-defaults",
      async (_event, input) => saveFasterWhisperDefaults(context.getSidecar(), input as SaveFasterWhisperDefaultsInput)
    ],
    ["openbbq:get-runtime-models", async () => getRuntimeModels(context.getSidecar())],
    [
      "openbbq:download-faster-whisper-model",
      async (_event, input) => downloadFasterWhisperModel(context.getSidecar(), input as DownloadFasterWhisperModelInput)
    ],
    [
      "openbbq:get-faster-whisper-model-download",
      async (_event, jobId) => getFasterWhisperModelDownload(context.getSidecar(), String(jobId))
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

export async function getWorkflowTemplate(sidecar: ManagedSidecar, source: SourceDraft): Promise<WorkflowStep[]> {
  const parameters = new URLSearchParams({ source_kind: source.kind });
  if (source.kind === "remote_url") {
    parameters.set("url", source.url);
  }
  const data = await requestJson<ApiSubtitleWorkflowTemplateData>(
    sidecar.connection,
    `/quickstart/subtitle/template?${parameters.toString()}`
  );
  return data.steps.map((step) => ({
    id: step.id,
    name: step.name,
    toolRef: step.tool_ref,
    summary: step.summary,
    status: step.status,
    selected: step.selected ?? undefined,
    inputs: step.inputs ?? undefined,
    outputs: step.outputs ?? undefined,
    parameters: step.parameters
  }));
}

export async function getWorkflowTools(sidecar: ManagedSidecar): Promise<WorkflowTool[]> {
  const data = await requestJson<ApiWorkflowToolCatalogData>(
    sidecar.connection,
    "/quickstart/subtitle/tools"
  );
  return data.tools.map((tool) => ({
    toolRef: tool.tool_ref,
    name: tool.name,
    description: tool.description,
    inputs: Object.fromEntries(
      Object.entries(tool.inputs).map(([name, spec]) => [
        name,
        {
          artifactTypes: spec.artifact_types,
          required: spec.required,
          multiple: spec.multiple
        }
      ])
    ),
    outputs: tool.outputs,
    parameters: tool.parameters
  }));
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

export async function getTaskMonitor(sidecar: ManagedSidecar, runId: string) {
  const encodedRunId = encodeURIComponent(runId);
  const run = await requestJson<ApiRunRecord>(sidecar.connection, `/runs/${encodedRunId}`);
  const eventData = await requestJson<{ workflow_id: string; events: ApiWorkflowEvent[] }>(
    sidecar.connection,
    `/runs/${encodedRunId}/events`
  );
  return toTaskMonitorModel(run, eventData.events);
}

export async function retryCheckpoint(sidecar: ManagedSidecar, runId: string) {
  await requestJson<ApiRunRecord>(sidecar.connection, `/runs/${encodeURIComponent(runId)}/retry-checkpoint`, {
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
    displayName: provider.display_name ?? null,
    enabled: provider.enabled ?? true
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
      defaultComputeType: settings.models.faster_whisper.default_compute_type,
      enabled: settings.models.faster_whisper.enabled ?? true
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

function toModelDownloadJob(job: ApiModelDownloadJob): RuntimeModelDownloadJob {
  return {
    jobId: job.job_id,
    provider: job.provider,
    model: job.model,
    status: job.status,
    percent: job.percent,
    currentBytes: job.current_bytes ?? null,
    totalBytes: job.total_bytes ?? null,
    error: job.error ?? null,
    startedAt: job.started_at,
    completedAt: job.completed_at ?? null,
    modelStatus: job.model_status ? toModelStatusModel(job.model_status) : null
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

function toProviderModelOption(model: ApiProviderModel): ProviderModelOption {
  return {
    id: model.id,
    label: model.label ?? null,
    ownedBy: model.owned_by ?? null,
    contextLength: model.context_length ?? null
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
        display_name: input.displayName,
        enabled: input.enabled
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

export async function getLlmProviderSecret(sidecar: ManagedSidecar, name: string): Promise<string> {
  const data = await requestJson<{ value: string }>(
    sidecar.connection,
    `/runtime/providers/${encodeURIComponent(name)}/secret`
  );
  return data.value;
}

export async function getLlmProviderModels(
  sidecar: ManagedSidecar,
  name: string
): Promise<ProviderModelOption[]> {
  const data = await requestJson<{ models: ApiProviderModel[] }>(
    sidecar.connection,
    `/runtime/providers/${encodeURIComponent(name)}/models`
  );
  return data.models.map(toProviderModelOption);
}

export async function testLlmProviderConnection(
  sidecar: ManagedSidecar,
  input: ProviderConnectionTestInput
): Promise<ProviderConnectionTestResult> {
  const data = await requestJson<ApiProviderConnectionTestData>(
    sidecar.connection,
    "/runtime/providers/test-connection",
    {
      method: "POST",
      body: {
        provider_name: input.providerName ?? null,
        base_url: input.baseUrl,
        api_key: input.apiKey,
        model: input.model
      }
    }
  );
  return { ok: data.ok, message: data.message };
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
        default_compute_type: input.defaultComputeType,
        enabled: input.enabled
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
): Promise<RuntimeModelDownloadJob> {
  const data = await requestJson<ApiModelDownloadData>(sidecar.connection, "/runtime/models/faster-whisper/download", {
    method: "POST",
    body: { model: input.model }
  });
  return toModelDownloadJob(data.job);
}

export async function getFasterWhisperModelDownload(
  sidecar: ManagedSidecar,
  jobId: string
): Promise<RuntimeModelDownloadJob> {
  const data = await requestJson<{ job: ApiModelDownloadJob }>(
    sidecar.connection,
    `/runtime/models/faster-whisper/downloads/${encodeURIComponent(jobId)}`
  );
  return toModelDownloadJob(data.job);
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
