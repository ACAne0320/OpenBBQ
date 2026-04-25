from __future__ import annotations

import json
from typing import Any, Protocol, TypeVar

from sqlalchemy.orm import Session

from openbbq.domain.base import JsonObject
from openbbq.storage.models import RecordModel

RecordT = TypeVar("RecordT", bound=RecordModel)
RowT = TypeVar("RowT")


class RecordJsonRow(Protocol):
    record_json: str


def record_payload(record: RecordModel) -> JsonObject:
    return record.model_dump(mode="json")


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dump_nullable_json(value: Any) -> str | None:
    if value is None:
        return None
    return dump_json(value)


def model_from_row(model_type: type[RecordT], row: RecordJsonRow) -> RecordT:
    return model_type.model_validate(json.loads(row.record_json))


def model_from_optional_row(model_type: type[RecordT], row: RecordJsonRow | None) -> RecordT | None:
    if row is None:
        return None
    return model_from_row(model_type, row)


def upsert_row(session: Session, row_type: type[RowT], row_id: str) -> RowT:
    row = session.get(row_type, row_id)
    if row is None:
        row = row_type(id=row_id)  # type: ignore[call-arg]
        session.add(row)
    return row
