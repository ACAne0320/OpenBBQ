from pathlib import Path

from openbbq.config import load_project_config
from openbbq.engine import run_workflow
from openbbq.plugins import discover_plugins
from openbbq.storage import ProjectStore


def test_run_mock_youtube_subtitle_workflow(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/youtube-subtitle-mock/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    config = load_project_config(project)

    result = run_workflow(config, discover_plugins(config.plugin_paths), "youtube-subtitle")

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    artifacts = store.list_artifacts()
    assert [artifact["name"] for artifact in artifacts] == [
        "download.video",
        "extract_audio.audio",
        "transcribe.transcript",
        "glossary.transcript",
        "translate.translation",
        "subtitle.subtitle",
    ]
    subtitle = [artifact for artifact in artifacts if artifact["type"] == "subtitle"][0]
    version = store.read_artifact_version(subtitle["current_version_id"])
    assert "OpenBBQ" in version.content
    assert version.record["metadata"]["format"] == "srt"
    assert version.record["metadata"]["segment_count"] == 1
