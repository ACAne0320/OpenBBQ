import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "../AppShell";

describe("AppShell", () => {
  it("renders nav items as buttons and reports navigation requests", async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();

    render(
      <AppShell active="New" footerLabel="Workspace" footerValue="creator-videos" onNavigate={onNavigate}>
        <p>Choose a source</p>
      </AppShell>
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Results" })).not.toBeInTheDocument();

    const activeNav = screen.getByRole("button", { name: "New" });
    expect(activeNav).toHaveAttribute("aria-current", "page");

    await user.click(screen.getByRole("button", { name: "Tasks" }));

    expect(onNavigate).toHaveBeenCalledWith("Tasks");
  });

  it("owns one main work surface around page content", () => {
    render(
      <AppShell active="New" footerLabel="Workspace" footerValue="creator-videos">
        <section aria-label="Source content">Choose a source</section>
      </AppShell>
    );

    const main = screen.getByRole("main");
    expect(main).toHaveClass("min-w-0", "bg-paper", "shadow-panel");
    expect(main).toContainElement(screen.getByLabelText("Source content"));
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });

  it("shows the color OpenBBQ icon in the app chrome", () => {
    render(
      <AppShell active="New" footerLabel="Workspace" footerValue="creator-videos">
        <p>Choose a source</p>
      </AppShell>
    );

    expect(screen.getByRole("img", { name: "OpenBBQ" })).toHaveAttribute(
      "src",
      expect.stringContaining("/src/assets/openbbq-icon-color.png")
    );
    expect(screen.queryByText("OB")).not.toBeInTheDocument();
  });
});
