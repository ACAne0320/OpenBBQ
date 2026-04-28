import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { failedTask } from "../../lib/mockData";
import type { RuntimeLogLine, TaskMonitorModel } from "../../lib/types";
import { TaskMonitor } from "../TaskMonitor";

const neutralLogs: RuntimeLogLine[] = [
  {
    sequence: 1,
    timestamp: "2026-04-27T03:15:12.000Z",
    level: "info",
    message: "Task state refreshed."
  }
];

function taskWithStatus(status: TaskMonitorModel["status"]): TaskMonitorModel {
  return {
    ...failedTask,
    status,
    errorMessage: status === "failed" ? failedTask.errorMessage : undefined,
    progress: failedTask.progress.map((step) =>
      status === "running" && step.id === "translate" ? { ...step, status: "running" } : step
    )
  };
}

function taskWithStaleFailedProgress(status: Exclude<TaskMonitorModel["status"], "failed">): TaskMonitorModel {
  return {
    ...failedTask,
    status,
    errorMessage: undefined,
    logs: neutralLogs
  };
}

describe("TaskMonitor", () => {
  it("shows compact progress and a dominant runtime log", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "sample-interview" })).toBeInTheDocument();
    expect(screen.getByText("Translate failed")).toBeInTheDocument();

    const progress = screen.getByLabelText("Task progress");
    expect(within(progress).getAllByTestId("progress-step")).toHaveLength(failedTask.progress.length);
    expect(progress).toHaveClass("py-3");

    const log = screen.getByLabelText("Runtime log");
    expect(screen.getByTestId("runtime-log-scroll")).toHaveClass("h-[420px]");
    expect(within(log).getByText(/provider returned rate limit/i)).toBeInTheDocument();
    expect(within(log).getByText("error")).toBeInTheDocument();
  });

  it("renders workflow progress rows inside the runtime log", () => {
    render(
      <TaskMonitor
        task={{
          ...failedTask,
          status: "running",
          progressLogs: [
            {
              sequence: 6,
              timestamp: "2026-04-28T10:00:00.000Z",
              stepId: "transcribe",
              attempt: 1,
              phase: "asr_parse",
              label: "ASR parsing",
              percent: 42,
              current: 84,
              total: 200,
              unit: "seconds"
            }
          ]
        }}
        onRetry={vi.fn()}
      />
    );

    expect(screen.getByLabelText("ASR parsing progress")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("84 / 200 seconds")).toBeInTheDocument();
  });

  it("renders progress events once in the merged terminal log", () => {
    render(
      <TaskMonitor
        task={{
          ...failedTask,
          status: "running",
          progressLogs: [
            {
              sequence: 2,
              timestamp: "2026-04-28T10:00:00.000Z",
              stepId: "download",
              attempt: 1,
              phase: "video_download",
              label: "Download video",
              percent: 3,
              current: 920624,
              total: 27371136,
              unit: "bytes"
            }
          ],
          logs: [
            {
              sequence: 1,
              timestamp: "2026-04-28T09:59:59.000Z",
              level: "info",
              message: "Workflow started."
            },
            {
              sequence: 2,
              timestamp: "2026-04-28T10:00:00.000Z",
              level: "info",
              message: "Download video 3%"
            },
            {
              sequence: 3,
              timestamp: "2026-04-28T10:00:01.000Z",
              level: "info",
              message: "Resolving output."
            }
          ]
        }}
        onRetry={vi.fn()}
      />
    );

    const log = screen.getByLabelText("Runtime log");
    expect(within(log).getByLabelText("Download video progress")).toBeInTheDocument();
    expect(within(log).getByText("3%")).toBeInTheDocument();
    expect(within(log).getByText("920624 / 27371136 bytes")).toBeInTheDocument();
    expect(within(log).getByText("Workflow started.")).toBeInTheDocument();
    expect(within(log).getByText("Resolving output.")).toBeInTheDocument();
    expect(within(log).queryByText("Download video 3%")).not.toBeInTheDocument();
  });

  it("keeps runtime logs in a fixed internal viewport pinned to the latest row", () => {
    const scrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get: () => 1200
    });

    try {
      render(
        <TaskMonitor
          task={{
            ...failedTask,
            logs: Array.from({ length: 40 }, (_, index) => ({
              sequence: index + 1,
              timestamp: `2026-04-28T10:00:${String(index).padStart(2, "0")}.000Z`,
              level: "info" as const,
              message: `Log line ${index + 1}`
            }))
          }}
          onRetry={vi.fn()}
        />
      );

      const viewport = screen.getByTestId("runtime-log-scroll");
      expect(viewport).toHaveClass("overflow-y-auto");
      expect(viewport).toHaveClass("overflow-x-hidden");
      expect(viewport.scrollTop).toBe(1200);
    } finally {
      if (scrollHeight) {
        Object.defineProperty(HTMLElement.prototype, "scrollHeight", scrollHeight);
      }
    }
  });

  it("shows the error banner and Retry checkpoint together for failed tasks", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/translation provider failed/i);
    expect(within(alert).getByRole("button", { name: "Retry checkpoint" })).toBeInTheDocument();
  });

  it("shows fallback failure copy and Retry checkpoint for failed tasks without an error message", () => {
    render(<TaskMonitor task={{ ...failedTask, errorMessage: undefined }} onRetry={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/task failed before openbbq received detailed error information/i);
    expect(within(alert).getByRole("button", { name: "Retry checkpoint" })).toBeInTheDocument();
  });

  it("hides the error banner and Retry checkpoint for running tasks", () => {
    render(<TaskMonitor task={taskWithStatus("running")} onRetry={vi.fn()} />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry checkpoint" })).not.toBeInTheDocument();
  });

  it("hides the error banner and Retry checkpoint for completed tasks", () => {
    render(<TaskMonitor task={taskWithStatus("completed")} onRetry={vi.fn()} />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry checkpoint" })).not.toBeInTheDocument();
  });

  it.each([
    ["queued", "Waiting to start"],
    ["running", "Translate running"],
    ["paused", "Task paused"],
    ["completed", "Task completed"],
    ["aborted", "Task aborted"]
  ] as const)("does not present stale failed progress as error UI for %s tasks", (status, summary) => {
    render(<TaskMonitor task={taskWithStaleFailedProgress(status)} onRetry={vi.fn()} />);

    expect(screen.getByText(summary)).toBeInTheDocument();
    expect(screen.queryByText("Translate failed")).not.toBeInTheDocument();
    expect(screen.queryByText(/1 failed/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry checkpoint" })).not.toBeInTheDocument();
  });

  it("exposes progress step labels and statuses to assistive technology", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} />);

    expect(screen.getByLabelText("Translate: failed")).toBeInTheDocument();
    expect(screen.getByLabelText("Export: blocked")).toBeInTheDocument();
  });

  it("only renders Request cancel for cancelable tasks with a handler", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();

    const { rerender } = render(<TaskMonitor task={failedTask} onRetry={vi.fn()} onCancel={onCancel} />);
    expect(screen.queryByRole("button", { name: "Request cancel" })).not.toBeInTheDocument();

    rerender(<TaskMonitor task={taskWithStatus("running")} onRetry={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Request cancel" })).not.toBeInTheDocument();

    rerender(<TaskMonitor task={taskWithStatus("running")} onRetry={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole("button", { name: "Request cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not render runtime parameter selectors or settings controls", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} />);

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText(/settings/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/parameter/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider setup/i)).not.toBeInTheDocument();
  });

  it("invokes onRetry from the failed-state retry action", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<TaskMonitor task={failedTask} onRetry={onRetry} />);

    await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("disables Retry checkpoint while retry is pending", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} retryPending />);

    expect(screen.getByRole("button", { name: "Retry checkpoint" })).toBeDisabled();
    expect(screen.getByText("Retrying checkpoint...")).toBeInTheDocument();
  });

  it("shows retry errors inside the failed-state banner area", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} retryError="Retry failed: sidecar unavailable." />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Retry failed: sidecar unavailable.");
  });
});
