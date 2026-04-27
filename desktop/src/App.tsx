import { useMemo, useRef, useState } from "react";

import { AppShell } from "./components/AppShell";
import type { NavItem } from "./components/AppShell";
import { ResultsReview } from "./components/ResultsReview";
import { SourceImport } from "./components/SourceImport";
import { TaskMonitor } from "./components/TaskMonitor";
import { WorkflowEditor } from "./components/WorkflowEditor";
import { createMockClient, type OpenBBQClient } from "./lib/apiClient";
import { workflowSteps } from "./lib/mockData";
import type { ReviewModel, Segment, SourceDraft, TaskMonitorModel, WorkflowStep } from "./lib/types";

type Screen = "source" | "workflow" | "monitor" | "results";

type AppProps = {
  client?: OpenBBQClient;
};

export function App({ client: providedClient }: AppProps = {}) {
  const defaultClient = useMemo(() => createMockClient(), []);
  const client = providedClient ?? defaultClient;
  const templateRequestId = useRef(0);
  const taskRequestId = useRef(0);
  const reviewRequestId = useRef(0);
  const retryInFlight = useRef(false);
  const [screen, setScreen] = useState<Screen>("source");
  const [source, setSource] = useState<SourceDraft | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>(workflowSteps);
  const [task, setTask] = useState<TaskMonitorModel | null>(null);
  const [review, setReview] = useState<ReviewModel | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [retryPending, setRetryPending] = useState(false);
  const footerValue =
    source?.kind === "remote_url" ? "remote URL" : source?.kind === "local_file" ? source.displayName : "creator-videos";

  async function handleSourceContinue(nextSource: SourceDraft) {
    const requestId = templateRequestId.current + 1;
    templateRequestId.current = requestId;
    setSource(nextSource);
    const nextSteps = await client.getWorkflowTemplate(nextSource);
    if (requestId !== templateRequestId.current) {
      return;
    }

    setSteps(nextSteps);
    setScreen("workflow");
  }

  function handleBackToSource() {
    templateRequestId.current += 1;
    taskRequestId.current += 1;
    reviewRequestId.current += 1;
    setSource(null);
    setSteps(workflowSteps);
    setTask(null);
    setReview(null);
    setRetryError(null);
    setRetryPending(false);
    retryInFlight.current = false;
    setScreen("source");
  }

  async function handleWorkflowContinue(nextSteps: WorkflowStep[]) {
    const requestId = taskRequestId.current + 1;
    taskRequestId.current = requestId;
    setSteps(nextSteps);
    setRetryError(null);
    setRetryPending(false);
    retryInFlight.current = false;
    const nextTask = await client.getTaskMonitor("run_sample");
    if (requestId !== taskRequestId.current) {
      return;
    }

    setTask(nextTask);
    setScreen("monitor");
  }

  async function handleRetry() {
    if (!task || retryInFlight.current) {
      return;
    }

    retryInFlight.current = true;
    setRetryError(null);
    setRetryPending(true);
    try {
      await client.retryCheckpoint(task.id);
      const nextTask = await client.getTaskMonitor(task.id);
      setTask(nextTask);
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : "checkpoint retry did not complete";
      setRetryError(`Retry failed: ${message}`);
    } finally {
      retryInFlight.current = false;
      setRetryPending(false);
    }
  }

  async function openReview(runId: string) {
    const requestId = reviewRequestId.current + 1;
    reviewRequestId.current = requestId;
    const nextReview = await client.getReview(runId);
    if (requestId !== reviewRequestId.current) {
      return;
    }

    setReview(nextReview);
    setScreen("results");
  }

  function handleNavigate(item: NavItem) {
    if (item === "New") {
      handleBackToSource();
      return;
    }

    if (item === "Tasks") {
      reviewRequestId.current += 1;
      if (task) {
        setScreen("monitor");
      }
      return;
    }

    if (item === "Results") {
      void openReview(task?.id ?? "run_sample");
    }
  }

  async function handleSegmentChange(segment: Segment) {
    await client.updateSegmentText({
      segmentId: segment.id,
      transcript: segment.transcript,
      translation: segment.translation
    });
  }

  const activeNav = screen === "monitor" ? "Tasks" : screen === "results" ? "Results" : "New";

  return (
    <AppShell active={activeNav} footerLabel={source ? "Source" : "Workspace"} footerValue={footerValue} onNavigate={handleNavigate}>
      {screen === "source" ? <SourceImport onContinue={handleSourceContinue} /> : null}
      {screen === "workflow" ? (
        <WorkflowEditor
          initialSteps={steps}
          onBack={handleBackToSource}
          onContinue={handleWorkflowContinue}
        />
      ) : null}
      {screen === "monitor" && task ? (
        <TaskMonitor task={task} onRetry={handleRetry} retryError={retryError} retryPending={retryPending} />
      ) : null}
      {screen === "results" && review ? (
        <ResultsReview model={review} onSegmentChange={handleSegmentChange} />
      ) : null}
    </AppShell>
  );
}
