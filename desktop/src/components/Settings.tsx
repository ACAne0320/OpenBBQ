import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import type {
  DiagnosticCheck,
  DownloadFasterWhisperModelInput,
  FasterWhisperSettingsModel,
  LlmProviderModel,
  RuntimeModelDownloadJob,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SecretStatus
} from "../lib/types";
import { Button } from "./Button";

type SettingsSection = "llm" | "asr" | "diagnostics" | "advanced";
type ModelStatusUpdate = RuntimeModelStatus[] | ((current: RuntimeModelStatus[]) => RuntimeModelStatus[]);

export type SettingsProps = {
  loadSettings(): Promise<RuntimeSettingsModel>;
  loadModels(): Promise<RuntimeModelStatus[]>;
  downloadFasterWhisperModel(input: DownloadFasterWhisperModelInput): Promise<RuntimeModelDownloadJob>;
  getFasterWhisperModelDownload(jobId: string): Promise<RuntimeModelDownloadJob>;
  loadDiagnostics(): Promise<DiagnosticCheck[]>;
  saveRuntimeDefaults(input: { llmProvider: string; asrProvider: string }): Promise<RuntimeSettingsModel>;
  saveLlmProvider(input: {
    name: string;
    type: "openai_compatible";
    baseUrl: string | null;
    defaultChatModel: string | null;
    secretValue: string | null;
    apiKeyRef: string | null;
    displayName: string | null;
  }): Promise<LlmProviderModel>;
  checkLlmProvider(name: string): Promise<SecretStatus>;
  saveFasterWhisperDefaults(input: {
    cacheDir: string;
    defaultModel: string;
    defaultDevice: string;
    defaultComputeType: string;
  }): Promise<RuntimeSettingsModel>;
};

const fallbackFasterWhisperModels = ["tiny", "base", "small", "medium", "large-v3"];

type ProviderDraft = {
  displayName: string;
  baseUrl: string;
  defaultChatModel: string;
  apiKeyRef: string;
  secretValue: string;
};

function defaultApiKeyRef(name: string): string {
  return `sqlite:openbbq/providers/${name}/api_key`;
}

function providerDraft(provider: LlmProviderModel): ProviderDraft {
  return {
    displayName: provider.displayName ?? provider.name,
    baseUrl: provider.baseUrl ?? "",
    defaultChatModel: provider.defaultChatModel ?? "",
    apiKeyRef: provider.apiKeyRef ?? "",
    secretValue: ""
  };
}

function defaultLlmProvider(name: string): LlmProviderModel {
  return {
    name,
    type: "openai_compatible",
    baseUrl: null,
    apiKeyRef: defaultApiKeyRef(name),
    defaultChatModel: null,
    displayName: name
  };
}

function llmProviderOptions(settings: RuntimeSettingsModel): LlmProviderModel[] {
  const defaultName = settings.defaults.llmProvider;
  if (settings.llmProviders.some((provider) => provider.name === defaultName)) {
    return settings.llmProviders;
  }

  return [defaultLlmProvider(defaultName), ...settings.llmProviders];
}

function upsertProvider(providers: LlmProviderModel[], saved: LlmProviderModel): LlmProviderModel[] {
  if (!providers.some((provider) => provider.name === saved.name)) {
    return [...providers, saved];
  }

  return providers.map((provider) => (provider.name === saved.name ? saved : provider));
}

function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function fasterWhisperStatuses(models: RuntimeModelStatus[], defaultModel: string): RuntimeModelStatus[] {
  const fasterWhisperModels = models.filter((model) => model.provider === "faster-whisper");
  const byName = new Map(fasterWhisperModels.map((model) => [model.model, model]));
  const names = [...fallbackFasterWhisperModels, ...fasterWhisperModels.map((model) => model.model)];

  if (defaultModel.trim().length > 0) {
    names.push(defaultModel);
  }

  const uniqueNames = names.filter((name, index) => names.indexOf(name) === index);
  const defaultIndex = uniqueNames.indexOf(defaultModel);
  const orderedNames =
    defaultIndex > 0
      ? [defaultModel, ...uniqueNames.slice(0, defaultIndex), ...uniqueNames.slice(defaultIndex + 1)]
      : uniqueNames;

  return orderedNames.map(
    (model) =>
      byName.get(model) ?? {
        provider: "faster-whisper",
        model,
        cacheDir: "",
        present: false,
        sizeBytes: 0,
        error: "Status unavailable"
      }
  );
}

function fasterWhisperModelOptions(statuses: RuntimeModelStatus[], defaultModel: string): string[] {
  const options = [
    ...fallbackFasterWhisperModels,
    ...statuses.map((status) => status.model).filter((model) => !fallbackFasterWhisperModels.includes(model))
  ];

  if (defaultModel.trim().length > 0 && !options.includes(defaultModel)) {
    return [defaultModel, ...options];
  }

  return options;
}

function formatBytes(bytes: number): string | null {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return null;
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  if (unitIndex === 0) {
    return `${bytes} B`;
  }

  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

function upsertModelStatus(models: RuntimeModelStatus[], saved: RuntimeModelStatus): RuntimeModelStatus[] {
  if (!models.some((model) => model.provider === saved.provider && model.model === saved.model)) {
    return [...models, saved];
  }

  return models.map((model) => (model.provider === saved.provider && model.model === saved.model ? saved : model));
}

export function Settings({
  checkLlmProvider,
  downloadFasterWhisperModel,
  getFasterWhisperModelDownload,
  loadDiagnostics,
  loadModels,
  loadSettings,
  saveFasterWhisperDefaults,
  saveLlmProvider,
  saveRuntimeDefaults
}: SettingsProps) {
  const [section, setSection] = useState<SettingsSection>("llm");
  const [settings, setSettings] = useState<RuntimeSettingsModel | null>(null);
  const [models, setModels] = useState<RuntimeModelStatus[]>([]);
  const [diagnostics, setDiagnostics] = useState<DiagnosticCheck[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [asrFeedback, setAsrFeedback] = useState<string | null>(null);
  const [asrMutationError, setAsrMutationError] = useState<string | null>(null);
  const [downloadJobs, setDownloadJobs] = useState<Record<string, RuntimeModelDownloadJob>>({});
  const inFlightDownloadPolls = useRef<Set<string>>(new Set());
  const appliedDownloadJobs = useRef<Set<string>>(new Set());

  const applyDownloadJob = useCallback(
    async (job: RuntimeModelDownloadJob) => {
      if (job.status === "failed") {
        setAsrMutationError(job.error ?? "Model download failed.");
        return;
      }

      if (job.status !== "completed" || !job.modelStatus || appliedDownloadJobs.current.has(job.jobId)) {
        return;
      }

      appliedDownloadJobs.current.add(job.jobId);

      const downloaded = job.modelStatus;
      setModels((current) => upsertModelStatus(current, downloaded));
      setAsrFeedback("Model downloaded.");

      try {
        const refreshed = await loadModels();
        const hasDownloadedStatus = refreshed.some(
          (status) => status.provider === downloaded.provider && status.model === downloaded.model && status.present
        );

        setModels(hasDownloadedStatus ? refreshed : upsertModelStatus(refreshed, downloaded));
      } catch (refreshError) {
        setAsrMutationError(errorMessage(refreshError, "Model status could not be refreshed."));
      }
    },
    [loadModels]
  );

  const pollDownloadJob = useCallback(
    async (jobId: string) => {
      if (inFlightDownloadPolls.current.has(jobId) || appliedDownloadJobs.current.has(jobId)) {
        return;
      }

      inFlightDownloadPolls.current.add(jobId);

      try {
        const nextJob = await getFasterWhisperModelDownload(jobId);
        setDownloadJobs((current) => ({ ...current, [nextJob.model]: nextJob }));
        await applyDownloadJob(nextJob);
      } catch (pollError) {
        setAsrMutationError(errorMessage(pollError, "Model download status could not be refreshed."));
      } finally {
        inFlightDownloadPolls.current.delete(jobId);
      }
    },
    [applyDownloadJob, getFasterWhisperModelDownload]
  );

  const downloadModel = useCallback(
    async (model: string) => {
      setAsrFeedback(null);
      setAsrMutationError(null);

      try {
        const downloadJob = await downloadFasterWhisperModel({ model });
        setDownloadJobs((current) => ({ ...current, [downloadJob.model]: downloadJob }));
        await applyDownloadJob(downloadJob);
      } catch (downloadError) {
        setAsrMutationError(errorMessage(downloadError, "Model could not be downloaded."));
      }
    },
    [applyDownloadJob, downloadFasterWhisperModel]
  );

  useEffect(() => {
    let cancelled = false;

    Promise.all([loadSettings(), loadModels(), loadDiagnostics()])
      .then(([nextSettings, nextModels, nextDiagnostics]) => {
        if (cancelled) {
          return;
        }

        setSettings(nextSettings);
        setModels(nextModels);
        setDiagnostics(nextDiagnostics);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Settings could not be loaded.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [loadDiagnostics, loadModels, loadSettings]);

  useEffect(() => {
    const activeJobs = Object.values(downloadJobs).filter(isActiveModelDownloadJob);

    if (activeJobs.length === 0) {
      return undefined;
    }

    const interval = window.setInterval(() => {
      for (const job of activeJobs) {
        void pollDownloadJob(job.jobId);
      }
    }, 750);

    return () => window.clearInterval(interval);
  }, [downloadJobs, pollDownloadJob]);

  if (error) {
    return (
      <div role="alert" className="rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-[#6b3f27]">
        {error}
      </div>
    );
  }

  if (!settings) {
    return (
      <section aria-label="Settings loading" className="text-sm font-medium text-muted">
        Loading settings...
      </section>
    );
  }

  return (
    <section className="grid min-h-[calc(100vh-84px)] grid-cols-1 gap-5 xl:grid-cols-[190px_minmax(0,1fr)]">
      <aside className="rounded-lg bg-paper-side p-3 shadow-control">
        <h1 className="font-serif text-[36px] leading-none text-ink-brown">Settings</h1>
        <nav className="mt-5 grid gap-2" aria-label="Settings sections">
          <SectionButton active={section === "llm"} onClick={() => setSection("llm")}>
            LLM provider
          </SectionButton>
          <SectionButton active={section === "asr"} onClick={() => setSection("asr")}>
            ASR model
          </SectionButton>
          <SectionButton active={section === "diagnostics"} onClick={() => setSection("diagnostics")}>
            Diagnostics
          </SectionButton>
          <SectionButton active={section === "advanced"} onClick={() => setSection("advanced")}>
            Advanced
          </SectionButton>
        </nav>
      </aside>

      <div className="min-w-0">
        {section === "llm" ? (
          <LlmProviderSection
            checkLlmProvider={checkLlmProvider}
            saveLlmProvider={saveLlmProvider}
            saveRuntimeDefaults={saveRuntimeDefaults}
            settings={settings}
            onSettingsChange={setSettings}
          />
        ) : null}
        {section === "asr" ? (
          <AsrSection
            downloadJobs={downloadJobs}
            feedback={asrFeedback}
            loadModels={loadModels}
            models={models}
            mutationError={asrMutationError}
            onDownloadModel={downloadModel}
            onFeedbackChange={setAsrFeedback}
            onModelsChange={setModels}
            onMutationErrorChange={setAsrMutationError}
            saveFasterWhisperDefaults={saveFasterWhisperDefaults}
            settings={settings}
            onSettingsChange={setSettings}
          />
        ) : null}
        {section === "diagnostics" ? <DiagnosticsSection checks={diagnostics} models={models} /> : null}
        {section === "advanced" ? <AdvancedSection settings={settings} /> : null}
      </div>
    </section>
  );
}

function SectionButton({ active, children, onClick }: { active: boolean; children: string; onClick(): void }) {
  return (
    <Button
      variant={active ? "primary" : "secondary"}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className="justify-start rounded-sm px-3 py-2.5 text-left"
    >
      {children}
    </Button>
  );
}

function LlmProviderSection({
  checkLlmProvider,
  onSettingsChange,
  saveLlmProvider,
  saveRuntimeDefaults,
  settings
}: {
  settings: RuntimeSettingsModel;
  onSettingsChange(settings: RuntimeSettingsModel): void;
  saveRuntimeDefaults: SettingsProps["saveRuntimeDefaults"];
  saveLlmProvider: SettingsProps["saveLlmProvider"];
  checkLlmProvider: SettingsProps["checkLlmProvider"];
}) {
  const [selectedName, setSelectedName] = useState(settings.defaults.llmProvider);
  const providers = useMemo(() => llmProviderOptions(settings), [settings]);
  const selected = useMemo(
    () => providers.find((provider) => provider.name === selectedName) ?? providers[0],
    [providers, selectedName]
  );
  const [draft, setDraft] = useState<ProviderDraft>(() =>
    selected
      ? providerDraft(selected)
      : { displayName: "", baseUrl: "", defaultChatModel: "", apiKeyRef: "", secretValue: "" }
  );
  const [secretStatus, setSecretStatus] = useState<SecretStatus | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) {
      return;
    }

    setDraft(providerDraft(selected));
    setSecretStatus(null);
    setFeedback(null);
    setMutationError(null);
  }, [selected]);

  if (!selected) {
    return (
      <section aria-label="LLM provider settings" className="rounded-lg bg-paper-muted p-5 shadow-control">
        <h2 className="text-2xl font-extrabold leading-tight text-ink-brown">LLM provider</h2>
        <p className="mt-3 text-sm text-muted">No LLM providers are configured.</p>
      </section>
    );
  }

  async function saveProvider() {
    setFeedback(null);
    setMutationError(null);

    try {
      const secretValue = emptyToNull(draft.secretValue);
      const saved = await saveLlmProvider({
        name: selected.name,
        type: "openai_compatible",
        baseUrl: emptyToNull(draft.baseUrl),
        defaultChatModel: emptyToNull(draft.defaultChatModel),
        secretValue,
        apiKeyRef: secretValue
          ? defaultApiKeyRef(selected.name)
          : (emptyToNull(draft.apiKeyRef) ?? defaultApiKeyRef(selected.name)),
        displayName: emptyToNull(draft.displayName)
      });

      onSettingsChange({
        ...settings,
        llmProviders: upsertProvider(settings.llmProviders, saved)
      });
      setDraft((current) => ({ ...current, secretValue: "" }));
      setFeedback("Provider saved.");
    } catch (error) {
      setMutationError(errorMessage(error, "Provider could not be saved."));
    }
  }

  async function setDefaultProvider() {
    setFeedback(null);
    setMutationError(null);

    try {
      const updated = await saveRuntimeDefaults({
        llmProvider: selected.name,
        asrProvider: settings.defaults.asrProvider
      });
      onSettingsChange(updated);
      setFeedback("Default provider updated.");
    } catch (error) {
      setMutationError(errorMessage(error, "Default provider could not be updated."));
    }
  }

  async function checkSecret() {
    setFeedback(null);
    setMutationError(null);

    try {
      setSecretStatus(await checkLlmProvider(selected.name));
    } catch (error) {
      setSecretStatus(null);
      setMutationError(errorMessage(error, "Secret could not be checked."));
    }
  }

  return (
    <section className="grid grid-cols-1 gap-4 xl:grid-cols-[220px_minmax(0,1fr)]" aria-label="LLM provider settings">
      <aside className="rounded-lg bg-paper-muted p-3 shadow-control">
        <p className="text-xs font-bold uppercase text-muted">Providers</p>
        <div className="mt-3 grid gap-2">
          {providers.map((provider) => {
            const selectedProvider = provider.name === selected.name;
            return (
              <button
                key={provider.name}
                type="button"
                aria-pressed={selectedProvider}
                onClick={() => setSelectedName(provider.name)}
                className={
                  selectedProvider
                    ? "min-h-[74px] rounded-md bg-paper-selected px-3 py-2 text-left shadow-selected transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    : "min-h-[74px] rounded-md bg-paper px-3 py-2 text-left shadow-control transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [@media(hover:hover)]:hover:bg-paper-selected"
                }
              >
                <span className="block text-sm font-extrabold text-ink-brown">
                  {provider.displayName ?? provider.name}
                </span>
                <span className="mt-1 block text-xs text-muted">{provider.name}</span>
                {settings.defaults.llmProvider === provider.name ? (
                  <span className="mt-1 block text-xs font-bold text-ready">Default</span>
                ) : null}
              </button>
            );
          })}
        </div>
      </aside>

      <section className="rounded-lg bg-paper-muted p-5 shadow-control">
        <p className="text-xs font-bold uppercase text-muted">OpenAI-compatible profile</p>
        <h2 className="mt-2 text-2xl font-extrabold leading-tight text-ink-brown">{selected.name}</h2>

        <div className="mt-4 grid gap-3">
          <TextInput
            label="Display name"
            value={draft.displayName}
            onChange={(displayName) => setDraft((current) => ({ ...current, displayName }))}
          />
          <TextInput
            label="Base URL"
            value={draft.baseUrl}
            onChange={(baseUrl) => setDraft((current) => ({ ...current, baseUrl }))}
          />
          <TextInput
            label="Default chat model"
            value={draft.defaultChatModel}
            onChange={(defaultChatModel) => setDraft((current) => ({ ...current, defaultChatModel }))}
          />
          <SecretInput
            label="API key"
            value={draft.secretValue}
            onChange={(secretValue) => setDraft((current) => ({ ...current, secretValue }))}
          />
        </div>

        {secretStatus ? (
          <div className="mt-4 rounded-md bg-paper px-3 py-2 text-sm shadow-control" aria-live="polite">
            <span className="font-bold text-ink-brown">
              {secretStatus.resolved ? "Secret resolved" : "Secret unresolved"}
            </span>
            <span className="ml-2 text-muted">
              {secretStatus.resolved
                ? (secretStatus.valuePreview ?? "configured")
                : "API key is not configured."}
            </span>
          </div>
        ) : null}
        {feedback ? (
          <p className="mt-3 text-sm font-semibold text-ready" aria-live="polite">
            {feedback}
          </p>
        ) : null}
        {mutationError ? <InlineError>{mutationError}</InlineError> : null}

        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => void saveProvider()}>
            Save provider
          </Button>
          <Button variant="secondary" onClick={() => void setDefaultProvider()}>
            Set as default
          </Button>
          <Button variant="secondary" onClick={() => void checkSecret()}>
            Check secret
          </Button>
        </div>
      </section>
    </section>
  );
}

function AsrSection({
  downloadJobs,
  feedback,
  loadModels,
  models,
  mutationError,
  onDownloadModel,
  onFeedbackChange,
  onModelsChange,
  onMutationErrorChange,
  onSettingsChange,
  saveFasterWhisperDefaults,
  settings
}: {
  settings: RuntimeSettingsModel;
  models: RuntimeModelStatus[];
  downloadJobs: Record<string, RuntimeModelDownloadJob>;
  feedback: string | null;
  mutationError: string | null;
  loadModels: SettingsProps["loadModels"];
  onDownloadModel(model: string): Promise<void>;
  onFeedbackChange(feedback: string | null): void;
  onModelsChange(update: ModelStatusUpdate): void;
  onMutationErrorChange(error: string | null): void;
  onSettingsChange(settings: RuntimeSettingsModel): void;
  saveFasterWhisperDefaults: SettingsProps["saveFasterWhisperDefaults"];
}) {
  const [draft, setDraft] = useState<FasterWhisperSettingsModel>(settings.fasterWhisper);
  const statuses = useMemo(() => fasterWhisperStatuses(models, draft.defaultModel), [draft.defaultModel, models]);
  const modelOptions = useMemo(() => fasterWhisperModelOptions(statuses, draft.defaultModel), [draft.defaultModel, statuses]);

  async function saveDefaults() {
    onFeedbackChange(null);
    onMutationErrorChange(null);

    try {
      const updated = await saveFasterWhisperDefaults({
        cacheDir: draft.cacheDir,
        defaultModel: draft.defaultModel,
        defaultDevice: draft.defaultDevice,
        defaultComputeType: draft.defaultComputeType
      });
      setDraft(updated.fasterWhisper);
      onSettingsChange(updated);
      try {
        onModelsChange(await loadModels());
        onFeedbackChange("ASR defaults saved.");
      } catch (error) {
        onFeedbackChange("ASR defaults saved.");
        onMutationErrorChange(errorMessage(error, "Model status could not be refreshed."));
      }
    } catch (error) {
      onMutationErrorChange(errorMessage(error, "ASR defaults could not be saved."));
    }
  }

  return (
    <section className="grid grid-cols-1 gap-4 xl:grid-cols-[220px_minmax(0,1fr)]" aria-label="ASR model settings">
      <aside className="rounded-lg bg-paper-muted p-3 shadow-control">
        <p className="text-xs font-bold uppercase text-muted">ASR providers</p>
        <div className="mt-3 min-h-[74px] rounded-md bg-paper-selected px-3 py-2 shadow-selected">
          <span className="block text-sm font-extrabold text-ink-brown">faster-whisper</span>
          <span className="mt-1 block text-xs font-bold text-ready">Default</span>
        </div>
      </aside>

      <section className="rounded-lg bg-paper-muted p-5 shadow-control">
        <p className="text-xs font-bold uppercase text-muted">Runtime speech model</p>
        <h2 className="mt-2 text-2xl font-extrabold leading-tight text-ink-brown">faster-whisper</h2>

        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          <SelectInput
            label="Default model"
            options={modelOptions}
            value={draft.defaultModel}
            onChange={(defaultModel) => setDraft((current) => ({ ...current, defaultModel }))}
          />
          <TextInput
            label="Default device"
            value={draft.defaultDevice}
            onChange={(defaultDevice) => setDraft((current) => ({ ...current, defaultDevice }))}
          />
          <TextInput
            label="Default compute type"
            value={draft.defaultComputeType}
            onChange={(defaultComputeType) => setDraft((current) => ({ ...current, defaultComputeType }))}
          />
          <TextInput
            label="Cache directory"
            value={draft.cacheDir}
            onChange={(cacheDir) => setDraft((current) => ({ ...current, cacheDir }))}
          />
        </div>

        <div className="mt-5 grid gap-2">
          {statuses.map((status) => {
            const size = formatBytes(status.sizeBytes);
            const unavailable = modelStatusUnavailable(status);
            const job = downloadJobs[status.model];
            const busy = job ? isActiveModelDownloadJob(job) : false;
            return (
              <div
                key={status.model}
                className="grid gap-3 rounded-md bg-paper px-3 py-3 text-sm shadow-control md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-bold text-ink-brown">{status.model}</span>
                    <span className={modelStatusClass(status)}>{modelStatusLabel(status)}</span>
                    {size ? <span className="text-muted">{size}</span> : null}
                  </div>
                  <p className="mt-1 break-all text-xs text-muted">{status.cacheDir || draft.cacheDir}</p>
                  {job ? <ModelDownloadProgress job={job} /> : null}
                </div>
                <Button
                  variant="secondary"
                  aria-label={`Download ${status.model}`}
                  disabled={status.present || unavailable || busy}
                  onClick={() => void onDownloadModel(status.model)}
                >
                  {busy ? "Downloading" : "Download"}
                </Button>
              </div>
            );
          })}
        </div>
        {feedback ? (
          <p className="mt-3 text-sm font-semibold text-ready" aria-live="polite">
            {feedback}
          </p>
        ) : null}
        {mutationError ? <InlineError>{mutationError}</InlineError> : null}

        <div className="mt-5">
          <Button variant="primary" onClick={() => void saveDefaults()}>
            Save ASR defaults
          </Button>
        </div>
      </section>
    </section>
  );
}

function isActiveModelDownloadJob(job: RuntimeModelDownloadJob): boolean {
  return job.status === "queued" || job.status === "running";
}

function modelDownloadPercent(job: RuntimeModelDownloadJob): number {
  if (!Number.isFinite(job.percent)) {
    return 0;
  }

  return Math.max(0, Math.min(100, job.percent));
}

function ModelDownloadProgress({ job }: { job: RuntimeModelDownloadJob }) {
  const percent = modelDownloadPercent(job);
  const roundedPercent = Math.round(percent);

  return (
    <div className="mt-2 grid gap-1">
      <div
        role="progressbar"
        aria-label={`${job.model} download progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={roundedPercent}
        className="h-2 overflow-hidden rounded-full bg-[#d8c8ae]"
      >
        <div className="h-full rounded-full bg-ready" style={{ width: `${percent}%` }} />
      </div>
      <p className="text-xs font-bold text-ink-brown">{roundedPercent}%</p>
      {job.error ? <p className="text-xs font-semibold text-[#8a3f25]">{job.error}</p> : null}
    </div>
  );
}

function DiagnosticsSection({ checks, models }: { checks: DiagnosticCheck[]; models: RuntimeModelStatus[] }) {
  return (
    <section aria-label="Diagnostics" className="rounded-lg bg-paper-muted p-5 shadow-control">
      <p className="text-xs font-bold uppercase text-muted">Runtime health</p>
      <h2 className="mt-2 text-2xl font-extrabold leading-tight text-ink-brown">Diagnostics</h2>

      <div className="mt-4 grid gap-2">
        {checks.map((check) => (
          <div key={check.id} className="rounded-md bg-paper px-3 py-2 shadow-control">
            <div className="flex flex-wrap items-center gap-2">
              <strong className="text-sm text-ink-brown">{check.id}</strong>
              <span className="rounded-sm bg-paper-side px-2 py-1 text-xs font-bold text-muted">{check.status}</span>
              <span className="rounded-sm bg-accent-soft px-2 py-1 text-xs font-bold text-[#6b3f27]">
                {check.severity}
              </span>
            </div>
            <p className="mt-1 text-sm text-muted">{check.message}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-2">
        <h3 className="text-sm font-extrabold text-ink-brown">Model cache</h3>
        {models.map((model) => (
          <div key={`${model.provider}-${model.model}`} className="rounded-md bg-paper px-3 py-2 text-sm shadow-control">
            <span className="font-bold text-ink-brown">{model.provider}</span>
            <span className="ml-2 text-muted">{model.model}</span>
            <span className={model.present ? "ml-2 font-bold text-ready" : "ml-2 font-bold text-[#8c4d29]"}>
              {model.present ? "present" : "missing"}
            </span>
            {model.error ? <p className="mt-1 text-muted">{model.error}</p> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function modelStatusUnavailable(status: RuntimeModelStatus): boolean {
  return status.error !== null;
}

function modelStatusLabel(status: RuntimeModelStatus) {
  if (modelStatusUnavailable(status)) {
    return "Status unavailable";
  }

  return status.present ? "Downloaded" : "Not downloaded";
}

function modelStatusClass(status: RuntimeModelStatus) {
  if (modelStatusUnavailable(status)) {
    return "font-bold text-muted";
  }

  return status.present ? "font-bold text-ready" : "font-bold text-[#8c4d29]";
}

function AdvancedSection({ settings }: { settings: RuntimeSettingsModel }) {
  return (
    <section aria-label="Advanced" className="rounded-lg bg-paper-muted p-5 shadow-control">
      <p className="text-xs font-bold uppercase text-muted">Read-only paths</p>
      <h2 className="mt-2 text-2xl font-extrabold leading-tight text-ink-brown">Advanced</h2>
      <div className="mt-4 grid gap-3">
        <ReadOnlyRow label="Runtime config path" value={settings.configPath} />
        <ReadOnlyRow label="Cache root" value={settings.cacheRoot} />
        <ReadOnlyRow label="faster-whisper cache directory" value={settings.fasterWhisper.cacheDir} />
      </div>
    </section>
  );
}

function SelectInput({
  label,
  onChange,
  options,
  value
}: {
  label: string;
  value: string;
  options: string[];
  onChange(value: string): void;
}) {
  return (
    <label className="grid gap-2 text-xs font-bold uppercase text-muted">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-11 min-w-0 rounded-md bg-paper px-3 text-sm font-normal normal-case text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function SecretInput({
  label,
  onChange,
  value
}: {
  label: string;
  value: string;
  onChange(value: string): void;
}) {
  const inputId = useId();
  const [visible, setVisible] = useState(false);
  const labelText = visible ? "Hide API key" : "Show API key";

  return (
    <div className="grid gap-2 text-xs font-bold uppercase text-muted">
      <label htmlFor={inputId}>{label}</label>
      <div className="grid grid-cols-[minmax(0,1fr)_44px]">
        <input
          id={inputId}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="min-h-11 min-w-0 rounded-l-md bg-paper px-3 text-sm font-normal normal-case text-ink shadow-control focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
        <Button
          variant="secondary"
          aria-label={labelText}
          className="rounded-l-none px-0"
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? <EyeOff aria-hidden="true" className="mx-auto size-4" /> : <Eye aria-hidden="true" className="mx-auto size-4" />}
        </Button>
      </div>
    </div>
  );
}

function TextInput({
  label,
  onChange,
  type = "text",
  value
}: {
  label: string;
  value: string;
  type?: "password" | "text";
  onChange(value: string): void;
}) {
  return (
    <label className="grid gap-2 text-xs font-bold uppercase text-muted">
      {label}
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-11 min-w-0 rounded-md bg-paper px-3 text-sm font-normal normal-case text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      />
    </label>
  );
}

function ReadOnlyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-2 rounded-md bg-paper px-3 py-2 shadow-control">
      <span className="text-xs font-bold uppercase text-muted">{label}</span>
      <code className="break-all text-sm text-ink-brown">{value}</code>
    </div>
  );
}

function InlineError({ children }: { children: string }) {
  return (
    <p className="mt-3 rounded-md bg-accent-soft px-3 py-2 text-sm font-semibold text-[#6b3f27]" aria-live="assertive">
      {children}
    </p>
  );
}
