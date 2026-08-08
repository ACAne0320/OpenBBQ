import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Api } from "../api/client";
import type { Cue, CueIssue, Progress, Session } from "../api/types";
import { I18nProvider } from "../app/i18n";
import { createAppServices, ServicesProvider, type AppServices } from "../app/services";
import { CUE_ROW_HEIGHT, CueListPanel } from "./CueListPanel";

const progress: Progress = { reviewed: 1, flagged: 1, unreviewed: 2, total: 4 };

function cue(id: number, overrides: Partial<Cue> = {}): Cue {
  return {
    id,
    start: id * 10,
    end: id * 10 + 4,
    duration: 4,
    source: `Source ${id}`,
    source_cps: 2.5,
    target: `目标 ${id}`,
    budget: null,
    over_budget: false,
    time_warning: false,
    term_warning: false,
    issues: [],
    status: "unreviewed",
    note: null,
    ...overrides,
  };
}

function issue(kind: CueIssue["kind"], overrides: Partial<CueIssue> = {}): CueIssue {
  return {
    cue_id: 1,
    kind,
    severity: "warning",
    message: kind,
    detail: {},
    source: "rule",
    dismissed: false,
    suggestion_ids: [],
    ...overrides,
  };
}

function testSession(): Session {
  return {
    workspace: "/tmp/review",
    title: "List test",
    source_type: "local_video",
    source_lang: "en",
    target_lang: "zh",
    languages: ["zh"],
    revision: "r1",
    progress,
    media: {
      kind: "video",
      url: "/api/media",
      name: "test.mp4",
      duration: 4000,
      playable: true,
      preview_status: "ready",
      preview_error: null,
    },
  };
}

function renderList(cues: Cue[]): AppServices {
  const services = createAppServices({} as Api);
  services.store.setState({
    session: testSession(),
    cues,
    revision: "r1",
    progress,
    selectedId: cues[0]?.id ?? null,
  });
  render(
    <I18nProvider initialLocale="en">
      <ServicesProvider services={services}>
        <CueListPanel />
      </ServicesProvider>
    </I18nProvider>,
  );
  return services;
}

describe("cue list", () => {
  it("virtualizes: renders only the visible window plus overscan", () => {
    const cues = Array.from({ length: 200 }, (_, index) => cue(index + 1));
    const { container } = render(
      <I18nProvider initialLocale="en">
        <ServicesProvider
          services={(() => {
            const services = createAppServices({} as Api);
            services.store.setState({
              session: testSession(),
              cues,
              revision: "r1",
              progress,
              selectedId: 1,
            });
            return services;
          })()}
        >
          <CueListPanel />
        </ServicesProvider>
      </I18nProvider>,
    );
    const rendered = container.querySelectorAll(".cue-row");
    expect(rendered.length).toBeGreaterThan(0);
    expect(rendered.length).toBeLessThan(30);
    const spacer = container.querySelector(".cue-list-spacer") as HTMLElement;
    expect(spacer.style.height).toBe(`${200 * CUE_ROW_HEIGHT}px`);
    // Rows are absolutely positioned at their virtual offset.
    const first = rendered[0] as HTMLElement;
    expect(first.style.transform).toBe("translateY(0px)");
  });

  it("shares one grid template between the header and the rows", () => {
    renderList([cue(1)]);
    const head = document.querySelector(".cue-table-head");
    const row = document.querySelector(".cue-summary");
    expect(head?.classList.contains("cue-grid")).toBe(true);
    expect(row?.classList.contains("cue-grid")).toBe(true);
  });

  it("renders issue badges with kind icons and semantics colors", () => {
    renderList([
      cue(1, {
        issues: [
          issue("term"),
          issue("budget"),
          issue("agent_note", { source: "agent", severity: "info" }),
          issue("timing", { dismissed: true }),
        ],
      }),
    ]);
    expect(screen.getByRole("img", { name: "Term issue" })).toHaveClass("warning");
    expect(screen.getByRole("img", { name: "Over budget" })).toHaveClass("warning");
    expect(screen.getByRole("img", { name: "Agent note" })).toHaveClass("agent");
    expect(screen.queryByRole("img", { name: "Timing issue" })).toBeNull();
  });

  it("filters by status, quality flag, and #id search", () => {
    const services = renderList([
      cue(1),
      cue(2, { status: "reviewed" }),
      cue(3, { status: "flagged" }),
      cue(7, { over_budget: true }),
    ]);
    expect(screen.getByRole("button", { name: "Unreviewed 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reviewed 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Flagged 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 4" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reviewed 1" }));
    expect(document.querySelectorAll(".cue-row")).toHaveLength(1);
    expect(screen.getByText("Source 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All 4" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search or #ID" }), {
      target: { value: "#7" },
    });
    expect(document.querySelectorAll(".cue-row")).toHaveLength(1);
    expect(screen.getByText("Source 7")).toBeInTheDocument();
    void services;
  });

  it("toggles list auto-scroll detachment from the toolbar", () => {
    const services = renderList([cue(1)]);
    const follow = screen.getByRole("button", { name: "Following playback" });
    expect(follow).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(follow);
    expect(screen.getByRole("button", { name: "Resume follow" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(services.store.getState().viewDetached).toBe(true);
  });

  it("detaches list auto-scroll on wheel and announces it with a toast", () => {
    const services = renderList([cue(1)]);
    fireEvent.wheel(document.querySelector(".cue-list")!);
    expect(services.store.getState().viewDetached).toBe(true);
    expect(services.store.getState().toast).toBe(
      "List stopped following — use Resume follow to jump back.",
    );
  });

  it("selects a cue from a row click", async () => {
    const services = renderList([cue(1), cue(2)]);
    fireEvent.click(screen.getByText("Source 2"));
    await waitFor(() => expect(services.store.getState().selectedId).toBe(2));
    expect(services.store.getState().currentTime).toBe(20);
  });
});
