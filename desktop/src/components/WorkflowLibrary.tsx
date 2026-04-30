import { CopyPlus, FileVideo, Link2, RefreshCw, SlidersHorizontal } from "lucide-react";

import type { WorkflowDefinition } from "../lib/types";
import { Button } from "./Button";

type WorkflowLibraryProps = {
  error?: string | null;
  loading?: boolean;
  workflows: WorkflowDefinition[];
  onCustomize: (workflow: WorkflowDefinition) => void;
  onRefresh: () => void;
  onUse: (workflow: WorkflowDefinition) => void;
};

function sourceLabel(workflow: WorkflowDefinition) {
  if (workflow.sourceTypes.includes("remote_url") && workflow.sourceTypes.includes("local_file")) {
    return "Local or remote source";
  }
  return workflow.sourceTypes.includes("remote_url") ? "Remote URL" : "Local media";
}

function originLabel(workflow: WorkflowDefinition) {
  return workflow.origin === "built_in" ? "Built-in" : "Custom";
}

function WorkflowIcon({ workflow }: { workflow: WorkflowDefinition }) {
  const Icon = workflow.sourceTypes.includes("remote_url") ? Link2 : FileVideo;
  return (
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-paper text-accent shadow-control">
      <Icon className="h-5 w-5" aria-hidden="true" />
    </span>
  );
}

export function WorkflowLibrary({
  error,
  loading = false,
  onCustomize,
  onRefresh,
  onUse,
  workflows
}: WorkflowLibraryProps) {
  return (
    <section className="grid min-h-[calc(100vh-76px)] grid-rows-[auto_1fr] gap-5">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase text-muted">Workflow library</p>
          <h1 className="mt-2 text-[32px] font-semibold leading-tight tracking-[-0.022em] text-ink-brown">
            Workflows
          </h1>
          <p className="mt-2 max-w-[68ch] text-sm leading-6 text-muted">
            Use a saved processing flow for a new task, or customize a copy before running it.
          </p>
        </div>
        <Button onClick={onRefresh} variant="secondary">
          <span className="inline-flex items-center gap-2">
            <RefreshCw size={16} aria-hidden="true" />
            Refresh
          </span>
        </Button>
      </header>

      <div className="min-h-0 overflow-auto pr-1">
        {error ? (
          <div className="mb-4 rounded-lg bg-accent-soft px-3.5 py-3 text-sm font-semibold text-ink" role="alert">
            {error}
          </div>
        ) : null}
        {loading ? (
          <div className="rounded-xl bg-paper-muted p-5 text-sm text-muted shadow-control">Loading workflows...</div>
        ) : null}
        {!loading && workflows.length === 0 ? (
          <div className="rounded-xl bg-paper-muted p-5 text-sm text-muted shadow-control">
            No workflows are available in this workspace.
          </div>
        ) : null}
        <ol className="grid gap-3">
          {workflows.map((workflow) => (
            <li key={workflow.id} className="rounded-xl bg-paper-muted p-4 shadow-control">
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                <div className="flex min-w-0 items-start gap-3">
                  <WorkflowIcon workflow={workflow} />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-[20px] font-semibold leading-tight tracking-[-0.012em] text-ink-brown">
                        {workflow.name}
                      </h2>
                      <span className="rounded-full bg-paper px-2.5 py-1 text-[11px] font-semibold text-muted shadow-control">
                        {originLabel(workflow)}
                      </span>
                    </div>
                    <p className="mt-1.5 max-w-[72ch] text-sm leading-6 text-muted">{workflow.description}</p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
                      <span className="rounded-full bg-paper px-3 py-1.5 shadow-control">{sourceLabel(workflow)}</span>
                      <span className="rounded-full bg-paper px-3 py-1.5 shadow-control">
                        {workflow.steps.length} steps
                      </span>
                      <span className="rounded-full bg-accent-soft px-3 py-1.5 font-semibold text-accent">
                        {workflow.resultTypes.join(", ")}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  <Button onClick={() => onUse(workflow)} variant="primary">
                    Use
                  </Button>
                  <Button onClick={() => onCustomize(workflow)} variant="secondary">
                    <span className="inline-flex items-center gap-2">
                      {workflow.origin === "built_in" ? (
                        <CopyPlus size={16} aria-hidden="true" />
                      ) : (
                        <SlidersHorizontal size={16} aria-hidden="true" />
                      )}
                      Customize
                    </span>
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
