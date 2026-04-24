from __future__ import annotations

from pathlib import Path
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list[Any] | dict[str, Any]
JsonObject: TypeAlias = dict[str, JsonValue]
PluginParameters: TypeAlias = JsonObject
PluginInputs: TypeAlias = JsonObject
ArtifactMetadata: TypeAlias = JsonObject
LineagePayload: TypeAlias = JsonObject


class OpenBBQModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )


def model_payload(value: OpenBBQModel) -> JsonObject:
    return value.model_dump(mode="json")


def format_pydantic_error(entity: str, error: PydanticValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    message = str(first.get("msg", "invalid value"))
    if location:
        return f"{entity}.{location}: {message}"
    return f"{entity}: {message}"


def dump_jsonable(value: Any) -> Any:
    if isinstance(value, OpenBBQModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): dump_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump_jsonable(item) for item in value]
    return value
