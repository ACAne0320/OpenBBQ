from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


def run(request: dict) -> dict:
    if request.get("tool_name") != "replace":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    segments = _segments(request)
    rules = request.get("parameters", {}).get("rules", [])
    updated = [_apply_rules(segment, rules) for segment in segments]
    return {
        "outputs": {
            "transcript": {
                "type": "asr_transcript",
                "content": updated,
                "metadata": {
                    "segment_count": len(updated),
                    "word_count": sum(
                        len(str(segment.get("text", "")).split()) for segment in updated
                    ),
                    "rule_count": len(rules),
                },
            }
        }
    }


def _segments(request: dict) -> list[dict[str, Any]]:
    transcript = request.get("inputs", {}).get("transcript", {})
    if not isinstance(transcript, dict) or "content" not in transcript:
        raise ValueError("glossary.replace requires transcript content.")
    content = transcript["content"]
    if not isinstance(content, list) or any(not isinstance(segment, dict) for segment in content):
        raise ValueError("glossary.replace transcript content must be a list of objects.")
    return content


def _apply_rules(segment: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    next_segment = deepcopy(segment)
    text = str(next_segment.get("text", ""))
    for rule in rules:
        find = str(rule["find"])
        replace = str(rule["replace"])
        if rule.get("is_regex", False):
            flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
            text = re.sub(find, replace, text, flags=flags)
            continue
        if rule.get("case_sensitive", False):
            text = text.replace(find, replace)
        else:
            text = re.sub(re.escape(find), replace, text, flags=re.IGNORECASE)
    next_segment["text"] = text
    return next_segment
