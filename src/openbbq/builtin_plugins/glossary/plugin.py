from __future__ import annotations

from copy import deepcopy
from typing import Any

from .rules import apply_text_rules, normalize_rules


def run(request: dict) -> dict:
    if request.get("tool_name") != "replace":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    segments = _segments(request)
    rules = normalize_rules(
        request.get("parameters", {}).get("rules", []),
        parameter_name="rules",
        tool_name="glossary.replace",
    )
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
    next_segment["text"] = apply_text_rules(str(next_segment.get("text", "")), rules)
    return next_segment
