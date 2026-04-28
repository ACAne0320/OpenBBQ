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

export type LocalMediaSelection = Extract<SourceDraft, { kind: "local_file" }>;

export type StepStatus = "locked" | "enabled" | "disabled";

export type WorkflowStep = {
  id: string;
  name: string;
  toolRef: string;
  summary: string;
  status: StepStatus;
  selected?: boolean;
  parameters: StepParameter[];
};

export type StepParameter =
  | { kind: "text"; key: string; label: string; value: string }
  | { kind: "select"; key: string; label: string; value: string; options: string[] }
  | { kind: "toggle"; key: string; label: string; description: string; value: boolean };

export type TaskStatus = "queued" | "running" | "paused" | "failed" | "completed" | "aborted";

export type TaskSummary = {
  id: string;
  title: string;
  workflowName: string;
  sourceSummary: string;
  status: TaskStatus;
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
};

export type FasterWhisperSettingsModel = {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
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
};

export type SaveFasterWhisperDefaultsInput = {
  cacheDir: string;
  defaultModel: string;
  defaultDevice: string;
  defaultComputeType: string;
};
