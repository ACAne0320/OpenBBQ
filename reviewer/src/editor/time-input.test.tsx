import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../app/i18n";
import { TimeInput } from "./TimeInput";

function renderInput(props: {
  value?: number;
  validate?: (seconds: number) => boolean;
  onCommit?: (seconds: number) => void;
}) {
  const onCommit = props.onCommit ?? vi.fn();
  render(
    <I18nProvider initialLocale="en">
      <TimeInput
        label="Start"
        value={props.value ?? 83.456}
        validate={props.validate ?? (() => true)}
        onCommit={onCommit}
      />
    </I18nProvider>,
  );
  return onCommit;
}

describe("TimeInput", () => {
  it("shows the formatted value and commits a parsed edit on blur", () => {
    const onCommit = renderInput({});
    const input = screen.getByRole("textbox", { name: "Start" });
    expect(input).toHaveValue("01:23.456");

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "1:30" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(90);
    expect(input).toHaveValue("01:30.000");
  });

  it("accepts bare seconds and commits on Enter", () => {
    const onCommit = renderInput({});
    const input = screen.getByRole("textbox", { name: "Start" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "95.5" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommit).toHaveBeenCalledWith(95.5);
  });

  it("rejects invalid text with an inline hint and does not commit", () => {
    const onCommit = renderInput({});
    const input = screen.getByRole("textbox", { name: "Start" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "garbage" } });
    fireEvent.blur(input);
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByText("Use MM:SS.mmm, e.g. 1:23.456")).toBeInTheDocument();
    expect(input).toHaveValue("01:23.456");
  });

  it("rejects values failing validation (start<end) with an inline hint", () => {
    const onCommit = renderInput({ validate: (seconds) => seconds < 90 });
    const input = screen.getByRole("textbox", { name: "Start" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "2:00" } });
    fireEvent.blur(input);
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByText("Start must be before end")).toBeInTheDocument();
    expect(input).toHaveValue("01:23.456");
  });

  it("does not commit when the value parses to the current value", () => {
    const onCommit = renderInput({});
    const input = screen.getByRole("textbox", { name: "Start" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "83.456" } });
    fireEvent.blur(input);
    expect(onCommit).not.toHaveBeenCalled();
  });
});
