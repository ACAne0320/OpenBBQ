import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type Api } from "../api/client";
import type { BatchDryRunResult } from "../api/types";
import { FindReplacePanel, highlightSpans } from "./FindReplacePanel";
import {
  createTestServices,
  makeCue,
  makeSnapshot,
  renderWithServices,
} from "../test-utils";

const previewResult: BatchDryRunResult = {
  revision: "r1",
  matches: [
    {
      cue_id: 1,
      field: "source",
      spans: [[7, 12]],
      text: "Hello world today",
    },
    {
      cue_id: 2,
      field: "target",
      spans: [[0, 5], [6, 11]],
      text: "world of worlds",
    },
  ],
};

function renderPanel(api: Partial<Api>, selection: number[] = [1]) {
  const services = createTestServices(
    { cues: [makeCue(1), makeCue(2)], selection },
    api,
  );
  services.store.setState({ findOpen: true });
  renderWithServices(<FindReplacePanel />, services);
  return services;
}

describe("FindReplacePanel", () => {
  it("requires a dry-run preview before execute, then executes the batch", async () => {
    const api: Partial<Api> = {
      batchPreview: vi.fn(async () => previewResult),
      batchReplace: vi.fn(async () => makeSnapshot("r2", [makeCue(1), makeCue(2)])),
    };
    const services = renderPanel(api);

    const execute = screen.getByRole("button", { name: /Replace 0/ });
    expect(execute).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "Find" }), {
      target: { value: "world" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Replace with" }), {
      target: { value: "there" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(api.batchPreview).toHaveBeenCalledTimes(1));
    expect(api.batchPreview).toHaveBeenCalledWith(
      expect.objectContaining({
        find: "world",
        replace: "there",
        fields: ["source", "target"],
        case_sensitive: false,
        regex: false,
      }),
    );
    await screen.findByText("3 matches");
    expect(screen.getByText("#1")).toBeInTheDocument();

    const executeNow = screen.getByRole("button", { name: /Replace 3/ });
    expect(executeNow).toBeEnabled();
    fireEvent.click(executeNow);
    await waitFor(() =>
      expect(api.batchReplace).toHaveBeenCalledWith(
        expect.objectContaining({ base_revision: "r1", find: "world", replace: "there" }),
      ),
    );
    // Panel closes after a successful execute.
    await waitFor(() => expect(services.store.getState().findOpen).toBe(false));
  });

  it("invalidates the preview when any field changes", async () => {
    const api: Partial<Api> = { batchPreview: vi.fn(async () => previewResult) };
    renderPanel(api);
    fireEvent.change(screen.getByRole("textbox", { name: "Find" }), {
      target: { value: "world" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByText("3 matches");

    fireEvent.click(screen.getByLabelText("Regex"));
    expect(screen.queryByText("3 matches")).toBeNull();
    expect(screen.getByRole("button", { name: /Replace 0/ })).toBeDisabled();
  });

  it("shows the invalid_regex error inline and keeps the panel open", async () => {
    const api: Partial<Api> = {
      batchPreview: vi.fn(async () => {
        throw new ApiError(422, { error: "invalid_regex", detail: "nothing to repeat" });
      }),
    };
    renderPanel(api);
    fireEvent.change(screen.getByRole("textbox", { name: "Find" }), {
      target: { value: "w*(" },
    });
    fireEvent.click(screen.getByLabelText("Regex"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByText(/Invalid regular expression: nothing to repeat/);
    expect(screen.getByRole("button", { name: /Replace 0/ })).toBeDisabled();
  });

  it("scopes the request to the multi-selection when chosen", async () => {
    const api: Partial<Api> = { batchPreview: vi.fn(async () => previewResult) };
    renderPanel(api, [1, 2]);
    fireEvent.change(screen.getByRole("textbox", { name: "Find" }), {
      target: { value: "world" },
    });
    fireEvent.click(screen.getByLabelText(/Selected cues/));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() =>
      expect(api.batchPreview).toHaveBeenCalledWith(
        expect.objectContaining({ cue_ids: [1, 2] }),
      ),
    );
  });

  it("disables the selection scope when only one cue is selected", () => {
    renderPanel({}, [1]);
    expect(screen.getByLabelText(/Selected cues/)).toBeDisabled();
  });
});

describe("highlightSpans", () => {
  it("wraps each span in a mark", () => {
    const { container } = renderWithServices(
      <span>{highlightSpans({ cue_id: 1, field: "source", spans: [[0, 5], [10, 15]], text: "Hello new world" })}</span>,
      createTestServices({ cues: [makeCue(1)] }),
    );
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0].textContent).toBe("Hello");
    expect(marks[1].textContent).toBe("world");
  });
});
