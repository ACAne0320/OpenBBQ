import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import type { OpenBBQClient } from "../lib/apiClient";
import { failedTask, reviewModel, workflowSteps } from "../lib/mockData";
import type { TaskMonitorModel, TaskSummary, WorkflowStep } from "../lib/types";

const workflowEditorRender = vi.hoisted(() => vi.fn());

vi.mock("../components/WorkflowEditor", () => ({
  WorkflowEditor: ({
    initialSteps,
    onBack,
    onContinue
  }: {
    initialSteps: Array<{ id: string }>;
    onBack?: () => void;
    onContinue?: (steps: Array<{ id: string }>) => void;
  }) => {
    workflowEditorRender(initialSteps);
    const remote = initialSteps[0]?.id === "fetch_source";

    return (
      <section aria-label="Mock workflow editor">
        <h1>Arrange workflow</h1>
        <p>{remote ? "Remote video -> translated SRT" : "Local video -> translated SRT"}</p>
        <p data-testid="workflow-first-step">{initialSteps[0]?.id}</p>
        <button type="button" onClick={onBack}>
          Back
        </button>
        <button type="button" onClick={() => onContinue?.(initialSteps)}>
          Continue
        </button>
      </section>
    );
  }
}));

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });

  return { promise, resolve };
}

function createTestClient(
  getWorkflowTemplate: OpenBBQClient["getWorkflowTemplate"],
  overrides: Partial<OpenBBQClient> = {}
): OpenBBQClient {
  return {
    getWorkflowTemplate,
    async startSubtitleTask() {
      return { runId: "run_sample" };
    },
    async listTasks() {
      return [];
    },
    async getTaskMonitor() {
      return failedTask;
    },
    async getReview() {
      return reviewModel;
    },
    async getRuntimeSettings() {
      return {
        configPath: "C:/Users/alex/.openbbq/config.toml",
        cacheRoot: "C:/Users/alex/.cache/openbbq",
        defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
        llmProviders: [
          {
            name: "openai-compatible",
            type: "openai_compatible",
            baseUrl: null,
            apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
            defaultChatModel: "gpt-4o-mini",
            displayName: "OpenAI-compatible"
          }
        ],
        fasterWhisper: {
          cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
          defaultModel: "base",
          defaultDevice: "cpu",
          defaultComputeType: "int8"
        }
      };
    },
    async saveRuntimeDefaults(input) {
      return {
        configPath: "C:/Users/alex/.openbbq/config.toml",
        cacheRoot: "C:/Users/alex/.cache/openbbq",
        defaults: input,
        llmProviders: [],
        fasterWhisper: {
          cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
          defaultModel: "base",
          defaultDevice: "cpu",
          defaultComputeType: "int8"
        }
      };
    },
    async saveLlmProvider(input) {
      return {
        name: input.name,
        type: input.type,
        baseUrl: input.baseUrl,
        apiKeyRef: input.apiKeyRef,
        defaultChatModel: input.defaultChatModel,
        displayName: input.displayName
      };
    },
    async checkLlmProvider(name) {
      const envName = name.toUpperCase().replace(/-/g, "_");
      return {
        reference: `env:${envName}_API_KEY`,
        resolved: true,
        display: `env:${envName}_API_KEY`,
        valuePreview: "configured",
        error: null
      };
    },
    async saveFasterWhisperDefaults(input) {
      return {
        configPath: "C:/Users/alex/.openbbq/config.toml",
        cacheRoot: "C:/Users/alex/.cache/openbbq",
        defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
        llmProviders: [],
        fasterWhisper: input
      };
    },
    async getRuntimeModels() {
      return [
        {
          provider: "faster-whisper",
          model: "base",
          cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
          present: false,
          sizeBytes: 0,
          error: null
        }
      ];
    },
    async getDiagnostics() {
      return [{ id: "cache.root_writable", status: "passed", severity: "error", message: "Runtime cache root is writable." }];
    },
    async updateSegmentText() {
      return undefined;
    },
    async retryCheckpoint() {
      return undefined;
    },
    ...overrides
  };
}

function remoteStepsFor(url: string): WorkflowStep[] {
  return [
    {
      id: "fetch_source",
      name: "Fetch Source",
      toolRef: "source.fetch_remote",
      summary: "url -> local media",
      status: "locked",
      parameters: [{ kind: "text", key: "url", label: "URL", value: url }]
    },
    ...workflowSteps
  ];
}

const runningTask: TaskMonitorModel = {
  ...failedTask,
  status: "running",
  errorMessage: undefined,
  progress: failedTask.progress.map((step) => (step.id === "translate" ? { ...step, status: "running" } : step)),
  logs: [
    ...failedTask.logs,
    {
      sequence: 6,
      timestamp: "2026-04-27T03:17:14.000Z",
      level: "info",
      message: "Retry accepted from checkpoint translate."
    }
  ]
};

const persistedTask: TaskSummary = {
  id: "run_persisted",
  title: "Demo video",
  workflowName: "Remote video -> translated SRT",
  sourceSummary: "https://www.youtube.com/watch?v=demo",
  status: "failed",
  updatedAt: "2026-04-28T00:05:00+00:00"
};

describe("App workflow flow", () => {
  beforeEach(() => {
    workflowEditorRender.mockClear();
  });

  it("passes the remote template to the workflow editor after source import continues", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();
    expect(screen.getByText("Remote video -> translated SRT")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-first-step")).toHaveTextContent("fetch_source");
    expect(workflowEditorRender).toHaveBeenLastCalledWith(
      expect.arrayContaining([expect.objectContaining({ id: "fetch_source" })])
    );
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("clears the selected source when going back to source import", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });

    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByRole("heading", { name: "Choose a source" })).toBeInTheDocument();
    expect(screen.getByLabelText(/video link/i)).toHaveValue("");
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText("creator-videos")).toBeInTheDocument();
    expect(screen.queryByText("remote URL")).not.toBeInTheDocument();
  });

  it("starts a task with the selected source and workflow before showing monitor", async () => {
    const user = userEvent.setup();
    const startSubtitleTask = vi.fn().mockResolvedValue({ runId: "run_test" });
    const getTaskMonitor = vi.fn().mockResolvedValue({ ...failedTask, id: "run_test" });
    const client = createTestClient(vi.fn().mockResolvedValue(remoteStepsFor("https://example.com/video.mp4")), {
      startSubtitleTask,
      getTaskMonitor
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });

    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Task monitor")).toBeInTheDocument();
    expect(startSubtitleTask).toHaveBeenCalledWith({
      source: { kind: "remote_url", url: "https://example.com/video.mp4" },
      steps: expect.arrayContaining([expect.objectContaining({ id: "fetch_source" })])
    });
    expect(getTaskMonitor).toHaveBeenCalledWith("run_test");
  });

  it("shows task history when Tasks is selected before a task exists", async () => {
    const user = userEvent.setup();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      listTasks: vi.fn().mockResolvedValue([])
    });
    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "Tasks" }));

    expect(await screen.findByRole("heading", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByText("No tasks yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tasks" })).toHaveAttribute("aria-current", "page");
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("opens Settings from the global navigation", async () => {
    const user = userEvent.setup();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getRuntimeSettings: vi.fn().mockResolvedValue({
        configPath: "C:/Users/alex/.openbbq/config.toml",
        cacheRoot: "C:/Users/alex/.cache/openbbq",
        defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
        llmProviders: [],
        fasterWhisper: {
          cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
          defaultModel: "base",
          defaultDevice: "cpu",
          defaultComputeType: "int8"
        }
      }),
      getRuntimeModels: vi.fn().mockResolvedValue([]),
      getDiagnostics: vi.fn().mockResolvedValue([]),
      saveRuntimeDefaults: vi.fn(),
      saveLlmProvider: vi.fn(),
      checkLlmProvider: vi.fn(),
      saveFasterWhisperDefaults: vi.fn()
    });

    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "Settings" }));

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });

  it("opens a persisted task from history without re-entering the source", async () => {
    const user = userEvent.setup();
    const listTasks = vi.fn().mockResolvedValue([persistedTask]);
    const getTaskMonitor = vi.fn().mockResolvedValue({
      ...failedTask,
      id: persistedTask.id,
      title: persistedTask.title,
      workflowName: persistedTask.workflowName
    });
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      listTasks,
      getTaskMonitor
    });

    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "Tasks" }));
    await user.click(await screen.findByRole("button", { name: /open demo video/i }));

    expect(listTasks).toHaveBeenCalledTimes(1);
    expect(getTaskMonitor).toHaveBeenCalledWith("run_persisted");
    expect(await screen.findByText("Task monitor")).toBeInTheDocument();
    expect(screen.getByText("Demo video")).toBeInTheDocument();
  });

  it("opens real review results automatically when a task completes", async () => {
    const user = userEvent.setup();
    const completedTask: TaskMonitorModel = {
      ...failedTask,
      id: "run_test",
      status: "completed",
      errorMessage: undefined,
      progress: failedTask.progress.map((step) => ({ ...step, status: "done" }))
    };
    const getReview = vi.fn().mockResolvedValue({
      ...reviewModel,
      title: "run_test results",
      videoSrc: "openbbq-file://artifact/video",
      subtitleText: "1\n00:00:00,000 --> 00:00:01,000\n真实字幕\n"
    });
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      startSubtitleTask: vi.fn().mockResolvedValue({ runId: "run_test" }),
      getTaskMonitor: vi.fn().mockResolvedValue(completedTask),
      getReview
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Review results")).toBeInTheDocument();
    expect(getReview).toHaveBeenCalledWith("run_test");
    expect(screen.getByText("run_test results")).toBeInTheDocument();
  });

  it("opens results from navigation using the loaded task run id", async () => {
    const user = userEvent.setup();
    const getReview = vi.fn().mockResolvedValue(reviewModel);
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview,
      getTaskMonitor: vi.fn().mockResolvedValue(failedTask)
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Task monitor");

    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(await screen.findByText("Review results")).toBeInTheDocument();
    expect(getReview).toHaveBeenCalledWith(failedTask.id);
    expect(screen.getByRole("button", { name: "Results" })).toHaveAttribute("aria-current", "page");
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("keeps the current screen while Results loads without a task and then shows review", async () => {
    const user = userEvent.setup();
    const review = createDeferred<typeof reviewModel>();
    const getReview = vi.fn(() => review.promise);
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), { getReview });

    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(screen.getByRole("heading", { name: "Choose a source" })).toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(getReview).toHaveBeenCalledWith("run_sample");

    await act(async () => {
      review.resolve(reviewModel);
      await review.promise;
    });

    expect(await screen.findByText("Review results")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Results" })).toHaveAttribute("aria-current", "page");
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("shows an error when workflow template loading fails", async () => {
    const user = userEvent.setup();
    const client = createTestClient(vi.fn().mockRejectedValue(new Error("template unavailable")));

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load workflow template: template unavailable"
    );
    expect(screen.getByRole("heading", { name: "Choose a source" })).toBeInTheDocument();
  });

  it("shows an error when task monitor loading fails", async () => {
    const user = userEvent.setup();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getTaskMonitor: vi.fn().mockRejectedValue(new Error("task unavailable"))
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not start task: task unavailable");
    expect(screen.getByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();
  });

  it("shows an error when review loading fails", async () => {
    const user = userEvent.setup();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview: vi.fn().mockRejectedValue(new Error("review unavailable"))
    });

    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load review results: review unavailable");
    expect(screen.getByRole("heading", { name: "Choose a source" })).toBeInTheDocument();
  });

  it("surfaces real-client review loading errors without falling back to mock data", async () => {
    const user = userEvent.setup();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview: vi.fn().mockRejectedValue(new Error("No readable review artifacts are available for this run."))
    });

    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load review results: No readable review artifacts are available for this run."
    );
    expect(screen.queryByText("Each result is saved as an editable versioned segment.")).not.toBeInTheDocument();
  });

  it("keeps Results active when an earlier source template resolves after review", async () => {
    const user = userEvent.setup();
    const sourceTemplate = createDeferred<WorkflowStep[]>();
    const client = createTestClient(vi.fn(() => sourceTemplate.promise), {
      getReview: vi.fn().mockResolvedValue(reviewModel)
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(await screen.findByText("Review results")).toBeInTheDocument();

    await act(async () => {
      sourceTemplate.resolve(workflowSteps);
      await sourceTemplate.promise;
    });

    expect(screen.getByText("Review results")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Results" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("heading", { name: "Arrange workflow" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("keeps Results active when an earlier task monitor resolves after review", async () => {
    const user = userEvent.setup();
    const taskMonitor = createDeferred<typeof failedTask>();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview: vi.fn().mockResolvedValue(reviewModel),
      getTaskMonitor: vi.fn(() => taskMonitor.promise)
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(await screen.findByText("Review results")).toBeInTheDocument();

    await act(async () => {
      taskMonitor.resolve(failedTask);
      await taskMonitor.promise;
    });

    expect(screen.getByText("Review results")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Results" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("Task monitor")).not.toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("keeps Tasks active when returning to the task monitor before review loading finishes", async () => {
    const user = userEvent.setup();
    const review = createDeferred<typeof reviewModel>();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview: vi.fn(() => review.promise),
      getTaskMonitor: vi.fn().mockResolvedValue(failedTask)
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Task monitor");

    await user.click(screen.getByRole("button", { name: "Results" }));
    await user.click(screen.getByRole("button", { name: "Tasks" }));

    expect(screen.getByText("Task monitor")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tasks" })).toHaveAttribute("aria-current", "page");

    await act(async () => {
      review.resolve(reviewModel);
      await review.promise;
    });

    expect(screen.getByText("Task monitor")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tasks" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("Review results")).not.toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("ignores a pending review when source import starts a new workflow", async () => {
    const user = userEvent.setup();
    const review = createDeferred<typeof reviewModel>();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview: vi.fn(() => review.promise)
    });

    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "Results" }));
    await user.type(screen.getByLabelText(/video link/i), "https://example.com/new-source.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();

    await act(async () => {
      review.resolve(reviewModel);
      await review.promise;
    });

    expect(screen.getByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();
    expect(screen.queryByText("Review results")).not.toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("ignores a pending review when workflow arrangement starts a task", async () => {
    const user = userEvent.setup();
    const review = createDeferred<typeof reviewModel>();
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview: vi.fn(() => review.promise),
      getTaskMonitor: vi.fn().mockResolvedValue(failedTask)
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });

    await user.click(screen.getByRole("button", { name: "Results" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Task monitor")).toBeInTheDocument();

    await act(async () => {
      review.resolve(reviewModel);
      await review.promise;
    });

    expect(screen.getByText("Task monitor")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tasks" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("Review results")).not.toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("retries the failed checkpoint once while pending and refreshes the task on success", async () => {
    const user = userEvent.setup();
    const retry = createDeferred<void>();
    const getTaskMonitor = vi.fn().mockResolvedValueOnce(failedTask).mockResolvedValueOnce(runningTask);
    const retryCheckpoint = vi.fn(() => retry.promise);
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getTaskMonitor,
      retryCheckpoint
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Translate failed");

    const retryButton = screen.getByRole("button", { name: "Retry checkpoint" });
    await user.click(retryButton);

    expect(retryCheckpoint).toHaveBeenCalledTimes(1);
    expect(retryCheckpoint).toHaveBeenCalledWith(failedTask.id);
    expect(retryButton).toBeDisabled();
    expect(screen.getByText("Retrying checkpoint...")).toBeInTheDocument();

    await user.click(retryButton);
    expect(retryCheckpoint).toHaveBeenCalledTimes(1);

    await act(async () => {
      retry.resolve(undefined);
      await retry.promise;
    });

    expect(getTaskMonitor).toHaveBeenLastCalledWith(failedTask.id);
    expect(await screen.findByText("Translate running")).toBeInTheDocument();
  });

  it("surfaces retry failures without leaving retry pending", async () => {
    const user = userEvent.setup();
    const retryCheckpoint = vi.fn().mockRejectedValue(new Error("sidecar unavailable"));
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getTaskMonitor: vi.fn().mockResolvedValue(failedTask),
      retryCheckpoint
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Translate failed");

    await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));

    expect(await screen.findByText("Retry failed: sidecar unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry checkpoint" })).toBeEnabled();
  });

  it("keeps retry pending across Results navigation and blocks duplicate retry", async () => {
    const user = userEvent.setup();
    const retry = createDeferred<void>();
    const retryCheckpoint = vi.fn(() => retry.promise);
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getReview: vi.fn().mockResolvedValue(reviewModel),
      getTaskMonitor: vi.fn().mockResolvedValue(failedTask),
      retryCheckpoint
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Translate failed");
    await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));
    expect(retryCheckpoint).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Results" }));
    expect(await screen.findByText("Review results")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tasks" }));

    expect(screen.getByText("Retrying checkpoint...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry checkpoint" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));
    expect(retryCheckpoint).toHaveBeenCalledTimes(1);
  });

  it("keeps a newer retry pending when an earlier task retry resolves later", async () => {
    const user = userEvent.setup();
    const firstRetry = createDeferred<void>();
    const secondRetry = createDeferred<void>();
    const getTaskMonitor = vi
      .fn()
      .mockResolvedValueOnce(failedTask)
      .mockResolvedValueOnce(failedTask)
      .mockResolvedValueOnce(runningTask);
    const retryCheckpoint = vi
      .fn()
      .mockImplementationOnce(() => firstRetry.promise)
      .mockImplementationOnce(() => secondRetry.promise);
    const client = createTestClient(vi.fn().mockResolvedValue(workflowSteps), {
      getTaskMonitor,
      retryCheckpoint
    });

    render(<App client={client} />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/first.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Translate failed");
    await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));

    await user.click(screen.getByRole("button", { name: "New" }));
    await user.type(screen.getByLabelText(/video link/i), "https://example.com/second.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Translate failed");
    await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));

    await act(async () => {
      firstRetry.resolve(undefined);
      await firstRetry.promise;
    });

    expect(getTaskMonitor).toHaveBeenCalledTimes(2);

    await waitFor(() => {
      expect(screen.getByText("Translate failed")).toBeInTheDocument();
      expect(screen.getByText("Retrying checkpoint...")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Retry checkpoint" })).toBeDisabled();
    });
  });

  it("keeps latest workflow props after an earlier template response resolves last", async () => {
    const user = userEvent.setup();
    const localTemplate = createDeferred<WorkflowStep[]>();
    const remoteTemplate = createDeferred<WorkflowStep[]>();
    const client = createTestClient(
      vi.fn((source) => (source.kind === "local_file" ? localTemplate.promise : remoteTemplate.promise))
    );

    render(<App client={client} />);

    await user.upload(
      screen.getByLabelText(/drag\/drop or click to choose a local file/i),
      new File(["local video"], "clip.mov", { type: "video/quicktime" })
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByLabelText(/video link/i), "https://example.com/later.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await act(async () => {
      remoteTemplate.resolve(remoteStepsFor("https://example.com/later.mp4"));
      await remoteTemplate.promise;
    });

    expect(await screen.findByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();
    expect(screen.getByText("Remote video -> translated SRT")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-first-step")).toHaveTextContent("fetch_source");

    const renderCountAfterLatestResponse = workflowEditorRender.mock.calls.length;

    await act(async () => {
      localTemplate.resolve(workflowSteps);
      await localTemplate.promise;
    });

    expect(workflowEditorRender).toHaveBeenCalledTimes(renderCountAfterLatestResponse);
    expect(workflowEditorRender).toHaveBeenLastCalledWith(
      expect.arrayContaining([expect.objectContaining({ id: "fetch_source" })])
    );
    expect(screen.getByText("Remote video -> translated SRT")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-first-step")).toHaveTextContent("fetch_source");
    expect(screen.queryByText("Local video -> translated SRT")).not.toBeInTheDocument();
  });
});
