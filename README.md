# OpenBBQ

**OpenBBQ** is an open-source workflow platform for media language processing.

It helps teams run structured pipelines for transcription, translation, subtitle generation, and quality review, while keeping humans in control at every important step.

OpenBBQ is designed for real production work: automate what should be automated, pause where judgment matters, and keep every output editable, versioned, and reusable.

## Why OpenBBQ?

In some Chinese fan-sub and creator communities, the process of translating and subtitling a video is colloquially called **“BBQ”**. Raw, untranslated media is sometimes described as “raw meat,” while translated and subtitled output becomes “cooked.”

**OpenBBQ** takes that cultural metaphor and gives it an open-source home: a platform for turning raw media into polished multilingual deliverables.

## What OpenBBQ Is

OpenBBQ is a workflow-first system for media language operations. It coordinates multi-stage pipelines such as:

- transcription
- translation
- subtitle segmentation
- review and quality assurance

The platform treats each stage as part of a controlled workflow rather than a one-off tool invocation. Human editors can step in, revise outputs, and continue execution from that point forward.

## Slice 1 CLI

The current backend is a local Python CLI managed with `uv`. It can initialize a project, load `openbbq.yaml`, discover trusted local plugin manifests, validate workflows, run deterministic mock workflows to completion, and inspect persisted state under `.openbbq/`.

Install dependencies and run the text fixture:

```bash
uv sync
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
uv run openbbq run text-demo --project tests/fixtures/projects/text-basic
uv run openbbq status text-demo --project tests/fixtures/projects/text-basic
```

Use `uv run openbbq --json <command>` for machine-readable output. `run` writes workflow state, event logs, and artifacts to the selected project's `.openbbq/` directory. Slice 2 commands such as `resume`, `abort`, `run --force`, `run --step`, and `artifact diff` currently return clear unsupported errors.
