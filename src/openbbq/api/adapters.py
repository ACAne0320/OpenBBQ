from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from openbbq.domain.base import OpenBBQModel

T = TypeVar("T", bound=OpenBBQModel)


def api_model(schema_type: type[T], value: OpenBBQModel) -> T:
    return schema_type.model_validate(value.model_dump())


def api_models(schema_type: type[T], values: Iterable[OpenBBQModel]) -> tuple[T, ...]:
    return tuple(api_model(schema_type, value) for value in values)
