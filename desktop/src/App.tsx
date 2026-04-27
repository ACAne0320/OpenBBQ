import { useMemo, useRef, useState } from "react";

import { AppShell } from "./components/AppShell";
import { SourceImport } from "./components/SourceImport";
import { WorkflowEditor } from "./components/WorkflowEditor";
import { createMockClient, type OpenBBQClient } from "./lib/apiClient";
import { workflowSteps } from "./lib/mockData";
import type { SourceDraft, WorkflowStep } from "./lib/types";

type Screen = "source" | "workflow";

type AppProps = {
  client?: OpenBBQClient;
};

export function App({ client: providedClient }: AppProps = {}) {
  const defaultClient = useMemo(() => createMockClient(), []);
  const client = providedClient ?? defaultClient;
  const templateRequestId = useRef(0);
  const [screen, setScreen] = useState<Screen>("source");
  const [source, setSource] = useState<SourceDraft | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>(workflowSteps);
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
    setSource(null);
    setSteps(workflowSteps);
    setScreen("source");
  }

  return (
    <AppShell active="New" footerLabel={source ? "Source" : "Workspace"} footerValue={footerValue}>
      {screen === "source" ? <SourceImport onContinue={handleSourceContinue} /> : null}
      {screen === "workflow" ? (
        <WorkflowEditor
          initialSteps={steps}
          onBack={handleBackToSource}
          onContinue={(nextSteps) => {
            setSteps(nextSteps);
          }}
        />
      ) : null}
    </AppShell>
  );
}
