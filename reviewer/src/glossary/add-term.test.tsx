import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Api } from "../api/client";
import { CueEditor } from "../editor/CueEditor";
import { AddTermDialog } from "./AddTermDialog";
import {
  createTestServices,
  makeCue,
  makeSnapshot,
  renderWithServices,
} from "../test-utils";

function renderEditorWithDialog(api: Partial<Api>) {
  const services = createTestServices(
    { cues: [makeCue(1, { issues: [] })] },
    api,
  );
  services.store.setState({
    draft: { source: "Source 1", target: "目标 1", start: 10, end: 14, note: "" },
  });
  renderWithServices(
    <>
      <CueEditor />
      <AddTermDialog />
    </>,
    services,
  );
  return services;
}

describe("add-term flow", () => {
  it("opens the dialog prefilled, submits, applies the snapshot, and toasts", async () => {
    const api: Partial<Api> = {
      addGlossaryTerm: vi.fn(async () => ({
        ...makeSnapshot("r2", [makeCue(1)]),
        glossary: "ws",
        term_report: { added: ["LLM"], updated: [], unchanged: [], aliases_added: 0 },
      })),
    };
    const services = createTestServices({ cues: [makeCue(1)] }, api);
    // Imitate the App shell wiring a real localizer.
    services.commands.setLocalizer(
      (key, values) =>
        `${key}${values ? ` ${JSON.stringify(values)}` : ""}`,
    );
    services.store.setState({ addTerm: { source: "LLM", target: "大语言模型", note: "" } });
    renderWithServices(<AddTermDialog />, services);

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByLabelText("Source term")).toHaveValue("LLM");
    expect(within(dialog).getByLabelText("Translation")).toHaveValue("大语言模型");

    fireEvent.click(within(dialog).getByRole("button", { name: "Add term" }));
    await waitFor(() =>
      expect(api.addGlossaryTerm).toHaveBeenCalledWith(
        expect.objectContaining({ source: "LLM", target: "大语言模型" }),
      ),
    );
    await waitFor(() => {
      const toast = services.store.getState().toast;
      expect(toast).toContain("glossary.success");
      expect(toast).toContain("大语言模型");
    });
    expect(services.store.getState().addTerm).toBeNull();
    expect(services.store.getState().revision).toBe("r2");
  });

  it("requires both fields before submitting", async () => {
    const services = createTestServices({ cues: [makeCue(1)] }, {});
    services.store.setState({ addTerm: { source: "LLM", target: "", note: "" } });
    renderWithServices(<AddTermDialog />, services);
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: "Add term" })).toBeDisabled();
  });

  it("launches the dialog from a textarea selection in the editor", async () => {
    renderEditorWithDialog({});
    const source = screen.getByRole("textbox", { name: "Source" }) as HTMLTextAreaElement;
    // Select "Source" inside the source textarea.
    source.setSelectionRange(0, 6);
    fireEvent.select(source);
    const action = await screen.findByRole("button", { name: "Add selection to glossary" });
    fireEvent.click(action);

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByLabelText("Source term")).toHaveValue("Source");
    expect(within(dialog).getByLabelText("Translation")).toHaveValue("");
  });

  it("prefills the translation side when selecting in the target textarea", async () => {
    renderEditorWithDialog({});
    const target = screen.getByRole("textbox", {
      name: "zh translation",
    }) as HTMLTextAreaElement;
    target.setSelectionRange(0, 2);
    fireEvent.select(target);
    fireEvent.click(
      await screen.findByRole("button", { name: "Add selection to glossary" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByLabelText("Source term")).toHaveValue("");
    expect(within(dialog).getByLabelText("Translation")).toHaveValue("目标");
  });
});
