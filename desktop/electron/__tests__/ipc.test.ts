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

  it("retries a failed checkpoint through the sidecar retry route", async () => {
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
      "http://127.0.0.1:53124/runs/run%201/retry-checkpoint",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("loads source workflow templates through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            template_id: "youtube-subtitle",
            workflow_id: "youtube-to-srt",
            steps: [
              {
                id: "download",
                name: "Download Video",
                tool_ref: "remote_video.download",
                summary: "url -> video",
                status: "locked",
                parameters: [
                  { kind: "text", key: "url", label: "URL", value: "https://example.test/watch" },
                  {
                    kind: "select",
                    key: "quality",
                    label: "Quality",
                    value: "best",
                    options: [
                      { value: "best", label: "Best available" },
                      { value: "18", label: "18 - MP4 - 640x360 - video + audio" }
                    ]
                  }
                ]
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
    const { getWorkflowTemplate } = await import("../ipc");

    await expect(getWorkflowTemplate(sidecar, { kind: "remote_url", url: "https://example.test/watch" })).resolves.toEqual([
      {
        id: "download",
        name: "Download Video",
        toolRef: "remote_video.download",
        summary: "url -> video",
        status: "locked",
        parameters: [
          { kind: "text", key: "url", label: "URL", value: "https://example.test/watch" },
          {
            kind: "select",
            key: "quality",
            label: "Quality",
            value: "best",
            options: [
              { value: "best", label: "Best available" },
              { value: "18", label: "18 - MP4 - 640x360 - video + audio" }
            ]
          }
        ]
      }
    ]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/quickstart/subtitle/template?source_kind=remote_url&url=https%3A%2F%2Fexample.test%2Fwatch",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("loads workflow tool catalog through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            tools: [
              {
                tool_ref: "translation.qa",
                name: "Translation QA",
                description: "Check translated segments.",
                inputs: {
                  translation: {
                    artifact_types: ["translation"],
                    required: true,
                    multiple: false
                  }
                },
                outputs: [{ name: "qa", type: "translation_qa" }],
                parameters: [{ kind: "text", key: "max_lines", label: "Max lines", value: "2" }]
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
    const { getWorkflowTools } = await import("../ipc");

    await expect(getWorkflowTools(sidecar)).resolves.toEqual([
      {
        toolRef: "translation.qa",
        name: "Translation QA",
        description: "Check translated segments.",
        inputs: {
          translation: {
            artifactTypes: ["translation"],
            required: true,
            multiple: false
          }
        },
        outputs: [{ name: "qa", type: "translation_qa" }],
        parameters: [{ kind: "text", key: "max_lines", label: "Max lines", value: "2" }]
      }
    ]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/quickstart/subtitle/tools",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("lists workflow definitions through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            workflows: [
              {
                id: "youtube-subtitle",
                name: "Remote video -> translated SRT",
                description: "Remote workflow",
                origin: "built_in",
                source_types: ["remote_url"],
                result_types: ["subtitle"],
                steps: [
                  {
                    id: "download",
                    name: "Download Video",
                    tool_ref: "remote_video.download",
                    summary: "url -> video",
                    status: "locked",
                    parameters: [{ kind: "text", key: "url", label: "URL", value: "about:blank" }]
                  }
                ]
              }
            ]
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { listWorkflowDefinitions } = await import("../ipc");

    await expect(listWorkflowDefinitions(sidecar)).resolves.toEqual([
      {
        id: "youtube-subtitle",
        name: "Remote video -> translated SRT",
        description: "Remote workflow",
        origin: "built_in",
        sourceTypes: ["remote_url"],
        resultTypes: ["subtitle"],
        steps: [
          {
            id: "download",
            name: "Download Video",
            toolRef: "remote_video.download",
            summary: "url -> video",
            status: "locked",
            parameters: [{ kind: "text", key: "url", label: "URL", value: "about:blank" }]
          }
        ],
        updatedAt: null
      }
    ]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/workflow-definitions",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("saves workflow definitions through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            id: "local-subtitle-custom",
            name: "Local custom",
            description: "Custom local workflow",
            origin: "custom",
            source_types: ["local_file"],
            result_types: ["subtitle"],
            steps: [
              {
                id: "extract_audio",
                name: "Extract Audio",
                tool_ref: "ffmpeg.extract_audio",
                summary: "video -> audio",
                status: "locked",
                outputs: [{ name: "audio", type: "audio" }],
                parameters: []
              }
            ],
            updated_at: "2026-04-30T00:00:00.000Z"
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { saveWorkflowDefinition } = await import("../ipc");

    await expect(
      saveWorkflowDefinition(sidecar, {
        id: "local-subtitle-custom",
        name: "Local custom",
        description: "Custom local workflow",
        sourceTypes: ["local_file"],
        resultTypes: ["subtitle"],
        steps: [
          {
            id: "extract_audio",
            name: "Extract Audio",
            toolRef: "ffmpeg.extract_audio",
            summary: "video -> audio",
            status: "locked",
            outputs: [{ name: "audio", type: "audio" }],
            parameters: []
          }
        ]
      })
    ).resolves.toMatchObject({ id: "local-subtitle-custom", origin: "custom" });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/workflow-definitions/local-subtitle-custom",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          id: "local-subtitle-custom",
          name: "Local custom",
          description: "Custom local workflow",
          source_types: ["local_file"],
          result_types: ["subtitle"],
          steps: [
            {
              id: "extract_audio",
              name: "Extract Audio",
              tool_ref: "ffmpeg.extract_audio",
              summary: "video -> audio",
              status: "locked",
              selected: null,
              inputs: null,
              outputs: [{ name: "audio", type: "audio" }],
              parameters: []
            }
          ]
        })
      })
    );
  });

  it("loads remote video format options through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            formats: [
              { value: "18", label: "18 - MP4 - 640x360 - video + audio" },
              { value: "best", label: "Best available" }
            ]
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { getRemoteVideoFormats } = await import("../ipc");

    await expect(
      getRemoteVideoFormats(sidecar, {
        url: "https://example.test/watch",
        auth: "browser_cookies",
        browser: "edge",
        browserProfile: "Default"
      })
    ).resolves.toEqual([
      { value: "18", label: "18 - MP4 - 640x360 - video + audio" },
      { value: "best", label: "Best available" }
    ]);

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/quickstart/remote-video/formats?url=https%3A%2F%2Fexample.test%2Fwatch&auth=browser_cookies&browser=edge&browser_profile=Default",
      expect.objectContaining({ method: "GET" })
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

  it("loads provider models through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            models: [
              {
                id: "openai/gpt-4.1-mini",
                label: "GPT-4.1 Mini",
                owned_by: "openai",
                context_length: 1047576
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
    const { getLlmProviderModels } = await import("../ipc");

    await expect(getLlmProviderModels(sidecar, "openrouter")).resolves.toEqual([
      {
        id: "openai/gpt-4.1-mini",
        label: "GPT-4.1 Mini",
        ownedBy: "openai",
        contextLength: 1047576
      }
    ]);

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/providers/openrouter/models",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("loads provider secret plaintext through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { value: "sk-local" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { getLlmProviderSecret } = await import("../ipc");

    await expect(getLlmProviderSecret(sidecar, "openai")).resolves.toBe("sk-local");
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/providers/openai/secret",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("tests provider connection through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ ok: true, data: { ok: true, message: "Connection test succeeded." } }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" }
        }
      )
    );
    vi.stubGlobal("fetch", fetchImpl);
    const { testLlmProviderConnection } = await import("../ipc");

    await expect(
      testLlmProviderConnection(sidecar, {
        providerName: "openai",
        baseUrl: "https://api.openai.com/v1",
        apiKey: "sk-test",
        model: "gpt-4.1-mini"
      })
    ).resolves.toEqual({ ok: true, message: "Connection test succeeded." });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/providers/test-connection",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          provider_name: "openai",
          base_url: "https://api.openai.com/v1",
          api_key: "sk-test",
          model: "gpt-4.1-mini"
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
            job: {
              job_id: "job_1",
              provider: "faster-whisper",
              model: "small",
              status: "running",
              percent: 30,
              current_bytes: 30,
              total_bytes: 100,
              error: null,
              started_at: "2026-04-28T10:00:00.000Z",
              completed_at: null,
              model_status: null
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
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/models/faster-whisper/download",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ model: "small" })
      })
    );
  });

  it("polls a faster-whisper model download job through the sidecar", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            job: {
              job_id: "job_1",
              provider: "faster-whisper",
              model: "small",
              status: "completed",
              percent: 100,
              current_bytes: 100,
              total_bytes: 100,
              error: null,
              started_at: "2026-04-28T10:00:00.000Z",
              completed_at: "2026-04-28T10:01:00.000Z",
              model_status: {
                provider: "faster-whisper",
                model: "small",
                cache_dir: "C:/models/fw",
                present: true,
                size_bytes: 10,
                error: null
              }
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
    const { getFasterWhisperModelDownload } = await import("../ipc");

    await expect(getFasterWhisperModelDownload(sidecar, "job 1")).resolves.toMatchObject({
      jobId: "job_1",
      status: "completed",
      percent: 100,
      modelStatus: {
        provider: "faster-whisper",
        model: "small",
        cacheDir: "C:/models/fw",
        present: true
      }
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runtime/models/faster-whisper/downloads/job%201",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("maps workflow progress events into task progress log lines", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            data: {
              id: "run_1",
              workflow_id: "youtube-to-srt",
              mode: "start",
              status: "running",
              project_root: "/tmp/project",
              plugin_paths: [],
              latest_event_sequence: 2,
              created_by: "desktop"
            }
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            data: {
              workflow_id: "youtube-to-srt",
              events: [
                {
                  id: "event_1",
                  workflow_id: "youtube-to-srt",
                  sequence: 1,
                  type: "step.progress",
                  level: "info",
                  message: "Download video 42%",
                  data: {
                    progress: {
                      phase: "video_download",
                      label: "Download video",
                      percent: 42,
                      current: 42,
                      total: 100,
                      unit: "bytes"
                    }
                  },
                  created_at: "2026-04-28T10:00:00.000Z",
                  step_id: "download",
                  attempt: 1
                }
              ]
            }
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );
    vi.stubGlobal("fetch", fetchImpl);
    const { getTaskMonitor } = await import("../ipc");

    await expect(getTaskMonitor(sidecar, "run_1")).resolves.toMatchObject({
      progressLogs: [
        {
          sequence: 1,
          timestamp: "2026-04-28T10:00:00.000Z",
          stepId: "download",
          attempt: 1,
          phase: "video_download",
          label: "Download video",
          percent: 42,
          current: 42,
          total: 100,
          unit: "bytes"
        }
      ]
    });
  });
});
