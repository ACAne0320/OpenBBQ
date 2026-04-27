import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../../App";
import { SourceImport } from "../SourceImport";

describe("SourceImport", () => {
  it("starts with Continue disabled", () => {
    render(<SourceImport onContinue={vi.fn()} />);

    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });

  it("enables Continue after a valid HTTP URL is entered", async () => {
    const user = userEvent.setup();
    render(<SourceImport onContinue={vi.fn()} />);

    await user.type(screen.getByLabelText(/video link/i), "https://www.youtube.com/watch?v=abc");

    expect(screen.getByRole("button", { name: /continue/i })).toBeEnabled();
  });

  it("keeps Continue disabled for invalid or non-HTTP URLs", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<SourceImport onContinue={onContinue} />);

    await user.type(screen.getByLabelText(/video link/i), "not-a-url");
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();

    await user.clear(screen.getByLabelText(/video link/i));
    await user.type(screen.getByLabelText(/video link/i), "ftp://example.com/video.mp4");
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();

    await user.keyboard("{Enter}");
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("submits a trimmed remote URL source", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<SourceImport onContinue={onContinue} />);

    await user.type(screen.getByLabelText(/video link/i), "   https://www.youtube.com/watch?v=abc   ");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(onContinue).toHaveBeenCalledWith({
      kind: "remote_url",
      url: "https://www.youtube.com/watch?v=abc"
    });
  });

  it("keeps whitespace-only input disabled and does not submit", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<SourceImport onContinue={onContinue} />);

    await user.type(screen.getByLabelText(/video link/i), "   ");
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();

    await user.keyboard("{Enter}");
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("selects a local file from the hidden file input and submits it", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<SourceImport onContinue={onContinue} />);
    const file = new File(["video"], "clip.mov", { type: "video/quicktime" });

    await user.upload(screen.getByLabelText(/drag\/drop or click to choose a local file/i), file);

    expect(screen.getByRole("button", { name: /continue/i })).toBeEnabled();
    expect(screen.getByText(/clip\.mov/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(onContinue).toHaveBeenCalledWith({
      kind: "local_file",
      path: "browser-file://clip.mov",
      displayName: "clip.mov"
    });
  });

  it("selects a dropped local file and submits it", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<SourceImport onContinue={onContinue} />);
    const file = new File(["audio"], "voice.wav", { type: "audio/wav" });

    fireEvent.drop(screen.getByRole("button", { name: /drag\/drop or click to choose a local file/i }), {
      dataTransfer: { files: [file] }
    });

    expect(screen.getByRole("button", { name: /continue/i })).toBeEnabled();
    expect(screen.getByText(/voice\.wav/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(onContinue).toHaveBeenCalledWith({
      kind: "local_file",
      path: "browser-file://voice.wav",
      displayName: "voice.wav"
    });
  });

  it("rejects unsupported dropped files", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(<SourceImport onContinue={onContinue} />);
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });

    fireEvent.drop(screen.getByRole("button", { name: /drag\/drop or click to choose a local file/i }), {
      dataTransfer: { files: [file] }
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Unsupported file type");
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("renders as section content without owning another main surface", () => {
    render(<SourceImport onContinue={vi.fn()} />);

    expect(screen.queryByRole("main")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose a source" })).toBeInTheDocument();
  });

  it("updates shell footer context after a valid URL continues", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getAllByRole("main")).toHaveLength(1);

    await user.type(screen.getByLabelText(/video link/i), "https://example.com/video.mp4");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(screen.getByText("Source")).toBeInTheDocument();
    expect(screen.getByText("remote URL")).toBeInTheDocument();
  });
});
