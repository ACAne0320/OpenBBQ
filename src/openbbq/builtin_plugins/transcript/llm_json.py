from __future__ import annotations

from typing import Any

from openbbq.builtin_plugins.llm import (
    completion_content as _completion_content,
    default_openai_client_factory as _default_client_factory,
    parse_indexed_text_items,
    segment_chunks as _segment_chunks,
)


def _parse_json_array(
    content: str,
    *,
    expected_count: int,
    error_prefix: str,
    item_label: str,
) -> list[dict[str, Any]]:
    return parse_indexed_text_items(
        content,
        expected_count=expected_count,
        error_prefix=error_prefix,
        item_label=item_label,
    )


__all__ = [
    "_completion_content",
    "_default_client_factory",
    "_parse_json_array",
    "_segment_chunks",
]
