from pathlib import Path

import tomllib
import yaml
from jsonschema import Draft7Validator

from openbbq.config.loader import load_project_config
from openbbq.plugins.registry import discover_plugins


FIXTURES = Path(__file__).parent / "fixtures"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _load_manifest(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def _tool_map(manifest: dict) -> dict[str, dict]:
    return {tool["name"]: tool for tool in manifest["tools"]}


def test_fixture_manifests_and_projects_match_phase_1_contracts():
    text_project = _load_yaml(FIXTURES / "projects/text-basic/openbbq.yaml")
    youtube_project = _load_yaml(FIXTURES / "projects/youtube-subtitle-mock/openbbq.yaml")
    mock_text_manifest = _load_manifest(FIXTURES / "plugins/mock-text/openbbq.plugin.toml")
    mock_media_manifest = _load_manifest(FIXTURES / "plugins/mock-media/openbbq.plugin.toml")

    mock_text_tools = _tool_map(mock_text_manifest)
    mock_media_tools = _tool_map(mock_media_manifest)

    assert mock_text_manifest["manifest_version"] == 2
    assert mock_media_manifest["manifest_version"] == 2
    assert set(mock_text_tools) == {
        "echo",
        "uppercase",
        "glossary_replace",
        "translate",
        "subtitle_export",
        "flaky_echo",
        "always_fail",
    }
    assert set(mock_media_tools) == {"youtube_download", "extract_audio", "transcribe"}
    assert mock_text_tools["uppercase"]["inputs"]["text"]["artifact_types"] == ["text"]
    assert mock_text_tools["uppercase"]["outputs"]["text"]["artifact_type"] == "text"
    assert mock_media_tools["extract_audio"]["inputs"]["video"]["artifact_types"] == ["video"]
    assert mock_media_tools["extract_audio"]["outputs"]["audio"]["artifact_type"] == "audio"

    projects = [text_project, youtube_project]
    tool_maps = {
        "mock_text": mock_text_tools,
        "mock_media": mock_media_tools,
    }

    for project in projects:
        for workflow in project["workflows"].values():
            for step in workflow["steps"]:
                plugin_name, tool_name = step["tool_ref"].split(".", 1)
                tool = tool_maps[plugin_name][tool_name]
                Draft7Validator(tool["parameter_schema"]).validate(step["parameters"])


def test_text_pause_fixture_pauses_before_uppercase():
    project = _load_yaml(FIXTURES / "projects/text-pause/openbbq.yaml")

    steps = project["workflows"]["text-demo"]["steps"]

    assert steps[0]["id"] == "seed"
    assert steps[1]["id"] == "uppercase"
    assert steps[1]["pause_before"] is True


def test_local_video_subtitle_fixture_uses_builtin_plugins():
    config = load_project_config(FIXTURES / "projects/local-video-subtitle")
    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "subtitle.export" in registry.tools


def test_local_video_translate_subtitle_fixture_uses_builtin_plugins():
    config = load_project_config(FIXTURES / "projects/local-video-translate-subtitle")
    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "glossary.replace" in registry.tools
    assert "transcript.segment" in registry.tools
    assert "translation.translate" in registry.tools
    assert "subtitle.export" in registry.tools


def test_remote_video_translate_subtitle_fixture_uses_builtin_plugins():
    config = load_project_config(FIXTURES / "projects/remote-video-translate-subtitle")
    registry = discover_plugins(config.plugin_paths)

    assert "remote_video.download" in registry.tools
    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "glossary.replace" in registry.tools
    assert "transcript.segment" in registry.tools
    assert "translation.translate" in registry.tools
    assert "subtitle.export" in registry.tools


def test_local_video_corrected_translate_subtitle_fixture_uses_builtin_plugins():
    config = load_project_config(FIXTURES / "projects/local-video-corrected-translate-subtitle")
    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "transcript.correct" in registry.tools
    assert "transcript.segment" in registry.tools
    assert "translation.translate" in registry.tools
    assert "subtitle.export" in registry.tools
    workflow = config.workflows["local-video-corrected-translate-subtitle"]
    correct_step = next(step for step in workflow.steps if step.id == "correct")
    translate_step = next(step for step in workflow.steps if step.id == "translate")
    assert correct_step.parameters["provider"] == "openai"
    assert "model" not in correct_step.parameters
    assert translate_step.parameters["provider"] == "openai"
    assert "model" not in translate_step.parameters
