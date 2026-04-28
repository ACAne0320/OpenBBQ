import { contextBridge, ipcRenderer } from "electron";

const api = {
  chooseLocalMedia: () => ipcRenderer.invoke("openbbq:choose-local-media"),
  getWorkflowTemplate: (source: unknown) => ipcRenderer.invoke("openbbq:get-workflow-template", source),
  startSubtitleTask: (input: unknown) => ipcRenderer.invoke("openbbq:start-subtitle-task", input),
  listTasks: () => ipcRenderer.invoke("openbbq:list-tasks"),
  getTaskMonitor: (runId: string) => ipcRenderer.invoke("openbbq:get-task-monitor", runId),
  getReview: (runId: string) => ipcRenderer.invoke("openbbq:get-review", runId),
  getRuntimeSettings: () => ipcRenderer.invoke("openbbq:get-runtime-settings"),
  saveRuntimeDefaults: (input: unknown) => ipcRenderer.invoke("openbbq:save-runtime-defaults", input),
  saveLlmProvider: (input: unknown) => ipcRenderer.invoke("openbbq:save-llm-provider", input),
  checkLlmProvider: (name: string) => ipcRenderer.invoke("openbbq:check-llm-provider", name),
  saveFasterWhisperDefaults: (input: unknown) => ipcRenderer.invoke("openbbq:save-faster-whisper-defaults", input),
  getRuntimeModels: () => ipcRenderer.invoke("openbbq:get-runtime-models"),
  getDiagnostics: () => ipcRenderer.invoke("openbbq:get-diagnostics"),
  updateSegmentText: (input: unknown) => ipcRenderer.invoke("openbbq:update-segment-text", input),
  retryCheckpoint: (runId: string) => ipcRenderer.invoke("openbbq:retry-checkpoint", runId)
};

contextBridge.exposeInMainWorld("openbbq", api);
