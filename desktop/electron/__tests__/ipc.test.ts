// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ManagedSidecar } from "../sidecar";

vi.mock("electron", () => ({
  dialog: { showOpenDialog: vi.fn() },
  ipcMain: { handle: vi.fn(), removeHandler: vi.fn() }
}));

const sidecar: ManagedSidecar = {
  connection: {
    host: "127.0.0.1",
    port: 53124,
    pid: 12345,
    token: "secret",
    baseUrl: "http://127.0.0.1:53124"
  },
  stderrText: () => "",
  stop: vi.fn()
};

describe("desktop IPC actions", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("retries a run through the sidecar resume route", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { id: "run_1" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { retryCheckpoint } = await import("../ipc");

    await retryCheckpoint(sidecar, "run 1");

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runs/run%201/resume",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("lists persisted quickstart tasks through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            tasks: [
              {
                id: "task_run_1",
                run_id: "run_1",
                workflow_id: "youtube-to-srt",
                workspace_root: "/workspace",
                generated_project_root: "/workspace/.openbbq/generated/youtube-subtitle/run_1",
                generated_config_path:
                  "/workspace/.openbbq/generated/youtube-subtitle/run_1/openbbq.yaml",
                plugin_paths: [],
                source_kind: "remote_url",
                source_uri: "https://www.youtube.com/watch?v=demo",
                source_summary: "Demo video",
                source_lang: "en",
                target_lang: "zh",
                provider: "openai",
                model: "gpt-4o-mini",
                asr_model: "base",
                asr_device: "cpu",
                asr_compute_type: "int8",
                quality: "best",
                auth: "auto",
                browser: null,
                browser_profile: null,
                output_path: null,
                source_artifact_id: null,
                cache_key: "cache-1",
                status: "completed",
                created_at: "2026-04-28T00:00:00+00:00",
                updated_at: "2026-04-28T00:05:00+00:00",
                completed_at: "2026-04-28T00:05:00+00:00",
                error: null
              }
            ]
          }
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { listTasks } = await import("../ipc");

    await expect(listTasks(sidecar)).resolves.toEqual([
      {
        id: "run_1",
        title: "Demo video",
        workflowName: "Remote video -> translated SRT",
        sourceSummary: "Demo video",
        status: "completed",
        updatedAt: "2026-04-28T00:05:00+00:00"
      }
    ]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/quickstart/tasks",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("loads runtime settings through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            settings: {
              version: 1,
              config_path: "C:/Users/alex/.openbbq/config.toml",
              cache: { root: "C:/Users/alex/.cache/openbbq" },
              defaults: { llm_provider: "openai-compatible", asr_provider: "faster-whisper" },
              providers: {
                "openai-compatible": {
                  name: "openai-compatible",
                  type: "openai_compatible",
                  base_url: "http://127.0.0.1:11434/v1",
                  api_key: "env:OPENBBQ_LLM_API_KEY",
                  default_chat_model: "qwen2.5",
                  display_name: "Local gateway"
                }
              },
              models: {
                faster_whisper: {
                  cache_dir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
                  default_model: "base",
                  default_device: "cpu",
                  default_compute_type: "int8"
                }
              }
            }
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { getRuntimeSettings } = await import("../ipc");

    await expect(getRuntimeSettings(sidecar)).resolves.toMatchObject({
      configPath: "C:/Users/alex/.openbbq/config.toml",
      cacheRoot: "C:/Users/alex/.cache/openbbq",
      defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
      llmProviders: [
        {
          name: "openai-compatible",
          baseUrl: "http://127.0.0.1:11434/v1",
          apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
          defaultChatModel: "qwen2.5",
          displayName: "Local gateway"
        }
      ],
      fasterWhisper: {
        cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
        defaultModel: "base",
        defaultDevice: "cpu",
        defaultComputeType: "int8"
      }
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/settings",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("saves faster-whisper defaults through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            settings: {
              version: 1,
              config_path: "config.toml",
              cache: { root: "cache" },
              defaults: { llm_provider: "openai-compatible", asr_provider: "faster-whisper" },
              providers: {},
              models: {
                faster_whisper: {
                  cache_dir: "C:/models/fw",
                  default_model: "small",
                  default_device: "cpu",
                  default_compute_type: "int8"
                }
              }
            },
            config_path: "config.toml"
          }
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { saveFasterWhisperDefaults } = await import("../ipc");

    await expect(
      saveFasterWhisperDefaults(sidecar, {
        cacheDir: "C:/models/fw",
        defaultModel: "small",
        defaultDevice: "cpu",
        defaultComputeType: "int8"
      })
    ).resolves.toMatchObject({
      fasterWhisper: { cacheDir: "C:/models/fw", defaultModel: "small" }
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/models/faster-whisper",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          cache_dir: "C:/models/fw",
          default_model: "small",
          default_device: "cpu",
          default_compute_type: "int8"
        })
      })
    );
  });

  it("downloads a faster-whisper model through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            model: {
              provider: "faster-whisper",
              model: "small",
              cache_dir: "C:/models/fw",
              present: true,
              size_bytes: 10,
              error: null
            }
          }
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { downloadFasterWhisperModel } = await import("../ipc");

    await expect(downloadFasterWhisperModel(sidecar, { model: "small" })).resolves.toEqual({
      provider: "faster-whisper",
      model: "small",
      cacheDir: "C:/models/fw",
      present: true,
      sizeBytes: 10,
      error: null
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/models/faster-whisper/download",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ model: "small" })
      })
    );
  });
});
