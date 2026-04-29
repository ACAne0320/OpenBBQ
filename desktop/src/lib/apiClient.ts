import { failedTask, reviewModel, workflowSteps } from "./mockData";
import type {
  DiagnosticCheck,
  DownloadFasterWhisperModelInput,
  LlmProviderModel,
  LocalMediaSelection,
  ProviderConnectionTestInput,
  ProviderConnectionTestResult,
  ProviderModelOption,
  ReviewModel,
  RuntimeModelDownloadJob,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SaveFasterWhisperDefaultsInput,
  SaveLlmProviderInput,
  SaveRuntimeDefaultsInput,
  SecretStatus,
  SourceDraft,
  StartSubtitleTaskInput,
  StartSubtitleTaskResult,
  StepParameter,
  TaskSummary,
  TaskMonitorModel,
  WorkflowTool,
  WorkflowStep
} from "./types";

export type OpenBBQClient = {
  chooseLocalMedia?(): Promise<LocalMediaSelection | null>;
  getWorkflowTemplate(source: SourceDraft): Promise<WorkflowStep[]>;
  getWorkflowTools(): Promise<WorkflowTool[]>;
  startSubtitleTask(input: StartSubtitleTaskInput): Promise<StartSubtitleTaskResult>;
  listTasks(): Promise<TaskSummary[]>;
  getTaskMonitor(runId: string): Promise<TaskMonitorModel>;
  getReview(runId: string): Promise<ReviewModel>;
  getRuntimeSettings(): Promise<RuntimeSettingsModel>;
  saveRuntimeDefaults(input: SaveRuntimeDefaultsInput): Promise<RuntimeSettingsModel>;
  saveLlmProvider(input: SaveLlmProviderInput): Promise<LlmProviderModel>;
  checkLlmProvider(name: string): Promise<SecretStatus>;
  getLlmProviderSecret(name: string): Promise<string>;
  getLlmProviderModels(name: string): Promise<ProviderModelOption[]>;
  testLlmProviderConnection(input: ProviderConnectionTestInput): Promise<ProviderConnectionTestResult>;
  saveFasterWhisperDefaults(input: SaveFasterWhisperDefaultsInput): Promise<RuntimeSettingsModel>;
  getRuntimeModels(): Promise<RuntimeModelStatus[]>;
  downloadFasterWhisperModel(input: DownloadFasterWhisperModelInput): Promise<RuntimeModelDownloadJob>;
  getFasterWhisperModelDownload(jobId: string): Promise<RuntimeModelDownloadJob>;
  getDiagnostics(): Promise<DiagnosticCheck[]>;
  updateSegmentText(input: {
    segmentId: string;
    transcript: string;
    translation: string;
  }): Promise<void>;
  retryCheckpoint(runId: string): Promise<void>;
};

function cloneModel<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function remoteDownloadStep(source: Extract<SourceDraft, { kind: "remote_url" }>): WorkflowStep {
  const parameters: StepParameter[] = [
    { kind: "text", key: "url", label: "URL", value: source.url },
    {
      kind: "text",
      key: "quality",
      label: "Quality",
      value: "best[ext=mp4][height<=720]/best[height<=720]/best"
    },
    { kind: "text", key: "auth", label: "Auth", value: "auto" }
  ];

  return {
    id: "download",
    name: "Download Video",
    toolRef: "remote_video.download",
    summary: "url -> video",
    status: "locked",
    outputs: [{ name: "video", type: "video" }],
    parameters
  };
}

function workflowTemplateForSource(source: SourceDraft): WorkflowStep[] {
  if (source.kind === "remote_url") {
    return [remoteDownloadStep(source), ...workflowSteps];
  }

  return workflowSteps;
}

const fasterWhisperModelNames = ["base", "tiny", "small", "medium", "large-v3"];

const workflowTools: WorkflowTool[] = [
  {
    toolRef: "translation.qa",
    name: "Translation QA",
    description: "Check translated segments for terminology misses, numeric drift, and subtitle readability risks.",
    inputs: { translation: { artifactTypes: ["translation"], required: true, multiple: false } },
    outputs: [{ name: "qa", type: "translation_qa" }],
    parameters: [
      { kind: "text", key: "max_lines", label: "Max lines", value: "2" },
      { kind: "text", key: "max_chars_per_line", label: "Max chars per line", value: "42" },
      { kind: "text", key: "max_chars_per_second", label: "Max chars per second", value: "20" }
    ]
  }
];

function initialFasterWhisperModels(cacheDir: string): RuntimeModelStatus[] {
  return fasterWhisperModelNames.map((model) => ({
    provider: "faster-whisper",
    model,
    cacheDir,
    present: false,
    sizeBytes: 0,
    error: null
  }));
}

export function createMockClient(): OpenBBQClient {
  let reviewState = cloneModel(reviewModel);
  let runtimeSettings: RuntimeSettingsModel = {
    configPath: "C:/Users/alex/.openbbq/config.toml",
    cacheRoot: "C:/Users/alex/.cache/openbbq",
    defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
    llmProviders: [
      {
        name: "openai-compatible",
        type: "openai_compatible",
        baseUrl: null,
        apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
        defaultChatModel: "gpt-4o-mini",
        displayName: "OpenAI-compatible",
        enabled: true
      }
    ],
    fasterWhisper: {
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      defaultModel: "base",
      defaultDevice: "cpu",
      defaultComputeType: "int8",
      enabled: true
    }
  };
  let runtimeModels: RuntimeModelStatus[] = initialFasterWhisperModels(runtimeSettings.fasterWhisper.cacheDir);
  const downloadJobs = new Map<string, RuntimeModelDownloadJob>();
  let downloadJobSequence = 0;
  const diagnostics: DiagnosticCheck[] = [
    {
      id: "cache.root_writable",
      status: "passed",
      severity: "error",
      message: "Runtime cache root is writable."
    }
  ];

  return {
    async getWorkflowTemplate(source) {
      return cloneModel(workflowTemplateForSource(source));
    },
    async getWorkflowTools() {
      return cloneModel(workflowTools);
    },
    async startSubtitleTask() {
      return { runId: "run_sample" };
    },
    async listTasks() {
      return [
        {
          id: "run_sample",
          title: "Sample task",
          workflowName: "Remote video -> translated SRT",
          sourceSummary: "Sample task",
          status: "failed",
          updatedAt: "2026-04-27T03:17:12.000Z"
        }
      ];
    },
    async getTaskMonitor() {
      return cloneModel(failedTask);
    },
    async getReview() {
      return cloneModel(reviewState);
    },
    async getRuntimeSettings() {
      return cloneModel(runtimeSettings);
    },
    async saveRuntimeDefaults(input) {
      runtimeSettings = {
        ...runtimeSettings,
        defaults: { llmProvider: input.llmProvider, asrProvider: input.asrProvider }
      };
      return cloneModel(runtimeSettings);
    },
    async saveLlmProvider(input) {
      const provider: LlmProviderModel = {
        name: input.name,
        type: input.type,
        baseUrl: input.baseUrl,
        apiKeyRef: input.apiKeyRef,
        defaultChatModel: input.defaultChatModel,
        displayName: input.displayName,
        enabled: input.enabled
      };
      const providerIndex = runtimeSettings.llmProviders.findIndex((item) => item.name === provider.name);
      runtimeSettings = {
        ...runtimeSettings,
        llmProviders:
          providerIndex === -1
            ? [...runtimeSettings.llmProviders, provider]
            : runtimeSettings.llmProviders.map((item) => (item.name === provider.name ? provider : item))
      };
      return cloneModel(provider);
    },
    async checkLlmProvider(name) {
      const provider = runtimeSettings.llmProviders.find((item) => item.name === name);
      const reference = provider?.apiKeyRef ?? "";
      return {
        reference,
        resolved: reference.length > 0,
        display: reference,
        valuePreview: reference.length > 0 ? "configured" : null,
        error: reference.length > 0 ? null : `Provider '${name}' does not define an API key reference.`
      };
    },
    async getLlmProviderSecret(name) {
      const provider = runtimeSettings.llmProviders.find((item) => item.name === name);
      if (!provider?.apiKeyRef) {
        throw new Error(`Provider '${name}' does not define an API key reference.`);
      }
      return "sk-mock-secret";
    },
    async getLlmProviderModels(name) {
      const provider = runtimeSettings.llmProviders.find((item) => item.name === name);
      if (!provider) {
        throw new Error(`Provider '${name}' is not configured.`);
      }
      if (provider.name === "local-gateway") {
        return [{ id: "qwen2.5", label: null, ownedBy: "local", contextLength: null }];
      }
      return [
        { id: "gpt-4o-mini", label: null, ownedBy: "openai", contextLength: null },
        { id: "gpt-4.1-mini", label: null, ownedBy: "openai", contextLength: null }
      ];
    },
    async testLlmProviderConnection(input) {
      if (!input.baseUrl || !input.model) {
        throw new Error("Base URL and model are required.");
      }
      return { ok: true, message: "Connection test succeeded." };
    },
    async saveFasterWhisperDefaults(input) {
      const cacheDirChanged = input.cacheDir !== runtimeSettings.fasterWhisper.cacheDir;
      runtimeSettings = {
        ...runtimeSettings,
        fasterWhisper: {
          cacheDir: input.cacheDir,
          defaultModel: input.defaultModel,
          defaultDevice: input.defaultDevice,
          defaultComputeType: input.defaultComputeType,
          enabled: input.enabled
        }
      };
      runtimeModels = cacheDirChanged
        ? initialFasterWhisperModels(input.cacheDir)
        : runtimeModels.map((model) =>
            model.provider === "faster-whisper" ? { ...model, cacheDir: input.cacheDir } : model
          );
      return cloneModel(runtimeSettings);
    },
    async getRuntimeModels() {
      return cloneModel(runtimeModels);
    },
    async downloadFasterWhisperModel(input) {
      if (!fasterWhisperModelNames.includes(input.model)) {
        throw new Error(`Unsupported faster-whisper model: ${input.model}`);
      }

      let downloadedModel: RuntimeModelStatus | null = null;
      runtimeModels = runtimeModels.map((model) => {
        if (model.provider !== "faster-whisper" || model.model !== input.model) {
          return model;
        }
        const updatedModel = {
          ...model,
          present: true,
          sizeBytes: Math.max(model.sizeBytes, 10)
        };
        downloadedModel = updatedModel;
        return updatedModel;
      });

      if (downloadedModel === null) {
        downloadedModel = {
          provider: "faster-whisper",
          model: input.model,
          cacheDir: runtimeSettings.fasterWhisper.cacheDir,
          present: true,
          sizeBytes: 10,
          error: null
        };
        runtimeModels = [...runtimeModels, downloadedModel];
      }

      downloadJobSequence += 1;
      const job: RuntimeModelDownloadJob = {
        jobId: `mock_fw_download_${downloadJobSequence}`,
        provider: "faster-whisper",
        model: input.model,
        status: "completed",
        percent: 100,
        currentBytes: downloadedModel.sizeBytes,
        totalBytes: downloadedModel.sizeBytes,
        error: null,
        startedAt: new Date(0).toISOString(),
        completedAt: new Date(0).toISOString(),
        modelStatus: downloadedModel
      };
      downloadJobs.set(job.jobId, cloneModel(job));
      return cloneModel(job);
    },
    async getFasterWhisperModelDownload(jobId) {
      const job = downloadJobs.get(jobId);
      if (!job) {
        throw new Error(`Unknown faster-whisper model download job: ${jobId}`);
      }
      return cloneModel(job);
    },
    async getDiagnostics() {
      return cloneModel(diagnostics);
    },
    async updateSegmentText(input) {
      reviewState = {
        ...reviewState,
        segments: reviewState.segments.map((segment) =>
          segment.id === input.segmentId
            ? {
                ...segment,
                transcript: input.transcript,
                translation: input.translation,
                savedState: "saved"
              }
            : segment
        )
      };
      return undefined;
    },
    async retryCheckpoint() {
      return undefined;
    }
  };
}
