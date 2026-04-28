import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TaskHistory } from "../TaskHistory";
import type { TaskSummary } from "../../lib/types";

const tasks: TaskSummary[] = [
  {
    id: "run_1",
    title: "Demo video",
    workflowName: "Remote video -> translated SRT",
    sourceSummary: "https://www.youtube.com/watch?v=demo",
    status: "failed",
    updatedAt: "2026-04-28T00:05:00+00:00"
  }
];

describe("TaskHistory", () => {
  it("opens a selected task from history", async () => {
    const user = userEvent.setup();
    const onOpenTask = vi.fn();

    render(
      <TaskHistory
        error={null}
        loading={false}
        onOpenTask={onOpenTask}
        onRefresh={vi.fn()}
        tasks={tasks}
      />
    );

    await user.click(screen.getByRole("button", { name: /open demo video/i }));

    expect(onOpenTask).toHaveBeenCalledWith("run_1");
  });

  it("shows an empty state when no historical tasks exist", () => {
    render(
      <TaskHistory
        error={null}
        loading={false}
        onOpenTask={vi.fn()}
        onRefresh={vi.fn()}
        tasks={[]}
      />
    );

    expect(screen.getByText("No tasks yet")).toBeInTheDocument();
  });
});
