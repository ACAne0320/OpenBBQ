# Real progress percentages design

## Context

The desktop app needs visible percentage progress for two surfaces:

- Faster Whisper model downloads in Settings > ASR model.
- Long-running task stages in the Task run page runtime log: video download,
  video-to-audio extraction, ASR parsing, and translation.

The current system cannot provide real percentages end to end. Workflow plugins
return `events` only after the plugin call finishes, so the task monitor cannot
observe in-flight work. The model download route is also synchronous: the
renderer starts a request and receives only the final model status. A real
percentage feature therefore needs a progress data path, not just a frontend
bar.

## Goals

- Report real `0..100` percentages for supported long-running operations.
- Show each model download percentage inline on the corresponding ASR model row.
- Show workflow stage percentages in the Task run page runtime log as
  log-styled progress rows.
- Preserve existing workflow step status, runtime logs, and task polling.
- Keep existing plugin compatibility: plugins that do not accept a progress
  callback continue to run unchanged.
- Make progress records safe to expose: no secrets, URLs with credentials, API
  keys, or local private values in progress messages.

## Non-goals

- Add cancellation or pause/resume for model downloads.
- Add progress for every possible third-party plugin.
- Replace the existing step progress dots in the task monitor.
- Add WebSocket/SSE consumption in Electron. Polling remains acceptable for this
  desktop UI.

## Progress event contract

Workflow progress is stored as regular workflow events with type
`step.progress`.

Each progress event includes:

```json
{
  "type": "step.progress",
  "step_id": "transcribe",
  "message": "ASR parsing 42%",
  "data": {
    "phase": "asr_parse",
    "label": "ASR parsing",
    "percent": 42.0,
    "current": 84.0,
    "total": 200.0,
    "unit": "seconds"
  }
}
```

Rules:

- `percent` is a number clamped to `0..100`.
- `label` is short UI text.
- `phase` is a stable machine key.
- `current`, `total`, and `unit` are optional but included when known.
- The workflow runner emits `0%` when a supported step starts and `100%` before
  the step completes. Built-in plugins emit intermediate percentages.
- Progress emission is throttled to avoid excessive event rows. It emits when
  percent changes by at least one point, when the phase/label changes, and always
  for `0` and `100`.

## Workflow progress architecture

Add a small backend progress reporter:

- `openbbq.workflow.progress.ProgressReporter` validates and appends
  `step.progress` events to the project store.
- `execute_step_attempt` creates a reporter for the active workflow step.
- `execute_plugin_tool` inspects the plugin entrypoint signature. If the
  callable accepts a `progress` keyword argument, it calls:

  ```python
  entrypoint(request_payload, progress=progress_callback)
  ```

  Otherwise it preserves the current one-argument call.

This keeps existing external plugins source-compatible while allowing built-in
plugins to stream progress during execution.

## Built-in workflow progress sources

### Video download

`remote_video.download` attaches a `yt-dlp` `progress_hooks` callback. It uses
`downloaded_bytes / total_bytes` when available, falling back to
`total_bytes_estimate`. The plugin emits `Download video` progress from `0` to
`99` while downloading and `100` after the final output file exists.

### Video to audio

`ffmpeg.extract_audio` first obtains source media duration with `ffprobe`. It
runs ffmpeg with `-progress pipe:1 -nostats` and parses `out_time_ms` or
`out_time` progress records. Percent is `encoded_time / duration`. The plugin
emits `Extract audio` progress from `0` to `100`.

### ASR parsing

`faster_whisper.transcribe` uses Faster Whisper's returned transcription info
duration and each emitted segment end time. Percent is
`segment.end / info.duration`. The plugin emits `ASR parsing` progress as the
segment generator is consumed and emits `100` when all segments are persisted in
the response payload.

### Translation

`translation.translate` already chunks subtitle segments. Percent is based on
completed translated segment count divided by total input segment count. The
plugin emits `Translate` progress after each chunk and emits `100` when all
segments have been translated.

## Model download progress architecture

Model downloads become background jobs because an HTTP request that blocks until
completion cannot update the renderer with percentages.

Add a process-local model download manager in the backend application layer:

- `POST /runtime/models/faster-whisper/download` starts or reuses a job for a
  model and returns the job status immediately.
- `GET /runtime/models/faster-whisper/downloads/{job_id}` returns the latest job
  status.
- Job state includes `job_id`, `provider`, `model`, `status`, `percent`,
  `current_bytes`, `total_bytes`, `error`, `started_at`, `completed_at`, and the
  final `ModelAssetStatus` when available.
- If the model is already present, the job returns `completed` at `100%`.
- Jobs are process-local. This is acceptable for the desktop sidecar because
  active progress only needs to survive the current app process.

The downloader uses Hugging Face metadata plus `snapshot_download` progress:

- Resolve `tiny/base/small/medium/large-v3` to Systran repository IDs.
- Query repository sibling metadata for the files Faster Whisper needs.
- Sum matching file sizes to establish `total_bytes`.
- Run `huggingface_hub.snapshot_download` with the same allow patterns as
  Faster Whisper, using a custom tqdm class to report downloaded byte deltas.
- Emit `100%` after the snapshot is complete and refresh model status from the
  runtime cache directory.

## API and Electron contract

Backend API additions:

- `FasterWhisperDownloadJob` schema.
- `FasterWhisperDownloadData` returns `job`.
- `FasterWhisperDownloadStatusData` returns `job`.

Electron additions:

- Map `ApiWorkflowEvent` `step.progress` records into renderer progress lines.
- Map `ApiModelDownloadJob` to renderer `RuntimeModelDownloadJob`.
- Expose `downloadFasterWhisperModel(input)` as the job-start method.
- Add `getFasterWhisperModelDownload(jobId)` for polling.

Renderer type additions:

- `ProgressPercent` data shared by task progress and model download UI.
- `TaskProgressLogLine` for Task run runtime log progress rows.
- `RuntimeModelDownloadJob` for ASR model row progress.

## Frontend behavior

### Settings > ASR model

Each downloadable model row can show:

- The model name and status.
- A real progress bar with percentage while a download job is queued or running.
- `Downloaded` and disabled Download button after completion.
- An inline error message if the job fails.

The Settings component polls active model download jobs until each reaches
`completed` or `failed`. On completion, it refreshes model statuses and updates
the row.

### Task run runtime log

The Task run page keeps the existing textual log rows. Above or alongside them
inside the same runtime log panel, it renders log-styled progress rows derived
from latest `step.progress` events:

- Timestamp column from the latest progress event.
- Stage label such as `Download video`, `Extract audio`, `ASR parsing`, or
  `Translate`.
- Progress bar and percentage.
- Optional current/total text such as `84 / 200 seconds` or `12 / 48 segments`.

The app's existing 1.5 second task monitor polling is sufficient. Every poll can
show newer percentage events.

## Error handling

- If a progress source cannot determine a total, it emits `0%` at start and
  `100%` at completion rather than fabricating intermediate percentages.
- A failed workflow step keeps its latest progress row visible and the normal
  failed log/error UI remains authoritative.
- A failed model download job shows the error on the model row and re-enables
  the Download button.
- All progress messages pass through the existing redaction path when emitted
  from plugin execution.

## Testing strategy

- Backend unit tests cover progress event validation, throttling, plugin
  callback compatibility, and progress event persistence.
- Built-in plugin tests use fake `yt-dlp`, fake `ffprobe`/`ffmpeg`, fake Faster
  Whisper segments, and fake translation clients to assert percentage events.
- Runtime API tests cover starting a model download job, polling progress,
  completion, failure, unsupported model rejection, and already-present models.
- Electron tests cover mapping progress events and model download jobs.
- React tests cover ASR model row progress bars and Task run runtime log
  progress rows.
- Existing full backend and desktop test suites remain the final verification
  gate.
