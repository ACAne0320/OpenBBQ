from __future__ import annotations

from fastapi import APIRouter

from openbbq.api.schemas import (
    ApiSuccess,
    WorkflowDefinitionData,
    WorkflowDefinitionListData,
    WorkflowDefinitionSaveRequest,
)
from openbbq.application.workflow_definitions import (
    get_workflow_definition,
    list_workflow_definitions,
    save_workflow_definition,
)
from openbbq.workflow_custom.models import WorkflowDefinition

router = APIRouter(tags=["workflow-definitions"])


@router.get(
    "/workflow-definitions",
    response_model=ApiSuccess[WorkflowDefinitionListData],
    response_model_exclude_none=True,
)
def list_workflow_definition_route() -> ApiSuccess[WorkflowDefinitionListData]:
    workflows = tuple(
        WorkflowDefinitionData.model_validate(workflow.model_dump(mode="json"))
        for workflow in list_workflow_definitions()
    )
    return ApiSuccess(data=WorkflowDefinitionListData(workflows=workflows))


@router.get(
    "/workflow-definitions/{workflow_id}",
    response_model=ApiSuccess[WorkflowDefinitionData],
    response_model_exclude_none=True,
)
def get_workflow_definition_route(workflow_id: str) -> ApiSuccess[WorkflowDefinitionData]:
    workflow = get_workflow_definition(workflow_id)
    return ApiSuccess(data=WorkflowDefinitionData.model_validate(workflow.model_dump(mode="json")))


@router.post(
    "/workflow-definitions",
    response_model=ApiSuccess[WorkflowDefinitionData],
    response_model_exclude_none=True,
)
def post_workflow_definition_route(
    body: WorkflowDefinitionSaveRequest,
) -> ApiSuccess[WorkflowDefinitionData]:
    workflow = save_workflow_definition(
        WorkflowDefinition.model_validate({**body.model_dump(mode="json"), "origin": "custom"})
    )
    return ApiSuccess(data=WorkflowDefinitionData.model_validate(workflow.model_dump(mode="json")))


@router.put(
    "/workflow-definitions/{workflow_id}",
    response_model=ApiSuccess[WorkflowDefinitionData],
    response_model_exclude_none=True,
)
def put_workflow_definition_route(
    workflow_id: str,
    body: WorkflowDefinitionSaveRequest,
) -> ApiSuccess[WorkflowDefinitionData]:
    workflow = save_workflow_definition(
        WorkflowDefinition.model_validate(
            {**body.model_dump(mode="json"), "id": workflow_id, "origin": "custom"}
        )
    )
    return ApiSuccess(data=WorkflowDefinitionData.model_validate(workflow.model_dump(mode="json")))
