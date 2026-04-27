import { Upload } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";

import type { SourceDraft } from "../lib/types";
import { Button } from "./Button";

type SourceImportProps = {
  onContinue: (source: SourceDraft) => void;
};

export function SourceImport({ onContinue }: SourceImportProps) {
  const [url, setUrl] = useState("");
  const trimmedUrl = url.trim();
  const canContinue = trimmedUrl.length > 0;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (canContinue) {
      onContinue({ kind: "remote_url", url: trimmedUrl });
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
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              className="min-h-[60px] rounded-lg bg-paper px-4 text-base font-normal text-ink shadow-control placeholder:text-[#9c8e78] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            />
          </label>

          <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 text-xs text-[#8c7b61]">
            <div className="h-px bg-line" />
            <span className="rounded-full bg-paper px-3 py-1.5 shadow-control">or import a local file</span>
            <div className="h-px bg-line" />
          </div>

          <button
            type="button"
            aria-label="Drag/drop or click to choose a local file"
            className="flex min-h-[240px] items-center justify-center rounded-lg bg-paper text-center shadow-selected transition-transform duration-150 active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span className="px-6">
              <Upload className="mx-auto mb-4 h-12 w-12 text-accent" aria-hidden="true" />
              <span className="block text-[26px] font-extrabold leading-tight text-ink-brown">
                Drag/drop or click to choose a local file
              </span>
              <span className="mt-3 block text-sm leading-6 text-muted">
                Supported types: MP4, MOV, MKV, M4A, WAV
              </span>
            </span>
          </button>
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
