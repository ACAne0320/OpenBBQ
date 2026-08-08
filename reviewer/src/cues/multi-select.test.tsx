import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Api } from "../api/client";
import { CueListPanel } from "./CueListPanel";
import {
  createTestServices,
  makeCue,
  makeSnapshot,
  renderWithServices,
} from "../test-utils";

function renderList(api: Partial<Api> = {}) {
  const services = createTestServices(
    { cues: [makeCue(1), makeCue(2), makeCue(3), makeCue(4)] },
    api,
  );
  renderWithServices(<CueListPanel />, services);
  return services;
}

describe("multi-select", () => {
  it("shift-click selects the range across the visible order", async () => {
    const services = renderList();
    // Anchor is cue 1 (initial selection).
    fireEvent.click(screen.getByText("Source 3"), { shiftKey: true });
    expect(services.store.getState().selection).toEqual([1, 2, 3]);
    expect(services.store.getState().selectedId).toBe(1);

    // Reverse direction from a new anchor.
    fireEvent.click(screen.getByText("Source 4"));
    await waitFor(() => expect(services.store.getState().selectedId).toBe(4));
    fireEvent.click(screen.getByText("Source 2"), { shiftKey: true });
    expect(services.store.getState().selection).toEqual([2, 3, 4]);
  });

  it("ctrl-click toggles individual cues", async () => {
    const services = renderList();
    fireEvent.click(screen.getByText("Source 3"), { ctrlKey: true });
    expect(services.store.getState().selection).toEqual([1, 3]);
    fireEvent.click(screen.getByText("Source 3"), { ctrlKey: true });
    expect(services.store.getState().selection).toEqual([1]);
  });

  it("plain click keeps the single-select behavior", async () => {
    const services = renderList();
    fireEvent.click(screen.getByText("Source 3"), { ctrlKey: true });
    fireEvent.click(screen.getByText("Source 2"));
    await waitFor(() => expect(services.store.getState().selectedId).toBe(2));
    expect(services.store.getState().selection).toEqual([2]);
    expect(services.store.getState().currentTime).toBe(20);
  });
});

describe("batch bar", () => {
  it("marks the selection via batchStatus", async () => {
    const api: Partial<Api> = {
      batchStatus: vi.fn(async () => makeSnapshot("r2", [makeCue(1), makeCue(2), makeCue(3), makeCue(4)])),
    };
    const services = renderList(api);
    fireEvent.click(screen.getByText("Source 2"), { shiftKey: true });
    const bar = screen.getByRole("group", { name: "2 selected" });
    expect(bar).toBeInTheDocument();

    fireEvent.click(within(bar).getByRole("button", { name: "Mark reviewed" }));
    await waitFor(() =>
      expect(api.batchStatus).toHaveBeenCalledWith(
        expect.objectContaining({ cue_ids: [1, 2], status: "reviewed" }),
      ),
    );
    void services;
  });

  it("deletes the selection after confirmation through the atomic endpoint", async () => {
    const api: Partial<Api> = {
      batchDelete: vi.fn(async () => makeSnapshot("r2", [makeCue(3), makeCue(4)])),
    };
    renderList(api);
    fireEvent.click(screen.getByText("Source 2"), { shiftKey: true });
    const bar = screen.getByRole("group", { name: "2 selected" });
    fireEvent.click(within(bar).getByRole("button", { name: "Delete" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Delete 2 cues? One undo restores the whole batch.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(api.batchDelete).toHaveBeenCalledWith(
        expect.objectContaining({ cue_ids: [1, 2] }),
      ),
    );
  });

  it("clears the selection from the bar", async () => {
    const services = renderList();
    fireEvent.click(screen.getByText("Source 3"), { shiftKey: true });
    const bar = screen.getByRole("group", { name: "3 selected" });
    fireEvent.click(within(bar).getByRole("button", { name: "Clear selection" }));
    expect(services.store.getState().selection).toEqual([1]);
    expect(screen.queryByRole("group", { name: /selected/ })).toBeNull();
  });

  it("hides the bar for a single selection", () => {
    renderList();
    expect(screen.queryByRole("group", { name: /selected/ })).toBeNull();
  });
});

describe("list/issues tabs", () => {
  it("switches to the issues view and persists the tab", () => {
    const services = renderList();
    expect(screen.getByRole("searchbox", { name: "Search or #ID" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Issues/ }));
    expect(screen.queryByRole("searchbox", { name: "Search or #ID" })).toBeNull();
    expect(screen.getByText("No open issues.")).toBeInTheDocument();
    expect(services.store.getState().prefs.leftTab).toBe("issues");
    expect(JSON.parse(window.localStorage.getItem("openbbq-review-prefs") ?? "{}")).toMatchObject(
      { leftTab: "issues" },
    );
  });
});
