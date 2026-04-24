from pathlib import Path

import pytest

from openbbq.application.plugins import plugin_info, plugin_list
from openbbq.application.projects import ProjectInitRequest, init_project, project_info
from openbbq.errors import ValidationError


def test_project_service_initializes_and_reports_project(tmp_path):
    result = init_project(ProjectInitRequest(project_root=tmp_path))
    info = project_info(project_root=tmp_path)

    assert result.config_path == tmp_path / "openbbq.yaml"
    assert info.name == "OpenBBQ Project"
    assert info.workflow_count == 0
    assert info.artifact_storage_path == tmp_path / ".openbbq" / "artifacts"


def test_project_service_rejects_existing_config(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n\nproject:\n  name: Demo\n\nworkflows: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="already exists"):
        init_project(ProjectInitRequest(project_root=tmp_path))


def test_plugin_service_lists_and_describes_fixture_plugin(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/text-basic/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )

    listed = plugin_list(project_root=project)
    info = plugin_info(project_root=project, plugin_name="mock_text")

    assert listed.plugins[0]["name"] == "mock_text"
    assert any(plugin["name"] == "faster_whisper" for plugin in listed.plugins)
    assert info.plugin["name"] == "mock_text"
    assert any(tool["name"] == "uppercase" for tool in info.plugin["tools"])
