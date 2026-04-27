export type ApiSuccess<T> = {
  ok: true;
  data: T;
};

export type ApiErrorEnvelope = {
  ok: false;
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
};

export type ApiEnvelope<T> = ApiSuccess<T> | ApiErrorEnvelope;

export type ApiRunRecord = {
  id: string;
  workflow_id: string;
  mode: "start" | "resume" | "step_rerun" | "force_rerun";
  status: "queued" | "running" | "paused" | "completed" | "failed" | "aborted";
  project_root: string;
  config_path?: string | null;
  plugin_paths: string[];
  started_at?: string | null;
  completed_at?: string | null;
  latest_event_sequence: number;
  error?: { code: string; message: string } | null;
  created_by: "api" | "cli" | "desktop";
};

export type ApiWorkflowEvent = {
  id: string;
  workflow_id: string;
  sequence: number;
  type: string;
  level: "debug" | "info" | "warning" | "error";
  message?: string | null;
  data: Record<string, unknown>;
  created_at: string;
  step_id?: string | null;
  attempt?: number | null;
};

export type ApiSubtitleJobData = {
  generated_project_root: string;
  generated_config_path: string;
  workflow_id: string;
  run_id: string;
  output_path?: string | null;
  source_artifact_id?: string | null;
};

export type ApiArtifactRecord = {
  id: string;
  type: string;
  name: string;
  versions: string[];
  current_version_id?: string | null;
  created_by_step_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type ApiArtifactPreviewData = {
  version: {
    id: string;
    artifact_id: string;
    version_number: number;
    content_path: string;
    content_hash: string;
    content_encoding: "text" | "json" | "bytes" | "file";
    content_size: number;
    metadata: Record<string, unknown>;
    lineage: Record<string, unknown>;
    created_at: string;
  };
  content: unknown;
  truncated: boolean;
  content_encoding: string;
  content_size: number;
};
