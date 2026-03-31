from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from sound_cut.errors import DependencyError, MediaError
from sound_cut.models import SourceMedia


def _require_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise DependencyError(f"Required dependency '{name}' is not installed or not on PATH")
    return binary


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or "ffmpeg command failed"
        raise MediaError(message) from exc


def probe_source_media(input_path: Path) -> SourceMedia:
    ffprobe = _require_binary("ffprobe")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(input_path),
        ]
    )
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        format_data = payload["format"]
        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        return SourceMedia(
            input_path=input_path,
            duration_s=float(format_data["duration"]),
            audio_codec=audio_stream.get("codec_name"),
            sample_rate_hz=int(audio_stream["sample_rate"]) if audio_stream.get("sample_rate") else None,
            channels=audio_stream.get("channels"),
            has_video=video_stream is not None,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MediaError(f"Invalid ffprobe JSON for {input_path}") from exc


def normalize_audio_for_analysis(input_path: Path, output_path: Path, *, sample_rate_hz: int) -> None:
    ffmpeg = _require_binary("ffmpeg")
    _run(
        [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate_hz),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(output_path),
        ]
    )
