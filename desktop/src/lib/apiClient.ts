import { failedTask, reviewModel, workflowSteps } from "./mockData";
import type {
  DiagnosticCheck,
  LlmProviderModel,
  LocalMediaSelection,
  ReviewModel,
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
  WorkflowStep
} from "./types";

export type OpenBBQClient = {
  chooseLocalMedia?(): Promise<LocalMediaSelection | null>;
  getWorkflowTemplate(source: SourceDraft): Promise<WorkflowStep[]>;
  startSubtitleTask(input: StartSubtitleTaskInput): Promise<StartSubtitleTaskResult>;
  listTasks(): Promise<TaskSummary[]>;
  getTaskMonitor(runId: string): Promise<TaskMonitorModel>;
  getReview(runId: string): Promise<ReviewModel>;
  getRuntimeSettings(): Promise<RuntimeSettingsModel>;
  saveRuntimeDefaults(input: SaveRuntimeDefaultsInput): Promise<RuntimeSettingsModel>;
  saveLlmProvider(input: SaveLlmProviderInput): Promise<LlmProviderModel>;
  checkLlmProvider(name: string): Promise<SecretStatus>;
  saveFasterWhisperDefaults(input: SaveFasterWhisperDefaultsInput): Promise<RuntimeSettingsModel>;
  getRuntimeModels(): Promise<RuntimeModelStatus[]>;
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

function remoteFetchStep(source: Extract<SourceDraft, { kind: "remote_url" }>): WorkflowStep {
  const parameters: StepParameter[] = [{ kind: "text", key: "url", label: "URL", value: source.url }];

  return {
    id: "fetch_source",
    name: "Fetch Source",
    toolRef: "source.fetch_remote",
    summary: "url -> local media",
    status: "locked",
    parameters
  };
}

function workflowTemplateForSource(source: SourceDraft): WorkflowStep[] {
  if (source.kind === "remote_url") {
    return [remoteFetchStep(source), ...workflowSteps];
  }

  return workflowSteps;
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
        displayName: "OpenAI-compatible"
      }
    ],
    fasterWhisper: {
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      defaultModel: "base",
      defaultDevice: "cpu",
      defaultComputeType: "int8"
    }
  };
  let runtimeModels: RuntimeModelStatus[] = [
    {
      provider: "faster_whisper",
      model: "base",
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      present: false,
      sizeBytes: 0,
      error: null
    }
  ];
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
        displayName: input.displayName
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
    async saveFasterWhisperDefaults(input) {
      runtimeSettings = {
        ...runtimeSettings,
        fasterWhisper: {
          cacheDir: input.cacheDir,
          defaultModel: input.defaultModel,
          defaultDevice: input.defaultDevice,
          defaultComputeType: input.defaultComputeType
        }
      };
      runtimeModels = runtimeModels.map((model) =>
        model.provider === "faster_whisper"
          ? { ...model, model: input.defaultModel, cacheDir: input.cacheDir }
          : model
      );
      return cloneModel(runtimeSettings);
    },
    async getRuntimeModels() {
      return cloneModel(runtimeModels);
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
