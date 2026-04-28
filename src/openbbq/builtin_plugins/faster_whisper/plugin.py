from __future__ import annotations

from pathlib import Path
from typing import Any


def run(request: dict, model_factory=None, progress=None) -> dict:
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
    initial_prompt = parameters.get("initial_prompt")
    hotwords = _optional_hotwords(parameters.get("hotwords"))
    condition_on_previous_text = parameters.get("condition_on_previous_text")
    chunk_length = parameters.get("chunk_length")
    hallucination_silence_threshold = parameters.get("hallucination_silence_threshold")
    vad_parameters = parameters.get("vad_parameters")
    download_root = _runtime_faster_whisper_cache(request)
    model_factory = _default_model_factory if model_factory is None else model_factory
    _report(progress, phase="asr_parse", label="ASR parsing", percent=0)
    model = model_factory(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )
    transcribe_kwargs: dict[str, Any] = {
        "language": language,
        "word_timestamps": word_timestamps,
        "vad_filter": vad_filter,
    }
    if initial_prompt is not None:
        transcribe_kwargs["initial_prompt"] = initial_prompt
    if hotwords is not None:
        transcribe_kwargs["hotwords"] = hotwords
    if condition_on_previous_text is not None:
        transcribe_kwargs["condition_on_previous_text"] = bool(condition_on_previous_text)
    if chunk_length is not None:
        transcribe_kwargs["chunk_length"] = int(chunk_length)
    if hallucination_silence_threshold is not None:
        transcribe_kwargs["hallucination_silence_threshold"] = float(
            hallucination_silence_threshold
        )
    if vad_parameters is not None:
        transcribe_kwargs["vad_parameters"] = vad_parameters
    segments, info = model.transcribe(
        audio_path,
        **transcribe_kwargs,
    )
    duration = float(getattr(info, "duration", 0) or 0)
    last_percent = 0.0
    content = []
    for segment in segments:
        content.append(_segment_payload(segment, include_words=word_timestamps))
        if duration > 0:
            current = min(float(segment.end), duration)
            last_percent = (current / duration) * 100
            _report(
                progress,
                phase="asr_parse",
                label="ASR parsing",
                percent=last_percent,
                current=current,
                total=duration,
                unit="seconds",
            )
    if last_percent < 100:
        _report(
            progress,
            phase="asr_parse",
            label="ASR parsing",
            percent=100,
            current=duration or None,
            total=duration or None,
            unit="seconds" if duration > 0 else None,
        )
    return {
        "outputs": {
            "transcript": {
                "type": "asr_transcript",
                "content": content,
                "metadata": {
                    "model": model_name,
                    "device": device,
                    "compute_type": compute_type,
                    "model_cache_dir": download_root,
                    "language": getattr(info, "language", language),
                    "duration_seconds": getattr(info, "duration", None),
                },
            }
        }
    }


def _report(
    progress,
    *,
    phase: str,
    label: str,
    percent: float,
    current=None,
    total=None,
    unit=None,
) -> None:
    if progress is None:
        return
    try:
        progress(
            phase=phase,
            label=label,
            percent=percent,
            current=current,
            total=total,
            unit=unit,
        )
    except Exception:
        return


def _default_model_factory(
    model_name: str,
    *,
    device: str,
    compute_type: str,
    download_root: str | None = None,
):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Install OpenBBQ with the media optional dependencies."
        ) from exc
    return WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=download_root,
    )


def _runtime_faster_whisper_cache(request: dict) -> str | None:
    runtime = request.get("runtime", {})
    if not isinstance(runtime, dict):
        return None
    cache = runtime.get("cache", {})
    if not isinstance(cache, dict):
        return None
    value = cache.get("faster_whisper")
    return value if isinstance(value, str) and value else None


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


def _optional_hotwords(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if not isinstance(value, list):
        raise ValueError("faster_whisper.transcribe parameter 'hotwords' must be a string list.")
    words: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                "faster_whisper.transcribe parameter 'hotwords' must be a string list."
            )
        words.append(item.strip())
    return ", ".join(words) if words else None
