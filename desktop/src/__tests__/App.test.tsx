import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import type { OpenBBQClient } from "../lib/apiClient";
import { failedTask, reviewModel, workflowSteps } from "../lib/mockData";
import type { TaskMonitorModel, WorkflowStep } from "../lib/types";

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
    async getTaskMonitor() {
      return failedTask;
    },
    async getReview() {
      return reviewModel;
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

  it("shows the task monitor after continuing from workflow arrangement", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Arrange workflow" });

    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Task monitor")).toBeInTheDocument();
    expect(screen.getByText(/provider returned rate limit/i)).toBeInTheDocument();
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
