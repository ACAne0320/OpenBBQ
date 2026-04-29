import { workflowSteps } from "../src/lib/mockData.js";
import type { SourceDraft, WorkflowStep } from "../src/lib/types.js";

export type QuickstartRequest =
  | {
      route: "/quickstart/subtitle/local";
      body: {
        input_path: string;
        source_lang: string;
        target_lang: string;
        asr_model: string;
        asr_device: string;
        asr_compute_type: string;
        correct_transcript: boolean;
      };
    }
  | {
      route: "/quickstart/subtitle/youtube";
      body: {
        url: string;
        source_lang: string;
        target_lang: string;
        asr_model: string;
        asr_device: string;
        asr_compute_type: string;
        correct_transcript: boolean;
        quality: string;
        auth: string;
        browser: string | null;
        browser_profile: string | null;
      };
    };

function cloneSteps(steps: WorkflowStep[]): WorkflowStep[] {
  return JSON.parse(JSON.stringify(steps)) as WorkflowStep[];
}

function remoteDownloadStep(source: Extract<SourceDraft, { kind: "remote_url" }>): WorkflowStep {
  return {
    id: "download",
    name: "Download Video",
    toolRef: "remote_video.download",
    summary: "url -> video",
    status: "locked",
    parameters: [
      { kind: "text", key: "url", label: "URL", value: source.url },
      {
        kind: "text",
        key: "quality",
        label: "Quality",
        value: "best[ext=mp4][height<=720]/best[height<=720]/best"
      },
      { kind: "text", key: "auth", label: "Auth", value: "auto" }
    ]
  };
}

export function workflowTemplateForSource(source: SourceDraft): WorkflowStep[] {
  const steps = cloneSteps(workflowSteps);
  if (source.kind === "remote_url") {
    return [remoteDownloadStep(source), ...steps];
  }

  return steps;
}

function parameterValue(steps: WorkflowStep[], stepId: string, key: string, fallback: string): string {
  const parameter = steps.find((step) => step.id === stepId)?.parameters.find((item) => item.key === key);
  if (!parameter) {
    return fallback;
  }

  if (parameter.kind === "toggle") {
    return parameter.value ? "true" : "false";
  }

  return parameter.value.trim() || fallback;
}

function optionalParameterValue(steps: WorkflowStep[], stepId: string, key: string): string | null {
  const value = parameterValue(steps, stepId, key, "").trim();
  return value.length > 0 ? value : null;
}

function languageCode(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "english") {
    return "en";
  }
  if (normalized === "chinese" || normalized === "zh-cn") {
    return "zh";
  }
  return normalized || "en";
}

function enabledStep(steps: WorkflowStep[], stepId: string): WorkflowStep | undefined {
  return steps.find((step) => step.id === stepId && step.status !== "disabled");
}

export function buildQuickstartRequest(source: SourceDraft, steps: WorkflowStep[]): QuickstartRequest {
  const transcribeEnabled = enabledStep(steps, "transcribe");
  const translateEnabled = enabledStep(steps, "translate");
  if (!transcribeEnabled || !translateEnabled) {
    throw new Error("Transcribe and Translate steps are required for the first desktop integration.");
  }

  const sourceLang = languageCode(parameterValue(steps, "translate", "source_lang", parameterValue(steps, "correct", "source_lang", "en")));
  const targetLang = languageCode(parameterValue(steps, "translate", "target_lang", "zh"));
  const common = {
    source_lang: sourceLang,
    target_lang: targetLang,
    asr_model: parameterValue(steps, "transcribe", "model", "base"),
    asr_device: parameterValue(steps, "transcribe", "device", "cpu"),
    asr_compute_type: parameterValue(steps, "transcribe", "compute_type", "int8"),
    correct_transcript: enabledStep(steps, "correct") !== undefined
  };

  if (source.kind === "local_file") {
    return {
      route: "/quickstart/subtitle/local",
      body: {
        input_path: source.path,
        ...common
      }
    };
  }

  const remoteSourceStepId = steps.some((step) => step.id === "download") ? "download" : "fetch_source";
  return {
    route: "/quickstart/subtitle/youtube",
    body: {
      url: source.url,
      ...common,
      quality: parameterValue(steps, remoteSourceStepId, "quality", "best[ext=mp4][height<=720]/best[height<=720]/best"),
      auth: parameterValue(steps, remoteSourceStepId, "auth", "auto"),
      browser: optionalParameterValue(steps, remoteSourceStepId, "browser"),
      browser_profile: optionalParameterValue(steps, remoteSourceStepId, "browser_profile")
    }
  };
}
