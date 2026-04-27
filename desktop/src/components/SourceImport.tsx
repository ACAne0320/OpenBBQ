import { Upload } from "lucide-react";
import type { ChangeEvent, DragEvent, FormEvent, KeyboardEvent } from "react";
import { useRef, useState } from "react";

import type { SourceDraft } from "../lib/types";
import { Button } from "./Button";

type SourceImportProps = {
  onContinue: (source: SourceDraft) => void;
};

type LocalFileSource = Extract<SourceDraft, { kind: "local_file" }>;

const fileInputId = "source-local-file";
const supportedFileExtensions = [".mp4", ".mov", ".mkv", ".m4a", ".wav"];
const supportedFileTypes = new Set([
  "video/mp4",
  "video/quicktime",
  "video/x-matroska",
  "audio/mp4",
  "audio/wav",
  "audio/wave",
  "audio/x-wav"
]);
const unsupportedFileMessage = "Unsupported file type. Use MP4, MOV, MKV, M4A, or WAV.";

function getValidRemoteUrl(value: string): string | null {
  const trimmedValue = value.trim();
  if (trimmedValue.length === 0) {
    return null;
  }

  try {
    const parsedUrl = new URL(trimmedValue);
    return parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:" ? trimmedValue : null;
  } catch {
    return null;
  }
}

function toLocalFileSource(file: File): LocalFileSource {
  return {
    kind: "local_file",
    path: `browser-file://${encodeURIComponent(file.name)}`,
    displayName: file.name
  };
}

function isSupportedLocalFile(file: File): boolean {
  const normalizedName = file.name.toLowerCase();
  const hasSupportedExtension = supportedFileExtensions.some((extension) => normalizedName.endsWith(extension));
  const normalizedType = file.type.toLowerCase();

  return hasSupportedExtension || supportedFileTypes.has(normalizedType);
}

export function SourceImport({ onContinue }: SourceImportProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [localSource, setLocalSource] = useState<LocalFileSource | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const validRemoteUrl = getValidRemoteUrl(url);
  const sourceDraft: SourceDraft | null = validRemoteUrl
    ? { kind: "remote_url", url: validRemoteUrl }
    : localSource;
  const canContinue = sourceDraft !== null;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sourceDraft) {
      onContinue(sourceDraft);
    }
  }

  function handleUrlChange(event: ChangeEvent<HTMLInputElement>) {
    setUrl(event.target.value);
    setFileError(null);
    if (event.target.value.length > 0) {
      setLocalSource(null);
    }
  }

  function selectFile(file: File | undefined) {
    if (!file) {
      return;
    }

    if (!isSupportedLocalFile(file)) {
      setLocalSource(null);
      setFileError(unsupportedFileMessage);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }

    setUrl("");
    setFileError(null);
    setLocalSource(toLocalFileSource(file));
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0]);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    selectFile(event.dataTransfer.files[0]);
  }

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
  }

  function handleFileTargetKeyDown(event: KeyboardEvent<HTMLLabelElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInputRef.current?.click();
    }
  }

  return (
    <section className="grid min-h-[calc(100vh-84px)] grid-rows-[auto_1fr] gap-5">
      <header>
        <p className="text-[11px] uppercase text-muted">New task</p>
        <h1 className="mt-2 font-serif text-[40px] leading-none text-ink-brown">Choose a source</h1>
      </header>

      <form className="grid min-h-0 grid-rows-[1fr_auto] gap-4" onSubmit={handleSubmit}>
        <div className="grid min-h-[460px] grid-rows-[auto_auto_1fr] gap-6 rounded-xl bg-paper-muted p-7 shadow-control">
          <label className="grid gap-2 text-sm font-medium text-ink-brown">
            Video link
            <input
              aria-label="Video link"
              value={url}
              onChange={handleUrlChange}
              placeholder="https://www.youtube.com/watch?v=..."
              className="min-h-[60px] rounded-lg bg-paper px-4 text-base font-normal text-ink shadow-control placeholder:text-[#9c8e78] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
          </label>

          <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 text-xs text-[#8c7b61]">
            <div className="h-px bg-line" />
            <span className="rounded-full bg-paper px-3 py-1.5 shadow-control">or import a local file</span>
            <div className="h-px bg-line" />
          </div>

          <input
            id={fileInputId}
            ref={fileInputRef}
            type="file"
            accept=".mp4,.mov,.mkv,.m4a,.wav,video/mp4,video/quicktime,video/x-matroska,audio/mp4,audio/wav"
            aria-label="Drag/drop or click to choose a local file"
            className="sr-only"
            onChange={handleFileChange}
          />
          <label
            htmlFor={fileInputId}
            role="button"
            tabIndex={0}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onKeyDown={handleFileTargetKeyDown}
            className="flex min-h-[240px] items-center justify-center rounded-lg bg-paper text-center shadow-selected transition-transform duration-150 active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span className="px-6">
              <Upload className="mx-auto mb-4 h-12 w-12 text-accent" aria-hidden="true" />
              <span className="block text-[26px] font-extrabold leading-tight text-ink-brown">
                Drag/drop or click to choose a local file
              </span>
              <span className="mt-3 block text-sm leading-6 text-muted">
                {localSource ? `Selected: ${localSource.displayName}` : "Supported types: MP4, MOV, MKV, M4A, WAV"}
              </span>
              {fileError ? (
                <span className="mt-2 block text-sm font-semibold text-accent" role="alert">
                  {fileError}
                </span>
              ) : null}
            </span>
          </label>
        </div>

        <footer className="flex items-center justify-between gap-3 text-xs text-muted">
          <span>Continue unlocks after you add a source.</span>
          <div className="flex gap-2">
            <Button>Cancel</Button>
            <Button disabled={!canContinue} type="submit" variant={canContinue ? "primary" : "disabled"}>
              Continue
            </Button>
          </div>
        </footer>
      </form>
    </section>
  );
}
