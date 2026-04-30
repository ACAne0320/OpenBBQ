import { FileVideo, Link2, Upload } from "lucide-react";
import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { RemoteVideoFormatInput, SelectOption, SourceDraft, WorkflowDefinition, WorkflowStep } from "../lib/types";
import { Button } from "./Button";

type WorkflowUseProps = {
  workflow: WorkflowDefinition;
  onBack: () => void;
  onChooseLocalMedia?: () => Promise<Extract<SourceDraft, { kind: "local_file" }> | null>;
  onLoadRemoteVideoFormats?: (input: RemoteVideoFormatInput) => Promise<SelectOption[]>;
  onRunTask: (source: SourceDraft, steps: WorkflowStep[]) => void;
};

const fileInputId = "workflow-use-local-file";
const defaultRemoteQuality = "best[ext=mp4][height<=720]/best[height<=720]/best";
const fallbackQualityOptions: SelectOption[] = [
  { value: defaultRemoteQuality, label: "Best up to 720p" },
  { value: "best[ext=mp4][height<=1080]/best[height<=1080]/best", label: "Best up to 1080p" },
  { value: "best", label: "Best available" }
];
const authOptions: Array<{ value: RemoteVideoFormatInput["auth"]; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "anonymous", label: "Anonymous" },
  { value: "browser_cookies", label: "Browser cookies" }
];

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

function toLocalFileSource(file: File): Extract<SourceDraft, { kind: "local_file" }> {
  return {
    kind: "local_file",
    path: `browser-file://${encodeURIComponent(file.name)}`,
    displayName: file.name
  };
}

function sourceSummary(source: SourceDraft | null) {
  if (!source) {
    return "No source selected";
  }
  return source.kind === "remote_url" ? source.url : source.displayName;
}

function selectOptionValue(option: SelectOption) {
  return typeof option === "string" ? option : option.value;
}

function selectOptionLabel(option: SelectOption) {
  return typeof option === "string" ? option : option.label;
}

function stepParameterValue(steps: WorkflowStep[], stepId: string, key: string, fallback: string) {
  const parameter = steps.find((step) => step.id === stepId || step.id === "fetch_source")?.parameters.find((item) => item.key === key);
  if (!parameter || parameter.kind === "toggle") {
    return fallback;
  }
  return parameter.value || fallback;
}

function remoteStepId(steps: WorkflowStep[]) {
  return steps.some((step) => step.id === "download") ? "download" : "fetch_source";
}

function mergeSelectedOption(options: SelectOption[], selectedValue: string) {
  if (options.some((option) => selectOptionValue(option) === selectedValue)) {
    return options;
  }
  return [{ value: selectedValue, label: "Configured quality" }, ...options];
}

function patchStepParameter(step: WorkflowStep, key: string, value: string): WorkflowStep {
  const parameterExists = step.parameters.some((parameter) => parameter.key === key);
  if (!parameterExists) {
    return {
      ...step,
      parameters: [...step.parameters, { kind: "text", key, label: key.replace(/_/g, " "), value }]
    };
  }
  return {
    ...step,
    parameters: step.parameters.map((parameter) => {
      if (parameter.key !== key || parameter.kind === "toggle") {
        return parameter;
      }
      return { ...parameter, value };
    })
  };
}

function patchRemoteStep(
  steps: WorkflowStep[],
  source: Extract<SourceDraft, { kind: "remote_url" }>,
  settings: {
    quality: string;
    auth: RemoteVideoFormatInput["auth"];
    browser: string;
    browserProfile: string;
  }
) {
  const stepId = remoteStepId(steps);
  return steps.map((step) => {
    if (step.id !== stepId) {
      return step;
    }
    let nextStep = patchStepParameter(step, "url", source.url);
    nextStep = patchStepParameter(nextStep, "quality", settings.quality);
    nextStep = patchStepParameter(nextStep, "auth", settings.auth);
    nextStep = patchStepParameter(nextStep, "browser", settings.browser);
    nextStep = patchStepParameter(nextStep, "browser_profile", settings.browserProfile);
    return nextStep;
  });
}

export function WorkflowUse({ onBack, onChooseLocalMedia, onLoadRemoteVideoFormats, onRunTask, workflow }: WorkflowUseProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [localSource, setLocalSource] = useState<Extract<SourceDraft, { kind: "local_file" }> | null>(null);
  const [remoteAuth, setRemoteAuth] = useState<RemoteVideoFormatInput["auth"]>(
    stepParameterValue(workflow.steps, remoteStepId(workflow.steps), "auth", "auto") as RemoteVideoFormatInput["auth"]
  );
  const [browser, setBrowser] = useState(stepParameterValue(workflow.steps, remoteStepId(workflow.steps), "browser", ""));
  const [browserProfile, setBrowserProfile] = useState(
    stepParameterValue(workflow.steps, remoteStepId(workflow.steps), "browser_profile", "")
  );
  const [quality, setQuality] = useState(stepParameterValue(workflow.steps, remoteStepId(workflow.steps), "quality", defaultRemoteQuality));
  const [qualityOptions, setQualityOptions] = useState<SelectOption[]>(fallbackQualityOptions);
  const [formatsLoading, setFormatsLoading] = useState(false);
  const [formatsError, setFormatsError] = useState<string | null>(null);
  const supportsLocal = workflow.sourceTypes.includes("local_file");
  const supportsRemote = workflow.sourceTypes.includes("remote_url");
  const validRemoteUrl = supportsRemote ? getValidRemoteUrl(url) : null;
  const source: SourceDraft | null = validRemoteUrl ? { kind: "remote_url", url: validRemoteUrl } : localSource;
  const mergedQualityOptions = useMemo(() => mergeSelectedOption(qualityOptions, quality), [quality, qualityOptions]);
  const canRun = source !== null && workflow.sourceTypes.includes(source.kind) && !formatsLoading;

  useEffect(() => {
    if (!validRemoteUrl || !onLoadRemoteVideoFormats) {
      setFormatsLoading(false);
      setFormatsError(null);
      return undefined;
    }

    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      setFormatsLoading(true);
      setFormatsError(null);
      void onLoadRemoteVideoFormats({
        url: validRemoteUrl,
        auth: remoteAuth,
        browser: browser || null,
        browserProfile: browserProfile || null
      })
        .then((formats) => {
          if (cancelled) {
            return;
          }
          setQualityOptions(formats.length > 0 ? formats : fallbackQualityOptions);
        })
        .catch((error) => {
          if (cancelled) {
            return;
          }
          const message = error instanceof Error && error.message ? error.message : "format lookup failed";
          setFormatsError(`Could not load video formats: ${message}`);
          setQualityOptions(fallbackQualityOptions);
        })
        .finally(() => {
          if (!cancelled) {
            setFormatsLoading(false);
          }
        });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [browser, browserProfile, onLoadRemoteVideoFormats, remoteAuth, validRemoteUrl]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (source && canRun) {
      const runSteps =
        source.kind === "remote_url"
          ? patchRemoteStep(workflow.steps, source, { quality, auth: remoteAuth, browser, browserProfile })
          : workflow.steps;
      onRunTask(source, runSteps);
    }
  }

  function handleUrlChange(event: ChangeEvent<HTMLInputElement>) {
    setUrl(event.target.value);
    if (event.target.value.length > 0) {
      setLocalSource(null);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setUrl("");
    setLocalSource(toLocalFileSource(file));
  }

  async function chooseLocalMedia() {
    if (!supportsLocal) {
      return;
    }
    if (!onChooseLocalMedia) {
      fileInputRef.current?.click();
      return;
    }

    const selected = await onChooseLocalMedia();
    if (!selected) {
      return;
    }
    setUrl("");
    setLocalSource(selected);
  }

  return (
    <section className="grid min-h-[calc(100vh-76px)] grid-rows-[auto_1fr_auto] gap-5">
      <header className="flex flex-col gap-1.5">
        <p className="text-[11px] font-semibold uppercase text-muted">Use workflow</p>
        <h1 className="text-[32px] font-semibold leading-tight tracking-[-0.022em] text-ink-brown">{workflow.name}</h1>
        <p className="max-w-[68ch] text-sm leading-6 text-muted">
          Choose the source for this run. Workflow defaults stay unchanged unless you customize the workflow.
        </p>
      </header>

      <form className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]" onSubmit={handleSubmit}>
        <div className="grid content-start gap-4">
          <section className="rounded-xl bg-paper-muted p-4 shadow-control" aria-label="Workflow source">
            <div className="mb-4 flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-paper text-accent shadow-control">
                <Upload className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-[20px] font-semibold leading-tight tracking-[-0.012em] text-ink-brown">Source</h2>
                <p className="mt-1.5 text-sm text-muted">Only compatible source inputs are enabled for this workflow.</p>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <label
                className={
                  supportsRemote
                    ? "grid gap-3 rounded-lg bg-paper p-4 shadow-control"
                    : "grid gap-3 rounded-lg bg-paper-side p-4 text-muted shadow-none"
                }
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-ink-brown">
                  <Link2 className="h-4 w-4 text-accent" aria-hidden="true" />
                  Remote URL
                </span>
                <input
                  aria-label="Remote URL"
                  disabled={!supportsRemote}
                  value={url}
                  onChange={handleUrlChange}
                  placeholder="https://www.youtube.com/watch?v=..."
                  className="min-h-11 rounded-md bg-paper-muted px-3 text-sm font-normal text-ink shadow-control placeholder:text-muted/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-paper-side"
                />
              </label>

              <div
                className={
                  supportsLocal
                    ? "grid gap-3 rounded-lg bg-paper p-4 shadow-control"
                    : "grid gap-3 rounded-lg bg-paper-side p-4 text-muted shadow-none"
                }
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-ink-brown">
                  <FileVideo className="h-4 w-4 text-accent" aria-hidden="true" />
                  Local media
                </span>
                <input
                  id={fileInputId}
                  ref={fileInputRef}
                  type="file"
                  className="sr-only"
                  accept=".mp4,.mov,.mkv,.m4a,.wav,video/mp4,video/quicktime,video/x-matroska,audio/mp4,audio/wav"
                  onChange={handleFileChange}
                />
                <Button disabled={!supportsLocal} onClick={chooseLocalMedia} variant={supportsLocal ? "secondary" : "disabled"}>
                  Choose file
                </Button>
                <span className="text-xs leading-snug text-muted">{localSource?.displayName ?? "MP4, MOV, MKV, M4A, WAV"}</span>
              </div>
            </div>
          </section>
          {supportsRemote ? (
            <section className="rounded-xl bg-paper-muted p-4 shadow-control" aria-label="Remote options">
              <div className="mb-4">
                <h2 className="text-[20px] font-semibold leading-tight tracking-[-0.012em] text-ink-brown">Remote options</h2>
                <p className="mt-1.5 text-sm text-muted">These settings apply only to this task run.</p>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <label className="grid gap-2 text-xs font-medium text-muted">
                  Auth
                  <select
                    value={remoteAuth}
                    onChange={(event) => setRemoteAuth(event.target.value as RemoteVideoFormatInput["auth"])}
                    className="min-h-11 rounded-md bg-paper px-3 text-sm font-normal text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    {authOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-2 text-xs font-medium text-muted">
                  Quality
                  <select
                    value={quality}
                    onChange={(event) => setQuality(event.target.value)}
                    disabled={!validRemoteUrl || formatsLoading}
                    className="min-h-11 rounded-md bg-paper px-3 text-sm font-normal text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-paper-side"
                  >
                    {mergedQualityOptions.map((option) => (
                      <option key={selectOptionValue(option)} value={selectOptionValue(option)}>
                        {selectOptionLabel(option)}
                      </option>
                    ))}
                  </select>
                </label>
                {remoteAuth === "browser_cookies" ? (
                  <>
                    <label className="grid gap-2 text-xs font-medium text-muted">
                      Browser
                      <input
                        value={browser}
                        onChange={(event) => setBrowser(event.target.value)}
                        placeholder="edge"
                        className="min-h-11 rounded-md bg-paper px-3 text-sm font-normal text-ink shadow-control placeholder:text-muted/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      />
                    </label>
                    <label className="grid gap-2 text-xs font-medium text-muted">
                      Browser profile
                      <input
                        value={browserProfile}
                        onChange={(event) => setBrowserProfile(event.target.value)}
                        placeholder="Default"
                        className="min-h-11 rounded-md bg-paper px-3 text-sm font-normal text-ink shadow-control placeholder:text-muted/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      />
                    </label>
                  </>
                ) : null}
              </div>
              <div className="mt-3 min-h-5 text-xs text-muted">
                {formatsLoading ? "Checking available formats..." : formatsError}
              </div>
            </section>
          ) : null}
        </div>

        <aside className="grid content-start gap-4 rounded-xl bg-paper-muted p-4 shadow-control">
          <div className="rounded-lg bg-paper p-4 shadow-control">
            <p className="text-xs uppercase text-muted">Workflow</p>
            <h2 className="mt-2 text-[20px] font-semibold leading-tight tracking-[-0.012em] text-ink-brown">
              {workflow.name}
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted">{workflow.description}</p>
          </div>
          <div className="rounded-lg bg-paper p-4 text-sm shadow-control">
            <span className="font-semibold text-ink-brown">Selected source</span>
            <span className="mt-2 block break-words text-muted">{sourceSummary(source)}</span>
          </div>
          <div className="rounded-lg bg-paper p-4 text-sm shadow-control">
            <span className="font-semibold text-ink-brown">Defaults</span>
            <span className="mt-2 block text-muted">{workflow.steps.length} configured steps</span>
            {source?.kind === "remote_url" ? (
              <span className="mt-2 block text-muted">Quality: {selectOptionLabel(mergedQualityOptions.find((option) => selectOptionValue(option) === quality) ?? quality)}</span>
            ) : null}
          </div>
        </aside>

        <footer className="flex items-center justify-end gap-2 xl:col-span-2">
          <Button onClick={onBack} variant="secondary">
            Back
          </Button>
          <Button disabled={!canRun} type="submit" variant={canRun ? "primary" : "disabled"}>
            Run task
          </Button>
        </footer>
      </form>
    </section>
  );
}
