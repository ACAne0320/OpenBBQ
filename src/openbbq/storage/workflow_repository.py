from __future__ import annotations

from openbbq.domain.base import JsonObject, dump_jsonable
from openbbq.errors import StepRunNotFoundError, WorkflowStateNotFoundError
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.id_generation import StepRunIdGenerator
from openbbq.storage.models import StepRunRecord, WorkflowState


class WorkflowRepository:
    def __init__(
        self,
        database: ProjectDatabase,
        *,
        id_generator: StepRunIdGenerator,
    ) -> None:
        self.database = database
        self.id_generator = id_generator

    def write_workflow_state(
        self, workflow_id: str, state: JsonObject | WorkflowState
    ) -> WorkflowState:
        record = dict(dump_jsonable(state))
        record["id"] = workflow_id
        typed = WorkflowState.model_validate(record)
        return self.database.write_workflow_state(typed)

    def read_workflow_state(self, workflow_id: str) -> WorkflowState:
        state = self.database.read_workflow_state(workflow_id)
        if state is None:
            raise WorkflowStateNotFoundError(f"workflow state not found: {workflow_id}")
        return state

    def write_step_run(
        self, workflow_id: str, step_run: JsonObject | StepRunRecord
    ) -> StepRunRecord:
        record = dict(dump_jsonable(step_run))
        record["workflow_id"] = workflow_id
        if not record.get("id"):
            record["id"] = self.id_generator.step_run_id()
        typed = StepRunRecord.model_validate(record)
        return self.database.write_step_run(typed)

    def read_step_run(self, workflow_id: str, step_run_id: str) -> StepRunRecord:
        step_run = self.database.read_step_run(workflow_id, step_run_id)
        if step_run is None:
            raise StepRunNotFoundError(f"step run not found: {step_run_id}")
        return step_run
