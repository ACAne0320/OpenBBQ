from __future__ import annotations

from pathlib import Path
import subprocess


def run(request: dict, runner=None, duration_probe=None, progress=None) -> dict:
    if request.get("tool_name") != "extract_audio":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    runner = _run_subprocess if runner is None else runner
    video = request.get("inputs", {}).get("video", {})
    video_path = video.get("file_path")
    video_file = Path(video_path) if isinstance(video_path, str) else None
    if video_file is None or not video_file.is_file():
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
    if progress is None:
        runner(command)
    else:
        duration_probe = _probe_duration_seconds if duration_probe is None else duration_probe
        duration_seconds = float(duration_probe(video_file) or 0)
        _report(
            progress,
            phase="extract_audio",
            label="Extract audio",
            percent=0,
            current=0,
            total=duration_seconds,
            unit="seconds",
        )
        runner(
            command,
            on_progress=lambda seconds: _report(
                progress,
                phase="extract_audio",
                label="Extract audio",
                percent=(seconds / duration_seconds) * 100 if duration_seconds > 0 else 0,
                current=seconds,
                total=duration_seconds,
                unit="seconds",
            ),
        )
        _report(
            progress,
            phase="extract_audio",
            label="Extract audio",
            percent=100,
            current=duration_seconds,
            total=duration_seconds,
            unit="seconds",
        )
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
    if progress is not None:
        progress(
            phase=phase,
            label=label,
            percent=percent,
            current=current,
            total=total,
            unit=unit,
        )


def _probe_duration_seconds(path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe binary was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr.strip()}") from exc
    try:
        return float(completed.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("ffprobe did not return a valid duration.") from exc


def _run_subprocess(command: list[str], on_progress=None) -> None:
    if on_progress is not None:
        _run_subprocess_with_progress(command, on_progress=on_progress)
        return
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg binary was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed: {exc.stderr.strip()}") from exc


def _run_subprocess_with_progress(command: list[str], *, on_progress) -> None:
    progress_command = [*command[:-1], "-progress", "pipe:1", "-nostats", command[-1]]
    try:
        process = subprocess.Popen(
            progress_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg binary was not found on PATH.") from exc
    output_lines: list[str] = []
    if process.stdout is not None:
        for line in process.stdout:
            output_lines.append(line)
            seconds = _progress_seconds(line)
            if seconds is not None:
                on_progress(seconds)
    return_code = process.wait()
    if return_code != 0:
        output = "".join(output_lines).strip()
        raise RuntimeError(f"ffmpeg failed: {output}")


def _progress_seconds(line: str) -> float | None:
    key, separator, value = line.strip().partition("=")
    if not separator:
        return None
    if key in {"out_time_ms", "out_time_us"}:
        try:
            return max(int(value) / 1_000_000, 0.0)
        except ValueError:
            return None
    if key == "out_time":
        return _parse_ffmpeg_time(value)
    return None


def _parse_ffmpeg_time(value: str) -> float | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None
    return max((hours * 3600) + (minutes * 60) + seconds, 0.0)
