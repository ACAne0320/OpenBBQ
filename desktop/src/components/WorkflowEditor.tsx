import { useMemo, useState } from "react";

import type { StepParameter, WorkflowStep } from "../lib/types";
import { Button } from "./Button";
import { Toggle } from "./Toggle";

type WorkflowEditorProps = {
  initialSteps: WorkflowStep[];
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
  return steps[0]?.id === "fetch_source" ? "Remote video -> translated SRT" : "Local video -> translated SRT";
}

type ParameterFieldProps = {
  parameter: StepParameter;
  stepId: string;
  onChange: (stepId: string, parameterKey: string, value: boolean | string) => void;
};

function ParameterField({ onChange, parameter, stepId }: ParameterFieldProps) {
  if (parameter.kind === "toggle") {
    return (
      <div className="flex min-h-[72px] items-center justify-between gap-4 rounded-lg bg-paper-muted px-3.5 py-3 shadow-control">
        <div>
          <div className="text-sm font-extrabold text-ink-brown">{parameter.label}</div>
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
            <option key={option} value={option}>
              {option}
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

export function WorkflowEditor({ initialSteps, onBack, onContinue }: WorkflowEditorProps) {
  const [steps, setSteps] = useState<WorkflowStep[]>(initialSteps);
  const [selectedStepId, setSelectedStepId] = useState(initialSteps.find((step) => step.selected)?.id ?? initialSteps[0]?.id);
  const selectedStep = useMemo(
    () => steps.find((step) => step.id === selectedStepId) ?? steps[0],
    [selectedStepId, steps]
  );
  const templateTitle = templateTitleForSteps(steps);

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

  return (
    <section className="grid min-h-[calc(100vh-84px)] grid-rows-[auto_1fr_auto] gap-5">
      <header>
        <p className="text-[11px] uppercase text-muted">New task</p>
        <h1 className="mt-2 font-serif text-[40px] leading-none text-ink-brown">Arrange workflow</h1>
        <p className="mt-2 text-sm text-muted">{templateTitle}</p>
      </header>

      <div className="grid min-h-0 grid-cols-1 gap-[18px] xl:grid-cols-[minmax(420px,1fr)_minmax(360px,0.82fr)]">
        <section aria-label="Workflow steps" className="grid min-h-0 min-w-0 grid-rows-[auto_1fr] gap-4">
          <div>
            <h2 className="text-[22px] font-extrabold leading-tight text-ink-brown">{templateTitle}</h2>
            <p className="mt-1.5 text-sm text-muted">Choose the step to configure and keep optional steps on only when needed.</p>
          </div>

          <ol className="grid content-start gap-2.5 overflow-auto pr-1">
            {steps.map((step, index) => {
              const selected = step.id === selectedStep?.id;
              const locked = isLocked(step);
              const enabled = step.status !== "disabled";

              return (
                <li
                  key={step.id}
                  className={
                    selected
                      ? "grid min-h-[94px] grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-lg bg-paper-selected p-3 shadow-selected"
                      : "grid min-h-[94px] grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-lg bg-paper-muted p-3 shadow-control"
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
                          ? "flex h-7 w-7 items-center justify-center rounded-full bg-accent text-xs font-bold text-[#fff8ea]"
                          : "flex h-7 w-7 items-center justify-center rounded-full bg-ink-brown text-xs font-bold text-[#fff8ea]"
                      }
                    >
                      {index + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[15px] font-extrabold leading-tight text-ink-brown">{step.name}</span>
                      <span className="mt-1 block truncate text-xs text-muted">{step.toolRef}</span>
                      <span className="mt-1 block text-xs text-muted">{step.summary}</span>
                    </span>
                  </button>

                  <div className="flex min-w-[92px] flex-col items-end justify-center gap-2">
                    <span
                      className={
                        selected
                          ? "rounded-full bg-[#ead3c1] px-2 py-1 text-[11px] font-medium text-[#8c4d29]"
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
                  </div>
                </li>
              );
            })}
          </ol>
        </section>

        {selectedStep ? (
          <section
            aria-label="Selected step parameters"
            className="grid min-h-0 min-w-0 grid-rows-[auto_1fr] rounded-xl bg-paper-muted p-5 shadow-control"
          >
            <div>
              <p className="text-xs uppercase text-muted">Selected step parameters</p>
              <h2 className="mt-2 text-2xl font-extrabold leading-tight text-ink-brown">{selectedStep.name}</h2>
              <p className="mt-1.5 text-sm text-muted">{selectedStep.toolRef}</p>
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
