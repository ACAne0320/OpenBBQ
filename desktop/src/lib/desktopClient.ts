import type { OpenBBQDesktopApi } from "../global";
import type { OpenBBQClient } from "./apiClient";

export function createDesktopClient(api: OpenBBQDesktopApi): OpenBBQClient {
  return {
    chooseLocalMedia: () => api.chooseLocalMedia(),
    listWorkflowDefinitions: () => api.listWorkflowDefinitions(),
    saveWorkflowDefinition: (input) => api.saveWorkflowDefinition(input),
    getRemoteVideoFormats: (input) => api.getRemoteVideoFormats(input),
    getWorkflowTemplate: (source) => api.getWorkflowTemplate(source),
    getWorkflowTools: () => api.getWorkflowTools(),
    startSubtitleTask: (input) => api.startSubtitleTask(input),
    listTasks: () => api.listTasks(),
    getTaskMonitor: (runId) => api.getTaskMonitor(runId),
    getReview: (runId) => api.getReview(runId),
    getRuntimeSettings: () => api.getRuntimeSettings(),
    saveRuntimeDefaults: (input) => api.saveRuntimeDefaults(input),
    saveLlmProvider: (input) => api.saveLlmProvider(input),
    checkLlmProvider: (name) => api.checkLlmProvider(name),
    getLlmProviderSecret: (name) => api.getLlmProviderSecret(name),
    getLlmProviderModels: (name) => api.getLlmProviderModels(name),
    testLlmProviderConnection: (input) => api.testLlmProviderConnection(input),
    saveFasterWhisperDefaults: (input) => api.saveFasterWhisperDefaults(input),
    getRuntimeModels: () => api.getRuntimeModels(),
    downloadFasterWhisperModel: (input) => api.downloadFasterWhisperModel(input),
    getFasterWhisperModelDownload: (jobId) => api.getFasterWhisperModelDownload(jobId),
    getDiagnostics: () => api.getDiagnostics(),
    updateSegmentText: (input) => api.updateSegmentText(input),
    retryCheckpoint: (runId) => api.retryCheckpoint(runId)
  };
}
