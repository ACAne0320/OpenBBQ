import { useMemo, useState } from "react";

import { AppShell } from "./components/AppShell";
import { SourceImport } from "./components/SourceImport";
import { WorkflowEditor } from "./components/WorkflowEditor";
import { createMockClient } from "./lib/apiClient";
import { workflowSteps } from "./lib/mockData";
import type { SourceDraft, WorkflowStep } from "./lib/types";

type Screen = "source" | "workflow";

export function App() {
  const client = useMemo(() => createMockClient(), []);
  const [screen, setScreen] = useState<Screen>("source");
  const [source, setSource] = useState<SourceDraft | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>(workflowSteps);
  const footerValue =
    source?.kind === "remote_url" ? "remote URL" : source?.kind === "local_file" ? source.displayName : "creator-videos";

  async function handleSourceContinue(nextSource: SourceDraft) {
    setSource(nextSource);
    setSteps(await client.getWorkflowTemplate(nextSource));
    setScreen("workflow");
  }

  return (
    <AppShell active="New" footerLabel={source ? "Source" : "Workspace"} footerValue={footerValue}>
      {screen === "source" ? <SourceImport onContinue={handleSourceContinue} /> : null}
      {screen === "workflow" ? (
        <WorkflowEditor
          initialSteps={steps}
          onBack={() => setScreen("source")}
          onContinue={(nextSteps) => {
            setSteps(nextSteps);
          }}
        />
      ) : null}
    </AppShell>
  );
}
