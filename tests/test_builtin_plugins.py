from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.plugins.registry import discover_plugins


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        """
version: 1
project:
  name: Builtins
workflows:
  demo:
    name: Demo
    steps:
      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: project.art_missing
        outputs:
          - name: audio
            type: audio
        parameters: {}
        on_error: abort
        max_retries: 0
""",
        encoding="utf-8",
    )
    return project


def test_builtin_plugin_path_is_discovered_by_default(tmp_path):
    config = load_project_config(write_project(tmp_path))

    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "subtitle.export" in registry.tools
