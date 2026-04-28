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

  it("adds fetch source for remote URLs", () => {
    const steps = workflowTemplateForSource({ kind: "remote_url", url: "https://example.test/watch" });

    expect(steps[0]).toMatchObject({ id: "fetch_source", toolRef: "source.fetch_remote" });
    expect(findParam(steps, "fetch_source", "url")).toMatchObject({ value: "https://example.test/watch" });
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
        target_lang: "zh"
      }
    });
    expect(request.body).not.toHaveProperty("provider");
    expect(request.body).not.toHaveProperty("model");
    expect(request.body).not.toHaveProperty("asr_model");
    expect(request.body).not.toHaveProperty("asr_device");
    expect(request.body).not.toHaveProperty("asr_compute_type");
  });

  it("maps remote workflow parameters to the YouTube quickstart request", () => {
    const steps = workflowTemplateForSource({ kind: "remote_url", url: "https://example.test/watch" });
    const request = buildQuickstartRequest({ kind: "remote_url", url: "https://example.test/watch" }, steps);

    expect(request.route).toBe("/quickstart/subtitle/youtube");
    expect(request.body).toMatchObject({
      url: "https://example.test/watch",
      source_lang: "en",
      target_lang: "zh",
      quality: "best[ext=mp4][height<=720]/best[height<=720]/best",
      auth: "auto"
    });
    expect(request.body).not.toHaveProperty("provider");
    expect(request.body).not.toHaveProperty("model");
    expect(request.body).not.toHaveProperty("asr_model");
    expect(request.body).not.toHaveProperty("asr_device");
    expect(request.body).not.toHaveProperty("asr_compute_type");
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
});
