import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../../App";
import { SourceImport } from "../SourceImport";

describe("SourceImport", () => {
  it("starts with Continue disabled", () => {
    render(<SourceImport onContinue={vi.fn()} />);

    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });

  it("enables Continue after a URL is entered", async () => {
    const user = userEvent.setup();
    render(<SourceImport onContinue={vi.fn()} />);

    await user.type(screen.getByLabelText(/video link/i), "https://www.youtube.com/watch?v=abc");

    expect(screen.getByRole("button", { name: /continue/i })).toBeEnabled();
  });

  it("submits a trimmed remote URL source", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<SourceImport onContinue={onContinue} />);

    await user.type(screen.getByLabelText(/video link/i), "   https://www.youtube.com/watch?v=abc   ");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(onContinue).toHaveBeenCalledWith({
      kind: "remote_url",
      url: "https://www.youtube.com/watch?v=abc"
    });
  });

  it("renders inside the shell without unrelated step-one surfaces", () => {
    render(<App />);

    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.queryByText(/live|history|provider|workflow/i)).not.toBeInTheDocument();
  });
});
