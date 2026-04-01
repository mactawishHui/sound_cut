from __future__ import annotations

import shutil
import tempfile
import wave
from pathlib import Path

from sound_cut.ffmpeg_tools import _require_binary, _run, export_delivery_audio, probe_source_media
from sound_cut.models import RenderPlan, RenderSummary
from sound_cut.timeline import kept_ranges


def _format_seconds(value: float) -> str:
    return f"{value:.9f}"


def _write_empty_wave(path: Path, *, sample_rate_hz: int, channels: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)


def _write_tiny_silent_wave(path: Path, *, sample_rate_hz: int, channels: int, frames: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(b"\x00\x00" * frames * channels)


def _wave_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def _render_internal_wave(plan: RenderPlan, output_path: Path, *, force_nonempty: bool = False) -> int:
    ffmpeg = _require_binary("ffmpeg")
    input_path = plan.source.input_path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    ranges = kept_ranges(plan.edl)
    fade_seconds = max(plan.crossfade_ms / 1000, 0.0)

    if not ranges:
        if force_nonempty:
            _write_tiny_silent_wave(
                output_path,
                sample_rate_hz=plan.source.sample_rate_hz or 44_100,
                channels=plan.source.channels or 1,
            )
        else:
            _write_empty_wave(
                output_path,
                sample_rate_hz=plan.source.sample_rate_hz or 44_100,
                channels=plan.source.channels or 1,
            )
        return 0

    with tempfile.TemporaryDirectory(prefix="sound-cut-render-segments-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        segment_paths: list[Path] = []

        for index, item in enumerate(ranges):
            segment_path = temp_dir / f"segment-{index:03d}.wav"
            segment_paths.append(segment_path)

            command = [
                ffmpeg,
                "-y",
                "-nostats",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-vn",
            ]

            filters: list[str] = [
                f"atrim=start={_format_seconds(item.start_s)}:end={_format_seconds(item.end_s)}",
                "asetpts=PTS-STARTPTS",
            ]
            if fade_seconds > 0 and item.duration_s > fade_seconds * 2:
                filters.append(f"afade=t=in:st=0:d={_format_seconds(fade_seconds)}")
                filters.append(
                    f"afade=t=out:st={_format_seconds(item.duration_s - fade_seconds)}:d={_format_seconds(fade_seconds)}"
                )
            command.extend(["-af", ",".join(filters)])

            command.extend(
                [
                    "-c:a",
                    "pcm_s16le",
                ]
            )
            if plan.source.sample_rate_hz is not None:
                command.extend(["-ar", str(plan.source.sample_rate_hz)])
            if plan.source.channels is not None:
                command.extend(["-ac", str(plan.source.channels)])
            command.append(str(segment_path))
            _run(command)

        if len(segment_paths) == 1:
            shutil.copyfile(segment_paths[0], output_path)
        else:
            command = [
                ffmpeg,
                "-y",
                "-nostats",
                "-loglevel",
                "error",
            ]
            for segment_path in segment_paths:
                command.extend(["-i", str(segment_path)])
            command.extend(
                [
                    "-filter_complex",
                    "".join(f"[{index}:a]" for index in range(len(segment_paths)))
                    + f"concat=n={len(segment_paths)}:v=0:a=1[out]",
                    "-map",
                    "[out]",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "wav",
                    "-ar",
                    str(plan.source.sample_rate_hz or 44_100),
                    "-ac",
                    str(plan.source.channels or 1),
                    str(output_path),
                ]
            )
            _run(command)

    return len(ranges)


def render_audio_from_edl(plan: RenderPlan) -> RenderSummary:
    output_path = plan.output_path

    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_output_path = temp_dir / "render.wav"
        delivery_suffix = output_path.suffix.lower()
        force_nonempty = delivery_suffix in {".mp3", ".m4a"}
        kept_segment_count = _render_internal_wave(
            plan,
            internal_output_path,
            force_nonempty=force_nonempty,
        )
        export_delivery_audio(internal_output_path, output_path, plan.source)

    if kept_segment_count == 0 and delivery_suffix == ".wav":
        output_duration_s = 0.0
    elif delivery_suffix == ".wav":
        output_duration_s = _wave_duration_s(output_path)
    else:
        output_duration_s = probe_source_media(output_path).duration_s
    return RenderSummary(
        input_duration_s=plan.source.duration_s,
        output_duration_s=output_duration_s,
        removed_duration_s=max(0.0, plan.source.duration_s - output_duration_s),
        kept_segment_count=kept_segment_count,
    )
