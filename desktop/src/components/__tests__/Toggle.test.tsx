import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Toggle } from "../Toggle";

describe("Toggle", () => {
  it("uses switch semantics and forwards safe button props", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(
      <Toggle
        checked={false}
        aria-label="Voice activity filter"
        className="custom-toggle"
        data-testid="vad-toggle"
        onChange={onChange}
      />
    );

    const toggle = screen.getByRole("switch", { name: "Voice activity filter" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toHaveClass("custom-toggle");
    expect(screen.getByTestId("vad-toggle")).toBe(toggle);

    await user.click(toggle);

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("does not report changes when disabled", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<Toggle checked label="Locked step" disabled onChange={onChange} />);

    const toggle = screen.getByRole("switch", { name: "Locked step" });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAttribute("aria-checked", "true");

    await user.click(toggle);

    expect(onChange).not.toHaveBeenCalled();
  });
});
