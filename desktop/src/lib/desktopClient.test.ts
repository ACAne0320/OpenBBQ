import { describe, expect, it, vi } from "vitest";

import { createDesktopClient } from "./desktopClient";
import { workflowSteps } from "./mockData";

describe("createDesktopClient", () => {
  it("forwards calls to the preload API", async () => {
    const api = {
      chooseLocalMedia: vi.fn().mockResolvedValue({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }),
      getWorkflowTemplate: vi.fn().mockResolvedValue(workflowSteps),
      startSubtitleTask: vi.fn().mockResolvedValue({ runId: "run_1" }),
      listTasks: vi.fn().mockResolvedValue([]),
      getTaskMonitor: vi.fn(),
      getReview: vi.fn(),
      updateSegmentText: vi.fn(),
      retryCheckpoint: vi.fn(),
      getRuntimeSettings: vi.fn().mockResolvedValue({
        configPath: "config.toml",
        cacheRoot: "cache",
        defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
        llmProviders: [],
        fasterWhisper: {
          cacheDir: "cache/models/faster-whisper",
          defaultModel: "base",
          defaultDevice: "cpu",
          defaultComputeType: "int8"
        }
      }),
      saveRuntimeDefaults: vi.fn().mockResolvedValue({
        configPath: "config.toml",
        cacheRoot: "cache",
        defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
        llmProviders: [],
        fasterWhisper: {
          cacheDir: "cache/models/faster-whisper",
          defaultModel: "base",
          defaultDevice: "cpu",
          defaultComputeType: "int8"
        }
      }),
      saveLlmProvider: vi.fn().mockResolvedValue({
        name: "openai-compatible",
        type: "openai_compatible",
        baseUrl: null,
        apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
        defaultChatModel: "gpt-4o-mini",
        displayName: null
      }),
      checkLlmProvider: vi.fn().mockResolvedValue({
        reference: "env:OPENBBQ_LLM_API_KEY",
        resolved: true,
        display: "env:OPENBBQ_LLM_API_KEY",
        valuePreview: "sk-...",
        error: null
      }),
      saveFasterWhisperDefaults: vi.fn().mockResolvedValue({
        configPath: "config.toml",
        cacheRoot: "cache",
        defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
        llmProviders: [],
        fasterWhisper: {
          cacheDir: "C:/models/fw",
          defaultModel: "small",
          defaultDevice: "cpu",
          defaultComputeType: "int8"
        }
      }),
      getRuntimeModels: vi.fn().mockResolvedValue([
        {
          provider: "faster_whisper",
          model: "base",
          cacheDir: "cache/models/faster-whisper",
          present: false,
          sizeBytes: 0,
          error: null
        }
      ]),
      getDiagnostics: vi.fn().mockResolvedValue([{ id: "runtime", status: "ok", severity: "info", message: "Ready" }])
    };
    const client = createDesktopClient(api);

    await expect(client.chooseLocalMedia?.()).resolves.toMatchObject({ displayName: "sample.mp4" });
    await expect(
      client.startSubtitleTask({
        source: { kind: "remote_url", url: "https://example.test/watch" },
        steps: workflowSteps
      })
    ).resolves.toEqual({ runId: "run_1" });
    expect(api.startSubtitleTask).toHaveBeenCalled();
    await expect(client.listTasks()).resolves.toEqual([]);
    expect(api.listTasks).toHaveBeenCalled();
    await expect(client.getRuntimeSettings()).resolves.toMatchObject({
      defaults: { llmProvider: "openai-compatible" }
    });
    await client.saveRuntimeDefaults({ llmProvider: "openai-compatible", asrProvider: "faster-whisper" });
    await client.saveLlmProvider({
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: null,
      defaultChatModel: "gpt-4o-mini",
      secretValue: null,
      apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
      displayName: null
    });
    await client.checkLlmProvider("openai-compatible");
    await client.saveFasterWhisperDefaults({
      cacheDir: "C:/models/fw",
      defaultModel: "small",
      defaultDevice: "cpu",
      defaultComputeType: "int8"
    });
    await client.getRuntimeModels();
    await client.getDiagnostics();
    expect(api.saveRuntimeDefaults).toHaveBeenCalled();
    expect(api.saveLlmProvider).toHaveBeenCalled();
    expect(api.checkLlmProvider).toHaveBeenCalledWith("openai-compatible");
    expect(api.saveFasterWhisperDefaults).toHaveBeenCalled();
    expect(api.getRuntimeModels).toHaveBeenCalled();
    expect(api.getDiagnostics).toHaveBeenCalled();
  });
});
