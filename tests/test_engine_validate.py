from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.engine.validation import validate_workflow
from openbbq.errors import ValidationError
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.project_store import ProjectStore


def test_validate_text_workflow_success():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)

    result = validate_workflow(config, registry, "text-demo")

    assert result.workflow_id == "text-demo"
    assert result.step_count == 2


def test_validate_does_not_create_storage_directories(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        f"""
version: 1
project:
  name: Validate Side Effects
plugins:
  paths:
    - {Path.cwd() / "tests/fixtures/plugins/mock-text"}
workflows:
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.echo
        inputs:
          text: hello
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    registry = discover_plugins(config.plugin_paths)

    result = validate_workflow(config, registry, "demo")

    assert result.workflow_id == "demo"
    assert not (tmp_path / ".openbbq").exists()


def test_validate_rejects_unknown_workflow():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)

    with pytest.raises(ValidationError):
        validate_workflow(config, registry, "missing")


def test_validate_rejects_missing_tool_reference(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        """
version: 1
project:
  name: Missing Tool
workflows:
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: missing.echo
        inputs:
          text: hello
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    registry = discover_plugins([])

    with pytest.raises(ValidationError, match="missing.echo"):
        validate_workflow(config, registry, "demo")


def test_validate_rejects_parameter_schema_errors(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        f"""
version: 1
project:
  name: Bad Params
plugins:
  paths:
    - {Path.cwd() / "tests/fixtures/plugins/mock-media"}
workflows:
  demo:
    name: Demo
    steps:
      - id: download
        name: Download
        tool_ref: mock_media.youtube_download
        inputs: {{}}
        outputs:
          - name: video
            type: video
        parameters:
          url: https://example.invalid/watch?v=openbbq
          quality: best
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    registry = discover_plugins(config.plugin_paths)

    with pytest.raises(ValidationError, match="format"):
        validate_workflow(config, registry, "demo")


def test_validate_rejects_incompatible_selector_artifact_type(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        f"""
version: 1
project:
  name: Bad Input Type
plugins:
  paths:
    - {Path.cwd() / "tests/fixtures/plugins/mock-media"}
    - {Path.cwd() / "tests/fixtures/plugins/mock-text"}
workflows:
  demo:
    name: Demo
    steps:
      - id: download
        name: Download
        tool_ref: mock_media.youtube_download
        inputs: {{}}
        outputs:
          - name: video
            type: video
        parameters:
          url: https://example.invalid/watch?v=openbbq
          format: mp4
          quality: best
      - id: uppercase
        name: Uppercase
        tool_ref: mock_text.uppercase
        inputs:
          text: download.video
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    registry = discover_plugins(config.plugin_paths)

    with pytest.raises(ValidationError, match="video"):
        validate_workflow(config, registry, "demo")


def test_validate_rejects_incompatible_project_artifact_type(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        f"""
version: 1
project:
  name: Bad Project Input Type
plugins:
  paths:
    - {Path.cwd() / "tests/fixtures/plugins/mock-text"}
workflows:
  demo:
    name: Demo
    steps:
      - id: uppercase
        name: Uppercase
        tool_ref: mock_text.uppercase
        inputs:
          text: project.ARTIFACT_ID
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )
    store = ProjectStore(tmp_path / ".openbbq")
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"video")
    artifact, _ = store.write_artifact_version(
        artifact_type="video",
        name="source.video",
        file_path=source,
        metadata={},
        created_by_step_id=None,
        lineage={"source": "test"},
    )
    config_path = tmp_path / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("ARTIFACT_ID", artifact.id),
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    registry = discover_plugins(config.plugin_paths)

    with pytest.raises(ValidationError, match="video"):
        validate_workflow(config, registry, "demo")


def test_validate_accepts_pause_flags(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        f"""
version: 1
project:
  name: Pause
plugins:
  paths:
    - {Path.cwd() / "tests/fixtures/plugins/mock-text"}
workflows:
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.echo
        pause_before: true
        inputs:
          text: hello
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    registry = discover_plugins(config.plugin_paths)

    result = validate_workflow(config, registry, "demo")

    assert result.workflow_id == "demo"
    assert result.step_count == 1
