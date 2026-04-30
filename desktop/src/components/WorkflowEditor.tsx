import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import type { StepParameter, WorkflowStep, WorkflowTool } from "../lib/types";
import { Button } from "./Button";
import { Toggle } from "./Toggle";

type WorkflowEditorProps = {
  initialSteps: WorkflowStep[];
  availableTools?: WorkflowTool[];
  onContinue: (steps: WorkflowStep[]) => void;
  onBack?: () => void;
};

function isLocked(step: WorkflowStep) {
  return step.status === "locked";
}

function statusLabel(step: WorkflowStep) {
  if (isLocked(step)) {
    return "Required";
  }

  return step.status === "enabled" ? "Enabled" : "Disabled";
}

function templateTitleForSteps(steps: WorkflowStep[]) {
  return steps[0]?.id === "download" || steps[0]?.id === "fetch_source"
    ? "Remote video -> translated SRT"
    : "Local video -> translated SRT";
}

function toolStepId(tool: WorkflowTool, steps: WorkflowStep[]) {
  const base = tool.toolRef.replace(/[^a-zA-Z0-9_-]+/g, "_").toLowerCase();
  if (!steps.some((step) => step.id === base)) {
    return base;
  }
  let index = 2;
  while (steps.some((step) => step.id === `${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}

function bindToolInputs(tool: WorkflowTool, steps: WorkflowStep[]) {
  const bindings: Record<string, string> = {};
  for (const [inputName, input] of Object.entries(tool.inputs)) {
    const match = [...steps]
      .reverse()
      .flatMap((step) => (step.outputs ?? []).map((output) => ({ step, output })))
      .find(({ output }) => input.artifactTypes.includes(output.type));
    if (!match && input.required) {
      return null;
    }
    if (match) {
      bindings[inputName] = `${match.step.id}.${match.output.name}`;
    }
  }
  return bindings;
}

function toolSummary(tool: WorkflowTool) {
  const input = Object.keys(tool.inputs)[0] ?? "input";
  const output = tool.outputs[0]?.type?.replace(/_/g, " ") ?? "output";
  return `${input} -> ${output}`;
}

function createStepFromTool(tool: WorkflowTool, steps: WorkflowStep[]): WorkflowStep | null {
  const inputs = bindToolInputs(tool, steps);
  if (!inputs) {
    return null;
  }
  return {
    id: toolStepId(tool, steps),
    name: tool.name,
    toolRef: tool.toolRef,
    summary: toolSummary(tool),
    status: "enabled",
    inputs,
    outputs: tool.outputs,
    parameters: tool.parameters.map((parameter) => ({ ...parameter }))
  };
}

function insertionIndexForStep(steps: WorkflowStep[]) {
  const subtitleIndex = steps.findIndex((step) => step.id === "subtitle");
  return subtitleIndex === -1 ? steps.length : subtitleIndex;
}

type ParameterFieldProps = {
  parameter: StepParameter;
  stepId: string;
  onChange: (stepId: string, parameterKey: string, value: boolean | string) => void;
};

type SelectParameter = Extract<StepParameter, { kind: "select" }>;

function selectOptionValue(option: SelectParameter["options"][number]) {
  return typeof option === "string" ? option : option.value;
}

function selectOptionLabel(option: SelectParameter["options"][number]) {
  return typeof option === "string" ? option : option.label;
}

function ParameterField({ onChange, parameter, stepId }: ParameterFieldProps) {
  if (parameter.kind === "toggle") {
    return (
      <div className="flex min-h-[72px] items-center justify-between gap-4 rounded-lg bg-paper-muted px-3.5 py-3 shadow-control">
        <div>
          <div className="text-sm font-semibold text-ink-brown">{parameter.label}</div>
          <div className="mt-1 text-xs leading-snug text-muted">{parameter.description}</div>
        </div>
        <Toggle
          checked={parameter.value}
          label={parameter.label}
          onChange={(checked) => onChange(stepId, parameter.key, checked)}
        />
      </div>
    );
  }

  if (parameter.kind === "select") {
    return (
      <label className="grid gap-2 text-xs font-medium text-muted">
        {parameter.label}
        <select
          value={parameter.value}
          onChange={(event) => onChange(stepId, parameter.key, event.target.value)}
          className="min-h-11 rounded-md bg-paper-muted px-3 text-sm font-normal text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {parameter.options.map((option) => (
            <option key={selectOptionValue(option)} value={selectOptionValue(option)}>
              {selectOptionLabel(option)}
            </option>
          ))}
        </select>
      </label>
    );
  }

  return (
    <label className="grid gap-2 text-xs font-medium text-muted">
      {parameter.label}
      <input
        value={parameter.value}
        onChange={(event) => onChange(stepId, parameter.key, event.target.value)}
        className="min-h-11 rounded-md bg-paper-muted px-3 text-sm font-normal text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      />
    </label>
  );
}

export function WorkflowEditor({ availableTools = [], initialSteps, onBack, onContinue }: WorkflowEditorProps) {
  const [steps, setSteps] = useState<WorkflowStep[]>(initialSteps);
  const [selectedStepId, setSelectedStepId] = useState(initialSteps.find((step) => step.selected)?.id ?? initialSteps[0]?.id);
  const [selectedToolRef, setSelectedToolRef] = useState(availableTools[0]?.toolRef ?? "");
  const selectedStep = useMemo(
    () => steps.find((step) => step.id === selectedStepId) ?? steps[0],
    [selectedStepId, steps]
  );
  const templateTitle = templateTitleForSteps(steps);
  const selectedTool = availableTools.find((tool) => tool.toolRef === selectedToolRef) ?? availableTools[0];
  const selectedToolBindable = selectedTool ? bindToolInputs(selectedTool, steps) !== null : false;

  function toggleStep(stepId: string, checked: boolean) {
    setSteps((current) =>
      current.map((step) => {
        if (step.id !== stepId || isLocked(step)) {
          return step;
        }

        return { ...step, status: checked ? "enabled" : "disabled" };
      })
    );
  }

  function updateParameter(stepId: string, parameterKey: string, value: boolean | string) {
    setSteps((current) =>
      current.map((step) => {
        if (step.id !== stepId) {
          return step;
        }

        return {
          ...step,
          parameters: step.parameters.map((parameter) => {
            if (parameter.key !== parameterKey) {
              return parameter;
            }

            if (parameter.kind === "toggle" && typeof value === "boolean") {
              return { ...parameter, value };
            }

            if (parameter.kind !== "toggle" && typeof value === "string") {
              return { ...parameter, value };
            }

            return parameter;
          })
        };
      })
    );
  }

  function addStep() {
    if (!selectedTool) {
      return;
    }
    const nextStep = createStepFromTool(selectedTool, steps);
    if (!nextStep) {
      return;
    }
    setSteps((current) => {
      const insertAt = insertionIndexForStep(current);
      return [...current.slice(0, insertAt), nextStep, ...current.slice(insertAt)];
    });
    setSelectedStepId(nextStep.id);
  }

  function removeStep(stepId: string) {
    setSteps((current) => {
      const step = current.find((item) => item.id === stepId);
      if (!step || isLocked(step)) {
        return current;
      }
      const next = current.filter((item) => item.id !== stepId);
      if (selectedStepId === stepId) {
        setSelectedStepId(next[0]?.id);
      }
      return next;
    });
  }

  function moveStep(stepId: string, direction: -1 | 1) {
    setSteps((current) => {
      const index = current.findIndex((step) => step.id === stepId);
      const targetIndex = index + direction;
      if (index < 0 || targetIndex < 0 || targetIndex >= current.length) {
        return current;
      }
      const next = [...current];
      const [step] = next.splice(index, 1);
      next.splice(targetIndex, 0, step);
      return next;
    });
  }

  return (
    <section className="grid min-h-[calc(100vh-76px)] grid-rows-[auto_1fr_auto] gap-5">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
        <p className="text-[11px] font-semibold uppercase text-muted">New task</p>
        <h1 className="mt-2 text-[32px] font-semibold leading-tight tracking-[-0.022em] text-ink-brown">Arrange workflow</h1>
        <p className="mt-2 text-sm text-muted">{templateTitle}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs text-muted">
          <span className="rounded-full bg-paper-muted px-3 py-1.5 shadow-control">{steps.length} steps</span>
          <span className="rounded-full bg-accent-soft px-3 py-1.5 font-semibold text-accent">
            {steps.filter((step) => step.status !== "disabled").length} active
          </span>
        </div>
      </header>

      <div className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(460px,1fr)_minmax(340px,420px)]">
        <section aria-label="Workflow steps" className="grid min-h-0 min-w-0 grid-rows-[auto_1fr] rounded-xl bg-paper-muted p-4 shadow-control">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-[20px] font-semibold leading-tight tracking-[-0.012em] text-ink-brown">{templateTitle}</h2>
              <p className="mt-1.5 text-sm text-muted">Configure the automation path before starting the run.</p>
            </div>
          </div>

          {availableTools.length > 0 ? (
            <div className="mb-4 grid gap-2 rounded-lg bg-paper p-3 shadow-control sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
              <label className="grid gap-2 text-xs font-medium text-muted">
                Add workflow step
                <select
                  value={selectedToolRef}
                  onChange={(event) => setSelectedToolRef(event.target.value)}
                  className="min-h-10 rounded-md bg-paper-muted px-3 text-sm font-normal text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  {availableTools.map((tool) => (
                    <option key={tool.toolRef} value={tool.toolRef}>
                      {tool.name}
                    </option>
                  ))}
                </select>
              </label>
              <Button disabled={!selectedToolBindable} onClick={addStep} variant={selectedToolBindable ? "secondary" : "disabled"}>
                <span className="inline-flex items-center gap-2">
                  <Plus size={16} aria-hidden="true" />
                  Add step
                </span>
              </Button>
            </div>
          ) : null}

          <ol className="grid content-start gap-2 overflow-auto pr-1">
            {steps.map((step, index) => {
              const selected = step.id === selectedStep?.id;
              const locked = isLocked(step);
              const enabled = step.status !== "disabled";
              const canMoveUp = index > 0;
              const canMoveDown = index < steps.length - 1;

              return (
                <li
                  key={step.id}
                  className={
                    selected
                      ? "grid min-h-[88px] grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-lg bg-paper-selected p-3 shadow-selected"
                      : "grid min-h-[88px] grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-lg bg-paper p-3 shadow-control"
                  }
                >
                  <button
                    type="button"
                    aria-label={`Select step ${index + 1}: ${step.name}`}
                    aria-pressed={selected}
                    onClick={() => setSelectedStepId(step.id)}
                    className="grid min-w-0 grid-cols-[34px_minmax(0,1fr)] items-center gap-3 rounded-md text-left transition-transform duration-150 active:scale-[0.99] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    <span
                      className={
                        selected
                          ? "flex h-7 w-7 items-center justify-center rounded-full bg-accent text-xs font-bold text-paper"
                          : enabled
                            ? "flex h-7 w-7 items-center justify-center rounded-full bg-state-running text-xs font-bold text-accent"
                            : "flex h-7 w-7 items-center justify-center rounded-full bg-paper-side text-xs font-bold text-muted"
                      }
                    >
                      {index + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[15px] font-semibold leading-tight text-ink-brown">{step.name}</span>
                      <span className="mt-1 block truncate text-xs text-muted">{step.toolRef}</span>
                      <span className="mt-1 block text-xs text-muted">{step.summary}</span>
                    </span>
                  </button>

                  <div className="flex min-w-[92px] flex-col items-end justify-center gap-2">
                    <span
                      className={
                        selected
                          ? "rounded-full bg-accent-soft px-2 py-1 text-[11px] font-medium text-accent"
                          : "rounded-full bg-paper px-2 py-1 text-[11px] font-medium text-muted shadow-control"
                      }
                    >
                      {statusLabel(step)}
                    </span>
                    <Toggle
                      checked={enabled}
                      disabled={locked}
                      label={locked ? `${step.name} is required` : `Enable ${step.name}`}
                      onChange={(checked) => toggleStep(step.id, checked)}
                    />
                    <div className="flex gap-1">
                      <button
                        type="button"
                        aria-label={`Move ${step.name} up`}
                        disabled={!canMoveUp}
                        onClick={() => moveStep(step.id, -1)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-paper text-muted shadow-control transition-colors hover:text-ink-brown focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-paper-side disabled:text-muted disabled:shadow-none"
                      >
                        <ArrowUp size={15} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        aria-label={`Move ${step.name} down`}
                        disabled={!canMoveDown}
                        onClick={() => moveStep(step.id, 1)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-paper text-muted shadow-control transition-colors hover:text-ink-brown focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-paper-side disabled:text-muted disabled:shadow-none"
                      >
                        <ArrowDown size={15} aria-hidden="true" />
                      </button>
                    </div>
                    {!locked ? (
                      <button
                        type="button"
                        aria-label={`Remove ${step.name}`}
                        onClick={() => removeStep(step.id)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-paper text-muted shadow-control transition-colors hover:text-ink-brown focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      >
                        <Trash2 size={15} aria-hidden="true" />
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>

        {selectedStep ? (
          <section
            aria-label="Selected step parameters"
            className="grid min-h-0 min-w-0 grid-rows-[auto_1fr] rounded-xl bg-paper-muted p-4 shadow-control"
          >
            <div className="rounded-lg bg-paper p-4 shadow-control">
              <p className="text-xs uppercase text-muted">Selected step parameters</p>
              <h2 className="mt-2 text-2xl font-semibold leading-tight tracking-[-0.012em] text-ink-brown">{selectedStep.name}</h2>
              <p className="mt-1.5 text-sm text-muted">{selectedStep.toolRef}</p>
              <span className="mt-3 inline-flex rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent">
                {statusLabel(selectedStep)}
              </span>
            </div>

            <div className="mt-5 grid content-start gap-3.5 overflow-auto pr-1">
              {selectedStep.parameters.map((parameter) => (
                <ParameterField
                  key={parameter.key}
                  parameter={parameter}
                  stepId={selectedStep.id}
                  onChange={updateParameter}
                />
              ))}
            </div>
          </section>
        ) : null}
      </div>

      <footer className="flex items-center justify-end gap-2">
        <Button disabled={!onBack} onClick={onBack} variant={onBack ? "secondary" : "disabled"}>
          Back
        </Button>
        <Button variant="primary" onClick={() => onContinue(steps)}>
          Continue
        </Button>
      </footer>
    </section>
  );
}
