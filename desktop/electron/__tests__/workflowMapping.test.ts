// @vitest-environment node
import { describe, expect, it } from "vitest";

import { buildQuickstartRequest, workflowTemplateForSource } from "../workflowMapping";
import type { WorkflowStep } from "../../src/lib/types";

const defaultSegmentParameters = {
  profile: "default",
  max_duration_seconds: 6,
  min_duration_seconds: 0.8,
  max_lines: 2,
  max_chars_per_line: 40,
  pause_threshold_ms: 500,
  prefer_sentence_boundaries: true,
  prefer_clause_boundaries: false,
  merge_short_segments: false,
  protect_terms: true
};

function findParam(steps: WorkflowStep[], stepId: string, key: string) {
  return steps.find((step) => step.id === stepId)?.parameters.find((parameter) => parameter.key === key);
}

describe("workflowTemplateForSource", () => {
  it("returns a local subtitle template for local files", () => {
    const steps = workflowTemplateForSource({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" });

    expect(steps[0]).toMatchObject({ id: "extract_audio", status: "locked" });
    expect(findParam(steps, "translate", "target_lang")).toMatchObject({ value: "zh" });
  });

  it("adds the backend download step for remote URLs", () => {
    const steps = workflowTemplateForSource({ kind: "remote_url", url: "https://example.test/watch" });

    expect(steps[0]).toMatchObject({ id: "download", toolRef: "remote_video.download" });
    expect(findParam(steps, "download", "url")).toMatchObject({ value: "https://example.test/watch" });
  });
});

describe("buildQuickstartRequest", () => {
  it("maps local workflow parameters to the local quickstart request", () => {
    const steps = workflowTemplateForSource({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" });
    const request = buildQuickstartRequest({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }, steps);

    expect(request).toEqual({
      route: "/quickstart/subtitle/local",
      body: {
        input_path: "C:/video/sample.mp4",
        source_lang: "en",
        target_lang: "zh",
        asr_model: "base",
        asr_device: "cpu",
        asr_compute_type: "int8",
        correct_transcript: true,
        segment_parameters: defaultSegmentParameters,
        step_order: ["extract_audio", "transcribe", "correct", "segment", "translate", "subtitle"],
        extra_steps: []
      }
    });
    expect(request.body).not.toHaveProperty("provider");
    expect(request.body).not.toHaveProperty("model");
  });

  it("maps remote workflow parameters to the YouTube quickstart request", () => {
    const steps = workflowTemplateForSource({ kind: "remote_url", url: "https://example.test/watch" }).map((step) =>
      step.id === "download"
        ? {
            ...step,
            parameters: step.parameters.map((parameter) =>
              parameter.key === "quality"
                ? { ...parameter, value: "bestvideo" }
                : parameter.key === "auth"
                  ? { ...parameter, value: "browser" }
                  : parameter
            )
          }
        : step
    );
    const request = buildQuickstartRequest({ kind: "remote_url", url: "https://example.test/watch" }, steps);

    expect(request.route).toBe("/quickstart/subtitle/youtube");
    expect(request.body).toMatchObject({
      url: "https://example.test/watch",
      source_lang: "en",
      target_lang: "zh",
      asr_model: "base",
      asr_device: "cpu",
      asr_compute_type: "int8",
      correct_transcript: true,
      segment_parameters: defaultSegmentParameters,
      step_order: ["download", "extract_audio", "transcribe", "correct", "segment", "translate", "subtitle"],
      quality: "bestvideo",
      auth: "browser"
    });
    expect(request.body).not.toHaveProperty("provider");
    expect(request.body).not.toHaveProperty("model");
  });

  it("uses edited workflow parameters", () => {
    const steps = workflowTemplateForSource({ kind: "remote_url", url: "https://example.test/watch" }).map((step) =>
      step.id === "translate"
        ? {
            ...step,
            parameters: step.parameters.map((parameter) =>
              parameter.key === "target_lang" && parameter.kind === "text" ? { ...parameter, value: "ja" } : parameter
            )
          }
        : step
    );

    expect(buildQuickstartRequest({ kind: "remote_url", url: "https://example.test/watch" }, steps).body).toMatchObject({
      target_lang: "ja"
    });
  });

  it("uses edited segment parameters", () => {
    const steps = workflowTemplateForSource({ kind: "remote_url", url: "https://example.test/watch" }).map((step) =>
      step.id === "segment"
        ? {
            ...step,
            parameters: step.parameters.map((parameter) =>
              parameter.key === "merge_short_segments" && parameter.kind === "toggle"
                ? { ...parameter, value: true }
                : parameter.key === "max_chars_per_line" && parameter.kind === "text"
                  ? { ...parameter, value: "30" }
                  : parameter
            )
          }
        : step
    );

    expect(buildQuickstartRequest({ kind: "remote_url", url: "https://example.test/watch" }, steps).body).toMatchObject({
      segment_parameters: {
        merge_short_segments: true,
        max_chars_per_line: 30
      }
    });
  });

  it("passes disabled correction through to quickstart requests", () => {
    const steps = workflowTemplateForSource({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }).map((step) =>
      step.id === "correct" ? { ...step, status: "disabled" as const } : step
    );

    expect(buildQuickstartRequest({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }, steps).body).toMatchObject({
      correct_transcript: false
    });
  });

  it("passes user-added steps through as extra quickstart steps", () => {
    const steps: WorkflowStep[] = [
      ...workflowTemplateForSource({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }),
      {
        id: "translation_qa",
        name: "Translation QA",
        toolRef: "translation.qa",
        summary: "translation -> translation qa",
        status: "enabled",
        inputs: { translation: "translate.translation" },
        outputs: [{ name: "qa", type: "translation_qa" }],
        parameters: [{ kind: "text", key: "max_lines", label: "Max lines", value: "2" }]
      }
    ];

    expect(buildQuickstartRequest({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }, steps).body).toMatchObject({
      extra_steps: [
        {
          id: "translation_qa",
          name: "Translation QA",
          tool_ref: "translation.qa",
          inputs: { translation: "translate.translation" },
          outputs: [{ name: "qa", type: "translation_qa" }],
          parameters: { max_lines: 2 }
        }
      ],
      step_order: [
        "extract_audio",
        "transcribe",
        "correct",
        "segment",
        "translate",
        "subtitle",
        "translation_qa"
      ]
    });
  });
});
