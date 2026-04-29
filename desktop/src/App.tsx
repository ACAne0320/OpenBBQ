import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "./components/AppShell";
import type { NavItem } from "./components/AppShell";
import { ResultsReview } from "./components/ResultsReview";
import { Settings } from "./components/Settings";
import { SourceImport } from "./components/SourceImport";
import { TaskHistory } from "./components/TaskHistory";
import { TaskMonitor } from "./components/TaskMonitor";
import { WorkflowEditor } from "./components/WorkflowEditor";
import type { OpenBBQClient } from "./lib/apiClient";
import { createDefaultClient } from "./lib/clientFactory";
import { workflowSteps } from "./lib/mockData";
import type { ReviewModel, Segment, SourceDraft, TaskMonitorModel, TaskSummary, WorkflowStep } from "./lib/types";

type Screen = "source" | "workflow" | "tasks" | "monitor" | "results" | "settings";

type AppProps = {
  client?: OpenBBQClient;
};

export function App({ client: providedClient }: AppProps = {}) {
  const defaultClient = useMemo(() => createDefaultClient(), []);
  const client = providedClient ?? defaultClient;
  const templateRequestId = useRef(0);
  const taskRequestId = useRef(0);
  const taskListRequestId = useRef(0);
  const reviewRequestId = useRef(0);
  const autoOpenedReviewRunId = useRef<string | null>(null);
  const retryRequestId = useRef(0);
  const retryInFlight = useRef(false);
  const [screen, setScreen] = useState<Screen>("source");
  const [source, setSource] = useState<SourceDraft | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>(workflowSteps);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [task, setTask] = useState<TaskMonitorModel | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
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

  function invalidateTaskListRequest() {
    taskListRequestId.current += 1;
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
    invalidateTaskListRequest();
    invalidateReviewRequest();
    cancelRetryState();
    setSource(null);
    setSteps(workflowSteps);
    setTask(null);
    setSelectedRunId(null);
    autoOpenedReviewRunId.current = null;
    setTasksError(null);
    setTasksLoading(false);
    setReview(null);
    setRetryError(null);
    setRetryPending(false);
    setLoadError(null);
    setScreen("source");
  }

  async function loadTaskHistory() {
    const requestId = taskListRequestId.current + 1;
    taskListRequestId.current = requestId;
    invalidateTemplateRequest();
    invalidateReviewRequest();
    setTasksError(null);
    setTasksLoading(true);
    setScreen("tasks");
    try {
      const nextTasks = await client.listTasks();
      if (requestId !== taskListRequestId.current) {
        return;
      }

      setTasks(nextTasks);
    } catch (error) {
      if (requestId !== taskListRequestId.current) {
        return;
      }

      setTasksError(formatLoadError("Could not load tasks", error));
    } finally {
      if (requestId === taskListRequestId.current) {
        setTasksLoading(false);
      }
    }
  }

  async function openTaskMonitor(runId: string) {
    const requestId = taskRequestId.current + 1;
    taskRequestId.current = requestId;
    invalidateTemplateRequest();
    invalidateReviewRequest();
    cancelRetryState();
    setLoadError(null);
    try {
      const nextTask = await client.getTaskMonitor(runId);
      if (requestId !== taskRequestId.current) {
        return;
      }

      setSelectedRunId(nextTask.id);
      setTask(nextTask);
      setScreen("monitor");
    } catch (error) {
      if (requestId !== taskRequestId.current) {
        return;
      }

      setTasksError(formatLoadError("Could not open task", error));
      setScreen("tasks");
    }
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

      setSelectedRunId(started.runId);
      const nextTask = await client.getTaskMonitor(started.runId);
      if (requestId !== taskRequestId.current) {
        return;
      }

      setSelectedRunId(nextTask.id);
      setTask(nextTask);
      setScreen("monitor");
      if (nextTask.status === "completed") {
        void openReview(nextTask.id);
      }
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
        return;
      }
      void loadTaskHistory();
      return;
    }

    if (item === "Results") {
      const runId = task?.id ?? selectedRunId;
      if (runId) {
        void openReview(runId);
        return;
      }
      setLoadError("Could not load review results: no task is selected");
      return;
    }

    if (item === "Settings") {
      invalidateTemplateRequest();
      invalidateTaskRequest();
      invalidateTaskListRequest();
      invalidateReviewRequest();
      cancelRetryState();
      setLoadError(null);
      setScreen("settings");
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

  useEffect(() => {
    if (screen !== "monitor" || task?.status !== "completed") {
      return;
    }
    if (autoOpenedReviewRunId.current === task.id) {
      return;
    }
    autoOpenedReviewRunId.current = task.id;
    void openReview(task.id);
  }, [screen, task]);

  const activeNav =
    screen === "settings"
      ? "Settings"
      : screen === "tasks" || screen === "monitor"
        ? "Tasks"
        : screen === "results"
          ? "Results"
          : "New";

  return (
    <AppShell active={activeNav} footerLabel={source ? "Source" : "Workspace"} footerValue={footerValue} onNavigate={handleNavigate}>
      {loadError ? (
        <div className="mb-4 rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-[#6b3f27]" role="alert">
          {loadError}
        </div>
      ) : null}
      {screen === "source" ? <SourceImport onContinue={handleSourceContinue} onChooseLocalMedia={client.chooseLocalMedia} /> : null}
      {screen === "workflow" ? (
        <WorkflowEditor
          initialSteps={steps}
          onBack={handleBackToSource}
          onContinue={handleWorkflowContinue}
        />
      ) : null}
      {screen === "tasks" ? (
        <TaskHistory
          error={tasksError}
          loading={tasksLoading}
          onOpenTask={openTaskMonitor}
          onRefresh={loadTaskHistory}
          tasks={tasks}
        />
      ) : null}
      {screen === "monitor" && task ? (
        <TaskMonitor task={task} onRetry={handleRetry} retryError={retryError} retryPending={retryPending} />
      ) : null}
      {screen === "results" && review ? (
        <ResultsReview model={review} onSegmentChange={handleSegmentChange} />
      ) : null}
      {screen === "settings" ? (
        <Settings
          checkLlmProvider={client.checkLlmProvider}
          downloadFasterWhisperModel={client.downloadFasterWhisperModel}
          getFasterWhisperModelDownload={client.getFasterWhisperModelDownload}
          loadDiagnostics={client.getDiagnostics}
          loadModels={client.getRuntimeModels}
          loadSettings={client.getRuntimeSettings}
          saveFasterWhisperDefaults={client.saveFasterWhisperDefaults}
          saveLlmProvider={client.saveLlmProvider}
          saveRuntimeDefaults={client.saveRuntimeDefaults}
        />
      ) : null}
    </AppShell>
  );
}
