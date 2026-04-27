import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { workflowSteps } from "../../lib/mockData";
import { WorkflowEditor } from "../WorkflowEditor";

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
});
