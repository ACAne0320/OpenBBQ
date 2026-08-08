import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Api } from "../api/client";
import { IssueCard } from "./IssueCard";
import { SuggestionCard } from "./SuggestionCard";
import {
  createTestServices,
  makeCue,
  makeIssue,
  makeSnapshot,
  makeSuggestion,
  renderWithServices,
} from "../test-utils";

// Hash of the fixture cue below, computed with the backend `_content_hash`.
const FRESH_HASH = "sha256:adec5fdede7df9f11f7555ea121815f7c5f0a656630aef3d267b29644f6eaaed";
const freshCue = () =>
  makeCue(1, {
    start: 10,
    end: 14.5,
    duration: 4.5,
    source: 'Hello "world"',
    target: "你好",
  });

describe("IssueCard", () => {
  it("dismisses the issue via the dismiss command", async () => {
    const api: Partial<Api> = {
      dismissIssue: vi.fn(async () => makeSnapshot("r2", [makeCue(1)])),
    };
    const services = createTestServices(
      { cues: [makeCue(1, { issues: [makeIssue("term")] })] },
      api,
    );
    const issue = makeIssue("term", { detail: { term: "LLM", expected: "大语言模型" } });
    renderWithServices(<IssueCard issue={issue} />, services);

    expect(screen.getByText(/大语言模型/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(api.dismissIssue).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ base_revision: "r1", kind: "term" }),
      ),
    );
  });

  it("launches the add-term dialog prefilled from the term detail", () => {
    const services = createTestServices({ cues: [makeCue(1)] });
    const issue = makeIssue("term", { detail: { term: "LLM", expected: "大语言模型" } });
    renderWithServices(<IssueCard issue={issue} />, services);
    fireEvent.click(screen.getByRole("button", { name: "Add glossary term" }));
    expect(services.store.getState().addTerm).toEqual({
      source: "LLM",
      target: "大语言模型",
      note: "",
    });
  });

  it("renders dismissed issues collapsed without actions", () => {
    const services = createTestServices({ cues: [makeCue(1)] });
    renderWithServices(<IssueCard issue={makeIssue("budget", { dismissed: true })} />, services);
    expect(screen.getByText("Dismissed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });
});

describe("SuggestionCard", () => {
  it("fills the draft when the proposed text is clicked (no mutation)", async () => {
    const services = createTestServices({
      cues: [freshCue()],
      suggestions: [makeSuggestion("s1", 1, { patch: { target: "proposed target" } })],
    });
    services.store.setState({
      draft: { source: 'Hello "world"', target: "你好", start: 10, end: 14.5, note: "" },
    });
    renderWithServices(
      <SuggestionCard suggestion={services.store.getState().suggestions[0]} />,
      services,
    );
    fireEvent.click(screen.getByText("proposed target"));
    expect(services.store.getState().draft?.target).toBe("proposed target");
    expect(services.store.getState().dirty).toBe(true);
  });

  it("accepts and rejects through commands without a confirm dialog", async () => {
    const api: Partial<Api> = {
      acceptSuggestion: vi.fn(async () => makeSnapshot("r2", [freshCue()])),
      rejectSuggestion: vi.fn(async () => makeSnapshot("r2", [freshCue()])),
    };
    const services = createTestServices(
      {
        cues: [freshCue()],
        suggestions: [makeSuggestion("s1", 1)],
      },
      api,
    );
    renderWithServices(
      <SuggestionCard suggestion={services.store.getState().suggestions[0]} />,
      services,
    );
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(api.acceptSuggestion).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ base_revision: "r1" }),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    // The accept bumped the revision, so the reject chains on it.
    await waitFor(() => expect(api.rejectSuggestion).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ base_revision: "r2" }),
    ));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("shows the stale hint only when the cue content drifted", () => {
    const services = createTestServices({
      cues: [freshCue()],
      suggestions: [makeSuggestion("s1", 1, { content_hash: FRESH_HASH })],
    });
    const { unmount } = renderWithServices(
      <SuggestionCard suggestion={services.store.getState().suggestions[0]} />,
      services,
    );
    expect(screen.queryByText("Suggestion may be stale")).toBeNull();
    unmount();

    services.store.setState({
      cues: [{ ...freshCue(), target: "您好" }],
    });
    renderWithServices(
      <SuggestionCard suggestion={services.store.getState().suggestions[0]} />,
      services,
    );
    expect(screen.getByText("Suggestion may be stale")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
  });
});
