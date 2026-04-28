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
});
