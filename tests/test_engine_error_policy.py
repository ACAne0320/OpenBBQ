from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.engine.service import run_workflow
from openbbq.engine.validation import validate_workflow
from openbbq.errors import ExecutionError
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.project_store import ProjectStore


def write_config(tmp_path, workflow_yaml: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        f"""
version: 1
project:
  name: Error Policy
plugins:
  paths:
    - {Path.cwd() / "tests/fixtures/plugins/mock-text"}
workflows:
{workflow_yaml}
""",
        encoding="utf-8",
    )
    return project


def test_validate_accepts_retry_and_skip_policies(tmp_path):
    project = write_config(
        tmp_path,
        """
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.flaky_echo
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {text: hello, fail_until_attempt: 1}
        on_error: retry
        max_retries: 1
""",
    )
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    result = validate_workflow(config, registry, "demo")

    assert result.workflow_id == "demo"


def test_retry_policy_succeeds_after_failed_attempt(tmp_path):
    project = write_config(
        tmp_path,
        """
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.flaky_echo
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {text: retry ok, fail_until_attempt: 1}
        on_error: retry
        max_retries: 1
""",
    )
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    result = run_workflow(config, registry, "demo")

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("demo")
    step_runs = [store.read_step_run("demo", step_run_id) for step_run_id in state.step_run_ids]
    assert [step_run.attempt for step_run in step_runs] == [1, 2]
    assert [step_run.status for step_run in step_runs] == ["failed", "completed"]
    current_version_id = store.list_artifacts()[0].current_version_id
    assert current_version_id is not None
    assert store.read_artifact_version(current_version_id).content == "retry ok"


def test_retry_policy_exhaustion_marks_workflow_failed(tmp_path):
    project = write_config(
        tmp_path,
        """
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.always_fail
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {message: still failing}
        on_error: retry
        max_retries: 1
""",
    )
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    with pytest.raises(ExecutionError, match="still failing"):
        run_workflow(config, registry, "demo")

    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("demo")
    assert state.status == "failed"
    step_runs = [store.read_step_run("demo", step_run_id) for step_run_id in state.step_run_ids]
    assert [step_run.status for step_run in step_runs] == ["failed", "failed"]


def test_skip_policy_continues_when_downstream_does_not_reference_skipped_output(tmp_path):
    project = write_config(
        tmp_path,
        """
  demo:
    name: Demo
    steps:
      - id: optional
        name: Optional
        tool_ref: mock_text.always_fail
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {message: optional failed}
        on_error: skip
        max_retries: 0
      - id: seed
        name: Seed
        tool_ref: mock_text.echo
        inputs:
          text: independent
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0
""",
    )
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    result = run_workflow(config, registry, "demo")

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("demo")
    step_runs = [store.read_step_run("demo", step_run_id) for step_run_id in state.step_run_ids]
    assert [step_run.status for step_run in step_runs] == ["skipped", "completed"]
    assert [artifact.name for artifact in store.list_artifacts()] == ["seed.text"]


def test_skipped_output_reference_fails_downstream_step(tmp_path):
    project = write_config(
        tmp_path,
        """
  demo:
    name: Demo
    steps:
      - id: optional
        name: Optional
        tool_ref: mock_text.always_fail
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {message: optional failed}
        on_error: skip
        max_retries: 0
      - id: use_optional
        name: Use Optional
        tool_ref: mock_text.uppercase
        inputs:
          text: optional.text
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0
""",
    )
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    with pytest.raises(ExecutionError, match="optional.text"):
        run_workflow(config, registry, "demo")

    assert ProjectStore(project / ".openbbq").read_workflow_state("demo").status == "failed"


def test_plugin_pause_requested_pauses_after_successful_step(tmp_path):
    project = write_config(
        tmp_path,
        """
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.flaky_echo
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {text: review me, pause_requested: true}
        on_error: abort
        max_retries: 0
      - id: uppercase
        name: Uppercase
        tool_ref: mock_text.uppercase
        inputs:
          text: seed.text
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0
""",
    )
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    result = run_workflow(config, registry, "demo")

    assert result.status == "paused"
    state = ProjectStore(project / ".openbbq").read_workflow_state("demo")
    assert state.status == "paused"
    assert state.current_step_id == "uppercase"
