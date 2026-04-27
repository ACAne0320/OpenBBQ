import { contextBridge, ipcRenderer } from "electron";

const api = {
  chooseLocalMedia: () => ipcRenderer.invoke("openbbq:choose-local-media"),
  getWorkflowTemplate: (source: unknown) => ipcRenderer.invoke("openbbq:get-workflow-template", source),
  startSubtitleTask: (input: unknown) => ipcRenderer.invoke("openbbq:start-subtitle-task", input),
  getTaskMonitor: (runId: string) => ipcRenderer.invoke("openbbq:get-task-monitor", runId),
  getReview: (runId: string) => ipcRenderer.invoke("openbbq:get-review", runId),
  updateSegmentText: (input: unknown) => ipcRenderer.invoke("openbbq:update-segment-text", input),
  retryCheckpoint: (runId: string) => ipcRenderer.invoke("openbbq:retry-checkpoint", runId)
};

contextBridge.exposeInMainWorld("openbbq", api);
