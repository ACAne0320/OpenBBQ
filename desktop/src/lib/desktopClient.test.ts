import { describe, expect, it, vi } from "vitest";

import { createDesktopClient } from "./desktopClient";
import { workflowSteps } from "./mockData";

describe("createDesktopClient", () => {
  it("forwards calls to the preload API", async () => {
    const api = {
      chooseLocalMedia: vi.fn().mockResolvedValue({ kind: "local_file", path: "C:/video/sample.mp4", displayName: "sample.mp4" }),
      listWorkflowDefinitions: vi.fn().mockResolvedValue([
        {
          id: "local-subtitle",
          name: "Local video -> translated SRT",
          description: "Local workflow",
          origin: "built_in",
          sourceTypes: ["local_file"],
          resultTypes: ["subtitle"],
          steps: workflowSteps
        }
      ]),
      saveWorkflowDefinition: vi.fn().mockResolvedValue({
        id: "local-subtitle-custom",
        name: "Local custom",
        description: "Custom workflow",
        origin: "custom",
        sourceTypes: ["local_file"],
        resultTypes: ["subtitle"],
        steps: workflowSteps,
        updatedAt: "2026-04-30T00:00:00.000Z"
      }),
      getRemoteVideoFormats: vi.fn().mockResolvedValue([{ value: "best", label: "Best available" }]),
      getWorkflowTemplate: vi.fn().mockResolvedValue(workflowSteps),
      getWorkflowTools: vi.fn().mockResolvedValue([]),
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
          defaultComputeType: "int8",
          enabled: true
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
          defaultComputeType: "int8",
          enabled: true
        }
      }),
      saveLlmProvider: vi.fn().mockResolvedValue({
        name: "openai-compatible",
        type: "openai_compatible",
        baseUrl: null,
        apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
        defaultChatModel: "gpt-4o-mini",
        displayName: null,
        enabled: true
      }),
      checkLlmProvider: vi.fn().mockResolvedValue({
        reference: "env:OPENBBQ_LLM_API_KEY",
        resolved: true,
        display: "env:OPENBBQ_LLM_API_KEY",
        valuePreview: "sk-...",
        error: null
      }),
      getLlmProviderSecret: vi.fn().mockResolvedValue("sk-test"),
      getLlmProviderModels: vi.fn().mockResolvedValue([
        { id: "gpt-4o-mini", label: null, ownedBy: "openai", contextLength: null }
      ]),
      testLlmProviderConnection: vi.fn().mockResolvedValue({
        ok: true,
        message: "Connection test succeeded."
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
          defaultComputeType: "int8",
          enabled: true
        }
      }),
      getRuntimeModels: vi.fn().mockResolvedValue([
        {
          provider: "faster-whisper",
          model: "base",
          cacheDir: "cache/models/faster-whisper",
          present: false,
          sizeBytes: 0,
          error: null
        }
      ]),
      downloadFasterWhisperModel: vi.fn().mockResolvedValue({
        jobId: "job_1",
        provider: "faster-whisper",
        model: "small",
        status: "running",
        percent: 30,
        currentBytes: 30,
        totalBytes: 100,
        error: null,
        startedAt: "2026-04-28T10:00:00.000Z",
        completedAt: null,
        modelStatus: null
      }),
      getFasterWhisperModelDownload: vi.fn().mockResolvedValue({
        jobId: "job_1",
        provider: "faster-whisper",
        model: "small",
        status: "completed",
        percent: 100,
        currentBytes: 100,
        totalBytes: 100,
        error: null,
        startedAt: "2026-04-28T10:00:00.000Z",
        completedAt: "2026-04-28T10:01:00.000Z",
        modelStatus: {
          provider: "faster-whisper",
          model: "small",
          cacheDir: "cache/models/faster-whisper",
          present: true,
          sizeBytes: 10,
          error: null
        }
      }),
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
    await expect(client.listWorkflowDefinitions()).resolves.toHaveLength(1);
    await expect(
      client.saveWorkflowDefinition({
        id: "local-subtitle-custom",
        name: "Local custom",
        description: "Custom workflow",
        sourceTypes: ["local_file"],
        resultTypes: ["subtitle"],
        steps: workflowSteps
      })
    ).resolves.toMatchObject({ origin: "custom" });
    expect(api.listWorkflowDefinitions).toHaveBeenCalled();
    expect(api.saveWorkflowDefinition).toHaveBeenCalled();
    await expect(
      client.getRemoteVideoFormats({ url: "https://example.test/watch", auth: "auto" })
    ).resolves.toEqual([{ value: "best", label: "Best available" }]);
    expect(api.getRemoteVideoFormats).toHaveBeenCalledWith({ url: "https://example.test/watch", auth: "auto" });
    await expect(client.getWorkflowTools()).resolves.toEqual([]);
    expect(api.getWorkflowTools).toHaveBeenCalled();
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
      displayName: null,
      enabled: true
    });
    await client.checkLlmProvider("openai-compatible");
    await client.getLlmProviderSecret("openai-compatible");
    await client.getLlmProviderModels("openai-compatible");
    await client.testLlmProviderConnection({
      providerName: "openai-compatible",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "sk-test",
      model: "gpt-4o-mini"
    });
    await client.saveFasterWhisperDefaults({
      cacheDir: "C:/models/fw",
      defaultModel: "small",
      defaultDevice: "cpu",
      defaultComputeType: "int8",
      enabled: true
    });
    await client.getRuntimeModels();
    await client.downloadFasterWhisperModel({ model: "small" });
    await client.getFasterWhisperModelDownload("job_1");
    await client.getDiagnostics();
    expect(api.saveRuntimeDefaults).toHaveBeenCalled();
    expect(api.saveLlmProvider).toHaveBeenCalled();
    expect(api.checkLlmProvider).toHaveBeenCalledWith("openai-compatible");
    expect(api.getLlmProviderSecret).toHaveBeenCalledWith("openai-compatible");
    expect(api.getLlmProviderModels).toHaveBeenCalledWith("openai-compatible");
    expect(api.testLlmProviderConnection).toHaveBeenCalled();
    expect(api.saveFasterWhisperDefaults).toHaveBeenCalled();
    expect(api.getRuntimeModels).toHaveBeenCalled();
    expect(api.downloadFasterWhisperModel).toHaveBeenCalledWith({ model: "small" });
    expect(api.getFasterWhisperModelDownload).toHaveBeenCalledWith("job_1");
    expect(api.getDiagnostics).toHaveBeenCalled();
  });
});
