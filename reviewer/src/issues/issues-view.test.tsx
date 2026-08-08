import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Api } from "../api/client";
import { IssuesView, groupIssues } from "./IssuesView";
import {
  createTestServices,
  makeCue,
  makeIssue,
  makeSnapshot,
  makeSuggestion,
  renderWithServices,
} from "../test-utils";

describe("groupIssues", () => {
  it("groups open issues by kind and skips empty groups", () => {
    const groups = groupIssues(
      [
        makeCue(1, { issues: [makeIssue("term"), makeIssue("budget")] }),
        makeCue(2, { issues: [makeIssue("term", { cue_id: 2 })] }),
      ],
      [],
    );
    expect(groups.map((group) => [group.kind, group.open.length])).toEqual([
      ["term", 2],
      ["budget", 1],
    ]);
  });

  it("routes dismissed issues and resolved suggestions to processed", () => {
    const groups = groupIssues(
      [makeCue(1, { issues: [makeIssue("term", { dismissed: true })] })],
      [
        makeSuggestion("s1", 1, { status: "rejected", kind: "agent_note" }),
        makeSuggestion("s2", 1, { status: "accepted", kind: "term" }),
      ],
    );
    const term = groups.find((group) => group.kind === "term");
    const agent = groups.find((group) => group.kind === "agent_note");
    expect(term?.open).toHaveLength(0);
    expect(term?.processed).toHaveLength(2);
    expect(agent?.processed).toHaveLength(1);
    expect(agent?.processed[0].reopenId).toBe("s1");
    expect(term?.processed[1].reopenId).toBeUndefined();
  });
});

describe("IssuesView", () => {
  it("shows the empty state when nothing is open", () => {
    const services = createTestServices({ cues: [makeCue(1)] });
    renderWithServices(<IssuesView />, services);
    expect(screen.getByText("No open issues.")).toBeInTheDocument();
  });

  it("jumps to a cue from an issue row", async () => {
    const services = createTestServices({
      cues: [makeCue(1), makeCue(2, { issues: [makeIssue("term", { cue_id: 2 })] })],
      selectedId: 1,
    });
    renderWithServices(<IssuesView />, services);
    expect(screen.getByText("Term issue")).toBeInTheDocument();
    fireEvent.click(screen.getByText("#2"));
    await waitFor(() => expect(services.store.getState().selectedId).toBe(2));
    expect(services.store.getState().currentTime).toBe(20);
  });

  it("keeps processed items collapsed until expanded, then reopens rejected suggestions", async () => {
    const api: Partial<Api> = {
      reopenSuggestion: vi.fn(async () => makeSnapshot("r2", [makeCue(1)])),
    };
    const services = createTestServices(
      {
        cues: [makeCue(1, { issues: [makeIssue("term", { dismissed: true })] })],
        suggestions: [makeSuggestion("s1", 1, { status: "rejected" })],
      },
      api,
    );
    renderWithServices(<IssuesView />, services);

    // Dismissed issue and rejected suggestion hide behind "Processed".
    expect(screen.queryByText("Restore")).toBeNull();
    const processedHeads = screen.getAllByText("Processed (1)");
    expect(processedHeads).toHaveLength(2);

    // Expanding the dismissed-issue section (term group) shows no reopen.
    fireEvent.click(processedHeads[0]);
    // Expanding the agent_note section reveals the rejected suggestion.
    fireEvent.click(processedHeads[1]);
    expect(screen.getByText("suggestion s1")).toBeInTheDocument();

    const reopen = screen.getByText("Restore");
    fireEvent.click(reopen);
    await waitFor(() =>
      expect(api.reopenSuggestion).toHaveBeenCalledWith(
        "s1",
        expect.objectContaining({ base_revision: "r1" }),
      ),
    );
  });

  it("collapses and expands a kind group", () => {
    const services = createTestServices({
      cues: [makeCue(1, { issues: [makeIssue("budget")] })],
    });
    renderWithServices(<IssuesView />, services);
    const head = screen.getByText("Over budget").closest("button") as HTMLElement;
    expect(screen.getByText("#1")).toBeInTheDocument();
    fireEvent.click(head);
    expect(screen.queryByText("#1")).toBeNull();
    fireEvent.click(head);
    expect(screen.getByText("#1")).toBeInTheDocument();
  });
});
