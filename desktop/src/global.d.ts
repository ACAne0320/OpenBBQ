import type {
  LocalMediaSelection,
  DiagnosticCheck,
  DownloadFasterWhisperModelInput,
  LlmProviderModel,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SaveFasterWhisperDefaultsInput,
  SaveLlmProviderInput,
  SaveRuntimeDefaultsInput,
  ReviewModel,
  SecretStatus,
  SourceDraft,
  StartSubtitleTaskInput,
  StartSubtitleTaskResult,
  TaskSummary,
  TaskMonitorModel,
  WorkflowStep
} from "./lib/types";

export type OpenBBQDesktopApi = {
  chooseLocalMedia(): Promise<LocalMediaSelection | null>;
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
  downloadFasterWhisperModel(input: DownloadFasterWhisperModelInput): Promise<RuntimeModelStatus>;
  getDiagnostics(): Promise<DiagnosticCheck[]>;
  updateSegmentText(input: { segmentId: string; transcript: string; translation: string }): Promise<void>;
  retryCheckpoint(runId: string): Promise<void>;
};

declare global {
  interface Window {
    openbbq?: OpenBBQDesktopApi;
  }
}
