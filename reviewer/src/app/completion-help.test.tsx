import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CompletionBanner, exportCommand } from "./CompletionBanner";
import { ShortcutHelp } from "./ShortcutHelp";
import { SHORTCUTS } from "./shortcuts";
import { createTestServices, makeCue, makeSuggestion, renderWithServices } from "../test-utils";

function completeServices() {
  const services = createTestServices({
    cues: [makeCue(1, { status: "reviewed" }), makeCue(2, { status: "reviewed" })],
  });
  services.store.setState({
    progress: { reviewed: 2, flagged: 0, unreviewed: 0, total: 2 },
  });
  return services;
}

describe("exportCommand", () => {
  it("builds the bilingual command for a language worksheet", () => {
    expect(exportCommand("/tmp/ws", "zh")).toBe(
      "openbbq export --workspace /tmp/ws --to zh --mode bilingual",
    );
  });

  it("builds the source command without a target language", () => {
    expect(exportCommand("/tmp/ws", null)).toBe("openbbq export --workspace /tmp/ws");
  });
});

describe("CompletionBanner", () => {
  it("renders only when every cue is reviewed", () => {
    const incomplete = createTestServices({ cues: [makeCue(1)] });
    const { unmount } = renderWithServices(<CompletionBanner />, incomplete);
    expect(screen.queryByText("All cues reviewed")).toBeNull();
    unmount();

    renderWithServices(<CompletionBanner />, completeServices());
    expect(screen.getByText("All cues reviewed")).toBeInTheDocument();
    expect(screen.getByText("No open issues")).toBeInTheDocument();
  });

  it("counts open issues and pending suggestions", () => {
    const services = completeServices();
    services.store.setState({
      cues: [
        makeCue(1, { status: "reviewed" }),
        makeCue(2, {
          status: "reviewed",
          issues: [
            {
              cue_id: 2,
              kind: "term",
              severity: "warning",
              message: "term",
              detail: {},
              source: "rule",
              dismissed: false,
              suggestion_ids: [],
            },
          ],
        }),
      ],
      suggestions: [makeSuggestion("s1", 2)],
    });
    renderWithServices(<CompletionBanner />, services);
    expect(screen.getByText("2 open items left")).toBeInTheDocument();
  });

  it("copies the export command and dismisses", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const services = completeServices();
    renderWithServices(<CompletionBanner />, services);

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith(
      "openbbq export --workspace /tmp/review --to zh --mode bilingual",
    );

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("All cues reviewed")).toBeNull();
    expect(services.store.getState().completedDismissed).toBe(true);
  });
});

describe("ShortcutHelp", () => {
  it("renders every table entry grouped by section", () => {
    const services = createTestServices({ cues: [makeCue(1)] });
    renderWithServices(<ShortcutHelp />, services);
    expect(screen.getByText("Keyboard shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Playback")).toBeInTheDocument();
    expect(screen.getByText("Editing")).toBeInTheDocument();
    expect(screen.getByText("Cue operations")).toBeInTheDocument();
    expect(screen.getByText("Tools")).toBeInTheDocument();
    // The overlay renders the table itself — count must match.
    const rows = document.querySelectorAll(".help-row");
    expect(rows).toHaveLength(SHORTCUTS.length);
    expect(screen.getByText("Find and replace")).toBeInTheDocument();
    expect(screen.getByText("⇧/⌘+Click")).toBeInTheDocument();
  });

  it("closes via the close button", () => {
    const services = createTestServices({ cues: [makeCue(1)] });
    services.store.setState({ helpOpen: true });
    renderWithServices(<ShortcutHelp />, services);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(services.store.getState().helpOpen).toBe(false);
  });

  it("drives P3 bindings through the same table", () => {
    const services = createTestServices({ cues: [makeCue(1)] });
    const find = SHORTCUTS.find((shortcut) => shortcut.id === "find");
    const escape = SHORTCUTS.find((shortcut) => shortcut.id === "escape");
    const help = SHORTCUTS.find((shortcut) => shortcut.id === "help");
    expect(find?.match?.(new KeyboardEvent("keydown", { key: "f", metaKey: true }))).toBe(true);
    expect(help?.match?.(new KeyboardEvent("keydown", { key: "?" }))).toBe(true);
    find?.run?.(services);
    expect(services.store.getState().findOpen).toBe(true);
    help?.run?.(services);
    expect(services.store.getState().helpOpen).toBe(true);
    // Escape closes the topmost overlay first, then the find panel.
    escape?.run?.(services);
    expect(services.store.getState().helpOpen).toBe(false);
    expect(services.store.getState().findOpen).toBe(true);
    escape?.run?.(services);
    expect(services.store.getState().findOpen).toBe(false);
  });
});
