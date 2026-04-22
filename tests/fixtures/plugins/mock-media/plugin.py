from __future__ import annotations


def _artifact_content(request: dict, name: str, default=None):
    value = request.get("inputs", {}).get(name, {})
    if "literal" in value:
        return value["literal"]
    return value.get("content", default)


def run(request):
    tool_name = request["tool_name"]
    parameters = request.get("parameters", {})

    if tool_name == "youtube_download":
        url = parameters["url"]
        content = f"MOCK_VIDEO:{url}".encode("utf-8")
        return {
            "outputs": {
                "video": {
                    "type": "video",
                    "content": content,
                    "metadata": {
                        "format": parameters["format"],
                        "duration_seconds": 12.5,
                        "resolution": {"width": 1920, "height": 1080},
                        "fps": 30.0,
                        "video_codec": "h264",
                        "audio_codec": "aac",
                    },
                }
            }
        }

    if tool_name == "extract_audio":
        video_content = _artifact_content(request, "video", b"")
        if isinstance(video_content, str):
            video_content = video_content.encode("utf-8")
        content = b"MOCK_AUDIO:" + video_content[:32]
        return {
            "outputs": {
                "audio": {
                    "type": "audio",
                    "content": content,
                    "metadata": {
                        "format": parameters["format"],
                        "duration_seconds": 12.5,
                        "sample_rate": parameters["sample_rate"],
                        "channels": parameters["channels"],
                        "codec": "mock-aac",
                    },
                }
            }
        }

    if tool_name == "transcribe":
        _artifact_content(request, "audio", b"")
        segments = [
            {
                "start": 0.0,
                "end": 2.4,
                "text": "Open BBQ demo transcript",
                "confidence": 0.98,
                "words": [
                    {"start": 0.0, "end": 0.5, "text": "Open", "confidence": 0.99},
                    {"start": 0.5, "end": 1.0, "text": "BBQ", "confidence": 0.99},
                    {"start": 1.0, "end": 1.8, "text": "demo", "confidence": 0.97},
                    {"start": 1.8, "end": 2.4, "text": "transcript", "confidence": 0.96},
                ],
            }
        ]
        return {
            "outputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": segments,
                    "metadata": {
                        "language": parameters["language"],
                        "model": parameters["model"],
                        "segment_count": len(segments),
                        "word_count": sum(len(segment.get("words", [])) for segment in segments),
                    },
                }
            }
        }

    raise ValueError(f"Unsupported tool: {tool_name}")
