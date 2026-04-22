from __future__ import annotations

from pathlib import Path
from typing import Any


def run(request: dict, model_factory=None) -> dict:
    if request.get("tool_name") != "transcribe":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    audio = request.get("inputs", {}).get("audio", {})
    audio_path = audio.get("file_path")
    if not isinstance(audio_path, str) or not Path(audio_path).is_file():
        raise ValueError("faster_whisper.transcribe requires a file-backed audio input.")
    parameters = request.get("parameters", {})
    model_name = parameters.get("model", "base")
    device = parameters.get("device", "cpu")
    compute_type = parameters.get("compute_type", "int8")
    word_timestamps = bool(parameters.get("word_timestamps", True))
    vad_filter = bool(parameters.get("vad_filter", False))
    language = parameters.get("language")
    model_factory = _default_model_factory if model_factory is None else model_factory
    model = model_factory(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=word_timestamps,
        vad_filter=vad_filter,
    )
    content = [_segment_payload(segment, include_words=word_timestamps) for segment in segments]
    return {
        "outputs": {
            "transcript": {
                "type": "asr_transcript",
                "content": content,
                "metadata": {
                    "model": model_name,
                    "device": device,
                    "compute_type": compute_type,
                    "language": getattr(info, "language", language),
                    "duration_seconds": getattr(info, "duration", None),
                },
            }
        }
    }


def _default_model_factory(model_name: str, *, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Install OpenBBQ with the media optional dependencies."
        ) from exc
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _segment_payload(segment: Any, *, include_words: bool) -> dict[str, Any]:
    payload = {
        "start": float(segment.start),
        "end": float(segment.end),
        "text": str(segment.text).strip(),
        "confidence": getattr(segment, "avg_logprob", None),
    }
    if include_words:
        words = getattr(segment, "words", None) or []
        payload["words"] = [
            {
                "start": float(word.start),
                "end": float(word.end),
                "text": str(word.word).strip(),
                "confidence": getattr(word, "probability", None),
            }
            for word in words
        ]
    return payload
