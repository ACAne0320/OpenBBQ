from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path

import yaml

from openbbq.config.workflows import WORKFLOW_ID_PATTERN
from openbbq.domain.base import JsonObject
from openbbq.errors import ValidationError
from openbbq.workflow_custom.models import WorkflowDefinition

WORKFLOW_CUSTOM_ROOT_ENV = "OPENBBQ_WORKFLOW_CUSTOM_ROOT"


def default_workflow_custom_root() -> Path:
    override = os.environ.get(WORKFLOW_CUSTOM_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent


class WorkflowDefinitionRepository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_workflow_custom_root()

    def list(self) -> tuple[WorkflowDefinition, ...]:
        if not self.root.exists():
            return ()
        workflows = []
        for path in sorted(self.root.glob("*.yaml")):
            workflows.append(self.read(path.stem))
        return tuple(workflows)

    def read(self, workflow_id: str) -> WorkflowDefinition:
        path = self._path_for_id(workflow_id)
        if not path.exists():
            raise ValidationError(f"Custom workflow '{workflow_id}' is not defined.")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValidationError(f"Custom workflow file '{path.name}' must be a mapping.")
        data: JsonObject = dict(raw)
        data.setdefault("id", workflow_id)
        data["origin"] = "custom"
        return WorkflowDefinition.model_validate(data)

    def write(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        if workflow.origin == "built_in":
            workflow = workflow.model_copy(update={"origin": "custom"})
        timestamp = datetime.now(UTC).isoformat()
        stored = workflow.model_copy(update={"updated_at": timestamp, "origin": "custom"})
        path = self._path_for_id(stored.id)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = stored.model_dump(mode="json", exclude_none=True)
        tmp_path = path.with_suffix(".yaml.tmp")
        tmp_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return stored

    def _path_for_id(self, workflow_id: str) -> Path:
        if WORKFLOW_ID_PATTERN.fullmatch(workflow_id) is None:
            raise ValidationError(f"Invalid custom workflow id: '{workflow_id}'.")
        return self.root / f"{workflow_id}.yaml"
