from __future__ import annotations

from pathlib import Path

from openbbq.application.quickstart_workflows import (
    LOCAL_SUBTITLE_TEMPLATE_ID,
    YOUTUBE_SUBTITLE_TEMPLATE_ID,
    subtitle_workflow_template_for_source,
)
from openbbq.errors import ValidationError
from openbbq.workflow_custom.models import WorkflowDefinition
from openbbq.workflow_custom.repository import WorkflowDefinitionRepository


def list_workflow_definitions(
    *, custom_root: Path | None = None
) -> tuple[WorkflowDefinition, ...]:
    repository = WorkflowDefinitionRepository(custom_root)
    return (*_built_in_workflows(), *repository.list())


def get_workflow_definition(
    workflow_id: str, *, custom_root: Path | None = None
) -> WorkflowDefinition:
    for workflow in _built_in_workflows():
        if workflow.id == workflow_id:
            return workflow
    return WorkflowDefinitionRepository(custom_root).read(workflow_id)


def save_workflow_definition(
    workflow: WorkflowDefinition, *, custom_root: Path | None = None
) -> WorkflowDefinition:
    if workflow.id in {LOCAL_SUBTITLE_TEMPLATE_ID, YOUTUBE_SUBTITLE_TEMPLATE_ID}:
        raise ValidationError(f"Custom workflow id '{workflow.id}' conflicts with a built-in workflow.")
    return WorkflowDefinitionRepository(custom_root).write(workflow)


def _built_in_workflows() -> tuple[WorkflowDefinition, ...]:
    local_template = subtitle_workflow_template_for_source(source_kind="local_file")
    remote_template = subtitle_workflow_template_for_source(source_kind="remote_url")
    return (
        WorkflowDefinition(
            id=LOCAL_SUBTITLE_TEMPLATE_ID,
            name="Local video -> translated SRT",
            description="Extract audio, transcribe, translate, and prepare an SRT subtitle for review.",
            origin="built_in",
            source_types=("local_file",),
            result_types=("subtitle",),
            steps=local_template["steps"],
        ),
        WorkflowDefinition(
            id=YOUTUBE_SUBTITLE_TEMPLATE_ID,
            name="Remote video -> translated SRT",
            description="Download a remote video, transcribe, translate, and prepare an SRT subtitle for review.",
            origin="built_in",
            source_types=("remote_url",),
            result_types=("subtitle",),
            steps=remote_template["steps"],
        ),
    )
