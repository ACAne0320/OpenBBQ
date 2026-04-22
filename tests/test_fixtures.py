from pathlib import Path

import tomllib
import yaml
from jsonschema import Draft7Validator


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

    assert set(mock_text_tools) == {
        "echo",
        "uppercase",
        "glossary_replace",
        "translate",
        "subtitle_export",
    }
    assert set(mock_media_tools) == {"youtube_download", "extract_audio", "transcribe"}

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
