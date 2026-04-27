import { useMemo, useRef, useState } from "react";

import { AppShell } from "./components/AppShell";
import { SourceImport } from "./components/SourceImport";
import { TaskMonitor } from "./components/TaskMonitor";
import { WorkflowEditor } from "./components/WorkflowEditor";
import { createMockClient, type OpenBBQClient } from "./lib/apiClient";
import { workflowSteps } from "./lib/mockData";
import type { SourceDraft, TaskMonitorModel, WorkflowStep } from "./lib/types";

type Screen = "source" | "workflow" | "monitor";

type AppProps = {
  client?: OpenBBQClient;
};

export function App({ client: providedClient }: AppProps = {}) {
  const defaultClient = useMemo(() => createMockClient(), []);
  const client = providedClient ?? defaultClient;
  const templateRequestId = useRef(0);
  const taskRequestId = useRef(0);
  const [screen, setScreen] = useState<Screen>("source");
  const [source, setSource] = useState<SourceDraft | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>(workflowSteps);
  const [task, setTask] = useState<TaskMonitorModel | null>(null);
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
    setSource(null);
    setSteps(workflowSteps);
    setTask(null);
    setScreen("source");
  }

  async function handleWorkflowContinue(nextSteps: WorkflowStep[]) {
    const requestId = taskRequestId.current + 1;
    taskRequestId.current = requestId;
    setSteps(nextSteps);
    const nextTask = await client.getTaskMonitor("run_sample");
    if (requestId !== taskRequestId.current) {
      return;
    }

    setTask(nextTask);
    setScreen("monitor");
  }

  function handleRetry() {
    if (!task) {
      return;
    }

    void client.retryCheckpoint(task.id);
  }

  return (
    <AppShell active={screen === "monitor" ? "Tasks" : "New"} footerLabel={source ? "Source" : "Workspace"} footerValue={footerValue}>
      {screen === "source" ? <SourceImport onContinue={handleSourceContinue} /> : null}
      {screen === "workflow" ? (
        <WorkflowEditor
          initialSteps={steps}
          onBack={handleBackToSource}
          onContinue={handleWorkflowContinue}
        />
      ) : null}
      {screen === "monitor" && task ? <TaskMonitor task={task} onRetry={handleRetry} /> : null}
    </AppShell>
  );
}
