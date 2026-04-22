from __future__ import annotations


def run(request: dict) -> dict:
    if request.get("tool_name") != "export":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    if parameters.get("format", "srt") != "srt":
        raise ValueError("subtitle.export currently supports only srt.")
    segments = _segments(request)
    subtitle = _format_srt(segments)
    duration = float(segments[-1]["end"]) if segments else 0.0
    return {
        "outputs": {
            "subtitle": {
                "type": "subtitle",
                "content": subtitle,
                "metadata": {
                    "format": "srt",
                    "segment_count": len(segments),
                    "duration_seconds": duration,
                },
            }
        }
    }


def _segments(request: dict) -> list[dict]:
    inputs = request.get("inputs", {})
    payload = inputs.get("transcript") or inputs.get("translation")
    if not isinstance(payload, dict) or "content" not in payload:
        raise ValueError("subtitle.export requires transcript or translation content.")
    content = payload["content"]
    if not isinstance(content, list):
        raise ValueError("subtitle.export input content must be a list of segments.")
    return content


def _format_srt(segments: list[dict]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_timestamp(float(segment['start']))} --> {_timestamp(float(segment['end']))}",
                    str(segment["text"]),
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
