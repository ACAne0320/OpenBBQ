import { useState } from "react";

import { AppShell } from "./components/AppShell";
import { SourceImport } from "./components/SourceImport";
import type { SourceDraft } from "./lib/types";

export function App() {
  const [source, setSource] = useState<SourceDraft | null>(null);
  const footerValue =
    source?.kind === "remote_url" ? "remote URL" : source?.kind === "local_file" ? source.displayName : "creator-videos";

  return (
    <AppShell active="New" footerLabel={source ? "Source" : "Workspace"} footerValue={footerValue}>
      <SourceImport onContinue={setSource} />
    </AppShell>
  );
}
