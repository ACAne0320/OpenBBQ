import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DiagnosticCheck, RuntimeModelStatus, RuntimeSettingsModel, SecretStatus } from "../../lib/types";
import { Settings, type SettingsProps } from "../Settings";

const settings: RuntimeSettingsModel = {
  configPath: "C:/Users/alex/.openbbq/config.toml",
  cacheRoot: "C:/Users/alex/.cache/openbbq",
  defaults: { llmProvider: "openai-compatible", asrProvider: "faster-whisper" },
  llmProviders: [
    {
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: "https://api.openai.com/v1",
      apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
      defaultChatModel: "gpt-4o-mini",
      displayName: "OpenAI-compatible"
    },
    {
      name: "local-gateway",
      type: "openai_compatible",
      baseUrl: "http://127.0.0.1:11434/v1",
      apiKeyRef: "sqlite:openbbq/providers/local-gateway/api_key",
      defaultChatModel: "qwen2.5",
      displayName: "Local gateway"
    }
  ],
  fasterWhisper: {
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    defaultModel: "base",
    defaultDevice: "cpu",
    defaultComputeType: "int8"
  }
};

const models: RuntimeModelStatus[] = [
  {
    provider: "faster-whisper",
    model: "base",
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    present: false,
    sizeBytes: 0,
    error: null
  },
  {
    provider: "faster-whisper",
    model: "small",
    cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
    present: true,
    sizeBytes: 20,
    error: null
  }
];

const diagnostics: DiagnosticCheck[] = [
  {
    id: "cache.root_writable",
    status: "passed",
    severity: "error",
    message: "Runtime cache root is writable."
  }
];

const secretStatus: SecretStatus = {
  reference: "env:OPENBBQ_LLM_API_KEY",
  resolved: true,
  display: "env:OPENBBQ_LLM_API_KEY",
  valuePreview: "configured",
  error: null
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function renderSettings(overrides: Partial<SettingsProps> = {}) {
  const props: SettingsProps = {
    loadSettings: vi.fn().mockResolvedValue(clone(settings)),
    loadModels: vi.fn().mockResolvedValue(clone(models)),
    loadDiagnostics: vi.fn().mockResolvedValue(clone(diagnostics)),
    saveRuntimeDefaults: vi.fn().mockImplementation(async (input: { llmProvider: string; asrProvider: string }) => ({
      ...clone(settings),
      defaults: input
    })),
    saveLlmProvider: vi.fn().mockImplementation(async (input) => ({
      name: input.name,
      type: input.type,
      baseUrl: input.baseUrl,
      apiKeyRef: input.apiKeyRef,
      defaultChatModel: input.defaultChatModel,
      displayName: input.displayName
    })),
    checkLlmProvider: vi.fn().mockResolvedValue(clone(secretStatus)),
    saveFasterWhisperDefaults: vi.fn().mockImplementation(async (input) => ({
      ...clone(settings),
      fasterWhisper: input
    })),
    downloadFasterWhisperModel: vi.fn().mockResolvedValue(clone(models[1])),
    ...overrides
  };

  render(<Settings {...props} />);

  return props;
}

describe("Settings", () => {
  it("loads settings and marks the default LLM provider", async () => {
    const props = renderSettings();

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(props.loadSettings).toHaveBeenCalledTimes(1);
    expect(props.loadModels).toHaveBeenCalledTimes(1);
    expect(props.loadDiagnostics).toHaveBeenCalledTimes(1);

    const defaultProvider = screen.getByRole("button", { name: /OpenAI-compatible openai-compatible Default/i });
    expect(defaultProvider).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Base URL")).toHaveValue("https://api.openai.com/v1");
  });

  it("switches to ASR and shows faster-whisper defaults and status", async () => {
    const user = userEvent.setup();
    renderSettings();

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));

    expect(screen.getByRole("heading", { name: "faster-whisper" })).toBeInTheDocument();
    const defaultModel = screen.getByLabelText("Default model");
    expect(defaultModel).toHaveValue("base");
    expect(within(defaultModel).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual([
      "tiny",
      "base",
      "small",
      "medium",
      "large-v3"
    ]);
    expect(screen.getByLabelText("Default device")).toHaveValue("cpu");
    expect(screen.getByLabelText("Default compute type")).toHaveValue("int8");
    expect(screen.getByLabelText("Cache directory")).toHaveValue("C:/Users/alex/.cache/openbbq/models/faster-whisper");
    expect(screen.getByText("Not downloaded")).toBeInTheDocument();
    expect(screen.getByText("Downloaded")).toBeInTheDocument();
  });

  it("selects another provider and saves runtime defaults with the current ASR provider", async () => {
    const user = userEvent.setup();
    const saveRuntimeDefaults = vi.fn().mockResolvedValue({
      ...clone(settings),
      defaults: { llmProvider: "local-gateway", asrProvider: "faster-whisper" }
    });
    renderSettings({ saveRuntimeDefaults });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: /Local gateway local-gateway/i }));
    await user.click(screen.getByRole("button", { name: "Set as default" }));

    expect(saveRuntimeDefaults).toHaveBeenCalledWith({
      llmProvider: "local-gateway",
      asrProvider: "faster-whisper"
    });
  });

  it("edits and saves an LLM provider with a typed API key and existing API key reference", async () => {
    const user = userEvent.setup();
    const saveLlmProvider = vi.fn().mockImplementation(async (input) => ({
      name: input.name,
      type: input.type,
      baseUrl: input.baseUrl,
      apiKeyRef: input.apiKeyRef,
      defaultChatModel: input.defaultChatModel,
      displayName: input.displayName
    }));
    renderSettings({ saveLlmProvider });

    await screen.findByRole("heading", { name: "Settings" });

    const secretInput = screen.getByLabelText("API key");
    expect(secretInput).toHaveAttribute("type", "password");
    expect(screen.queryByLabelText("API key reference")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show API key" }));
    expect(secretInput).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Hide API key" }));
    expect(secretInput).toHaveAttribute("type", "password");

    await user.clear(screen.getByLabelText("Display name"));
    await user.type(screen.getByLabelText("Display name"), "Production LLM");
    await user.clear(screen.getByLabelText("Base URL"));
    await user.type(screen.getByLabelText("Base URL"), "https://llm.example.test/v1");
    await user.clear(screen.getByLabelText("Default chat model"));
    await user.type(screen.getByLabelText("Default chat model"), "gpt-4.1-mini");
    await user.type(secretInput, "sk-test-secret");
    await user.click(screen.getByRole("button", { name: "Save provider" }));

    expect(saveLlmProvider).toHaveBeenCalledWith({
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: "https://llm.example.test/v1",
      defaultChatModel: "gpt-4.1-mini",
      secretValue: "sk-test-secret",
      apiKeyRef: "sqlite:openbbq/providers/openai-compatible/api_key",
      displayName: "Production LLM"
    });
    expect(secretInput).toHaveValue("");
  });

  it("preserves the existing API key reference when saving provider metadata without a new secret", async () => {
    const user = userEvent.setup();
    const saveLlmProvider = vi.fn().mockImplementation(async (input) => ({
      name: input.name,
      type: input.type,
      baseUrl: input.baseUrl,
      apiKeyRef: input.apiKeyRef,
      defaultChatModel: input.defaultChatModel,
      displayName: input.displayName
    }));
    renderSettings({ saveLlmProvider });

    await screen.findByRole("heading", { name: "Settings" });
    await user.clear(screen.getByLabelText("Display name"));
    await user.type(screen.getByLabelText("Display name"), "Production LLM");
    await user.click(screen.getByRole("button", { name: "Save provider" }));

    expect(saveLlmProvider).toHaveBeenCalledWith({
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: "https://api.openai.com/v1",
      defaultChatModel: "gpt-4o-mini",
      secretValue: null,
      apiKeyRef: "env:OPENBBQ_LLM_API_KEY",
      displayName: "Production LLM"
    });
  });

  it("bootstraps the default LLM provider when no providers are configured", async () => {
    const user = userEvent.setup();
    const saveLlmProvider = vi.fn().mockImplementation(async (input) => ({
      name: input.name,
      type: input.type,
      baseUrl: input.baseUrl,
      apiKeyRef: input.apiKeyRef,
      defaultChatModel: input.defaultChatModel,
      displayName: input.displayName
    }));
    renderSettings({
      loadSettings: vi.fn().mockResolvedValue({
        ...clone(settings),
        llmProviders: []
      }),
      saveLlmProvider
    });

    await screen.findByRole("heading", { name: "Settings" });
    expect(screen.getByRole("button", { name: /openai-compatible Default/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByLabelText("API key reference")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Base URL"), "https://llm.example.test/v1");
    await user.type(screen.getByLabelText("Default chat model"), "gpt-4.1-mini");
    await user.type(screen.getByLabelText("API key"), "sk-test-secret");
    await user.click(screen.getByRole("button", { name: "Save provider" }));

    expect(saveLlmProvider).toHaveBeenCalledWith({
      name: "openai-compatible",
      type: "openai_compatible",
      baseUrl: "https://llm.example.test/v1",
      defaultChatModel: "gpt-4.1-mini",
      secretValue: "sk-test-secret",
      apiKeyRef: "sqlite:openbbq/providers/openai-compatible/api_key",
      displayName: "openai-compatible"
    });
  });

  it("checks a provider secret without echoing the typed secret", async () => {
    const user = userEvent.setup();
    const checkLlmProvider = vi.fn().mockResolvedValue(clone(secretStatus));
    renderSettings({ checkLlmProvider });

    await screen.findByRole("heading", { name: "Settings" });
    await user.type(screen.getByLabelText("API key"), "sk-test-secret");
    await user.click(screen.getByRole("button", { name: "Check secret" }));

    expect(checkLlmProvider).toHaveBeenCalledWith("openai-compatible");
    expect(await screen.findByText("Secret resolved")).toBeInTheDocument();
    expect(screen.getByText("configured")).toBeInTheDocument();
    expect(screen.queryByText("sk-test-secret")).not.toBeInTheDocument();
  });

  it("does not expose the API key reference when a provider secret is unresolved", async () => {
    const user = userEvent.setup();
    const checkLlmProvider = vi.fn().mockResolvedValue({
      reference: "sqlite:openbbq/providers/openai-compatible/api_key",
      resolved: false,
      display: "sqlite:openbbq/providers/openai-compatible/api_key",
      valuePreview: null,
      error: "Secret sqlite:openbbq/providers/openai-compatible/api_key was not found."
    });
    renderSettings({ checkLlmProvider });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "Check secret" }));

    expect(await screen.findByText("Secret unresolved")).toBeInTheDocument();
    expect(screen.getByText("API key is not configured.")).toBeInTheDocument();
    expect(screen.queryByText(/sqlite:openbbq\/providers\/openai-compatible\/api_key/)).not.toBeInTheDocument();
  });

  it("renders LLM mutation failures without throwing unhandled rejections", async () => {
    const user = userEvent.setup();
    renderSettings({ saveLlmProvider: vi.fn().mockRejectedValue(new Error("Provider write failed.")) });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "Save provider" }));

    expect(await screen.findByText("Provider write failed.")).toBeInTheDocument();
  });

  it("renders default-provider and secret-check failures", async () => {
    const user = userEvent.setup();
    renderSettings({
      saveRuntimeDefaults: vi.fn().mockRejectedValue(new Error("Defaults write failed.")),
      checkLlmProvider: vi.fn().mockRejectedValue(new Error("Secret check failed."))
    });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "Set as default" }));

    expect(await screen.findByText("Defaults write failed.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Check secret" }));

    expect(await screen.findByText("Secret check failed.")).toBeInTheDocument();
  });

  it("saves faster-whisper defaults", async () => {
    const user = userEvent.setup();
    const saveFasterWhisperDefaults = vi.fn().mockImplementation(async (input) => ({
      ...clone(settings),
      fasterWhisper: input
    }));
    renderSettings({ saveFasterWhisperDefaults });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.selectOptions(screen.getByLabelText("Default model"), "small");
    await user.clear(screen.getByLabelText("Default compute type"));
    await user.type(screen.getByLabelText("Default compute type"), "float16");
    await user.click(screen.getByRole("button", { name: "Save ASR defaults" }));

    expect(saveFasterWhisperDefaults).toHaveBeenCalledWith({
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      defaultModel: "small",
      defaultDevice: "cpu",
      defaultComputeType: "float16"
    });
  });

  it("syncs ASR inputs to canonical saved settings", async () => {
    const user = userEvent.setup();
    const saveFasterWhisperDefaults = vi.fn().mockResolvedValue({
      ...clone(settings),
      fasterWhisper: {
        cacheDir: "C:/OpenBBQ/cache/faster-whisper",
        defaultModel: "small.en",
        defaultDevice: "cpu",
        defaultComputeType: "int8"
      }
    });
    renderSettings({ saveFasterWhisperDefaults });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.selectOptions(screen.getByLabelText("Default model"), "small");
    await user.click(screen.getByRole("button", { name: "Save ASR defaults" }));

    expect(await screen.findByText("ASR defaults saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Default model")).toHaveValue("small.en");
    expect(screen.getByLabelText("Cache directory")).toHaveValue("C:/OpenBBQ/cache/faster-whisper");
  });

  it("refreshes model statuses after saving faster-whisper defaults", async () => {
    const user = userEvent.setup();
    const cacheDir = "C:/OpenBBQ/cache/faster-whisper";
    const refreshedModels: RuntimeModelStatus[] = [
      {
        provider: "faster-whisper",
        model: "base",
        cacheDir,
        present: false,
        sizeBytes: 0,
        error: null
      },
      {
        provider: "faster-whisper",
        model: "small",
        cacheDir,
        present: false,
        sizeBytes: 0,
        error: null
      }
    ];
    const loadModels = vi.fn().mockResolvedValueOnce(clone(models)).mockResolvedValueOnce(clone(refreshedModels));
    const saveFasterWhisperDefaults = vi.fn().mockImplementation(async (input) => ({
      ...clone(settings),
      fasterWhisper: input
    }));
    renderSettings({ loadModels, saveFasterWhisperDefaults });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    expect(screen.getByRole("button", { name: "Download small" })).toBeDisabled();

    await user.clear(screen.getByLabelText("Cache directory"));
    await user.type(screen.getByLabelText("Cache directory"), cacheDir);
    await user.click(screen.getByRole("button", { name: "Save ASR defaults" }));

    expect(await screen.findByText("ASR defaults saved.")).toBeInTheDocument();
    expect(loadModels).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Downloaded")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download small" })).toBeEnabled();
  });

  it("downloads a selected faster-whisper model and refreshes model status", async () => {
    const user = userEvent.setup();
    const downloadedModels: RuntimeModelStatus[] = [
      {
        provider: "faster-whisper",
        model: "base",
        cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
        present: true,
        sizeBytes: 10,
        error: null
      },
      models[1]
    ];
    const loadModels = vi.fn().mockResolvedValueOnce(clone(models)).mockResolvedValueOnce(clone(downloadedModels));
    const downloadFasterWhisperModel = vi.fn().mockResolvedValue(downloadedModels[0]);
    renderSettings({ loadModels, downloadFasterWhisperModel });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.click(screen.getByRole("button", { name: "Download base" }));

    expect(downloadFasterWhisperModel).toHaveBeenCalledWith({ model: "base" });
    expect(loadModels).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Model downloaded.")).toBeInTheDocument();
    expect(screen.getAllByText("Downloaded").length).toBeGreaterThanOrEqual(2);
  });

  it("keeps downloaded model status when refresh fails after download succeeds", async () => {
    const user = userEvent.setup();
    const downloadedModel: RuntimeModelStatus = {
      provider: "faster-whisper",
      model: "base",
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      present: true,
      sizeBytes: 10,
      error: null
    };
    const loadModels = vi
      .fn()
      .mockResolvedValueOnce(clone(models))
      .mockRejectedValueOnce(new Error("Model status refresh failed."));
    const downloadFasterWhisperModel = vi.fn().mockResolvedValue(downloadedModel);
    renderSettings({ loadModels, downloadFasterWhisperModel });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.click(screen.getByRole("button", { name: "Download base" }));

    expect(downloadFasterWhisperModel).toHaveBeenCalledWith({ model: "base" });
    expect(loadModels).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Model downloaded.")).toBeInTheDocument();
    expect(screen.getAllByText("Downloaded").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("Model could not be downloaded.")).not.toBeInTheDocument();
  });

  it("renders ASR download failures", async () => {
    const user = userEvent.setup();
    renderSettings({
      downloadFasterWhisperModel: vi.fn().mockRejectedValue(new Error("Model download failed."))
    });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.click(screen.getByRole("button", { name: "Download base" }));

    expect(await screen.findByText("Model download failed.")).toBeInTheDocument();
  });

  it("renders ASR mutation failures", async () => {
    const user = userEvent.setup();
    renderSettings({ saveFasterWhisperDefaults: vi.fn().mockRejectedValue(new Error("ASR write failed.")) });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));
    await user.click(screen.getByRole("button", { name: "Save ASR defaults" }));

    expect(await screen.findByText("ASR write failed.")).toBeInTheDocument();
  });

  it("renders unavailable model status when faster-whisper status is absent", async () => {
    const user = userEvent.setup();
    renderSettings({ loadModels: vi.fn().mockResolvedValue([]) });

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "ASR model" }));

    expect(screen.getAllByText("Status unavailable")).toHaveLength(5);
    expect(screen.queryByText("Not downloaded")).not.toBeInTheDocument();
  });

  it("renders diagnostics and advanced content", async () => {
    const user = userEvent.setup();
    renderSettings();

    await screen.findByRole("heading", { name: "Settings" });
    await user.click(screen.getByRole("button", { name: "Diagnostics" }));

    expect(screen.getByRole("heading", { name: "Diagnostics" })).toBeInTheDocument();
    expect(screen.getByText("cache.root_writable")).toBeInTheDocument();
    expect(screen.getByText("Runtime cache root is writable.")).toBeInTheDocument();
    expect(screen.getAllByText("faster-whisper").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Advanced" }));

    const advanced = screen.getByLabelText("Advanced");
    expect(within(advanced).getByText("Runtime config path")).toBeInTheDocument();
    expect(within(advanced).getByText("C:/Users/alex/.openbbq/config.toml")).toBeInTheDocument();
    expect(within(advanced).getByText("Cache root")).toBeInTheDocument();
    expect(within(advanced).getByText("C:/Users/alex/.cache/openbbq")).toBeInTheDocument();
  });
});
