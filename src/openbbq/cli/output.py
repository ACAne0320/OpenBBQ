from __future__ import annotations

import json
import sys
from typing import Any

from openbbq.domain.base import JsonObject, dump_jsonable
from openbbq.errors import OpenBBQError


def emit(payload: JsonObject, json_output: bool, text: Any) -> None:
    payload = dump_jsonable(payload)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
        return
    if text is not None:
        print(text)


def emit_error(error: OpenBBQError, json_output: bool) -> None:
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(error.message, file=sys.stderr)


def jsonable_content(content: Any) -> Any:
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content
