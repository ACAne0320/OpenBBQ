import { useEffect, useState } from "react";

import type {
  DiagnosticCheck,
  FasterWhisperSettingsModel,
  LlmProviderModel,
  RuntimeModelStatus,
  RuntimeSettingsModel,
  SecretStatus
} from "../lib/types";
import { Button } from "./Button";

type SettingsSection = "llm" | "asr" | "diagnostics" | "advanced";

export type SettingsProps = {
  loadSettings(): Promise<RuntimeSettingsModel>;
  loadModels(): Promise<RuntimeModelStatus[]>;
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

type ProviderDraft = {
  displayName: string;
  baseUrl: string;
  defaultChatModel: string;
  apiKeyRef: string;
  secretValue: string;
};

function providerDraft(provider: LlmProviderModel): ProviderDraft {
  return {
    displayName: provider.displayName ?? provider.name,
    baseUrl: provider.baseUrl ?? "",
    defaultChatModel: provider.defaultChatModel ?? "",
    apiKeyRef: provider.apiKeyRef ?? `sqlite:openbbq/providers/${provider.name}/api_key`,
    secretValue: ""
  };
}

function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function Settings({
  checkLlmProvider,
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
            models={models}
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
  const selected = settings.llmProviders.find((provider) => provider.name === selectedName) ?? settings.llmProviders[0];
  const [draft, setDraft] = useState<ProviderDraft>(() =>
    selected
      ? providerDraft(selected)
      : { displayName: "", baseUrl: "", defaultChatModel: "", apiKeyRef: "", secretValue: "" }
  );
  const [secretStatus, setSecretStatus] = useState<SecretStatus | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) {
      return;
    }

    setDraft(providerDraft(selected));
    setSecretStatus(null);
    setFeedback(null);
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
    const saved = await saveLlmProvider({
      name: selected.name,
      type: "openai_compatible",
      baseUrl: emptyToNull(draft.baseUrl),
      defaultChatModel: emptyToNull(draft.defaultChatModel),
      secretValue: emptyToNull(draft.secretValue),
      apiKeyRef: emptyToNull(draft.apiKeyRef),
      displayName: emptyToNull(draft.displayName)
    });

    onSettingsChange({
      ...settings,
      llmProviders: settings.llmProviders.map((provider) => (provider.name === saved.name ? saved : provider))
    });
    setDraft((current) => ({ ...current, secretValue: "" }));
    setFeedback("Provider saved.");
  }

  async function setDefaultProvider() {
    setFeedback(null);
    const updated = await saveRuntimeDefaults({
      llmProvider: selected.name,
      asrProvider: settings.defaults.asrProvider
    });
    onSettingsChange(updated);
    setFeedback("Default provider updated.");
  }

  async function checkSecret() {
    setFeedback(null);
    setSecretStatus(await checkLlmProvider(selected.name));
  }

  return (
    <section className="grid grid-cols-1 gap-4 xl:grid-cols-[220px_minmax(0,1fr)]" aria-label="LLM provider settings">
      <aside className="rounded-lg bg-paper-muted p-3 shadow-control">
        <p className="text-xs font-bold uppercase text-muted">Providers</p>
        <div className="mt-3 grid gap-2">
          {settings.llmProviders.map((provider) => {
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
          <TextInput
            label="API key reference"
            value={draft.apiKeyRef}
            onChange={(apiKeyRef) => setDraft((current) => ({ ...current, apiKeyRef }))}
          />
          <TextInput
            label="API key"
            type="password"
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
                : (secretStatus.error ?? secretStatus.reference)}
            </span>
          </div>
        ) : null}
        {feedback ? (
          <p className="mt-3 text-sm font-semibold text-ready" aria-live="polite">
            {feedback}
          </p>
        ) : null}

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
  models,
  onSettingsChange,
  saveFasterWhisperDefaults,
  settings
}: {
  settings: RuntimeSettingsModel;
  models: RuntimeModelStatus[];
  onSettingsChange(settings: RuntimeSettingsModel): void;
  saveFasterWhisperDefaults: SettingsProps["saveFasterWhisperDefaults"];
}) {
  const [draft, setDraft] = useState<FasterWhisperSettingsModel>(settings.fasterWhisper);
  const status = models.find((model) => model.provider === "faster_whisper");

  async function saveDefaults() {
    const updated = await saveFasterWhisperDefaults({
      cacheDir: draft.cacheDir,
      defaultModel: draft.defaultModel,
      defaultDevice: draft.defaultDevice,
      defaultComputeType: draft.defaultComputeType
    });
    onSettingsChange(updated);
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
          <TextInput
            label="Default model"
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

        <div className="mt-4 rounded-md bg-paper px-3 py-2 text-sm shadow-control">
          <span className="font-bold text-ink-brown">{status?.model ?? draft.defaultModel}</span>
          <span className="ml-2 text-muted">{status?.cacheDir ?? draft.cacheDir}</span>
          <span className={status?.present ? "ml-2 font-bold text-ready" : "ml-2 font-bold text-[#8c4d29]"}>
            {status?.present ? "Model cache present" : "Model cache missing"}
          </span>
        </div>

        <div className="mt-5">
          <Button variant="primary" onClick={() => void saveDefaults()}>
            Save ASR defaults
          </Button>
        </div>
      </section>
    </section>
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
