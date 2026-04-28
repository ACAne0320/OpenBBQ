import type {
  LocalMediaSelection,
  ReviewModel,
  SourceDraft,
  StartSubtitleTaskInput,
  StartSubtitleTaskResult,
  TaskSummary,
  TaskMonitorModel,
  WorkflowStep
} from "./lib/types";

export type OpenBBQDesktopApi = {
  chooseLocalMedia(): Promise<LocalMediaSelection | null>;
  getWorkflowTemplate(source: SourceDraft): Promise<WorkflowStep[]>;
  startSubtitleTask(input: StartSubtitleTaskInput): Promise<StartSubtitleTaskResult>;
  listTasks(): Promise<TaskSummary[]>;
  getTaskMonitor(runId: string): Promise<TaskMonitorModel>;
  getReview(runId: string): Promise<ReviewModel>;
  updateSegmentText(input: { segmentId: string; transcript: string; translation: string }): Promise<void>;
  retryCheckpoint(runId: string): Promise<void>;
};

declare global {
  interface Window {
    openbbq?: OpenBBQDesktopApi;
  }
}
