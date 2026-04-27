import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../../App";
import type { OpenBBQClient } from "../../lib/apiClient";
import { failedTask, reviewModel, workflowSteps } from "../../lib/mockData";
import type { WorkflowStep } from "../../lib/types";
import { WorkflowEditor } from "../WorkflowEditor";

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

describe("WorkflowEditor", () => {
  it("renders the local workflow template with step details", () => {
    render(<WorkflowEditor initialSteps={workflowSteps} onContinue={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();
    expect(screen.getAllByText("Local video -> translated SRT").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /select step 1: extract audio/i })).toBeInTheDocument();
    expect(screen.getByText("ffmpeg.extract_audio")).toBeInTheDocument();
    expect(screen.getByText("video -> audio")).toBeInTheDocument();
  });

  it("selects a workflow step and shows its editable parameter panel", async () => {
    const user = userEvent.setup();
    render(<WorkflowEditor initialSteps={workflowSteps} onContinue={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /select step 5: translate subtitle/i }));

    const panel = screen.getByLabelText("Selected step parameters");
    expect(within(panel).getByRole("heading", { name: "Translate Subtitle" })).toBeInTheDocument();
    expect(within(panel).getByLabelText("Target language")).toHaveValue("zh");
  });

  it("toggles optional steps off and on", async () => {
    const user = userEvent.setup();
    render(<WorkflowEditor initialSteps={workflowSteps} onContinue={vi.fn()} />);

    const toggle = screen.getByRole("switch", { name: "Enable Correct Transcript" });
    expect(toggle).toHaveAttribute("aria-checked", "true");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Disabled")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.getAllByText("Enabled").length).toBeGreaterThan(0);
  });

  it("keeps locked steps enabled and non-editable", async () => {
    const user = userEvent.setup();
    render(<WorkflowEditor initialSteps={workflowSteps} onContinue={vi.fn()} />);

    const lockedToggle = screen.getByRole("switch", { name: "Extract Audio is required" });
    expect(lockedToggle).toBeDisabled();
    expect(lockedToggle).toHaveAttribute("aria-checked", "true");

    await user.click(lockedToggle);
    expect(lockedToggle).toHaveAttribute("aria-checked", "true");
  });

  it("directly edits text parameters and continues with the edited steps", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<WorkflowEditor initialSteps={workflowSteps} onContinue={onContinue} />);

    await user.click(screen.getByRole("button", { name: /select step 5: translate subtitle/i }));
    await user.clear(screen.getByLabelText("Target language"));
    await user.type(screen.getByLabelText("Target language"), "ja");

    expect(screen.getByLabelText("Target language")).toHaveValue("ja");

    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(onContinue).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          id: "translate",
          parameters: expect.arrayContaining([expect.objectContaining({ key: "target_lang", value: "ja" })])
        })
      ])
    );
  });

  it("does not render removed workflow or global settings controls", () => {
    render(<WorkflowEditor initialSteps={workflowSteps} onContinue={vi.fn()} />);

    expect(screen.queryByText(/edit step/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/global settings/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/workflow controls/i)).not.toBeInTheDocument();
  });

  it("renders the remote template after source import continues", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();
    expect(screen.getAllByText("Remote video -> translated SRT").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /select step 1: fetch source/i })).toBeInTheDocument();
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

  it("ignores stale workflow template responses after a newer source is submitted", async () => {
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

    localTemplate.resolve(workflowSteps);
    remoteTemplate.resolve(remoteStepsFor("https://example.com/later.mp4"));

    expect(await screen.findByRole("heading", { name: "Arrange workflow" })).toBeInTheDocument();
    expect(screen.getAllByText("Remote video -> translated SRT").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /select step 1: fetch source/i })).toBeInTheDocument();
    expect(screen.queryByText("Local video -> translated SRT")).not.toBeInTheDocument();
  });
});
