import type {
  LocalMediaSelection,
  DiagnosticCheck,
  DownloadFasterWhisperModelInput,
  LlmProviderModel,
  ProviderConnectionTestInput,
  ProviderConnectionTestResult,
  ProviderModelOption,
  RemoteVideoFormatInput,
  RuntimeModelDownloadJob,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SaveFasterWhisperDefaultsInput,
  SaveLlmProviderInput,
  SaveRuntimeDefaultsInput,
  SaveWorkflowDefinitionInput,
  ReviewModel,
  SecretStatus,
  SelectOption,
  SourceDraft,
  StartSubtitleTaskInput,
  StartSubtitleTaskResult,
  TaskSummary,
  TaskMonitorModel,
  WorkflowDefinition,
  WorkflowTool,
  WorkflowStep
} from "./lib/types";

export type OpenBBQDesktopApi = {
  chooseLocalMedia(): Promise<LocalMediaSelection | null>;
  listWorkflowDefinitions(): Promise<WorkflowDefinition[]>;
  saveWorkflowDefinition(input: SaveWorkflowDefinitionInput): Promise<WorkflowDefinition>;
  getRemoteVideoFormats(input: RemoteVideoFormatInput): Promise<SelectOption[]>;
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
  updateSegmentText(input: { segmentId: string; transcript: string; translation: string }): Promise<void>;
  retryCheckpoint(runId: string): Promise<void>;
};

declare global {
  interface Window {
    openbbq?: OpenBBQDesktopApi;
  }
}
