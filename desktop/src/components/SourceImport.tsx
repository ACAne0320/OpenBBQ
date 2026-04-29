import { FileVideo, Link2, Upload } from "lucide-react";
import type { ChangeEvent, DragEvent, FormEvent, KeyboardEvent } from "react";
import { useRef, useState } from "react";

import type { SourceDraft } from "../lib/types";
import { Button } from "./Button";

type SourceImportProps = {
  onContinue: (source: SourceDraft) => void;
  onChooseLocalMedia?: () => Promise<LocalFileSource | null>;
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

export function SourceImport({ onChooseLocalMedia, onContinue }: SourceImportProps) {
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

  async function chooseLocalMedia() {
    if (!onChooseLocalMedia) {
      fileInputRef.current?.click();
      return;
    }

    const selected = await onChooseLocalMedia();
    if (!selected) {
      return;
    }

    setUrl("");
    setFileError(null);
    setLocalSource(selected);
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
      void chooseLocalMedia();
    }
  }

  return (
    <section className="grid min-h-[calc(100vh-76px)] grid-rows-[auto_1fr] gap-5">
      <header className="flex flex-col gap-1.5">
        <p className="text-[11px] font-semibold uppercase text-muted">New task</p>
        <h1 className="text-[32px] font-semibold leading-tight tracking-[-0.022em] text-ink-brown">Choose a source</h1>
        <p className="max-w-[68ch] text-sm leading-6 text-muted">
          Start with a remote video link or a local media file. OpenBBQ will build the matching subtitle workflow next.
        </p>
      </header>

      <form className="grid min-h-0 grid-rows-[1fr_auto] gap-4" onSubmit={handleSubmit}>
        <div className="grid min-h-[420px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
          <section className="grid content-start gap-4 rounded-xl bg-paper-muted p-5 shadow-control" aria-label="Remote video source">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-paper text-accent shadow-control">
                <Link2 className="h-5 w-5" aria-hidden="true" />
              </span>
              <span>
                <span className="block text-lg font-semibold tracking-[-0.012em] text-ink-brown">Remote video</span>
                <span className="mt-1 block text-sm leading-6 text-muted">Paste a source URL and OpenBBQ will choose the remote workflow.</span>
              </span>
            </div>
            <label className="mt-3 grid gap-2 text-sm font-medium text-ink-brown">
              Video link
              <input
                aria-label="Video link"
                value={url}
                onChange={handleUrlChange}
                placeholder="https://www.youtube.com/watch?v=..."
                className="min-h-[52px] rounded-lg bg-paper px-4 text-base font-normal text-ink shadow-control placeholder:text-muted/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              />
            </label>
            <div className="grid gap-2 rounded-lg bg-paper px-3.5 py-3 text-sm shadow-control">
              <span className="font-semibold text-ink-brown">Workflow preview</span>
              <span className="text-muted">Fetch source, extract audio, transcribe, translate, then prepare subtitle review.</span>
            </div>
          </section>

          <section className="grid gap-4 rounded-xl bg-paper-muted p-5 shadow-control" aria-label="Local media source">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-paper text-accent shadow-control">
                <FileVideo className="h-5 w-5" aria-hidden="true" />
              </span>
              <span>
                <span className="block text-lg font-semibold tracking-[-0.012em] text-ink-brown">Local media</span>
                <span className="mt-1 block text-sm leading-6 text-muted">Use a local file when the source is already downloaded.</span>
              </span>
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
              htmlFor={onChooseLocalMedia ? undefined : fileInputId}
              role="button"
              tabIndex={0}
              onClick={(event) => {
                if (!onChooseLocalMedia) {
                  return;
                }
                event.preventDefault();
                void chooseLocalMedia();
              }}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onKeyDown={handleFileTargetKeyDown}
              className="flex min-h-[210px] items-center justify-center rounded-lg bg-paper text-center shadow-selected transition-transform duration-150 active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span className="px-6">
                <span className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-lg bg-accent-soft text-accent">
                  <Upload className="h-6 w-6" aria-hidden="true" />
                </span>
                <span className="block text-[18px] font-semibold leading-tight tracking-[-0.012em] text-ink-brown">
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
          </section>
        </div>

        <footer className="flex flex-col gap-3 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
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
