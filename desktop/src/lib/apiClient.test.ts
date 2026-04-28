import { describe, expect, it } from "vitest";

import { createMockClient } from "./apiClient";

describe("createMockClient", () => {
  it("persists segment text edits for later review fetches without sharing state across clients", async () => {
    const client = createMockClient();
    const otherClient = createMockClient();

    await client.updateSegmentText({
      segmentId: "seg-03",
      transcript: "Edited transcript.",
      translation: "Edited translation."
    });

    const editedReview = await client.getReview("run_sample");
    const editedSegment = editedReview.segments.find((segment) => segment.id === "seg-03");
    expect(editedSegment).toMatchObject({
      transcript: "Edited transcript.",
      translation: "Edited translation.",
      savedState: "saved"
    });

    const untouchedReview = await otherClient.getReview("run_sample");
    expect(untouchedReview.segments.find((segment) => segment.id === "seg-03")).toMatchObject({
      transcript: "Each result is saved as an editable versioned segment.",
      translation: "Each result is saved as an editable versioned segment."
    });
  });

  it("returns cloned source-aware workflow templates", async () => {
    const client = createMockClient();

    const localWorkflow = await client.getWorkflowTemplate({
      kind: "local_file",
      path: "sample.mp4",
      displayName: "sample.mp4"
    });
    localWorkflow[0].name = "Mutated";
    localWorkflow[1].parameters[3].key = "mutated";

    const freshLocalWorkflow = await client.getWorkflowTemplate({
      kind: "local_file",
      path: "sample.mp4",
      displayName: "sample.mp4"
    });
    expect(freshLocalWorkflow[0].name).toBe("Extract Audio");
    expect(freshLocalWorkflow[1].parameters[3]).toMatchObject({ key: "compute_type" });

    const remoteWorkflow = await client.getWorkflowTemplate({
      kind: "remote_url",
      url: "https://example.test/video"
    });
    expect(remoteWorkflow[0]).toMatchObject({
      id: "fetch_source",
      toolRef: "source.fetch_remote",
      summary: "url -> local media"
    });
    expect(remoteWorkflow[1]).toMatchObject({ id: "extract_audio" });
  });

  it("returns a sample run id when starting a mock subtitle task", async () => {
    const client = createMockClient();
    await expect(
      client.startSubtitleTask({
        source: { kind: "remote_url", url: "https://example.test/video" },
        steps: await client.getWorkflowTemplate({ kind: "remote_url", url: "https://example.test/video" })
      })
    ).resolves.toEqual({ runId: "run_sample" });
  });

  it("returns completed faster-whisper download jobs and updates model presence", async () => {
    const client = createMockClient();

    const job = await client.downloadFasterWhisperModel({ model: "small" });
    expect(job).toMatchObject({
      provider: "faster-whisper",
      model: "small",
      status: "completed",
      percent: 100,
      modelStatus: {
        provider: "faster-whisper",
        model: "small",
        present: true,
        sizeBytes: 10,
        error: null
      }
    });
    await expect(client.getFasterWhisperModelDownload(job.jobId)).resolves.toMatchObject({
      jobId: job.jobId,
      status: "completed",
      percent: 100
    });

    const downloadedModels = await client.getRuntimeModels();
    expect(downloadedModels.find((model) => model.model === "small")).toMatchObject({
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      present: true,
      sizeBytes: 10,
      error: null
    });

    await client.saveFasterWhisperDefaults({
      cacheDir: "D:/openbbq/models/faster-whisper",
      defaultModel: "base",
      defaultDevice: "cpu",
      defaultComputeType: "int8"
    });

    const modelsAfterCacheChange = await client.getRuntimeModels();
    expect(modelsAfterCacheChange.find((model) => model.model === "small")).toMatchObject({
      cacheDir: "D:/openbbq/models/faster-whisper",
      present: false,
      sizeBytes: 0,
      error: null
    });
  });

  it("rejects unsupported faster-whisper model downloads", async () => {
    const client = createMockClient();

    await expect(client.downloadFasterWhisperModel({ model: "unknown-size" })).rejects.toThrow(
      "Unsupported faster-whisper model"
    );
  });
});
