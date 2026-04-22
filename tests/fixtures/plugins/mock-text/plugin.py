from __future__ import annotations

import json
import re
from copy import deepcopy


def _input_value(request: dict, name: str, default=None):
    value = request.get("inputs", {}).get(name, {})
    if "literal" in value:
        return value["literal"]
    return value.get("content", default)


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return json.dumps(value, ensure_ascii=False)


def _segments_from_transcript(content):
    if isinstance(content, str):
        return json.loads(content)
    return deepcopy(content)


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_srt(segments):
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_srt_timestamp(segment['start'])} --> {_srt_timestamp(segment['end'])}",
                    _as_text(segment["text"]),
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def run(request):
    tool_name = request["tool_name"]
    parameters = request.get("parameters", {})

    if tool_name == "echo":
        text = _as_text(_input_value(request, "text"))
        return {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": text,
                    "metadata": {},
                }
            }
        }

    if tool_name == "uppercase":
        text = _as_text(_input_value(request, "text"))
        return {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": text.upper(),
                    "metadata": {},
                }
            }
        }

    if tool_name == "glossary_replace":
        segments = _segments_from_transcript(_input_value(request, "transcript", []))
        rules = parameters.get("rules", [])
        updated = []
        for segment in segments:
            next_segment = deepcopy(segment)
            text = _as_text(next_segment.get("text", ""))
            for rule in rules:
                pattern = rule["find"]
                replacement = rule["replace"]
                if rule.get("is_regex"):
                    flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
                    text = re.sub(pattern, replacement, text, flags=flags)
                else:
                    if rule.get("case_sensitive", False):
                        text = text.replace(pattern, replacement)
                    else:
                        text = re.sub(re.escape(pattern), replacement, text, flags=re.IGNORECASE)
            next_segment["text"] = text
            updated.append(next_segment)
        return {
            "outputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": updated,
                    "metadata": {
                        "language": request.get("parameters", {}).get("language", "en"),
                        "model": "mock-glossary",
                        "segment_count": len(updated),
                        "word_count": sum(
                            len(_as_text(segment.get("text", "")).split()) for segment in updated
                        ),
                    },
                }
            }
        }

    if tool_name == "translate":
        segments = _segments_from_transcript(_input_value(request, "transcript", []))
        source_lang = parameters["source_lang"]
        target_lang = parameters["target_lang"]
        translated = []
        for segment in segments:
            next_segment = deepcopy(segment)
            next_segment["source_text"] = _as_text(segment.get("text", ""))
            next_segment["text"] = f"[{target_lang}] {next_segment['source_text']}"
            translated.append(next_segment)
        return {
            "outputs": {
                "translation": {
                    "type": "translation",
                    "content": translated,
                    "metadata": {
                        "source_lang": source_lang,
                        "target_lang": target_lang,
                        "model": parameters["model"],
                        "segment_count": len(translated),
                    },
                }
            }
        }

    if tool_name == "subtitle_export":
        segments = _segments_from_transcript(_input_value(request, "translation", []))
        subtitle = _format_srt(segments)
        return {
            "outputs": {
                "subtitle": {
                    "type": "subtitle",
                    "content": subtitle,
                    "metadata": {
                        "format": parameters["format"],
                        "segment_count": len(segments),
                        "duration_seconds": float(segments[-1]["end"]) if segments else 0.0,
                    },
                }
            }
        }

    raise ValueError(f"Unsupported tool: {tool_name}")
