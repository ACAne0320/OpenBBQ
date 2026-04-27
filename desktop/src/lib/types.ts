export type SourceKind = "local_file" | "remote_url";

export type SourceDraft =
  | { kind: "local_file"; path: string; displayName: string }
  | { kind: "remote_url"; url: string };

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

export type TaskMonitorModel = {
  id: string;
  title: string;
  workflowName: string;
  status: TaskStatus;
  progress: ProgressStep[];
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
  waveform: WaveformBar[];
  segments: Segment[];
};
