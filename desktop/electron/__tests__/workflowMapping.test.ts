// @vitest-environment node
import { describe, expect, it } from "vitest";

import { buildQuickstartRequest, workflowTemplateForSource } from "../workflowMapping";
import type { WorkflowStep } from "../../src/lib/types";

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
        correct_transcript: true
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

  it("passes disabled correction through to quickstart requests", () => {
    const steps = workflowTemplateForSource({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }).map((step) =>
      step.id === "correct" ? { ...step, status: "disabled" as const } : step
    );

    expect(buildQuickstartRequest({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }, steps).body).toMatchObject({
      correct_transcript: false
    });
  });
});
