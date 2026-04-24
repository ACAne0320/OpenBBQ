from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.transitions import (
    mark_step_run_completed,
    mark_step_run_started,
    mark_workflow_running,
)


def test_transition_helpers_write_typed_workflow_and_step_run_records(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    state = mark_workflow_running(
        store,
        workflow_id="text-demo",
        workflow_name="Text Demo",
        current_step_id="seed",
        config_hash="abc",
        step_run_ids=(),
    )
    step_run = mark_step_run_started(
        store,
        workflow_id="text-demo",
        step_id="seed",
        attempt=1,
    )
    completed = mark_step_run_completed(
        store,
        workflow_id="text-demo",
        step_run=step_run,
        input_artifact_version_ids={},
        output_bindings={},
    )

    assert state.status == "running"
    assert step_run.status == "running"
    assert completed.status == "completed"
