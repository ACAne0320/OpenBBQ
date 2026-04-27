import { failedTask, reviewModel, workflowSteps } from "./mockData";
import type { ReviewModel, SourceDraft, TaskMonitorModel, WorkflowStep } from "./types";

export type OpenBBQClient = {
  getWorkflowTemplate(source: SourceDraft): Promise<WorkflowStep[]>;
  getTaskMonitor(runId: string): Promise<TaskMonitorModel>;
  getReview(runId: string): Promise<ReviewModel>;
  updateSegmentText(input: {
    segmentId: string;
    transcript: string;
    translation: string;
  }): Promise<void>;
  retryCheckpoint(runId: string): Promise<void>;
};

export function createMockClient(): OpenBBQClient {
  return {
    async getWorkflowTemplate() {
      return workflowSteps;
    },
    async getTaskMonitor() {
      return failedTask;
    },
    async getReview() {
      return reviewModel;
    },
    async updateSegmentText() {
      return undefined;
    },
    async retryCheckpoint() {
      return undefined;
    }
  };
}
