from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from sound_cut.core.errors import DependencyError, MediaError
from sound_cut.core.models import SourceMedia

_MIN_DELIVERY_BIT_RATE_BPS = 64_000
_MAX_DELIVERY_BIT_RATE_BPS = 128_000


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


def _parse_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _estimate_bit_rate_bps(input_path: Path, *, duration_s: float) -> int | None:
    if duration_s <= 0:
        return None
    try:
        size_bytes = input_path.stat().st_size
    except OSError:
        return None
    return round(size_bytes * 8 / duration_s)


def _parse_source_media(payload: dict, *, input_path: Path) -> SourceMedia:
    streams = payload["streams"]
    format_data = payload["format"]
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    duration_s = float(format_data["duration"])
    if video_stream is not None:
        bit_rate_bps = _parse_int(audio_stream.get("bit_rate"))
    else:
        bit_rate_bps = _parse_int(format_data.get("bit_rate"))
        if bit_rate_bps is None:
            bit_rate_bps = _parse_int(audio_stream.get("bit_rate"))
        if bit_rate_bps is None:
            bit_rate_bps = _estimate_bit_rate_bps(input_path, duration_s=duration_s)
    return SourceMedia(
        input_path=input_path,
        duration_s=duration_s,
        audio_codec=audio_stream.get("codec_name"),
        sample_rate_hz=_parse_int(audio_stream.get("sample_rate")),
        channels=_parse_int(audio_stream.get("channels")),
        bit_rate_bps=bit_rate_bps,
        has_video=video_stream is not None,
    )


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
        return _parse_source_media(payload, input_path=input_path)
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


def normalize_loudness(source_wav: Path, output_wav: Path, *, target_lufs: float) -> None:
    ffmpeg = _require_binary("ffmpeg")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    sample_rate_hz: int | None = None
    channels: int | None = None
    try:
        source_media = probe_source_media(source_wav)
        sample_rate_hz = source_media.sample_rate_hz
        channels = source_media.channels
    except (DependencyError, MediaError):
        pass

    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(source_wav),
        "-vn",
        "-af",
        f"loudnorm=I={target_lufs}",
        "-c:a",
        "pcm_s16le",
    ]
    if sample_rate_hz is not None:
        command.extend(["-ar", str(sample_rate_hz)])
    if channels is not None:
        command.extend(["-ac", str(channels)])
    command.extend(
        [
            "-f",
            "wav",
            str(output_wav),
        ]
    )
    _run(
        command
    )


def _subtitle_codec_for_suffix(suffix: str) -> str:
    mapping = {
        ".mp4": "mov_text",
        ".mov": "mov_text",
        ".m4v": "mov_text",
        ".mkv": "srt",
    }
    try:
        return mapping[suffix.lower()]
    except KeyError as exc:
        raise MediaError(f"Unsupported video container for subtitle embedding: {suffix}") from exc


def delivery_codec_for_suffix(suffix: str) -> tuple[str, str | None]:
    mapping = {
        ".mp3": ("libmp3lame", "128k"),
        ".m4a": ("aac", "128k"),
        ".wav": ("pcm_s16le", None),
    }
    try:
        return mapping[suffix.lower()]
    except KeyError as exc:
        raise MediaError(f"Unsupported output format: {suffix}") from exc


def resolve_delivery_bitrate_bps(source: SourceMedia, suffix: str) -> int | None:
    suffix = suffix.lower()
    if suffix == ".wav":
        return None
    if suffix not in {".mp3", ".m4a"}:
        raise MediaError(f"Unsupported output format: {suffix}")
    if source.bit_rate_bps is None:
        return _MAX_DELIVERY_BIT_RATE_BPS
    return min(
        max(source.bit_rate_bps, _MIN_DELIVERY_BIT_RATE_BPS),
        _MAX_DELIVERY_BIT_RATE_BPS,
    )


def export_delivery_audio(source_wav: Path, output_path: Path, source: SourceMedia) -> None:
    ffmpeg = _require_binary("ffmpeg")
    codec_name, _ = delivery_codec_for_suffix(output_path.suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(source_wav),
        "-c:a",
        codec_name,
    ]
    audio_bitrate_bps = resolve_delivery_bitrate_bps(source, output_path.suffix)
    if audio_bitrate_bps is not None:
        command.extend(["-b:a", str(audio_bitrate_bps)])
    if output_path.suffix.lower() == ".m4a":
        command.extend(["-f", "ipod"])
    elif output_path.suffix.lower() == ".wav":
        command.extend(["-f", "wav"])
    command.append(str(output_path))
    _run(command)


def embed_subtitle_track(video_path: Path, srt_path: Path, output_path: Path) -> None:
    ffmpeg = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subtitle_codec = _subtitle_codec_for_suffix(output_path.suffix)
    _run(
        [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(srt_path),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            subtitle_codec,
            "-map",
            "0:v",
            "-map",
            "0:a",
            "-map",
            "1:s",
            str(output_path),
        ]
    )
