from openbbq.application.runs import RunCreateRequest, abort_run, create_run, get_run, resume_run
from openbbq.application.workflows import workflow_status
from openbbq.errors import ExecutionError
from tests.helpers import write_project_fixture


def test_create_run_executes_workflow_with_sync_executor(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    loaded = get_run(project_root=project, run_id=created.id)

    assert created.workflow_id == "text-demo"
    assert loaded.status == "completed"
    assert loaded.latest_event_sequence > 0


def test_resume_run_updates_run_record_to_final_workflow_status(tmp_path):
    project = write_project_fixture(tmp_path, "text-pause")

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    resumed = resume_run(project_root=project, run_id=created.id)
    loaded = get_run(project_root=project, run_id=created.id)

    assert workflow_status(project_root=project, workflow_id="text-demo").status == "completed"
    assert resumed.status == "completed"
    assert loaded.status == "completed"
    assert loaded.completed_at is not None
    assert loaded.latest_event_sequence > created.latest_event_sequence


def test_abort_paused_run_updates_run_record_to_aborted(tmp_path):
    project = write_project_fixture(tmp_path, "text-pause")

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    aborted = abort_run(project_root=project, run_id=created.id)
    loaded = get_run(project_root=project, run_id=created.id)

    assert workflow_status(project_root=project, workflow_id="text-demo").status == "aborted"
    assert aborted.status == "aborted"
    assert loaded.status == "aborted"
    assert loaded.completed_at is not None
    assert loaded.latest_event_sequence > created.latest_event_sequence


def test_create_run_records_unexpected_exception_as_failed(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")

    def fail_unexpectedly(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("openbbq.application.runs.run_workflow_command", fail_unexpectedly)

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    loaded = get_run(project_root=project, run_id=created.id)

    assert loaded.status == "failed"
    assert loaded.error is not None
    assert loaded.error.code == "internal_error"
    assert loaded.error.message == "boom"


def test_create_run_records_openbbq_error_code_and_message(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")

    def fail_with_domain_error(*args, **kwargs):
        raise ExecutionError(
            "workflow cannot start",
            code="invalid_workflow_state",
            exit_code=1,
        )

    monkeypatch.setattr("openbbq.application.runs.run_workflow_command", fail_with_domain_error)

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    loaded = get_run(project_root=project, run_id=created.id)

    assert loaded.status == "failed"
    assert loaded.error is not None
    assert loaded.error.code == "invalid_workflow_state"
    assert loaded.error.message == "workflow cannot start"


def test_resume_run_can_submit_without_blocking(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-pause")
    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    submitted = []

    def capture_submit(function, *args):
        submitted.append((function, args))

        class Result:
            pass

        return Result()

    monkeypatch.setattr("openbbq.application.runs._EXECUTOR.submit", capture_submit)

    resumed = resume_run(project_root=project, run_id=created.id, execute_inline=False)

    assert resumed.status == "queued"
    assert submitted
    assert submitted[0][0].__name__ == "_execute_resume"
