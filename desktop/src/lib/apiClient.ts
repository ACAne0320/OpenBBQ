import { failedTask, reviewModel, workflowSteps } from "./mockData";
import type {
  LocalMediaSelection,
  ReviewModel,
  SourceDraft,
  StartSubtitleTaskInput,
  StartSubtitleTaskResult,
  StepParameter,
  TaskSummary,
  TaskMonitorModel,
  WorkflowStep
} from "./types";

export type OpenBBQClient = {
  chooseLocalMedia?(): Promise<LocalMediaSelection | null>;
  getWorkflowTemplate(source: SourceDraft): Promise<WorkflowStep[]>;
  startSubtitleTask(input: StartSubtitleTaskInput): Promise<StartSubtitleTaskResult>;
  listTasks(): Promise<TaskSummary[]>;
  getTaskMonitor(runId: string): Promise<TaskMonitorModel>;
  getReview(runId: string): Promise<ReviewModel>;
  updateSegmentText(input: {
    segmentId: string;
    transcript: string;
    translation: string;
  }): Promise<void>;
  retryCheckpoint(runId: string): Promise<void>;
};

function cloneModel<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function remoteFetchStep(source: Extract<SourceDraft, { kind: "remote_url" }>): WorkflowStep {
  const parameters: StepParameter[] = [{ kind: "text", key: "url", label: "URL", value: source.url }];

  return {
    id: "fetch_source",
    name: "Fetch Source",
    toolRef: "source.fetch_remote",
    summary: "url -> local media",
    status: "locked",
    parameters
  };
}

function workflowTemplateForSource(source: SourceDraft): WorkflowStep[] {
  if (source.kind === "remote_url") {
    return [remoteFetchStep(source), ...workflowSteps];
  }

  return workflowSteps;
}

export function createMockClient(): OpenBBQClient {
  let reviewState = cloneModel(reviewModel);

  return {
    async getWorkflowTemplate(source) {
      return cloneModel(workflowTemplateForSource(source));
    },
    async startSubtitleTask() {
      return { runId: "run_sample" };
    },
    async listTasks() {
      return [
        {
          id: "run_sample",
          title: "Sample task",
          workflowName: "Remote video -> translated SRT",
          sourceSummary: "Sample task",
          status: "failed",
          updatedAt: "2026-04-27T03:17:12.000Z"
        }
      ];
    },
    async getTaskMonitor() {
      return cloneModel(failedTask);
    },
    async getReview() {
      return cloneModel(reviewState);
    },
    async updateSegmentText(input) {
      reviewState = {
        ...reviewState,
        segments: reviewState.segments.map((segment) =>
          segment.id === input.segmentId
            ? {
                ...segment,
                transcript: input.transcript,
                translation: input.translation,
                savedState: "saved"
              }
            : segment
        )
      };
      return undefined;
    },
    async retryCheckpoint() {
      return undefined;
    }
  };
}
