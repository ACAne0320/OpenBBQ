# Real Progress Percentages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real percentage progress for Faster Whisper model downloads and for desktop task stages: video download, video-to-audio extraction, ASR parsing, and translation.

**Architecture:** Add a backend `step.progress` event pipeline for workflow steps, update built-in plugins to emit real percentages while they run, convert model downloads to pollable background jobs, then map those contracts through Electron into Settings and Task run progress bars. Existing task polling and workflow logs remain the UI refresh mechanism.

**Tech Stack:** Python, FastAPI, pytest, huggingface_hub, yt-dlp, ffmpeg/ffprobe, TypeScript, Electron IPC, React, Vitest, Playwright.

---

## File structure

- Create `src/openbbq/workflow/progress.py`: validation, throttling, and event append helpers for workflow step progress.
- Modify `src/openbbq/plugins/execution.py`: pass a progress callback to plugin entrypoints that accept `progress`.
- Modify `src/openbbq/workflow/steps.py`: create the per-step progress reporter and pass it through plugin execution.
- Modify built-in plugins:
  - `src/openbbq/builtin_plugins/remote_video/plugin.py`
  - `src/openbbq/builtin_plugins/ffmpeg/plugin.py`
  - `src/openbbq/builtin_plugins/faster_whisper/plugin.py`
  - `src/openbbq/builtin_plugins/translation/plugin.py`
- Create `src/openbbq/runtime/model_download_jobs.py`: process-local Faster Whisper download job manager.
- Modify `src/openbbq/runtime/models_assets.py`: expose Hugging Face repository resolution and progress-capable download helper.
- Modify `src/openbbq/application/runtime.py`, `src/openbbq/api/schemas.py`, and `src/openbbq/api/routes/runtime.py`: model download job contracts and routes.
- Modify Electron mappings:
  - `desktop/electron/apiTypes.ts`
  - `desktop/electron/ipc.ts`
  - `desktop/electron/taskMapping.ts`
  - `desktop/src/global.d.ts`
  - `desktop/src/lib/apiClient.ts`
  - `desktop/src/lib/desktopClient.ts`
  - `desktop/src/lib/types.ts`
- Modify React UI:
  - `desktop/src/components/Settings.tsx`
  - `desktop/src/components/TaskMonitor.tsx`
  - `desktop/src/lib/mockData.ts`
- Update tests:
  - `tests/test_workflow_progress.py`
  - `tests/test_plugins_progress.py`
  - `tests/test_api_projects_plugins_runtime.py`
  - `desktop/electron/__tests__/ipc.test.ts`
  - `desktop/src/components/__tests__/Settings.test.tsx`
  - `desktop/src/components/__tests__/TaskMonitor.test.tsx`
  - `desktop/src/__tests__/App.test.tsx`
  - `desktop/tests/desktop-ui.spec.ts`

### Task 1: Workflow progress event pipeline

**Files:**
- Create: `src/openbbq/workflow/progress.py`
- Modify: `src/openbbq/plugins/execution.py`
- Modify: `src/openbbq/workflow/steps.py`
- Test: `tests/test_workflow_progress.py`

- [ ] **Step 1: Write failing tests for progress reporter validation and throttling**

Add `tests/test_workflow_progress.py`:

```python
from pathlib import Path

from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.progress import ProgressReporter


def test_progress_reporter_appends_clamped_step_progress_events(tmp_path: Path):
    store = ProjectStore(tmp_path / ".openbbq")
    reporter = ProgressReporter(
        store,
        workflow_id="demo",
        step_id="transcribe",
        attempt=1,
        min_percent_delta=1,
    )

    reporter.report(phase="asr_parse", label="ASR parsing", percent=-10, current=0, total=100, unit="seconds")
    reporter.report(phase="asr_parse", label="ASR parsing", percent=42.4, current=42.4, total=100, unit="seconds")
    reporter.report(phase="asr_parse", label="ASR parsing", percent=42.8, current=42.8, total=100, unit="seconds")
    reporter.report(phase="asr_parse", label="ASR parsing", percent=120, current=100, total=100, unit="seconds")

    events = store.list_events("demo")
    assert [event.type for event in events] == ["step.progress", "step.progress", "step.progress"]
    assert [event.data["progress"]["percent"] for event in events] == [0, 42.4, 100]
    assert events[1].message == "ASR parsing 42%"
    assert events[1].step_id == "transcribe"
    assert events[1].attempt == 1


def test_progress_reporter_always_emits_phase_changes(tmp_path: Path):
    store = ProjectStore(tmp_path / ".openbbq")
    reporter = ProgressReporter(store, workflow_id="demo", step_id="download", attempt=1)

    reporter.report(phase="resolve", label="Resolve metadata", percent=5)
    reporter.report(phase="download", label="Download video", percent=5)

    events = store.list_events("demo")
    assert [event.data["progress"]["phase"] for event in events] == ["resolve", "download"]
```

- [ ] **Step 2: Run tests and verify they fail for missing module**

Run:

```bash
uv run pytest tests/test_workflow_progress.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'openbbq.workflow.progress'`.

- [ ] **Step 3: Implement `ProgressReporter`**

Create `src/openbbq/workflow/progress.py`:

```python
from __future__ import annotations

import math

from openbbq.storage.project_store import ProjectStore


class ProgressReporter:
    def __init__(
        self,
        store: ProjectStore,
        *,
        workflow_id: str,
        step_id: str,
        attempt: int,
        min_percent_delta: float = 1.0,
    ) -> None:
        self._store = store
        self._workflow_id = workflow_id
        self._step_id = step_id
        self._attempt = attempt
        self._min_percent_delta = min_percent_delta
        self._last_percent: float | None = None
        self._last_phase: str | None = None
        self._last_label: str | None = None

    def report(
        self,
        *,
        phase: str,
        label: str,
        percent: float,
        current: float | None = None,
        total: float | None = None,
        unit: str | None = None,
    ) -> None:
        normalized = _clamp_percent(percent)
        if not self._should_emit(phase=phase, label=label, percent=normalized):
            return
        self._last_phase = phase
        self._last_label = label
        self._last_percent = normalized
        progress = {
            "phase": phase,
            "label": label,
            "percent": normalized,
        }
        if current is not None:
            progress["current"] = current
        if total is not None:
            progress["total"] = total
        if unit is not None:
            progress["unit"] = unit
        self._store.append_event(
            self._workflow_id,
            {
                "type": "step.progress",
                "step_id": self._step_id,
                "attempt": self._attempt,
                "message": f"{label} {normalized:.0f}%",
                "data": {"progress": progress},
            },
        )

    def _should_emit(self, *, phase: str, label: str, percent: float) -> bool:
        if self._last_percent is None:
            return True
        if percent in {0, 100} and percent != self._last_percent:
            return True
        if phase != self._last_phase or label != self._last_label:
            return True
        return abs(percent - self._last_percent) >= self._min_percent_delta


def _clamp_percent(value: float) -> float:
    if not math.isfinite(value):
        return 0
    return max(0, min(100, float(value)))
```

- [ ] **Step 4: Run tests and verify reporter behavior passes**

Run:

```bash
uv run pytest tests/test_workflow_progress.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Write failing plugin callback compatibility tests**

Append to `tests/test_workflow_progress.py`:

```python
from pathlib import Path

from openbbq.plugins.execution import execute_plugin_tool
from openbbq.plugins.models import PluginSpec, ToolSpec
from openbbq.plugins.payloads import PluginRequest


def _plugin(tmp_path: Path, source: str) -> PluginSpec:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    manifest_path = plugin_dir / "openbbq.plugin.toml"
    manifest_path.write_text("name = 'demo'\nversion = '1.0.0'\n", encoding="utf-8")
    return PluginSpec(
        name="demo",
        version="1.0.0",
        runtime="python",
        manifest_path=manifest_path,
        entrypoint="plugin:run",
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        plugin_name="demo",
        name="demo",
        description="Demo tool.",
        input_artifact_types=[],
        output_artifact_types=["text"],
        parameter_schema={},
        effects=[],
        manifest_path=Path("openbbq.plugin.toml"),
    )


def _request(tmp_path: Path) -> PluginRequest:
    return PluginRequest(
        project_root=str(tmp_path),
        workflow_id="demo",
        step_id="step",
        attempt=1,
        tool_name="demo",
        parameters={},
        inputs={},
        work_dir=str(tmp_path / "work"),
    )


def test_execute_plugin_tool_passes_progress_callback_when_entrypoint_accepts_it(tmp_path: Path):
    plugin = _plugin(
        tmp_path,
        """
def run(request, progress=None):
    progress(phase="demo", label="Demo", percent=37)
    return {"outputs": {"out": {"type": "text", "content": "ok"}}}
""",
    )
    calls = []

    execute_plugin_tool(plugin, _tool(), _request(tmp_path), progress=lambda **payload: calls.append(payload))

    assert calls == [{"phase": "demo", "label": "Demo", "percent": 37}]


def test_execute_plugin_tool_keeps_one_argument_plugins_compatible(tmp_path: Path):
    plugin = _plugin(
        tmp_path,
        """
def run(request):
    return {"outputs": {"out": {"type": "text", "content": "ok"}}}
""",
    )

    response = execute_plugin_tool(plugin, _tool(), _request(tmp_path), progress=lambda **payload: None)

    assert response.outputs["out"].content == "ok"
```

- [ ] **Step 6: Run tests and verify callback tests fail**

Run:

```bash
uv run pytest tests/test_workflow_progress.py -q
```

Expected: fail with `TypeError` for unexpected `progress` argument in `execute_plugin_tool`.

- [ ] **Step 7: Pass progress through plugin execution**

Modify `src/openbbq/plugins/execution.py`:

```python
import inspect
```

Change the function signature:

```python
def execute_plugin_tool(
    plugin: PluginSpec,
    tool: ToolSpec,
    request: PluginRequest,
    redactor=None,
    progress=None,
) -> PluginResponse:
```

Replace the entrypoint call with:

```python
        request_payload = request.model_dump(mode="json")
        if progress is not None and _accepts_progress(entrypoint):
            response = entrypoint(request_payload, progress=progress)
        else:
            response = entrypoint(request_payload)
```

Add helper:

```python
def _accepts_progress(entrypoint) -> bool:
    try:
        signature = inspect.signature(entrypoint)
    except (TypeError, ValueError):
        return False
    parameters = signature.parameters
    if "progress" in parameters:
        return True
    return any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
```

- [ ] **Step 8: Connect `ProgressReporter` in `execute_step_attempt`**

Modify `src/openbbq/workflow/steps.py`:

```python
from openbbq.workflow.progress import ProgressReporter
```

Before `execute_plugin_tool`, create:

```python
        reporter = ProgressReporter(
            context.store,
            workflow_id=context.workflow.id,
            step_id=step.id,
            attempt=attempt,
        )
```

Pass callback:

```python
        raw_response = execute_plugin_tool(
            plugin,
            tool,
            request,
            redactor=redact_runtime_secrets,
            progress=reporter.report,
        )
```

- [ ] **Step 9: Run targeted progress tests**

Run:

```bash
uv run pytest tests/test_workflow_progress.py -q
```

Expected: all tests pass.

- [ ] **Step 10: Commit Task 1**

```bash
git add tests/test_workflow_progress.py src/openbbq/workflow/progress.py src/openbbq/plugins/execution.py src/openbbq/workflow/steps.py
git commit -m "feat: add workflow progress events"
```

### Task 2: Built-in plugin percentage emitters

**Files:**
- Modify: `src/openbbq/builtin_plugins/remote_video/plugin.py`
- Modify: `src/openbbq/builtin_plugins/ffmpeg/plugin.py`
- Modify: `src/openbbq/builtin_plugins/faster_whisper/plugin.py`
- Modify: `src/openbbq/builtin_plugins/translation/plugin.py`
- Test: `tests/test_plugins_progress.py`

- [ ] **Step 1: Write failing tests for built-in plugin progress callbacks**

Create `tests/test_plugins_progress.py` with four focused tests:

```python
from pathlib import Path
from types import SimpleNamespace

from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin
from openbbq.builtin_plugins.translation import plugin as translation_plugin


def test_remote_video_reports_download_percentages(tmp_path: Path):
    calls = []

    class FakeDownloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def extract_info(self, url, download):
            hook = self.options["progress_hooks"][0]
            hook({"status": "downloading", "downloaded_bytes": 25, "total_bytes": 100})
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            (tmp_path / "video.mp4").write_bytes(b"video")
            hook({"status": "finished", "downloaded_bytes": 100, "total_bytes": 100})
            return {"title": "sample"}

    remote_video_plugin.run(
        {
            "tool_name": "download",
            "parameters": {"url": "https://example.com/video", "format": "mp4"},
            "work_dir": str(tmp_path),
        },
        downloader_factory=FakeDownloader,
        progress=lambda **payload: calls.append(payload),
    )

    assert [call["percent"] for call in calls] == [0, 25, 50, 100]
    assert calls[-1]["phase"] == "video_download"


def test_ffmpeg_reports_extract_audio_percentages(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    calls = []

    def fake_probe_duration(path):
        assert path == video
        return 10.0

    def fake_runner(command, on_progress):
        on_progress(2.5)
        on_progress(7.5)
        audio.write_bytes(b"audio")

    ffmpeg_plugin.run(
        {
            "tool_name": "extract_audio",
            "inputs": {"video": {"file_path": str(video)}},
            "parameters": {"format": "wav", "sample_rate": 16000},
            "work_dir": str(tmp_path),
        },
        runner=fake_runner,
        duration_probe=fake_probe_duration,
        progress=lambda **payload: calls.append(payload),
    )

    assert [call["percent"] for call in calls] == [0, 25, 75, 100]
    assert calls[-1]["phase"] == "extract_audio"


def test_faster_whisper_reports_asr_percentages(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    calls = []

    class FakeModel:
        def transcribe(self, audio_path, **kwargs):
            segments = [
                SimpleNamespace(start=0, end=2, text="hello", avg_logprob=None, words=[]),
                SimpleNamespace(start=2, end=5, text="world", avg_logprob=None, words=[]),
            ]
            return segments, SimpleNamespace(language="en", duration=5)

    whisper_plugin.run(
        {
            "tool_name": "transcribe",
            "inputs": {"audio": {"file_path": str(audio)}},
            "parameters": {"model": "base", "word_timestamps": False},
            "runtime": {},
            "work_dir": str(tmp_path),
        },
        model_factory=lambda *args, **kwargs: FakeModel(),
        progress=lambda **payload: calls.append(payload),
    )

    assert [call["percent"] for call in calls] == [0, 40, 100]
    assert calls[-1]["phase"] == "asr_parse"


def test_translation_reports_completed_segment_percentages():
    calls = []

    class FakeClient:
        def chat(self):
            raise AssertionError("not used")

    def fake_translate_chunk(**kwargs):
        return [{"index": item.index, "text": f"zh {item.text}"} for item in kwargs["chunk"]]

    original = translation_plugin._translate_chunk
    translation_plugin._translate_chunk = fake_translate_chunk
    try:
        translation_plugin.run_translation(
            {
                "tool_name": "translate",
                "parameters": {"source_lang": "en", "target_lang": "zh"},
                "inputs": {
                    "subtitle_segments": {
                        "type": "subtitle_segments",
                        "content": [
                            {"index": 0, "start": 0, "end": 1, "text": "a"},
                            {"index": 1, "start": 1, "end": 2, "text": "b"},
                        ],
                    }
                },
                "runtime": {"providers": {"openai": {"api_key": "sk-test", "model": "gpt"}}},
            },
            client_factory=lambda **kwargs: FakeClient(),
            error_prefix="translation.translate",
            include_provider_metadata=True,
            input_names=("subtitle_segments",),
            progress=lambda **payload: calls.append(payload),
        )
    finally:
        translation_plugin._translate_chunk = original

    assert calls[0]["percent"] == 0
    assert calls[-1]["percent"] == 100
    assert calls[-1]["phase"] == "translate"
```

- [ ] **Step 2: Run tests and verify they fail on unsupported keyword arguments**

Run:

```bash
uv run pytest tests/test_plugins_progress.py -q
```

Expected: fail because built-in plugin functions do not yet accept `progress`, `duration_probe`, or progress-aware runners.

- [ ] **Step 3: Implement remote video progress**

Modify `remote_video.plugin.run` signature:

```python
def run(request: dict, downloader_factory=None, progress=None) -> dict:
```

Add helper:

```python
def _report(progress, *, phase: str, label: str, percent: float, current=None, total=None, unit=None) -> None:
    if progress is not None:
        progress(phase=phase, label=label, percent=percent, current=current, total=total, unit=unit)
```

Before attempts, emit:

```python
    _report(progress, phase="video_download", label="Download video", percent=0, unit="bytes")
```

Add progress hook to options:

```python
            options = _options_for_attempt(base_options, attempt)
            options["progress_hooks"] = [_yt_dlp_progress_hook(progress)]
```

Add helper:

```python
def _yt_dlp_progress_hook(progress):
    def hook(payload: dict[str, Any]) -> None:
        status = payload.get("status")
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
        current = payload.get("downloaded_bytes")
        if status == "downloading" and isinstance(total, (int, float)) and total > 0 and isinstance(current, (int, float)):
            _report(
                progress,
                phase="video_download",
                label="Download video",
                percent=min((current / total) * 100, 99),
                current=current,
                total=total,
                unit="bytes",
            )
        elif status == "finished":
            _report(progress, phase="video_download", label="Download video", percent=100, unit="bytes")

    return hook
```

- [ ] **Step 4: Implement ffmpeg progress**

Modify `ffmpeg.plugin.run` signature:

```python
def run(request: dict, runner=None, duration_probe=None, progress=None) -> dict:
```

Use:

```python
    duration_probe = _probe_duration_seconds if duration_probe is None else duration_probe
    duration_seconds = duration_probe(Path(video_path))
    _report(progress, phase="extract_audio", label="Extract audio", percent=0, current=0, total=duration_seconds, unit="seconds")
```

Call runner with progress:

```python
    runner(command, on_progress=lambda seconds: _report(
        progress,
        phase="extract_audio",
        label="Extract audio",
        percent=(seconds / duration_seconds) * 100 if duration_seconds > 0 else 0,
        current=seconds,
        total=duration_seconds,
        unit="seconds",
    ))
```

Emit 100 after successful runner:

```python
    _report(progress, phase="extract_audio", label="Extract audio", percent=100, current=duration_seconds, total=duration_seconds, unit="seconds")
```

Implement `_probe_duration_seconds` with `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1`.

Change `_run_subprocess(command)` to `_run_subprocess(command, on_progress=None)` and use `subprocess.Popen` with `-progress pipe:1 -nostats` parsing.

- [ ] **Step 5: Implement Faster Whisper ASR progress**

Modify `faster_whisper.plugin.run` signature:

```python
def run(request: dict, model_factory=None, progress=None) -> dict:
```

Before model creation:

```python
    _report(progress, phase="asr_parse", label="ASR parsing", percent=0)
```

Replace list comprehension with a loop:

```python
    duration = float(getattr(info, "duration", 0) or 0)
    content = []
    for segment in segments:
        content.append(_segment_payload(segment, include_words=word_timestamps))
        if duration > 0:
            current = min(float(segment.end), duration)
            _report(
                progress,
                phase="asr_parse",
                label="ASR parsing",
                percent=(current / duration) * 100,
                current=current,
                total=duration,
                unit="seconds",
            )
    _report(progress, phase="asr_parse", label="ASR parsing", percent=100, current=duration or None, total=duration or None, unit="seconds" if duration > 0 else None)
```

- [ ] **Step 6: Implement translation progress**

Modify signatures:

```python
def run(request: dict, client_factory=None, progress=None) -> dict:
def run_translate(request: dict, client_factory=None, progress=None) -> dict:
def run_translation(..., progress=None) -> dict:
```

Before chunk loop:

```python
    total_segments = len(segments)
    translated_count = 0
    _report(progress, phase="translate", label="Translate", percent=0, current=0, total=total_segments, unit="segments")
```

After each chunk response:

```python
        translated = _translate_chunk(...)
        translated_segments.extend(translated)
        translated_count += len(chunk)
        _report(
            progress,
            phase="translate",
            label="Translate",
            percent=(translated_count / total_segments) * 100 if total_segments else 100,
            current=translated_count,
            total=total_segments,
            unit="segments",
        )
```

- [ ] **Step 7: Run targeted plugin progress tests**

Run:

```bash
uv run pytest tests/test_plugins_progress.py -q
```

Expected: all plugin progress tests pass.

- [ ] **Step 8: Run existing plugin tests for regressions**

Run:

```bash
uv run pytest tests/test_builtin_remote_video.py tests/test_builtin_ffmpeg.py tests/test_builtin_faster_whisper.py tests/test_builtin_translation.py -q
```

Expected: all targeted built-in plugin tests pass.

- [ ] **Step 9: Commit Task 2**

```bash
git add tests/test_plugins_progress.py src/openbbq/builtin_plugins/remote_video/plugin.py src/openbbq/builtin_plugins/ffmpeg/plugin.py src/openbbq/builtin_plugins/faster_whisper/plugin.py src/openbbq/builtin_plugins/translation/plugin.py
git commit -m "feat: report built-in plugin progress"
```

### Task 3: Faster Whisper model download jobs

**Files:**
- Create: `src/openbbq/runtime/model_download_jobs.py`
- Modify: `src/openbbq/runtime/models.py`
- Modify: `src/openbbq/runtime/models_assets.py`
- Modify: `src/openbbq/application/runtime.py`
- Modify: `src/openbbq/api/schemas.py`
- Modify: `src/openbbq/api/routes/runtime.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Write failing API tests for model download jobs**

Append to `tests/test_api_projects_plugins_runtime.py`:

```python
def test_runtime_starts_and_polls_faster_whisper_download_job(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    progress_values = [0, 40, 100]

    def fake_download(model, *, cache_dir, device, compute_type, progress=None):
        for percent in progress_values:
            progress(percent=percent, current_bytes=percent, total_bytes=100)
        model_dir = cache_dir / f"models--Systran--faster-whisper-{model}"
        _write_faster_whisper_payload(model_dir)

    monkeypatch.setattr("openbbq.application.runtime.download_faster_whisper_model", fake_download)

    client, headers = authed_client(project)
    start = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "small"},
    )
    assert start.status_code == 200
    job = start.json()["data"]["job"]
    assert job["model"] == "small"
    assert job["status"] in {"running", "completed"}

    poll = _poll_download_job(client, headers, job["job_id"])
    assert poll.status_code == 200
    assert poll.json()["data"]["job"]["percent"] == 100
    assert poll.json()["data"]["job"]["status"] == "completed"


def test_runtime_download_job_reports_failure(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))

    def fake_download(model, *, cache_dir, device, compute_type, progress=None):
        progress(percent=10, current_bytes=10, total_bytes=100)
        raise RuntimeError("network failed")

    monkeypatch.setattr("openbbq.application.runtime.download_faster_whisper_model", fake_download)

    client, headers = authed_client(project)
    start = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "small"},
    )
    job = start.json()["data"]["job"]

    poll = _poll_download_job(client, headers, job["job_id"])
    assert poll.json()["data"]["job"]["status"] == "failed"
    assert poll.json()["data"]["job"]["error"] == "network failed"


def _poll_download_job(client, headers, job_id: str):
    import time

    response = None
    for _ in range(20):
        response = client.get(f"/runtime/models/faster-whisper/downloads/{job_id}", headers=headers)
        status = response.json()["data"]["job"]["status"]
        if status in {"completed", "failed"}:
            return response
        time.sleep(0.01)
    assert response is not None
    return response
```

- [ ] **Step 2: Run tests and verify route contract fails**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_starts_and_polls_faster_whisper_download_job tests/test_api_projects_plugins_runtime.py::test_runtime_download_job_reports_failure -q
```

Expected: fail because response still returns `model`, and status route does not exist.

- [ ] **Step 3: Add model download job domain model**

Modify `src/openbbq/runtime/models.py` to add:

```python
ModelDownloadStatus = Literal["queued", "running", "completed", "failed"]


class ModelDownloadJob(OpenBBQModel):
    job_id: str
    provider: str
    model: str
    status: ModelDownloadStatus
    percent: float = 0
    current_bytes: int | None = None
    total_bytes: int | None = None
    error: str | None = None
    started_at: str
    completed_at: str | None = None
    model_status: ModelAssetStatus | None = None
```

- [ ] **Step 4: Implement process-local job manager**

Create `src/openbbq/runtime/model_download_jobs.py` with:

```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from openbbq.runtime.models import ModelAssetStatus, ModelDownloadJob


class ModelDownloadJobManager:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="openbbq-model-download")
        self._jobs: dict[str, ModelDownloadJob] = {}
        self._active_by_model: dict[tuple[str, str], str] = {}
        self._lock = Lock()

    def start(self, *, provider: str, model: str, worker) -> ModelDownloadJob:
        key = (provider, model)
        with self._lock:
            existing_id = self._active_by_model.get(key)
            if existing_id is not None:
                existing = self._jobs[existing_id]
                if existing.status in {"queued", "running"}:
                    return existing
            job = ModelDownloadJob(
                job_id=uuid4().hex,
                provider=provider,
                model=model,
                status="queued",
                started_at=_now(),
            )
            self._jobs[job.job_id] = job
            self._active_by_model[key] = job.job_id
        self._executor.submit(self._run, job.job_id, worker)
        return self.get(job.job_id)

    def get(self, job_id: str) -> ModelDownloadJob:
        with self._lock:
            return self._jobs[job_id].model_copy(deep=True)

    def update_progress(self, job_id: str, *, percent: float, current_bytes: int | None = None, total_bytes: int | None = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": "running",
                    "percent": max(0, min(100, percent)),
                    "current_bytes": current_bytes,
                    "total_bytes": total_bytes,
                }
            )

    def _run(self, job_id: str, worker) -> None:
        try:
            self.update_progress(job_id, percent=0)
            model_status = worker(lambda **payload: self.update_progress(job_id, **payload))
            self._complete(job_id, model_status)
        except Exception as exc:
            self._fail(job_id, str(exc))

    def _complete(self, job_id: str, model_status: ModelAssetStatus) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={"status": "completed", "percent": 100, "completed_at": _now(), "model_status": model_status}
            )

    def _fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(update={"status": "failed", "error": error, "completed_at": _now()})


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


model_download_jobs = ModelDownloadJobManager()
```

- [ ] **Step 5: Update application runtime service**

Modify `src/openbbq/application/runtime.py`:

```python
from openbbq.runtime.model_download_jobs import model_download_jobs
from openbbq.runtime.models import ModelDownloadJob
```

Change result models:

```python
class FasterWhisperDownloadResult(OpenBBQModel):
    job: ModelDownloadJob


class FasterWhisperDownloadStatusResult(OpenBBQModel):
    job: ModelDownloadJob
```

Change `faster_whisper_download` to start a job:

```python
    def worker(progress):
        download_faster_whisper_model(
            request.model,
            cache_dir=faster_whisper.cache_dir,
            device=faster_whisper.default_device,
            compute_type=faster_whisper.default_compute_type,
            progress=progress,
        )
        return faster_whisper_model_status(settings, model=request.model)

    job = model_download_jobs.start(provider="faster-whisper", model=request.model, worker=worker)
    return FasterWhisperDownloadResult(job=job)
```

Add:

```python
def faster_whisper_download_status(job_id: str) -> FasterWhisperDownloadStatusResult:
    return FasterWhisperDownloadStatusResult(job=model_download_jobs.get(job_id))
```

- [ ] **Step 6: Update API schemas and routes**

Modify `src/openbbq/api/schemas.py`:

```python
from openbbq.runtime.models import DoctorCheck, ModelAssetStatus, ModelDownloadJob, ProviderProfile, RuntimeSettings


class FasterWhisperDownloadData(OpenBBQModel):
    job: ModelDownloadJob


class FasterWhisperDownloadStatusData(OpenBBQModel):
    job: ModelDownloadJob
```

Modify `src/openbbq/api/routes/runtime.py` to return `job` and add:

```python
@router.get(
    "/runtime/models/faster-whisper/downloads/{job_id}",
    response_model=ApiSuccess[FasterWhisperDownloadStatusData],
)
def get_faster_whisper_download(job_id: str) -> ApiSuccess[FasterWhisperDownloadStatusData]:
    result = faster_whisper_download_status(job_id)
    return ApiSuccess(data=FasterWhisperDownloadStatusData(job=result.job))
```

- [ ] **Step 7: Make Faster Whisper model download helper progress-capable**

Modify `src/openbbq/runtime/models_assets.py` signature:

```python
def download_faster_whisper_model(..., progress=None) -> None:
```

Implement repository resolution and call `snapshot_download` directly with allow patterns and custom tqdm class. The callback payload must be:

```python
progress(percent=percent, current_bytes=current_bytes, total_bytes=total_bytes)
```

The helper must still raise `ExecutionError` if `huggingface_hub` is unavailable.

- [ ] **Step 8: Run targeted runtime API tests**

Run:

```bash
uv run pytest tests/test_api_projects_plugins_runtime.py::test_runtime_starts_and_polls_faster_whisper_download_job tests/test_api_projects_plugins_runtime.py::test_runtime_download_job_reports_failure tests/test_api_projects_plugins_runtime.py::test_runtime_download_rejects_unsupported_faster_whisper_model -q
```

Expected: targeted tests pass.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/openbbq/runtime/model_download_jobs.py src/openbbq/runtime/models.py src/openbbq/runtime/models_assets.py src/openbbq/application/runtime.py src/openbbq/api/schemas.py src/openbbq/api/routes/runtime.py tests/test_api_projects_plugins_runtime.py
git commit -m "feat: add model download progress jobs"
```

### Task 4: Electron and renderer data contracts

**Files:**
- Modify: `desktop/electron/apiTypes.ts`
- Modify: `desktop/electron/ipc.ts`
- Modify: `desktop/electron/taskMapping.ts`
- Modify: `desktop/src/global.d.ts`
- Modify: `desktop/src/lib/types.ts`
- Modify: `desktop/src/lib/apiClient.ts`
- Modify: `desktop/src/lib/desktopClient.ts`
- Test: `desktop/electron/__tests__/ipc.test.ts`

- [ ] **Step 1: Write failing Electron mapping tests**

Add IPC/mapping expectations in `desktop/electron/__tests__/ipc.test.ts`:

```typescript
it("maps workflow progress events into task progress log lines", async () => {
  mockFetchJson
    .mockResolvedValueOnce({
      ok: true,
      data: {
        id: "run_1",
        workflow_id: "youtube-to-srt",
        mode: "start",
        status: "running",
        project_root: "/tmp/project",
        plugin_paths: [],
        latest_event_sequence: 2,
        created_by: "desktop"
      }
    })
    .mockResolvedValueOnce({
      ok: true,
      data: {
        workflow_id: "youtube-to-srt",
        events: [
          {
            id: "event_1",
            workflow_id: "youtube-to-srt",
            sequence: 1,
            type: "step.progress",
            level: "info",
            message: "Download video 42%",
            data: { progress: { phase: "video_download", label: "Download video", percent: 42, current: 42, total: 100, unit: "bytes" } },
            created_at: "2026-04-28T10:00:00.000Z",
            step_id: "download",
            attempt: 1
          }
        ]
      }
    });

  const { getTaskMonitor } = await import("../ipc");
  const monitor = await getTaskMonitor(sidecar, "run_1");

  expect(monitor.progressLogs).toEqual([
    expect.objectContaining({ stepId: "download", label: "Download video", percent: 42 })
  ]);
});
```

Add download job mapping test:

```typescript
it("starts and polls faster-whisper model download jobs", async () => {
  mockFetchJson
    .mockResolvedValueOnce({
      ok: true,
      data: { job: { job_id: "job_1", provider: "faster-whisper", model: "small", status: "running", percent: 30, started_at: "2026-04-28T10:00:00.000Z" } }
    })
    .mockResolvedValueOnce({
      ok: true,
      data: { job: { job_id: "job_1", provider: "faster-whisper", model: "small", status: "completed", percent: 100, started_at: "2026-04-28T10:00:00.000Z", completed_at: "2026-04-28T10:01:00.000Z" } }
    });

  const { downloadFasterWhisperModel, getFasterWhisperModelDownload } = await import("../ipc");
  await expect(downloadFasterWhisperModel(sidecar, { model: "small" })).resolves.toMatchObject({ jobId: "job_1", percent: 30 });
  await expect(getFasterWhisperModelDownload(sidecar, "job_1")).resolves.toMatchObject({ jobId: "job_1", status: "completed", percent: 100 });
});
```

- [ ] **Step 2: Run Electron tests and verify they fail**

Run:

```bash
cd desktop && pnpm exec vitest run electron/__tests__/ipc.test.ts
```

Expected: fail because `progressLogs` and `getFasterWhisperModelDownload` do not exist.

- [ ] **Step 3: Add renderer types**

Modify `desktop/src/lib/types.ts`:

```typescript
export type ProgressPercent = {
  phase: string;
  label: string;
  percent: number;
  current?: number | null;
  total?: number | null;
  unit?: string | null;
};

export type TaskProgressLogLine = ProgressPercent & {
  sequence: number;
  timestamp: string;
  stepId: string;
  attempt?: number | null;
};

export type RuntimeModelDownloadJob = {
  jobId: string;
  provider: string;
  model: string;
  status: "queued" | "running" | "completed" | "failed";
  percent: number;
  currentBytes?: number | null;
  totalBytes?: number | null;
  error?: string | null;
  startedAt: string;
  completedAt?: string | null;
  modelStatus?: RuntimeModelStatus | null;
};
```

Add `progressLogs: TaskProgressLogLine[]` to `TaskMonitorModel`.

- [ ] **Step 4: Add Electron API types and mappers**

Modify `desktop/electron/apiTypes.ts` with `ApiModelDownloadJob` and updated download response.

Modify `desktop/electron/taskMapping.ts`:

```typescript
function toProgressLogs(events: ApiWorkflowEvent[]): TaskProgressLogLine[] {
  return events
    .filter((event) => event.type === "step.progress" && event.step_id && isProgressPayload(event.data.progress))
    .map((event) => {
      const progress = event.data.progress as ApiProgressPayload;
      return {
        sequence: event.sequence,
        timestamp: event.created_at,
        stepId: event.step_id as string,
        attempt: event.attempt ?? null,
        phase: progress.phase,
        label: progress.label,
        percent: clampPercent(progress.percent),
        current: progress.current ?? null,
        total: progress.total ?? null,
        unit: progress.unit ?? null
      };
    });
}
```

Add `progressLogs: toProgressLogs(events)` in `toTaskMonitorModel`.

- [ ] **Step 5: Add IPC methods**

Modify `desktop/electron/ipc.ts`:

```typescript
function toModelDownloadJob(job: ApiModelDownloadJob): RuntimeModelDownloadJob {
  return {
    jobId: job.job_id,
    provider: job.provider,
    model: job.model,
    status: job.status,
    percent: job.percent,
    currentBytes: job.current_bytes ?? null,
    totalBytes: job.total_bytes ?? null,
    error: job.error ?? null,
    startedAt: job.started_at,
    completedAt: job.completed_at ?? null,
    modelStatus: job.model_status ? toModelStatusModel(job.model_status) : null
  };
}
```

Change `downloadFasterWhisperModel` to return `RuntimeModelDownloadJob`, and add:

```typescript
export async function getFasterWhisperModelDownload(sidecar: ManagedSidecar, jobId: string): Promise<RuntimeModelDownloadJob> {
  const data = await requestJson<{ job: ApiModelDownloadJob }>(
    sidecar.connection,
    `/runtime/models/faster-whisper/downloads/${encodeURIComponent(jobId)}`
  );
  return toModelDownloadJob(data.job);
}
```

Expose the method in `preload.cts`, `global.d.ts`, `desktopClient.ts`, and `apiClient.ts`.

- [ ] **Step 6: Run Electron tests**

Run:

```bash
cd desktop && pnpm exec vitest run electron/__tests__/ipc.test.ts src/lib/desktopClient.test.ts src/lib/apiClient.test.ts
```

Expected: targeted TypeScript tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add desktop/electron/apiTypes.ts desktop/electron/ipc.ts desktop/electron/taskMapping.ts desktop/electron/preload.cts desktop/src/global.d.ts desktop/src/lib/types.ts desktop/src/lib/apiClient.ts desktop/src/lib/desktopClient.ts desktop/electron/__tests__/ipc.test.ts desktop/src/lib/desktopClient.test.ts desktop/src/lib/apiClient.test.ts
git commit -m "feat: map progress contracts to desktop"
```

### Task 5: Settings ASR model download progress UI

**Files:**
- Modify: `desktop/src/components/Settings.tsx`
- Modify: `desktop/src/components/__tests__/Settings.test.tsx`
- Modify: `desktop/src/lib/mockData.ts`

- [ ] **Step 1: Write failing Settings UI test**

Add to `desktop/src/components/__tests__/Settings.test.tsx`:

```typescript
it("shows real percentage progress for the selected ASR model download", async () => {
  const user = userEvent.setup();
  const downloadFasterWhisperModel = vi.fn().mockResolvedValue({
    jobId: "job-small",
    provider: "faster-whisper",
    model: "small",
    status: "running",
    percent: 35,
    startedAt: "2026-04-28T10:00:00.000Z"
  });
  const getFasterWhisperModelDownload = vi.fn().mockResolvedValue({
    jobId: "job-small",
    provider: "faster-whisper",
    model: "small",
    status: "completed",
    percent: 100,
    startedAt: "2026-04-28T10:00:00.000Z",
    completedAt: "2026-04-28T10:01:00.000Z",
    modelStatus: {
      provider: "faster-whisper",
      model: "small",
      cacheDir: "C:/Users/alex/.cache/openbbq/models/faster-whisper",
      present: true,
      sizeBytes: 10,
      error: null
    }
  });

  renderSettings({ downloadFasterWhisperModel, getFasterWhisperModelDownload });
  await screen.findByRole("heading", { name: "Settings" });
  await user.click(screen.getByRole("button", { name: "ASR model" }));
  await user.click(screen.getByRole("button", { name: "Download small" }));

  expect(await screen.findByText("35%")).toBeInTheDocument();
  expect(await screen.findByText("100%")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download small" })).toBeDisabled();
});
```

- [ ] **Step 2: Run Settings test and verify it fails**

Run:

```bash
cd desktop && pnpm exec vitest run src/components/__tests__/Settings.test.tsx
```

Expected: fail because Settings props and UI do not support model download jobs.

- [ ] **Step 3: Update Settings props and download state**

Modify `SettingsProps`:

```typescript
downloadFasterWhisperModel(input: DownloadFasterWhisperModelInput): Promise<RuntimeModelDownloadJob>;
getFasterWhisperModelDownload(jobId: string): Promise<RuntimeModelDownloadJob>;
```

In `AsrSection`, replace `downloadingModel` with:

```typescript
const [downloadJobs, setDownloadJobs] = useState<Record<string, RuntimeModelDownloadJob>>({});
```

When clicking Download:

```typescript
const job = await downloadFasterWhisperModel({ model });
setDownloadJobs((current) => ({ ...current, [model]: job }));
```

Poll active jobs in an effect:

```typescript
useEffect(() => {
  const active = Object.values(downloadJobs).filter((job) => job.status === "queued" || job.status === "running");
  if (active.length === 0) return undefined;
  const interval = window.setInterval(() => {
    for (const job of active) {
      void getFasterWhisperModelDownload(job.jobId).then((nextJob) => {
        setDownloadJobs((current) => ({ ...current, [nextJob.model]: nextJob }));
        if (nextJob.status === "completed" && nextJob.modelStatus) {
          onModelsChange(upsertModelStatus(models, nextJob.modelStatus));
        }
      });
    }
  }, 750);
  return () => window.clearInterval(interval);
}, [downloadJobs, getFasterWhisperModelDownload, models, onModelsChange]);
```

- [ ] **Step 4: Render model row progress bars**

Inside each model row:

```tsx
{job ? (
  <div className="mt-2 grid gap-1" aria-label={`${status.model} download progress`}>
    <div className="h-2 overflow-hidden rounded-full bg-[#d8c8ae]">
      <div className="h-full rounded-full bg-ready" style={{ width: `${job.percent}%` }} />
    </div>
    <p className="text-xs font-bold text-ink-brown">{Math.round(job.percent)}%</p>
    {job.error ? <p className="text-xs font-semibold text-[#8a3f25]">{job.error}</p> : null}
  </div>
) : null}
```

Disable button while job is queued/running or model is present.

- [ ] **Step 5: Run Settings tests**

Run:

```bash
cd desktop && pnpm exec vitest run src/components/__tests__/Settings.test.tsx
```

Expected: Settings component tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add desktop/src/components/Settings.tsx desktop/src/components/__tests__/Settings.test.tsx desktop/src/lib/mockData.ts
git commit -m "feat: show model download percentages"
```

### Task 6: Task run runtime log progress UI

**Files:**
- Modify: `desktop/src/components/TaskMonitor.tsx`
- Modify: `desktop/src/components/__tests__/TaskMonitor.test.tsx`
- Modify: `desktop/src/__tests__/App.test.tsx`
- Modify: `desktop/src/lib/mockData.ts`

- [ ] **Step 1: Write failing TaskMonitor UI test**

Add to `desktop/src/components/__tests__/TaskMonitor.test.tsx`:

```typescript
it("renders workflow progress rows inside the runtime log", () => {
  render(
    <TaskMonitor
      task={{
        ...failedTask,
        status: "running",
        progressLogs: [
          {
            sequence: 6,
            timestamp: "2026-04-28T10:00:00.000Z",
            stepId: "transcribe",
            attempt: 1,
            phase: "asr_parse",
            label: "ASR parsing",
            percent: 42,
            current: 84,
            total: 200,
            unit: "seconds"
          }
        ]
      }}
      onRetry={vi.fn()}
    />
  );

  expect(screen.getByLabelText("ASR parsing progress")).toBeInTheDocument();
  expect(screen.getByText("42%")).toBeInTheDocument();
  expect(screen.getByText("84 / 200 seconds")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run TaskMonitor tests and verify they fail**

Run:

```bash
cd desktop && pnpm exec vitest run src/components/__tests__/TaskMonitor.test.tsx
```

Expected: fail because progress rows are not rendered.

- [ ] **Step 3: Add progress row rendering**

In `TaskMonitor.tsx`, add:

```typescript
function progressDetail(line: TaskProgressLogLine): string | null {
  if (line.current == null || line.total == null || !line.unit) {
    return null;
  }
  return `${Math.round(line.current)} / ${Math.round(line.total)} ${line.unit}`;
}
```

Before textual log rows inside runtime log container:

```tsx
{task.progressLogs.map((line) => (
  <div key={`progress-${line.sequence}`} className="grid grid-cols-[176px_112px_minmax(0,1fr)] gap-2 py-1">
    <span className="text-[#c7aa7a]">{line.timestamp}</span>
    <span className="rounded-sm bg-[#403329] px-1.5 text-center text-[10px] uppercase leading-5 text-[#d9c4a2]">
      progress
    </span>
    <div aria-label={`${line.label} progress`} className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="min-w-[96px] text-[#f8ead2]">{line.label}</span>
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#5a4627]">
          <div className="h-full rounded-full bg-[#ffd08f]" style={{ width: `${line.percent}%` }} />
        </div>
        <span className="w-10 text-right font-bold text-[#ffd08f]">{Math.round(line.percent)}%</span>
      </div>
      {progressDetail(line) ? <p className="mt-1 text-[#c7aa7a]">{progressDetail(line)}</p> : null}
    </div>
  </div>
))}
```

- [ ] **Step 4: Update mock task data**

Add `progressLogs: []` to existing mock task objects. Add one running mock progress row where App tests need runtime progress.

- [ ] **Step 5: Run renderer tests**

Run:

```bash
cd desktop && pnpm exec vitest run src/components/__tests__/TaskMonitor.test.tsx src/__tests__/App.test.tsx
```

Expected: targeted renderer tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add desktop/src/components/TaskMonitor.tsx desktop/src/components/__tests__/TaskMonitor.test.tsx desktop/src/__tests__/App.test.tsx desktop/src/lib/mockData.ts
git commit -m "feat: show task progress in runtime log"
```

### Task 7: End-to-end and full verification

**Files:**
- Modify: `desktop/tests/desktop-ui.spec.ts`

- [ ] **Step 1: Add Playwright coverage for progress surfaces**

Add a desktop UI test that opens Settings, starts a mock model download, and asserts the progress text appears. Add a second test that opens the task monitor and asserts runtime progress rows do not overflow.

- [ ] **Step 2: Run Python target suite**

Run:

```bash
uv run pytest tests/test_workflow_progress.py tests/test_plugins_progress.py tests/test_api_projects_plugins_runtime.py tests/test_builtin_remote_video.py tests/test_builtin_ffmpeg.py tests/test_builtin_faster_whisper.py tests/test_builtin_translation.py -q
```

Expected: targeted backend and plugin tests pass.

- [ ] **Step 3: Run full backend suite**

Run:

```bash
uv run pytest
```

Expected: all backend tests pass.

- [ ] **Step 4: Run backend lint and format checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: both commands pass with no required formatting changes.

- [ ] **Step 5: Run desktop unit tests**

Run:

```bash
cd desktop && pnpm test
```

Expected: all Vitest tests pass.

- [ ] **Step 6: Run desktop build**

Run:

```bash
cd desktop && pnpm build
```

Expected: TypeScript, Vite, and Electron build pass.

- [ ] **Step 7: Run Playwright with local Chromium**

Run:

```bash
cd desktop && PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium pnpm exec playwright test
```

Expected: both desktop Playwright projects pass.

- [ ] **Step 8: Manual browser verification with Chrome DevTools MCP**

After Codex is restarted so `chrome-devtools` MCP uses `/usr/bin/chromium`, start the dev server and verify:

```bash
cd desktop && pnpm dev
```

Use the browser to confirm:

- Settings > ASR model shows a model row progress bar with a numeric percentage while a download job is active.
- Task run > Runtime log shows progress rows for supported workflow stages.
- No horizontal overflow at 1440px, 900px, or 390px widths.

- [ ] **Step 9: Commit verification updates**

```bash
git add desktop/tests/desktop-ui.spec.ts
git commit -m "test: cover progress UI surfaces"
```
