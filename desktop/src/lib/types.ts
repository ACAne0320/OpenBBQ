export type SourceKind = "local_file" | "remote_url";

export type SourceDraft =
  | { kind: "local_file"; path: string; displayName: string }
  | { kind: "remote_url"; url: string };

export type StartSubtitleTaskInput = {
  source: SourceDraft;
  steps: WorkflowStep[];
};

export type StartSubtitleTaskResult = {
  runId: string;
};

export type WorkflowOutput = {
  name: string;
  type: string;
};

export type WorkflowInputSpec = {
  artifactTypes: string[];
  required: boolean;
  multiple: boolean;
};

export type WorkflowTool = {
  toolRef: string;
  name: string;
  description: string;
  inputs: Record<string, WorkflowInputSpec>;
  outputs: WorkflowOutput[];
  parameters: StepParameter[];
};

export type LocalMediaSelection = Extract<SourceDraft, { kind: "local_file" }>;

export type StepStatus = "locked" | "enabled" | "disabled";

export type WorkflowStep = {
  id: string;
  name: string;
  toolRef: string;
  summary: string;
  status: StepStatus;
  selected?: boolean;
  inputs?: Record<string, string>;
  outputs?: WorkflowOutput[];
  parameters: StepParameter[];
};

export type WorkflowDefinition = {
  id: string;
  name: string;
  description: string;
  origin: "built_in" | "custom";
  sourceTypes: SourceKind[];
  resultTypes: string[];
  steps: WorkflowStep[];
  updatedAt?: string | null;
};

export type SaveWorkflowDefinitionInput = {
  id: string;
  name: string;
  description: string;
  sourceTypes: SourceKind[];
  resultTypes: string[];
  steps: WorkflowStep[];
};

export type SelectOption = string | { value: string; label: string };

export type RemoteVideoFormatInput = {
  url: string;
  auth: "auto" | "anonymous" | "browser_cookies";
  browser?: string | null;
  browserProfile?: string | null;
};

export type StepParameter =
  | { kind: "text"; key: string; label: string; value: string }
  | { kind: "select"; key: string; label: string; value: string; options: SelectOption[] }
  | { kind: "toggle"; key: string; label: string; description: string; value: boolean };

export type TaskStatus = "queued" | "running" | "paused" | "failed" | "completed" | "aborted";

export type TaskSummary = {
  id: string;
  title: string;
  workflowName: string;
  sourceKind: SourceKind;
  sourceUri: string;
  sourceSummary: string;
  status: TaskStatus;
  createdAt: string;
  updatedAt: string;
};

export type ProgressStep = {
  id: string;
  label: string;
  status: "done" | "running" | "failed" | "blocked";
};

export type RuntimeLogLine = {
  sequence: number;
  timestamp: string;
  level: "info" | "warning" | "error";
  message: string;
};

export type ProgressPercent = {
  phase: string;
  label: string;
  percent: number;
  current?: number | null;
  total?: number | null;
  unit?: string | null;
};

export type TaskProgressLogLine = ProgressPercent & {
  sequence: number;
  timestamp: string;
  stepId: string;
  attempt?: number | null;
};

export type TaskMonitorModel = {
  id: string;
  title: string;
  workflowName: string;
  status: TaskStatus;
  progress: ProgressStep[];
  progressLogs: TaskProgressLogLine[];
  logs: RuntimeLogLine[];
  errorMessage?: string;
};

export type Segment = {
  id: string;
  index: number;
  startMs: number;
  endMs: number;
  transcript: string;
  translation: string;
  savedState: "saved" | "saving" | "error";
};

export type WaveformBar = {
  id: string;
  level: number;
};

export type ReviewModel = {
  title: string;
  durationMs: number;
  currentMs: number;
  activeSegmentId: string;
  videoSrc?: string;
  subtitleText?: string;
  waveform: WaveformBar[];
  waveformSource: "audio_loudness" | "placeholder";
  segments: Segment[];
};

export type RuntimeSettingsModel = {
  configPath: string;
  cacheRoot: string;
  defaults: { llmProvider: string; asrProvider: string };
  llmProviders: LlmProviderModel[];
  fasterWhisper: FasterWhisperSettingsModel;
};

export type LlmProviderModel = {
  name: string;
  type: "openai_compatible";
  baseUrl: string | null;
  apiKeyRef: string | null;
  defaultChatModel: string | null;
  displayName: string | null;
  enabled: boolean;
};

export type ProviderModelOption = {
  id: string;
  label: string | null;
  ownedBy: string | null;
  contextLength: number | null;
};

export type FasterWhisperSettingsModel = {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
  enabled: boolean;
};

export type RuntimeModelStatus = {
  provider: string;
  model: string;
  cacheDir: string;
  present: boolean;
  sizeBytes: number;
  error: string | null;
};

export type RuntimeModelDownloadJob = {
  jobId: string;
  provider: string;
  model: string;
  status: "queued" | "running" | "completed" | "failed";
  percent: number;
  currentBytes?: number | null;
  totalBytes?: number | null;
  error?: string | null;
  startedAt: string;
  completedAt?: string | null;
  modelStatus?: RuntimeModelStatus | null;
};

export type DownloadFasterWhisperModelInput = {
  model: string;
};

export type SecretStatus = {
  reference: string;
  resolved: boolean;
  display: string;
  valuePreview: string | null;
  error: string | null;
};

export type ProviderConnectionTestInput = {
  providerName?: string | null;
  baseUrl: string;
  apiKey: string | null;
  model: string;
};

export type ProviderConnectionTestResult = {
  ok: boolean;
  message: string;
};

export type DiagnosticCheck = {
  id: string;
  status: string;
  severity: string;
  message: string;
};

export type SaveRuntimeDefaultsInput = {
  llmProvider: string;
  asrProvider: string;
};

export type SaveLlmProviderInput = {
  name: string;
  type: "openai_compatible";
  baseUrl: string | null;
  defaultChatModel: string | null;
  secretValue: string | null;
  apiKeyRef: string | null;
  displayName: string | null;
  enabled: boolean;
};

export type SaveFasterWhisperDefaultsInput = {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
  enabled: boolean;
};
