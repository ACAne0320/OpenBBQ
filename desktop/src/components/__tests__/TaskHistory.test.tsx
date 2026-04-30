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
    sourceKind: "remote_url",
    sourceUri: "https://www.youtube.com/watch?v=demo",
    sourceSummary: "https://www.youtube.com/watch?v=demo",
    status: "failed",
    createdAt: "2026-04-30T09:48:11.467169+00:00",
    updatedAt: "2026-04-30T09:49:43.830035+00:00"
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
    expect(screen.getByText("Remote video -> translated SRT")).toBeInTheDocument();
    expect(screen.getByText("Video URL")).toBeInTheDocument();
    expect(screen.getByText("https://www.youtube.com/watch?v=demo")).toBeInTheDocument();
    expect(screen.getByText("Created")).toBeInTheDocument();
    expect(screen.getByText("2026-04-30 09:48:11")).toBeInTheDocument();
    expect(screen.queryByText("2026-04-30T09:48:11.467169+00:00")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-04-30T09:49:43.830035+00:00")).not.toBeInTheDocument();
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
