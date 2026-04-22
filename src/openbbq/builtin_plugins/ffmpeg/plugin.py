from __future__ import annotations

from pathlib import Path
import subprocess


def run(request: dict, runner=None) -> dict:
    if request.get("tool_name") != "extract_audio":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    runner = _run_subprocess if runner is None else runner
    video = request.get("inputs", {}).get("video", {})
    video_path = video.get("file_path")
    if not isinstance(video_path, str) or not Path(video_path).is_file():
        raise ValueError("ffmpeg.extract_audio requires a file-backed video input.")
    parameters = request.get("parameters", {})
    audio_format = parameters.get("format", "wav")
    sample_rate = int(parameters.get("sample_rate", 16000))
    channels = int(parameters.get("channels", 1))
    if audio_format != "wav":
        raise ValueError("ffmpeg.extract_audio currently supports wav output only.")
    output_path = Path(request["work_dir"]) / "audio.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        str(output_path),
    ]
    runner(command)
    return {
        "outputs": {
            "audio": {
                "type": "audio",
                "file_path": str(output_path),
                "metadata": {
                    "format": audio_format,
                    "sample_rate": sample_rate,
                    "channels": channels,
                },
            }
        }
    }


def _run_subprocess(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg binary was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed: {exc.stderr.strip()}") from exc
