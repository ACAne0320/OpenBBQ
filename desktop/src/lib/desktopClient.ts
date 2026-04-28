import type { OpenBBQDesktopApi } from "../global";
import type { OpenBBQClient } from "./apiClient";

export function createDesktopClient(api: OpenBBQDesktopApi): OpenBBQClient {
  return {
    chooseLocalMedia: () => api.chooseLocalMedia(),
    getWorkflowTemplate: (source) => api.getWorkflowTemplate(source),
    startSubtitleTask: (input) => api.startSubtitleTask(input),
    listTasks: () => api.listTasks(),
    getTaskMonitor: (runId) => api.getTaskMonitor(runId),
    getReview: (runId) => api.getReview(runId),
    getRuntimeSettings: () => api.getRuntimeSettings(),
    saveRuntimeDefaults: (input) => api.saveRuntimeDefaults(input),
    saveLlmProvider: (input) => api.saveLlmProvider(input),
    checkLlmProvider: (name) => api.checkLlmProvider(name),
    saveFasterWhisperDefaults: (input) => api.saveFasterWhisperDefaults(input),
    getRuntimeModels: () => api.getRuntimeModels(),
    getDiagnostics: () => api.getDiagnostics(),
    updateSegmentText: (input) => api.updateSegmentText(input),
    retryCheckpoint: (runId) => api.retryCheckpoint(runId)
  };
}
