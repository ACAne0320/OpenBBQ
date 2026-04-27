import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { failedTask } from "../../lib/mockData";
import type { TaskMonitorModel } from "../../lib/types";
import { TaskMonitor } from "../TaskMonitor";

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

describe("TaskMonitor", () => {
  it("shows compact progress and a dominant runtime log", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "sample-interview" })).toBeInTheDocument();
    expect(screen.getByText("Translate failed")).toBeInTheDocument();

    const progress = screen.getByLabelText("Task progress");
    expect(within(progress).getAllByTestId("progress-step")).toHaveLength(failedTask.progress.length);
    expect(progress).toHaveClass("py-3");

    const log = screen.getByLabelText("Runtime log");
    expect(log).toHaveClass("min-h-[520px]");
    expect(within(log).getByText(/provider returned rate limit/i)).toBeInTheDocument();
    expect(within(log).getByText("error")).toBeInTheDocument();
  });

  it("shows the error banner and Retry checkpoint together for failed tasks", () => {
    render(<TaskMonitor task={failedTask} onRetry={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/translation provider failed/i);
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
});
