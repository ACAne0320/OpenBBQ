import { clsx } from "clsx";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Eye, EyeOff, Plus, X } from "lucide-react";

import type {
  DiagnosticCheck,
  DownloadFasterWhisperModelInput,
  FasterWhisperSettingsModel,
  LlmProviderModel,
  ProviderModelOption,
  RuntimeModelDownloadJob,
  RuntimeModelStatus,
  RuntimeSettingsModel
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
  getLlmProviderSecret(name: string): Promise<string>;
  getLlmProviderModels(name: string): Promise<ProviderModelOption[]>;
  testLlmProviderConnection(input: {
    providerName?: string | null;
    baseUrl: string;
    apiKey: string | null;
    model: string;
  }): Promise<{ ok: boolean; message: string }>;
  saveFasterWhisperDefaults(input: {
    cacheDir: string;
    defaultModel: string;
    defaultDevice: string;
    defaultComputeType: string;
  }): Promise<RuntimeSettingsModel>;
};

const fallbackFasterWhisperModels = ["tiny", "base", "small", "medium", "large-v3"];

type ProviderDraft = {
  name: string;
  baseUrl: string;
  defaultChatModel: string;
  apiKeyRef: string;
  secretValue: string;
};

const providerPresets: LlmProviderModel[] = [
  {
    name: "openai",
    type: "openai_compatible",
    baseUrl: "https://api.openai.com/v1",
    apiKeyRef: null,
    defaultChatModel: null,
    displayName: null
  },
  {
    name: "deepseek",
    type: "openai_compatible",
    baseUrl: "https://api.deepseek.com",
    apiKeyRef: null,
    defaultChatModel: null,
    displayName: null
  },
  {
    name: "openrouter",
    type: "openai_compatible",
    baseUrl: "https://openrouter.ai/api/v1",
    apiKeyRef: null,
    defaultChatModel: null,
    displayName: null
  },
  {
    name: "ollama",
    type: "openai_compatible",
    baseUrl: "http://127.0.0.1:11434/v1",
    apiKeyRef: null,
    defaultChatModel: null,
    displayName: null
  }
];

function defaultApiKeyRef(name: string): string {
  return `sqlite:openbbq/providers/${name}/api_key`;
}

function providerDraft(provider: LlmProviderModel): ProviderDraft {
  return {
    name: providerDisplayName(provider),
    baseUrl: provider.baseUrl ?? "",
    defaultChatModel: provider.defaultChatModel ?? "",
    apiKeyRef: provider.apiKeyRef ?? "",
    secretValue: ""
  };
}

function providerDisplayName(provider: LlmProviderModel): string {
  return provider.displayName ?? provider.name;
}

function providerStorageName(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function defaultLlmProvider(name: string): LlmProviderModel {
  return {
    name,
    type: "openai_compatible",
    baseUrl: null,
    apiKeyRef: defaultApiKeyRef(name),
    defaultChatModel: null,
    displayName: null
  };
}

function llmProviderOptions(settings: RuntimeSettingsModel): LlmProviderModel[] {
  const defaultName = settings.defaults.llmProvider;
  const providersByName = new Map<string, LlmProviderModel>();

  for (const provider of providerPresets) {
    providersByName.set(provider.name, provider);
  }
  for (const provider of settings.llmProviders) {
    providersByName.set(provider.name, provider);
  }

  if (!providersByName.has(defaultName)) {
    providersByName.set(defaultName, defaultLlmProvider(defaultName));
  }

  return [...providersByName.values()];
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

function modelStatusKey(status: RuntimeModelStatus): string {
  return `${status.provider}:${status.model}`;
}

function sameModelStatus(left: RuntimeModelStatus, right: RuntimeModelStatus): boolean {
  return left.provider === right.provider && left.model === right.model;
}

function mergeRefreshedModelStatuses(
  models: RuntimeModelStatus[],
  currentModels: RuntimeModelStatus[],
  completedStatuses: Iterable<RuntimeModelStatus>
): RuntimeModelStatus[] {
  let merged = models;

  for (const status of completedStatuses) {
    const currentStatus = currentModels.find((model) => sameModelStatus(model, status));
    const statusToPreserve = currentStatus?.present ? currentStatus : status;

    if (statusToPreserve.present) {
      merged = upsertModelStatus(merged, statusToPreserve);
    }
  }

  return merged;
}

export function Settings({
  downloadFasterWhisperModel,
  getFasterWhisperModelDownload,
  getLlmProviderSecret,
  getLlmProviderModels,
  loadDiagnostics,
  loadModels,
  loadSettings,
  saveFasterWhisperDefaults,
  saveLlmProvider,
  saveRuntimeDefaults,
  testLlmProviderConnection
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
  const completedDownloadStatuses = useRef<Map<string, RuntimeModelStatus>>(new Map());
  const downloadStateGeneration = useRef(0);

  const resetDownloadState = useCallback(() => {
    downloadStateGeneration.current += 1;
    inFlightDownloadPolls.current.clear();
    appliedDownloadJobs.current.clear();
    completedDownloadStatuses.current.clear();
    setDownloadJobs({});
  }, []);

  const applyDownloadJob = useCallback(
    async (job: RuntimeModelDownloadJob, generation: number) => {
      if (generation !== downloadStateGeneration.current) {
        return;
      }

      if (job.status === "failed") {
        setAsrMutationError(job.error ?? "Model download failed.");
        return;
      }

      if (job.status !== "completed" || !job.modelStatus || appliedDownloadJobs.current.has(job.jobId)) {
        return;
      }

      appliedDownloadJobs.current.add(job.jobId);

      const downloaded = job.modelStatus;
      completedDownloadStatuses.current.set(modelStatusKey(downloaded), downloaded);
      setModels((current) => upsertModelStatus(current, downloaded));
      setAsrFeedback("Model downloaded.");

      try {
        const refreshed = await loadModels();
        if (generation !== downloadStateGeneration.current) {
          return;
        }

        const hasDownloadedStatus = refreshed.some(
          (status) => status.provider === downloaded.provider && status.model === downloaded.model && status.present
        );

        setModels((current) =>
          mergeRefreshedModelStatuses(
            hasDownloadedStatus ? refreshed : upsertModelStatus(refreshed, downloaded),
            current,
            completedDownloadStatuses.current.values()
          )
        );
      } catch (refreshError) {
        if (generation === downloadStateGeneration.current) {
          setAsrMutationError(errorMessage(refreshError, "Model status could not be refreshed."));
        }
      }
    },
    [loadModels]
  );

  const pollDownloadJob = useCallback(
    async (jobId: string) => {
      if (inFlightDownloadPolls.current.has(jobId) || appliedDownloadJobs.current.has(jobId)) {
        return;
      }

      const generation = downloadStateGeneration.current;
      inFlightDownloadPolls.current.add(jobId);

      try {
        const nextJob = await getFasterWhisperModelDownload(jobId);
        if (generation !== downloadStateGeneration.current) {
          return;
        }

        setDownloadJobs((current) => ({ ...current, [nextJob.model]: nextJob }));
        await applyDownloadJob(nextJob, generation);
      } catch (pollError) {
        if (generation === downloadStateGeneration.current) {
          setAsrMutationError(errorMessage(pollError, "Model download status could not be refreshed."));
        }
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
      const generation = downloadStateGeneration.current;

      try {
        const downloadJob = await downloadFasterWhisperModel({ model });
        if (generation !== downloadStateGeneration.current) {
          return;
        }

        setDownloadJobs((current) => ({ ...current, [downloadJob.model]: downloadJob }));
        await applyDownloadJob(downloadJob, generation);
      } catch (downloadError) {
        if (generation === downloadStateGeneration.current) {
          setAsrMutationError(errorMessage(downloadError, "Model could not be downloaded."));
        }
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
      <div role="alert" className="rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-ink">
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
    <section className="grid min-h-[calc(100vh-76px)] grid-rows-[auto_minmax(0,1fr)] gap-5">
      <header>
        <p className="text-[11px] font-semibold uppercase text-muted">Runtime</p>
        <h1 className="mt-2 text-[32px] font-semibold leading-tight tracking-[-0.022em] text-ink-brown">Settings</h1>
        <p className="mt-2 max-w-[68ch] text-sm leading-6 text-muted">
          Configure providers, local speech models, diagnostics, and read-only runtime paths.
        </p>
      </header>

      <div className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="rounded-xl bg-paper-side p-3 shadow-control">
          <nav className="grid grid-cols-2 gap-2 xl:grid-cols-1" aria-label="Settings sections">
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

        <div className="min-w-0 overflow-hidden">
        {section === "llm" ? (
          <LlmProviderSection
            getLlmProviderModels={getLlmProviderModels}
            getLlmProviderSecret={getLlmProviderSecret}
            saveLlmProvider={saveLlmProvider}
            saveRuntimeDefaults={saveRuntimeDefaults}
            settings={settings}
            testLlmProviderConnection={testLlmProviderConnection}
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
            onDownloadStateReset={resetDownloadState}
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
      </div>
    </section>
  );
}

function SectionButton({ active, children, onClick }: { active: boolean; children: string; onClick(): void }) {
  return (
    <Button
      variant="secondary"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={clsx(
        "justify-start rounded-md px-3 py-2.5 text-left",
        active ? "bg-paper-selected text-accent shadow-selected" : "bg-paper/70 text-muted"
      )}
    >
      {children}
    </Button>
  );
}

function LlmProviderSection({
  getLlmProviderSecret,
  getLlmProviderModels,
  onSettingsChange,
  saveLlmProvider,
  saveRuntimeDefaults,
  settings,
  testLlmProviderConnection
}: {
  settings: RuntimeSettingsModel;
  onSettingsChange(settings: RuntimeSettingsModel): void;
  saveRuntimeDefaults: SettingsProps["saveRuntimeDefaults"];
  saveLlmProvider: SettingsProps["saveLlmProvider"];
  getLlmProviderSecret: SettingsProps["getLlmProviderSecret"];
  getLlmProviderModels: SettingsProps["getLlmProviderModels"];
  testLlmProviderConnection: SettingsProps["testLlmProviderConnection"];
}) {
  const [selectedName, setSelectedName] = useState(settings.defaults.llmProvider);
  const providers = useMemo(() => llmProviderOptions(settings), [settings]);
  const selected = useMemo(
    () => providers.find((provider) => provider.name === selectedName) ?? providers[0],
    [providers, selectedName]
  );
  const [customDraft, setCustomDraft] = useState<ProviderDraft>({
    name: "",
    baseUrl: "",
    defaultChatModel: "",
    apiKeyRef: "",
    secretValue: ""
  });
  const [customModalOpen, setCustomModalOpen] = useState(false);
  const [customConnectionLoading, setCustomConnectionLoading] = useState(false);
  const [customFeedback, setCustomFeedback] = useState<string | null>(null);
  const [customMutationError, setCustomMutationError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ProviderDraft>(() =>
    selected
      ? providerDraft(selected)
      : { name: "", baseUrl: "", defaultChatModel: "", apiKeyRef: "", secretValue: "" }
  );
  const [providerModels, setProviderModels] = useState<ProviderModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [apiKeyDirty, setApiKeyDirty] = useState(false);
  const [secretLoading, setSecretLoading] = useState(false);
  const [connectionLoading, setConnectionLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const selectedConfigured = settings.llmProviders.some((provider) => provider.name === selected.name);

  useEffect(() => {
    const nextSelected = providers.find((provider) => provider.name === selectedName) ?? providers[0];
    if (!nextSelected) {
      return;
    }

    setDraft(providerDraft(nextSelected));
    setProviderModels([]);
    setApiKeyDirty(false);
    setFeedback(null);
    setMutationError(null);
  }, [providers, selectedName]);

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
      const displayName = draft.name.trim();
      const name = selectedConfigured ? selected.name : providerStorageName(displayName);
      if (!displayName || !name) {
        setMutationError("Provider name is required.");
        return;
      }

      const secretValue = apiKeyDirty ? emptyToNull(draft.secretValue) : null;
      const saved = await saveLlmProvider({
        name,
        type: "openai_compatible",
        baseUrl: emptyToNull(draft.baseUrl),
        defaultChatModel: emptyToNull(draft.defaultChatModel),
        secretValue,
        apiKeyRef: secretValue
          ? defaultApiKeyRef(name)
          : (emptyToNull(draft.apiKeyRef) ?? defaultApiKeyRef(name)),
        displayName: displayName === name ? null : displayName
      });

      onSettingsChange({
        ...settings,
        llmProviders: upsertProvider(settings.llmProviders, saved)
      });
      setSelectedName(saved.name);
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

  async function saveCustomProvider() {
    setCustomMutationError(null);

    try {
      const displayName = customDraft.name.trim();
      const name = providerStorageName(displayName);
      if (!displayName || !name) {
        setCustomMutationError("Provider name is required.");
        return;
      }

      const secretValue = emptyToNull(customDraft.secretValue);
      const saved = await saveLlmProvider({
        name,
        type: "openai_compatible",
        baseUrl: emptyToNull(customDraft.baseUrl),
        defaultChatModel: emptyToNull(customDraft.defaultChatModel),
        secretValue,
        apiKeyRef: secretValue
          ? defaultApiKeyRef(name)
          : (emptyToNull(customDraft.apiKeyRef) ?? defaultApiKeyRef(name)),
        displayName: displayName === name ? null : displayName
      });

      onSettingsChange({
        ...settings,
        llmProviders: upsertProvider(settings.llmProviders, saved)
      });
      setSelectedName(saved.name);
      setCustomDraft({ name: "", baseUrl: "", defaultChatModel: "", apiKeyRef: "", secretValue: "" });
      setCustomModalOpen(false);
      setFeedback("Provider saved.");
    } catch (error) {
      setCustomMutationError(errorMessage(error, "Provider could not be saved."));
    }
  }

  async function fetchModels() {
    setFeedback(null);
    setMutationError(null);
    setModelsLoading(true);

    try {
      const models = await getLlmProviderModels(selected.name);
      setProviderModels(models);
      const currentModel = draft.defaultChatModel.trim();
      if (!currentModel && models[0]) {
        setDraft((current) => ({ ...current, defaultChatModel: models[0].id }));
      }
      setFeedback(models.length > 0 ? "Models loaded." : "No models returned by this provider.");
    } catch (error) {
      setProviderModels([]);
      setMutationError(errorMessage(error, "Models could not be loaded."));
    } finally {
      setModelsLoading(false);
    }
  }

  async function revealSavedApiKey() {
    if (apiKeyDirty || draft.secretValue || !selectedConfigured) {
      return;
    }

    setSecretLoading(true);
    setMutationError(null);
    try {
      const secretValue = await getLlmProviderSecret(selected.name);
      setDraft((current) => ({ ...current, secretValue }));
    } catch (error) {
      setMutationError(errorMessage(error, "API key could not be loaded."));
    } finally {
      setSecretLoading(false);
    }
  }

  async function testConnection() {
    setFeedback(null);
    setMutationError(null);
    setConnectionLoading(true);

    try {
      const result = await testLlmProviderConnection({
        providerName: selectedConfigured ? selected.name : null,
        baseUrl: draft.baseUrl,
        apiKey: emptyToNull(draft.secretValue),
        model: draft.defaultChatModel
      });
      setFeedback(result.message);
    } catch (error) {
      setMutationError(errorMessage(error, "Connection test failed."));
    } finally {
      setConnectionLoading(false);
    }
  }

  async function testCustomConnection() {
    setCustomFeedback(null);
    setCustomMutationError(null);
    setCustomConnectionLoading(true);

    try {
      const result = await testLlmProviderConnection({
        providerName: null,
        baseUrl: customDraft.baseUrl,
        apiKey: emptyToNull(customDraft.secretValue),
        model: customDraft.defaultChatModel
      });
      setCustomFeedback(result.message);
    } catch (error) {
      setCustomMutationError(errorMessage(error, "Connection test failed."));
    } finally {
      setCustomConnectionLoading(false);
    }
  }

  return (
    <>
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
                  {providerDisplayName(provider)}
                </span>
                <span className="mt-1 block text-xs text-muted">
                  {settings.llmProviders.some((item) => item.name === provider.name) ? "Saved profile" : "Preset"}
                </span>
                {settings.defaults.llmProvider === provider.name ? (
                  <span className="mt-1 block text-xs font-bold text-ready">Default</span>
                ) : null}
              </button>
            );
          })}
        </div>
        <Button
          variant="secondary"
          className="mt-3 w-full justify-start px-3"
          onClick={() => {
            setCustomFeedback(null);
            setCustomMutationError(null);
            setCustomModalOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
          Add custom provider
        </Button>
      </aside>

      <section className="rounded-lg bg-paper-muted p-5 shadow-control">
        <p className="text-xs font-bold uppercase text-muted">OpenAI-compatible profile</p>
        <h2 className="mt-2 text-2xl font-extrabold leading-tight text-ink-brown">{selected.name}</h2>

        <div className="mt-4 grid gap-3">
          <TextInput
            label="Provider name"
            value={draft.name}
            onChange={(name) => {
              setDraft((current) => ({ ...current, name }));
            }}
          />
          <TextInput
            label="Base URL"
            value={draft.baseUrl}
            onChange={(baseUrl) => {
              setDraft((current) => ({ ...current, baseUrl }));
            }}
          />
          <ModelInput
            label="Default chat model"
            models={providerModels}
            value={draft.defaultChatModel}
            onChange={(defaultChatModel) => {
              setDraft((current) => ({ ...current, defaultChatModel }));
            }}
          />
          <SecretInput
            label="API key"
            value={draft.secretValue}
            loading={secretLoading}
            onChange={(secretValue) => {
              setApiKeyDirty(true);
              setDraft((current) => ({ ...current, secretValue }));
            }}
            onBeforeReveal={revealSavedApiKey}
          />
        </div>

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
          <Button variant="secondary" disabled={!selectedConfigured} onClick={() => void setDefaultProvider()}>
            Set as default
          </Button>
          <Button variant="secondary" disabled={!selectedConfigured || modelsLoading} onClick={() => void fetchModels()}>
            {modelsLoading ? "Fetching models" : "Fetch models"}
          </Button>
          <Button variant="secondary" disabled={connectionLoading} onClick={() => void testConnection()}>
            {connectionLoading ? "Testing connection" : "Test connection"}
          </Button>
        </div>
      </section>
    </section>
    {customModalOpen ? (
      <div className="fixed inset-0 z-50 grid place-items-center bg-ink/45 px-4 py-6" role="presentation">
        <section
          aria-label="Add custom provider"
          aria-modal="true"
          role="dialog"
          className="w-full max-w-[560px] rounded-lg bg-paper-muted p-5 shadow-panel"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase text-muted">OpenAI-compatible profile</p>
              <h2 className="mt-2 text-2xl font-extrabold leading-tight text-ink-brown">Add custom provider</h2>
            </div>
            <Button
              aria-label="Close custom provider dialog"
              className="shrink-0 px-0"
              variant="secondary"
              onClick={() => setCustomModalOpen(false)}
            >
              <X className="mx-auto h-4 w-4" aria-hidden="true" />
            </Button>
          </div>

          <div className="mt-4 grid gap-3">
            <TextInput
              label="Provider name"
              value={customDraft.name}
              onChange={(name) => setCustomDraft((current) => ({ ...current, name }))}
            />
            <TextInput
              label="Base URL"
              value={customDraft.baseUrl}
              onChange={(baseUrl) => setCustomDraft((current) => ({ ...current, baseUrl }))}
            />
            <ModelInput
              label="Default chat model"
              models={[]}
              value={customDraft.defaultChatModel}
              onChange={(defaultChatModel) => setCustomDraft((current) => ({ ...current, defaultChatModel }))}
            />
            <SecretInput
              label="API key"
              value={customDraft.secretValue}
              onChange={(secretValue) => setCustomDraft((current) => ({ ...current, secretValue }))}
            />
          </div>

          {customFeedback ? (
            <p className="mt-3 text-sm font-semibold text-ready" aria-live="polite">
              {customFeedback}
            </p>
          ) : null}
          {customMutationError ? <InlineError>{customMutationError}</InlineError> : null}

          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={() => setCustomModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="secondary" disabled={customConnectionLoading} onClick={() => void testCustomConnection()}>
              {customConnectionLoading ? "Testing connection" : "Test connection"}
            </Button>
            <Button variant="primary" onClick={() => void saveCustomProvider()}>
              Save provider
            </Button>
          </div>
        </section>
      </div>
    ) : null}
    </>
  );
}

function AsrSection({
  downloadJobs,
  feedback,
  loadModels,
  models,
  mutationError,
  onDownloadModel,
  onDownloadStateReset,
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
  onDownloadStateReset(): void;
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
      onDownloadStateReset();
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
        className="h-2 overflow-hidden rounded-full bg-paper-side"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${percent}%` }} />
      </div>
      <p className="text-xs font-bold text-ink-brown">{roundedPercent}%</p>
      {job.error ? <p className="text-xs font-semibold text-accent">{job.error}</p> : null}
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
              <span className="rounded-sm bg-accent-soft px-2 py-1 text-xs font-bold text-ink">
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
            <span className={model.present ? "ml-2 font-bold text-ready" : "ml-2 font-bold text-accent"}>
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

  return status.present ? "font-bold text-ready" : "font-bold text-accent";
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
  loading = false,
  onBeforeReveal,
  onChange,
  value
}: {
  label: string;
  value: string;
  loading?: boolean;
  onBeforeReveal?(): Promise<void> | void;
  onChange(value: string): void;
}) {
  const inputId = useId();
  const [visible, setVisible] = useState(false);
  const labelText = visible ? "Hide API key" : "Show API key";

  async function toggleVisibility() {
    if (!visible) {
      await onBeforeReveal?.();
    }
    setVisible((current) => !current);
  }

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
          disabled={loading}
          className="rounded-l-none px-0"
          onClick={() => void toggleVisibility()}
        >
          {visible ? <EyeOff aria-hidden="true" className="mx-auto size-4" /> : <Eye aria-hidden="true" className="mx-auto size-4" />}
        </Button>
      </div>
    </div>
  );
}

function ModelInput({
  label,
  models,
  onChange,
  value
}: {
  label: string;
  value: string;
  models: ProviderModelOption[];
  onChange(value: string): void;
}) {
  const listId = useId();

  return (
    <label className="grid gap-2 text-xs font-bold uppercase text-muted">
      {label}
      <input
        aria-label={label}
        list={models.length > 0 ? listId : undefined}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-11 min-w-0 rounded-md bg-paper px-3 text-sm font-normal normal-case text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      />
      {models.length > 0 ? (
        <datalist id={listId}>
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.label ?? model.ownedBy ?? model.id}
            </option>
          ))}
        </datalist>
      ) : null}
    </label>
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
    <p className="mt-3 rounded-md bg-accent-soft px-3 py-2 text-sm font-semibold text-ink" aria-live="assertive">
      {children}
    </p>
  );
}
