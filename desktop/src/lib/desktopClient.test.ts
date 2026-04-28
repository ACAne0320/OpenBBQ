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
      retryCheckpoint: vi.fn()
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
  });
});
