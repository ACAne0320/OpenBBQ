from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError as PydanticValidationError
import yaml

from openbbq.domain.base import JsonObject, OpenBBQModel, format_pydantic_error
from openbbq.errors import ValidationError

TModel = TypeVar("TModel", bound=OpenBBQModel)


def load_yaml_mapping(path: Path) -> JsonObject:
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ValidationError(f"Project config '{path}' was not found.") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"Project config '{path}' contains malformed YAML.") from exc
    if not isinstance(raw, dict):
        raise ValidationError(f"Project config '{path}' must contain a YAML mapping.")
    return raw


def build_model(model_type: type[TModel], field_path: str, **values: Any) -> TModel:
    try:
        return model_type(**values)
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error(field_path, exc)) from exc


def require_mapping(value: Any, field_path: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_path} must be a mapping.")
    return value


def optional_mapping(value: Any, field_path: str) -> JsonObject:
    if value is None:
        return {}
    return require_mapping(value, field_path)


def require_nonempty_string(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_path} must be a non-empty string.")
    return value


def require_bool(value: Any, field_path: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field_path} must be a boolean.")
    return value
