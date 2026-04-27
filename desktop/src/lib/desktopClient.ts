import type { OpenBBQDesktopApi } from "../global";
import type { OpenBBQClient } from "./apiClient";

export function createDesktopClient(api: OpenBBQDesktopApi): OpenBBQClient {
  return {
    chooseLocalMedia: () => api.chooseLocalMedia(),
    getWorkflowTemplate: (source) => api.getWorkflowTemplate(source),
    startSubtitleTask: (input) => api.startSubtitleTask(input),
    getTaskMonitor: (runId) => api.getTaskMonitor(runId),
    getReview: (runId) => api.getReview(runId),
    updateSegmentText: (input) => api.updateSegmentText(input),
    retryCheckpoint: (runId) => api.retryCheckpoint(runId)
  };
}
