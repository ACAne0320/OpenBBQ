# Phase 2 Remote Video Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 2 Slice 3 so the CLI can run a complete remote-video translated subtitle workflow using a built-in `remote_video.download` plugin.

**Architecture:** Keep the workflow engine unchanged and add remote video acquisition as a built-in plugin. `remote_video.download` reads the URL from workflow parameters, uses the `yt-dlp` Python API through an injectable downloader factory, and returns a file-backed mp4 `video` artifact for the existing ffmpeg, ASR, glossary, translation, and subtitle chain.

**Tech Stack:** Python 3.11, uv, pytest, Ruff, yt-dlp as optional `download` dependency, existing OpenBBQ plugin registry and artifact store.

---

## File Structure

- Modify `pyproject.toml`: add optional `download` dependency.
- Create `src/openbbq/builtin_plugins/remote_video/__init__.py`: package marker.
- Create `src/openbbq/builtin_plugins/remote_video/openbbq.plugin.toml`: manifest for `remote_video.download`.
- Create `src/openbbq/builtin_plugins/remote_video/plugin.py`: yt-dlp-backed remote video downloader.
- Modify `tests/test_builtin_plugins.py`: discovery, successful download, and error-path unit tests.
- Modify `tests/test_package_layout.py`: package data and optional dependency assertions.
- Modify `tests/test_fixtures.py`: remote translated fixture validation.
- Create `tests/fixtures/projects/remote-video-translate-subtitle/openbbq.yaml`: canonical remote translated media workflow.
- Create `tests/test_phase2_remote_video_slice.py`: deterministic CLI end-to-end test for the full remote translated subtitle workflow.
- Modify `README.md`: document optional download setup and remote translated subtitle smoke flow.
- Modify `docs/Target-Workflows.md`: rename source step to `remote_video.download` and mark availability.
- Modify `docs/Roadmap.md`: include remote video download in Phase 2.

## Task 1: Built-In Manifest, Discovery, Package Data, and Download Extra

**Files:**
- Modify: `pyproject.toml`
- Create: `src/openbbq/builtin_plugins/remote_video/__init__.py`
- Create: `src/openbbq/builtin_plugins/remote_video/openbbq.plugin.toml`
- Create: `src/openbbq/builtin_plugins/remote_video/plugin.py`
- Modify: `tests/test_builtin_plugins.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Write failing discovery and package layout tests**

Add this import to `tests/test_builtin_plugins.py`:

```python
from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin
```

Append this assertion to `test_builtin_plugin_path_is_discovered_by_default()`:

```python
    assert "remote_video.download" in registry.tools
```

Update `test_builtin_plugin_manifests_are_configured_as_package_data()` in `tests/test_package_layout.py` so the expected built-in manifest set includes `remote_video`:

```python
    assert {manifest.parent.name for manifest in manifests} == {
        "faster_whisper",
        "ffmpeg",
        "glossary",
        "llm",
        "remote_video",
        "subtitle",
    }
```

Add this test to `tests/test_package_layout.py`:

```python
def test_download_extra_declares_yt_dlp_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["download"] == [
        "yt-dlp>=2024.12.0"
    ]
```

- [ ] **Step 2: Run discovery tests to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_builtin_plugin_path_is_discovered_by_default tests/test_package_layout.py -q
```

Expected: FAIL because `remote_video.download`, its manifest, and the `download` extra do not exist.

- [ ] **Step 3: Add remote video package directory**

Create the package directory:

```bash
mkdir -p src/openbbq/builtin_plugins/remote_video
```

Create `src/openbbq/builtin_plugins/remote_video/__init__.py`:

```python
"""Remote video download built-in plugin."""
```

- [ ] **Step 4: Add remote video manifest**

Create `src/openbbq/builtin_plugins/remote_video/openbbq.plugin.toml`:

```toml
name = "remote_video"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "download"
description = "Download a remote video URL to a file-backed mp4 video artifact."
input_artifact_types = []
output_artifact_types = ["video"]
effects = ["network", "writes_files"]

[tools.parameter_schema]
type = "object"
additionalProperties = false
required = ["url"]

[tools.parameter_schema.properties.url]
type = "string"

[tools.parameter_schema.properties.format]
type = "string"
enum = ["mp4"]
default = "mp4"

[tools.parameter_schema.properties.quality]
type = "string"
default = "best"
```

- [ ] **Step 5: Add initial remote video plugin**

Create `src/openbbq/builtin_plugins/remote_video/plugin.py`:

```python
def run(request, downloader_factory=None):
    raise RuntimeError("This built-in plugin has not been implemented yet.")
```

- [ ] **Step 6: Add `download` extra**

Update `pyproject.toml`:

```toml
[project.optional-dependencies]
media = ["faster-whisper>=1.2"]
llm = ["openai>=1.0"]
download = ["yt-dlp>=2024.12.0"]
```

Leave `[tool.setuptools.package-data]` as:

```toml
"openbbq.builtin_plugins" = ["*/openbbq.plugin.toml"]
```

- [ ] **Step 7: Run discovery tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_builtin_plugin_path_is_discovered_by_default tests/test_package_layout.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add pyproject.toml src/openbbq/builtin_plugins/remote_video tests/test_builtin_plugins.py tests/test_package_layout.py
git commit -m "feat: Add remote video plugin manifest"
```

## Task 2: `remote_video.download` Success Path

**Files:**
- Modify: `src/openbbq/builtin_plugins/remote_video/plugin.py`
- Modify: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Add fake downloader helpers**

Add these helper classes to `tests/test_builtin_plugins.py` after `RecordingOpenAIClientFactory`:

```python
class RecordingDownloader:
    def __init__(self, options, output_bytes=b"video"):
        self.options = options
        self.output_bytes = output_bytes
        self.extract_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.output_bytes)
        return {
            "id": "source-123",
            "title": "Remote Video",
            "extractor": "generic",
        }


class RecordingDownloaderFactory:
    def __init__(self):
        self.calls = []
        self.downloader = None

    def __call__(self, options):
        self.calls.append(options)
        self.downloader = RecordingDownloader(options)
        return self.downloader
```

- [ ] **Step 2: Write failing success test**

Add this test to `tests/test_builtin_plugins.py`:

```python
def test_remote_video_download_uses_yt_dlp_factory_and_returns_file_output(tmp_path):
    factory = RecordingDownloaderFactory()

    response = remote_video_plugin.run(
        {
            "tool_name": "download",
            "work_dir": str(tmp_path / "work"),
            "parameters": {
                "url": "https://video.example/watch/123",
                "format": "mp4",
                "quality": "best",
            },
            "inputs": {},
        },
        downloader_factory=factory,
    )

    expected_output = tmp_path / "work/video.mp4"
    assert expected_output.read_bytes() == b"video"
    assert factory.calls == [
        {
            "outtmpl": str(tmp_path / "work/video.%(ext)s"),
            "merge_output_format": "mp4",
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        }
    ]
    assert factory.downloader.extract_calls == [
        {"url": "https://video.example/watch/123", "download": True}
    ]
    assert response == {
        "outputs": {
            "video": {
                "type": "video",
                "file_path": str(expected_output),
                "metadata": {
                    "url": "https://video.example/watch/123",
                    "format": "mp4",
                    "quality": "best",
                    "title": "Remote Video",
                    "source_id": "source-123",
                    "extractor": "generic",
                },
            }
        }
    }
```

- [ ] **Step 3: Run success test to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_remote_video_download_uses_yt_dlp_factory_and_returns_file_output -q
```

Expected: FAIL because `remote_video.download` still raises.

- [ ] **Step 4: Implement remote video plugin success path**

Replace `src/openbbq/builtin_plugins/remote_video/plugin.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_BEST_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"


class MissingDownloadDependencyError(RuntimeError):
    pass


def run(request: dict, downloader_factory=None) -> dict:
    if request.get("tool_name") != "download":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    url = _required_string(parameters, "url")
    output_format = parameters.get("format", "mp4")
    if output_format != "mp4":
        raise ValueError("remote_video.download currently supports mp4 output only.")
    quality = str(parameters.get("quality", "best"))
    work_dir = Path(request["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path = work_dir / "video.mp4"
    options = {
        "outtmpl": str(work_dir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "format": _format_selector(quality),
    }
    if downloader_factory is None:
        downloader_factory = _default_downloader_factory
    try:
        with downloader_factory(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except MissingDownloadDependencyError:
        raise
    except Exception as exc:
        raise RuntimeError(f"yt-dlp failed: {exc}") from exc
    if not output_path.is_file():
        raise RuntimeError("yt-dlp did not produce the expected video output.")
    metadata = {
        "url": url,
        "format": "mp4",
        "quality": quality,
    }
    if isinstance(info, dict):
        _copy_string_metadata(info, metadata, "title", "title")
        _copy_string_metadata(info, metadata, "id", "source_id")
        _copy_string_metadata(info, metadata, "extractor", "extractor")
    return {
        "outputs": {
            "video": {
                "type": "video",
                "file_path": str(output_path),
                "metadata": metadata,
            }
        }
    }


def _default_downloader_factory(options: dict[str, Any]):
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise MissingDownloadDependencyError(
            "yt-dlp is not installed. Install OpenBBQ with the download optional dependencies."
        ) from exc
    return YoutubeDL(options)


def _required_string(parameters: dict[str, Any], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"remote_video.download parameter '{name}' must be a non-empty string."
        )
    return value


def _format_selector(quality: str) -> str:
    if quality == "best":
        return DEFAULT_BEST_FORMAT
    return quality


def _copy_string_metadata(
    source: dict[str, Any], target: dict[str, Any], source_key: str, target_key: str
) -> None:
    value = source.get(source_key)
    if isinstance(value, str):
        target[target_key] = value
```

- [ ] **Step 5: Run success test to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_remote_video_download_uses_yt_dlp_factory_and_returns_file_output -q
```

Expected: PASS.

- [ ] **Step 6: Run all built-in plugin tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/openbbq/builtin_plugins/remote_video/plugin.py tests/test_builtin_plugins.py
git commit -m "feat: Add built-in remote video downloader"
```

## Task 3: `remote_video.download` Error Paths

**Files:**
- Modify: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Add fake failure helpers**

Add these helpers to `tests/test_builtin_plugins.py` after `RecordingDownloaderFactory`:

```python
class NoOutputDownloader(RecordingDownloader):
    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        return {"id": "source-123"}


class FailingDownloader(RecordingDownloader):
    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        raise RuntimeError("download unavailable")


class CustomDownloaderFactory:
    def __init__(self, downloader_class):
        self.downloader_class = downloader_class
        self.calls = []
        self.downloader = None

    def __call__(self, options):
        self.calls.append(options)
        self.downloader = self.downloader_class(options)
        return self.downloader
```

- [ ] **Step 2: Add error-path tests**

Add these tests to `tests/test_builtin_plugins.py`:

```python
def test_remote_video_download_requires_url(tmp_path):
    with pytest.raises(ValueError, match="url"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": ""},
                "inputs": {},
            },
            downloader_factory=RecordingDownloaderFactory(),
        )


def test_remote_video_download_rejects_non_mp4_format(tmp_path):
    with pytest.raises(ValueError, match="mp4 output only"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {
                    "url": "https://video.example/watch/123",
                    "format": "webm",
                },
                "inputs": {},
            },
            downloader_factory=RecordingDownloaderFactory(),
        )


def test_remote_video_download_wraps_downloader_failures(tmp_path):
    with pytest.raises(RuntimeError, match="yt-dlp failed: download unavailable"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": "https://video.example/watch/123"},
                "inputs": {},
            },
            downloader_factory=CustomDownloaderFactory(FailingDownloader),
        )


def test_remote_video_download_requires_expected_output_file(tmp_path):
    with pytest.raises(RuntimeError, match="expected video output"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": "https://video.example/watch/123"},
                "inputs": {},
            },
            downloader_factory=CustomDownloaderFactory(NoOutputDownloader),
        )


def test_remote_video_download_missing_dependency_message(monkeypatch, tmp_path):
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("missing yt-dlp")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="download optional dependencies"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": "https://video.example/watch/123"},
                "inputs": {},
            }
        )
```

- [ ] **Step 3: Run error tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_remote_video_download_requires_url tests/test_builtin_plugins.py::test_remote_video_download_rejects_non_mp4_format tests/test_builtin_plugins.py::test_remote_video_download_wraps_downloader_failures tests/test_builtin_plugins.py::test_remote_video_download_requires_expected_output_file tests/test_builtin_plugins.py::test_remote_video_download_missing_dependency_message -q
```

Expected: PASS.

- [ ] **Step 4: Run all built-in plugin tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/test_builtin_plugins.py
git commit -m "test: Cover remote video downloader errors"
```

## Task 4: Canonical Remote Translated Subtitle Fixture

**Files:**
- Create: `tests/fixtures/projects/remote-video-translate-subtitle/openbbq.yaml`
- Modify: `tests/test_fixtures.py`

- [ ] **Step 1: Create fixture file**

Create `tests/fixtures/projects/remote-video-translate-subtitle/openbbq.yaml`:

```yaml
version: 1

project:
  id: remote-video-translate-subtitle
  name: Remote Video Translate Subtitle

workflows:
  remote-video-translate-subtitle:
    name: Remote Video Translate Subtitle
    steps:
      - id: download
        name: Download Video
        tool_ref: remote_video.download
        inputs: {}
        outputs:
          - name: video
            type: video
        parameters:
          url: https://example.com/video
          format: mp4
          quality: best
        on_error: abort
        max_retries: 0

      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: download.video
        outputs:
          - name: audio
            type: audio
        parameters:
          format: wav
          sample_rate: 16000
          channels: 1
        on_error: abort
        max_retries: 0

      - id: transcribe
        name: Transcribe
        tool_ref: faster_whisper.transcribe
        inputs:
          audio: extract_audio.audio
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          model: base
          device: cpu
          compute_type: int8
          word_timestamps: true
        on_error: abort
        max_retries: 0

      - id: glossary
        name: Apply Glossary
        tool_ref: glossary.replace
        inputs:
          transcript: transcribe.transcript
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          rules:
            - find: Open BBQ
              replace: OpenBBQ
              is_regex: false
              case_sensitive: false
        on_error: abort
        max_retries: 0

      - id: translate
        name: Translate
        tool_ref: llm.translate
        inputs:
          transcript: glossary.transcript
        outputs:
          - name: translation
            type: translation
        parameters:
          source_lang: en
          target_lang: zh-Hans
          model: gpt-4o-mini
          temperature: 0
        on_error: abort
        max_retries: 0

      - id: subtitle
        name: Export Subtitle
        tool_ref: subtitle.export
        inputs:
          translation: translate.translation
        outputs:
          - name: subtitle
            type: subtitle
        parameters:
          format: srt
        on_error: abort
        max_retries: 0
```

- [ ] **Step 2: Add fixture validation test**

Append this test to `tests/test_fixtures.py`:

```python
def test_remote_video_translate_subtitle_fixture_uses_builtin_plugins():
    config = load_project_config(FIXTURES / "projects/remote-video-translate-subtitle")
    registry = discover_plugins(config.plugin_paths)

    assert "remote_video.download" in registry.tools
    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "glossary.replace" in registry.tools
    assert "llm.translate" in registry.tools
    assert "subtitle.export" in registry.tools
```

- [ ] **Step 3: Run fixture test**

Run:

```bash
uv run pytest tests/test_fixtures.py::test_remote_video_translate_subtitle_fixture_uses_builtin_plugins -q
```

Expected: PASS after Tasks 1 through 3.

- [ ] **Step 4: Run fixture and validation suites**

Run:

```bash
uv run pytest tests/test_fixtures.py tests/test_config.py tests/test_engine_validate.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/fixtures/projects/remote-video-translate-subtitle/openbbq.yaml tests/test_fixtures.py
git commit -m "docs: Add remote translated video workflow fixture"
```

## Task 5: Deterministic CLI End-To-End Remote Workflow

**Files:**
- Create: `tests/test_phase2_remote_video_slice.py`

- [ ] **Step 1: Write deterministic CLI E2E test**

Create `tests/test_phase2_remote_video_slice.py`:

```python
import json
from pathlib import Path

from openbbq.cli.app import main


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeChatCompletions:
    def create(self, **kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        translated = [
            {"index": segment["index"], "text": f"[zh-Hans] {segment['text']}"}
            for segment in request["segments"]
        ]
        return FakeCompletion(json.dumps(translated, ensure_ascii=False))


class FakeChat:
    completions = FakeChatCompletions()


class FakeOpenAIClient:
    chat = FakeChat()


class FakeDownloader:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url, download=True):
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return {"id": "remote-1", "title": "Remote Test", "extractor": "generic"}


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(
        "tests/fixtures/projects/remote-video-translate-subtitle/openbbq.yaml"
    ).read_text(encoding="utf-8")
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_cli_runs_remote_video_translate_subtitle_with_fake_plugins(
    tmp_path, monkeypatch, capsys
):
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.llm import plugin as llm_plugin
    from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin

    def fake_downloader_factory(options):
        return FakeDownloader(options)

    def fake_runner(command):
        Path(command[-1]).write_bytes(b"audio")

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello Open BBQ"
        avg_logprob = -0.1
        words = []

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeWhisperModel:
        def __init__(self, model, device, compute_type):
            pass

        def transcribe(self, audio_path, language=None, word_timestamps=True, vad_filter=False):
            return [FakeSegment()], FakeInfo()

    def fake_client_factory(*, api_key, base_url):
        return FakeOpenAIClient()

    monkeypatch.setattr(remote_video_plugin, "_default_downloader_factory", fake_downloader_factory)
    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)
    monkeypatch.setattr(llm_plugin, "_default_client_factory", fake_client_factory)
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENBBQ_LLM_BASE_URL", "https://llm.example/v1")

    project = write_project(tmp_path)

    assert (
        main(
            [
                "--project",
                str(project),
                "--json",
                "run",
                "remote-video-translate-subtitle",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

    assert (
        main(
            [
                "--project",
                str(project),
                "--json",
                "artifact",
                "list",
                "--workflow",
                "remote-video-translate-subtitle",
            ]
        )
        == 0
    )
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == [
        "download.video",
        "extract_audio.audio",
        "transcribe.transcript",
        "glossary.transcript",
        "translate.translation",
        "subtitle.subtitle",
    ]

    subtitle_id = artifacts[-1]["id"]
    assert main(["--project", str(project), "--json", "artifact", "show", subtitle_id]) == 0
    subtitle = json.loads(capsys.readouterr().out)
    assert "[zh-Hans] Hello OpenBBQ" in subtitle["current_version"]["content"]
```

- [ ] **Step 2: Run E2E test**

Run:

```bash
uv run pytest tests/test_phase2_remote_video_slice.py -q
```

Expected: PASS after Tasks 1 through 4.

- [ ] **Step 3: Run related integration tests**

Run:

```bash
uv run pytest tests/test_phase2_remote_video_slice.py tests/test_phase2_translation_slice.py tests/test_phase2_local_video_subtitle.py tests/test_cli_integration.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/test_phase2_remote_video_slice.py
git commit -m "test: Add deterministic remote translated subtitle workflow"
```

## Task 6: Documentation Updates

**Files:**
- Modify: `README.md`
- Modify: `docs/Target-Workflows.md`
- Modify: `docs/Roadmap.md`

- [ ] **Step 1: Update README**

Add this section after the existing `## Phase 2 Translation Preview` section:

````markdown
## Phase 2 Remote Video Preview

Slice 3 adds remote video download through `yt-dlp` and a full remote translated subtitle workflow. Install the download, media, and LLM optional dependency groups before running a real remote smoke test:

```bash
uv sync --extra download --extra media --extra llm
export OPENBBQ_LLM_API_KEY=sk-your-key
export OPENBBQ_LLM_BASE_URL=https://api.openai.com/v1
cp -R tests/fixtures/projects/remote-video-translate-subtitle ./demo-remote
# Edit ./demo-remote/openbbq.yaml and set download.parameters.url to the source URL.
uv run openbbq run remote-video-translate-subtitle --project ./demo-remote
```

Default CI uses fake downloaders, fake media, and fake OpenAI clients; it does not require network access, ffmpeg, Whisper models, or LLM credentials.
````

- [ ] **Step 2: Update `docs/Target-Workflows.md`**

Replace the introductory phase sentence with:

```markdown
Phase 1 proves the workflow engine contracts using mock plugins. Phase 2 introduces real remote video download, local media processing, glossary replacement, translation, and subtitle plugins for CLI-driven workflows.
```

Rename the target workflow heading:

```markdown
## Remote Video to Subtitle File
```

Replace the pipeline text with:

```text
remote_video.download -> ffmpeg.extract_audio -> faster_whisper.transcribe -> glossary.replace -> llm.translate -> subtitle.export
```

Replace the workflow description sentence with:

```markdown
A complete media language processing pipeline: download a remote video URL, extract audio, transcribe speech word-by-word, apply glossary rules, translate with an LLM, and export a subtitle file.
```

Replace the first step heading and field table with:

```markdown
#### 1. Download Remote Video

| Field | Value |
|---|---|
| `tool_ref` | `remote_video.download` |
| `effects` | `network`, `writes_files` |
| Output artifact | `video` |
```

Replace the first step parameter table with:

```markdown
| Name | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | Remote video URL supported by `yt-dlp`. |
| `format` | string | no | Output container. Currently only `mp4` is supported. Defaults to `mp4`. |
| `quality` | string | no | `yt-dlp` format selector. Defaults to `best`. |
```

Replace the ASR tool ref field with:

```markdown
| `tool_ref` | `faster_whisper.transcribe` |
```

Replace the artifact flow summary diagram with:

```text
url, format, quality
        │
        ▼
[remote_video.download] ──► video
                               │
                               ▼
                   [ffmpeg.extract_audio] ──► audio
                                                │
                                                ▼
                          [faster_whisper.transcribe] ──► asr_transcript
                                                                 │
                                                            ┌────┘
                                                            │  glossary rules
                                                            ▼
                                         [glossary.replace] ──► asr_transcript (modified)
                                                                        │
                                                                        ▼
                                                    [llm.translate] ──► translation
                                                                             │
                                                                             ▼
                                                       [subtitle.export] ──► subtitle
```

Replace the availability table with:

```markdown
| Step | Plugin | Phase |
|---|---|---|
| Download remote video | `remote_video.download` | Phase 2 Slice 3 |
| Convert to audio | `ffmpeg.extract_audio` | Phase 2 Slice 1 |
| ASR recognition | `faster_whisper.transcribe` | Phase 2 Slice 1 |
| Rule / glossary replacement | `glossary.replace` | Phase 2 Slice 2 |
| Translation (LLM) | `llm.translate` | Phase 2 Slice 2 |
| Export subtitle | `subtitle.export` | Phase 2 Slice 1 |
```

- [ ] **Step 3: Update `docs/Roadmap.md`**

Add this bullet under Phase 2:

```markdown
- Built-in yt-dlp remote video download
```

- [ ] **Step 4: Run docs-adjacent tests**

Run:

```bash
uv run pytest tests/test_fixtures.py tests/test_package_layout.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md docs/Target-Workflows.md docs/Roadmap.md
git commit -m "docs: Document remote translated subtitle workflow"
```

## Task 7: Full Verification

**Files:**
- All files changed by Tasks 1 through 6.

- [ ] **Step 1: Sync default dependencies**

Run:

```bash
uv sync
```

Expected: command exits 0.

- [ ] **Step 2: Verify download optional dependencies can sync**

Run:

```bash
uv sync --extra download
```

Expected: command exits 0 and installs `yt-dlp`.

- [ ] **Step 3: Verify combined optional dependencies can sync**

Run:

```bash
uv sync --extra download --extra media --extra llm
```

Expected: command exits 0 and installs `yt-dlp`, `faster-whisper`, and `openai`.

- [ ] **Step 4: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 5: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: all checks pass.

- [ ] **Step 6: Run format check**

Run:

```bash
uv run ruff format --check .
```

Expected: all files already formatted.

- [ ] **Step 7: Run existing CLI validation smoke**

Run:

```bash
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
```

Expected: `Workflow 'text-demo' is valid.`

- [ ] **Step 8: Validate remote translated fixture**

Run:

```bash
uv run openbbq validate remote-video-translate-subtitle --project tests/fixtures/projects/remote-video-translate-subtitle
```

Expected: `Workflow 'remote-video-translate-subtitle' is valid.`

- [ ] **Step 9: Build wheel**

Run:

```bash
uv build --wheel --out-dir tmp/remote-video-wheel
```

Expected: command exits 0 and the build log includes `openbbq/builtin_plugins/remote_video/openbbq.plugin.toml`.

- [ ] **Step 10: Confirm git status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes after all task commits.
