import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import type { OpenBBQClient } from "../lib/apiClient";
import { failedTask, reviewModel, workflowSteps } from "../lib/mockData";
import type { WorkflowStep } from "../lib/types";

const workflowEditorRender = vi.hoisted(() => vi.fn());

vi.mock("../components/WorkflowEditor", () => ({
  WorkflowEditor: ({
    initialSteps,
    onBack
  }: {
    initialSteps: Array<{ id: string }>;
    onBack?: () => void;
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

function createTestClient(getWorkflowTemplate: OpenBBQClient["getWorkflowTemplate"]): OpenBBQClient {
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
    }
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
