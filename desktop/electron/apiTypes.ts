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

export type ApiProgressPayload = {
  phase: string;
  label: string;
  percent: number;
  current?: number | null;
  total?: number | null;
  unit?: string | null;
};

export type ApiSubtitleJobData = {
  generated_project_root: string;
  generated_config_path: string;
  workflow_id: string;
  run_id: string;
  output_path?: string | null;
  source_artifact_id?: string | null;
};

export type ApiQuickstartTaskRecord = {
  id: string;
  run_id: string;
  workflow_id: string;
  workspace_root: string;
  generated_project_root: string;
  generated_config_path: string;
  plugin_paths: string[];
  source_kind: "local_file" | "remote_url";
  source_uri: string;
  source_summary?: string | null;
  source_lang: string;
  target_lang: string;
  provider: string;
  model?: string | null;
  asr_model?: string | null;
  asr_device?: string | null;
  asr_compute_type?: string | null;
  quality?: string | null;
  auth?: string | null;
  browser?: string | null;
  browser_profile?: string | null;
  output_path?: string | null;
  source_artifact_id?: string | null;
  cache_key: string;
  status: "queued" | "running" | "paused" | "completed" | "failed" | "aborted";
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  error?: { code: string; message: string } | null;
};

export type ApiWorkflowStepParameter =
  | { kind: "text"; key: string; label: string; value: string }
  | { kind: "select"; key: string; label: string; value: string; options: string[] }
  | { kind: "toggle"; key: string; label: string; description: string; value: boolean };

export type ApiSubtitleWorkflowStep = {
  id: string;
  name: string;
  tool_ref: string;
  summary: string;
  status: "locked" | "enabled" | "disabled";
  selected?: boolean | null;
  inputs?: Record<string, string> | null;
  outputs?: Array<{ name: string; type: string }> | null;
  parameters: ApiWorkflowStepParameter[];
};

export type ApiSubtitleWorkflowTemplateData = {
  template_id: string;
  workflow_id: string;
  steps: ApiSubtitleWorkflowStep[];
};

export type ApiWorkflowToolInputSpec = {
  artifact_types: string[];
  required: boolean;
  multiple: boolean;
};

export type ApiWorkflowTool = {
  tool_ref: string;
  name: string;
  description: string;
  inputs: Record<string, ApiWorkflowToolInputSpec>;
  outputs: Array<{ name: string; type: string }>;
  parameters: ApiWorkflowStepParameter[];
};

export type ApiWorkflowToolCatalogData = {
  tools: ApiWorkflowTool[];
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

export type ApiProviderProfile = {
  name: string;
  type: "openai_compatible";
  base_url?: string | null;
  api_key?: string | null;
  default_chat_model?: string | null;
  display_name?: string | null;
  enabled?: boolean | null;
};

export type ApiProviderModel = {
  id: string;
  label?: string | null;
  owned_by?: string | null;
  context_length?: number | null;
};

export type ApiProviderConnectionTestData = {
  ok: boolean;
  message: string;
};

export type ApiRuntimeSettings = {
  version: number;
  config_path: string;
  cache: { root: string };
  defaults: { llm_provider: string; asr_provider: string };
  providers: Record<string, ApiProviderProfile>;
  models: {
    faster_whisper: {
      cache_dir: string;
      default_model: string;
      default_device: string;
      default_compute_type: string;
      enabled?: boolean | null;
    };
  };
};

export type ApiSecretCheck = {
  reference: string;
  resolved: boolean;
  display: string;
  value_preview?: string | null;
  error?: string | null;
};

export type ApiDoctorCheck = {
  id: string;
  status: string;
  severity: string;
  message: string;
};

export type ApiModelAssetStatus = {
  provider: string;
  model: string;
  cache_dir: string;
  present: boolean;
  size_bytes: number;
  error?: string | null;
};

export type ApiModelDownloadJob = {
  job_id: string;
  provider: string;
  model: string;
  status: "queued" | "running" | "completed" | "failed";
  percent: number;
  current_bytes?: number | null;
  total_bytes?: number | null;
  error?: string | null;
  started_at: string;
  completed_at?: string | null;
  model_status?: ApiModelAssetStatus | null;
};

export type ApiModelDownloadData = {
  job: ApiModelDownloadJob;
};
