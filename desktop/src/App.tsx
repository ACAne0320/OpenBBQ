import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "./components/AppShell";
import type { NavItem } from "./components/AppShell";
import { ResultsReview } from "./components/ResultsReview";
import { SourceImport } from "./components/SourceImport";
import { TaskMonitor } from "./components/TaskMonitor";
import { WorkflowEditor } from "./components/WorkflowEditor";
import type { OpenBBQClient } from "./lib/apiClient";
import { createDefaultClient } from "./lib/clientFactory";
import { workflowSteps } from "./lib/mockData";
import type { ReviewModel, Segment, SourceDraft, TaskMonitorModel, WorkflowStep } from "./lib/types";

type Screen = "source" | "workflow" | "monitor" | "results";

type AppProps = {
  client?: OpenBBQClient;
};

export function App({ client: providedClient }: AppProps = {}) {
  const defaultClient = useMemo(() => createDefaultClient(), []);
  const client = providedClient ?? defaultClient;
  const templateRequestId = useRef(0);
  const taskRequestId = useRef(0);
  const reviewRequestId = useRef(0);
  const retryRequestId = useRef(0);
  const retryInFlight = useRef(false);
  const [screen, setScreen] = useState<Screen>("source");
  const [source, setSource] = useState<SourceDraft | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>(workflowSteps);
  const [task, setTask] = useState<TaskMonitorModel | null>(null);
  const [review, setReview] = useState<ReviewModel | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [retryPending, setRetryPending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const footerValue =
    source?.kind === "remote_url" ? "remote URL" : source?.kind === "local_file" ? source.displayName : "creator-videos";

  function invalidateReviewRequest() {
    reviewRequestId.current += 1;
  }

  function invalidateTemplateRequest() {
    templateRequestId.current += 1;
  }

  function invalidateTaskRequest() {
    taskRequestId.current += 1;
  }

  function cancelRetryState() {
    retryRequestId.current += 1;
    retryInFlight.current = false;
    setRetryError(null);
    setRetryPending(false);
  }

  function formatLoadError(prefix: string, error: unknown): string {
    const message = error instanceof Error && error.message ? error.message : "sidecar request failed";
    return `${prefix}: ${message}`;
  }

  async function handleSourceContinue(nextSource: SourceDraft) {
    const requestId = templateRequestId.current + 1;
    templateRequestId.current = requestId;
    invalidateReviewRequest();
    setSource(nextSource);
    setLoadError(null);
    try {
      const nextSteps = await client.getWorkflowTemplate(nextSource);
      if (requestId !== templateRequestId.current) {
        return;
      }

      setSteps(nextSteps);
      setScreen("workflow");
    } catch (error) {
      if (requestId !== templateRequestId.current) {
        return;
      }

      setLoadError(formatLoadError("Could not load workflow template", error));
    }
  }

  function handleBackToSource() {
    invalidateTemplateRequest();
    invalidateTaskRequest();
    invalidateReviewRequest();
    cancelRetryState();
    setSource(null);
    setSteps(workflowSteps);
    setTask(null);
    setReview(null);
    setRetryError(null);
    setRetryPending(false);
    setLoadError(null);
    setScreen("source");
  }

  async function handleWorkflowContinue(nextSteps: WorkflowStep[]) {
    if (!source) {
      setLoadError("Could not start task: source is missing");
      return;
    }

    const requestId = taskRequestId.current + 1;
    taskRequestId.current = requestId;
    invalidateReviewRequest();
    cancelRetryState();
    setSteps(nextSteps);
    setRetryError(null);
    setRetryPending(false);
    setLoadError(null);
    try {
      const started = await client.startSubtitleTask({ source, steps: nextSteps });
      if (requestId !== taskRequestId.current) {
        return;
      }

      const nextTask = await client.getTaskMonitor(started.runId);
      if (requestId !== taskRequestId.current) {
        return;
      }

      setTask(nextTask);
      setScreen("monitor");
    } catch (error) {
      if (requestId !== taskRequestId.current) {
        return;
      }

      setLoadError(formatLoadError("Could not start task", error));
    }
  }

  async function handleRetry() {
    if (!task || retryInFlight.current) {
      return;
    }

    retryInFlight.current = true;
    const requestId = retryRequestId.current + 1;
    retryRequestId.current = requestId;
    setRetryError(null);
    setRetryPending(true);
    try {
      await client.retryCheckpoint(task.id);
      if (requestId !== retryRequestId.current) {
        return;
      }

      const nextTask = await client.getTaskMonitor(task.id);
      if (requestId !== retryRequestId.current) {
        return;
      }

      setTask(nextTask);
    } catch (error) {
      if (requestId !== retryRequestId.current) {
        return;
      }

      const message = error instanceof Error && error.message ? error.message : "checkpoint retry did not complete";
      setRetryError(`Retry failed: ${message}`);
    } finally {
      if (requestId === retryRequestId.current) {
        retryInFlight.current = false;
        setRetryPending(false);
      }
    }
  }

  async function openReview(runId: string) {
    invalidateTemplateRequest();
    invalidateTaskRequest();
    const requestId = reviewRequestId.current + 1;
    reviewRequestId.current = requestId;
    setLoadError(null);
    try {
      const nextReview = await client.getReview(runId);
      if (requestId !== reviewRequestId.current) {
        return;
      }

      setReview(nextReview);
      setScreen("results");
    } catch (error) {
      if (requestId !== reviewRequestId.current) {
        return;
      }

      setLoadError(formatLoadError("Could not load review results", error));
    }
  }

  function handleNavigate(item: NavItem) {
    if (item === "New") {
      handleBackToSource();
      return;
    }

    if (item === "Tasks") {
      invalidateReviewRequest();
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

  useEffect(() => {
    if (screen !== "monitor" || !task) {
      return undefined;
    }

    if (task.status !== "queued" && task.status !== "running" && task.status !== "paused") {
      return undefined;
    }

    const interval = window.setInterval(() => {
      const runId = task.id;
      void client
        .getTaskMonitor(runId)
        .then((nextTask) => {
          setTask((current) => (current?.id === runId ? nextTask : current));
        })
        .catch(() => undefined);
    }, 1500);

    return () => window.clearInterval(interval);
  }, [client, screen, task]);

  const activeNav = screen === "monitor" ? "Tasks" : screen === "results" ? "Results" : "New";

  return (
    <AppShell active={activeNav} footerLabel={source ? "Source" : "Workspace"} footerValue={footerValue} onNavigate={handleNavigate}>
      {loadError ? (
        <div className="mb-4 rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-[#6b3f27]" role="alert">
          {loadError}
        </div>
      ) : null}
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
