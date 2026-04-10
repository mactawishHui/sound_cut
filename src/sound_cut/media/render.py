from __future__ import annotations

import shutil
import tempfile
import wave
from pathlib import Path

from sound_cut.core.errors import MediaError
from sound_cut.core.models import (
    EditDecisionList,
    LoudnessNormalizationConfig,
    RenderPlan,
    RenderSummary,
    SourceMedia,
)
from sound_cut.editing.timeline import kept_ranges
from sound_cut.media.ffmpeg_tools import (
    _require_binary,
    _run,
    export_delivery_audio,
    normalize_loudness,
    probe_source_media,
)


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


def _resolve_wav_duration_s(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / handle.getframerate()
    except (OSError, EOFError, wave.Error):
        return probe_source_media(path).duration_s


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


def _render_full_internal_wave(source: SourceMedia, output_path: Path) -> None:
    ffmpeg = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(source.input_path),
        "-vn",
        "-c:a",
        "pcm_s16le",
    ]
    if source.sample_rate_hz is not None:
        command.extend(["-ar", str(source.sample_rate_hz)])
    if source.channels is not None:
        command.extend(["-ac", str(source.channels)])
    command.extend(
        [
            "-f",
            "wav",
            str(output_path),
        ]
    )
    _run(command)


def _render_internal_video(source: SourceMedia, edl: EditDecisionList, output_path: Path) -> None:
    ranges = kept_ranges(edl)
    if not ranges:
        raise MediaError("Cannot render video with empty keep ranges")

    ffmpeg = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_steps: list[str] = []
    concat_inputs: list[str] = []
    for index, item in enumerate(ranges):
        label = f"v{index}"
        filter_steps.append(
            f"[0:v]trim=start={_format_seconds(item.start_s)}:end={_format_seconds(item.end_s)},setpts=PTS-STARTPTS[{label}]"
        )
        concat_inputs.append(f"[{label}]")
    filter_steps.append(
        "".join(concat_inputs) + f"concat=n={len(ranges)}:v=1:a=0[vout]"
    )

    _run(
        [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(source.input_path),
            "-filter_complex",
            ";".join(filter_steps),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def _mux_audio_with_video(video_path: Path, audio_path: Path, output_path: Path, *, copy_video: bool) -> None:
    ffmpeg = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy" if copy_video else "libx264",
        "-c:a",
        "copy",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run(command)


def render_video_from_edl(*, video_source: SourceMedia, audio_plan: RenderPlan) -> RenderSummary:
    output_path = audio_plan.output_path
    with tempfile.TemporaryDirectory(prefix="sound-cut-video-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_audio_path = temp_dir / "audio.render.wav"
        kept_segment_count = _render_internal_wave(
            audio_plan,
            internal_audio_path,
            force_nonempty=True,
        )
        delivery_audio_input = internal_audio_path
        if audio_plan.loudness.enabled and kept_segment_count > 0:
            delivery_audio_input = temp_dir / "audio.normalized.wav"
            normalize_loudness(
                internal_audio_path,
                delivery_audio_input,
                target_lufs=audio_plan.loudness.target_lufs,
            )
        delivery_audio_path = temp_dir / "audio.track.m4a"
        export_delivery_audio(delivery_audio_input, delivery_audio_path, audio_plan.source)

        cut_video_path = temp_dir / "video.cut.mp4"
        _render_internal_video(video_source, audio_plan.edl, cut_video_path)
        _mux_audio_with_video(cut_video_path, delivery_audio_path, output_path, copy_video=True)

    output_duration_s = probe_source_media(output_path).duration_s
    return RenderSummary(
        input_duration_s=video_source.duration_s,
        output_duration_s=output_duration_s,
        removed_duration_s=max(0.0, video_source.duration_s - output_duration_s),
        kept_segment_count=kept_segment_count,
    )


def render_full_video(
    *, video_source: SourceMedia, audio_source: SourceMedia, output_path: Path, loudness: LoudnessNormalizationConfig
) -> RenderSummary:
    with tempfile.TemporaryDirectory(prefix="sound-cut-video-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_audio_path = temp_dir / "audio.render.wav"
        _render_full_internal_wave(audio_source, internal_audio_path)

        delivery_audio_input = internal_audio_path
        if loudness.enabled:
            delivery_audio_input = temp_dir / "audio.normalized.wav"
            normalize_loudness(
                internal_audio_path,
                delivery_audio_input,
                target_lufs=loudness.target_lufs,
            )

        delivery_audio_path = temp_dir / "audio.track.m4a"
        export_delivery_audio(delivery_audio_input, delivery_audio_path, audio_source)
        _mux_audio_with_video(video_source.input_path, delivery_audio_path, output_path, copy_video=True)

    output_duration_s = probe_source_media(output_path).duration_s
    return RenderSummary(
        input_duration_s=video_source.duration_s,
        output_duration_s=output_duration_s,
        removed_duration_s=max(0.0, video_source.duration_s - output_duration_s),
        kept_segment_count=1,
    )


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
        delivery_input_path = internal_output_path
        if plan.loudness.enabled and kept_segment_count > 0:
            delivery_input_path = temp_dir / "normalized.wav"
            normalize_loudness(
                internal_output_path,
                delivery_input_path,
                target_lufs=plan.loudness.target_lufs,
            )
        export_delivery_audio(delivery_input_path, output_path, plan.source)

    if kept_segment_count == 0 and delivery_suffix == ".wav":
        output_duration_s = 0.0
    elif delivery_suffix == ".wav":
        output_duration_s = _resolve_wav_duration_s(output_path)
    else:
        output_duration_s = probe_source_media(output_path).duration_s
    return RenderSummary(
        input_duration_s=plan.source.duration_s,
        output_duration_s=output_duration_s,
        removed_duration_s=max(0.0, plan.source.duration_s - output_duration_s),
        kept_segment_count=kept_segment_count,
    )


def render_full_audio(
    *, source: SourceMedia, output_path: Path, loudness: LoudnessNormalizationConfig
) -> RenderSummary:
    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_output_path = temp_dir / "render.wav"
        _render_full_internal_wave(source, internal_output_path)
        delivery_input_path = internal_output_path
        if loudness.enabled:
            delivery_input_path = temp_dir / "normalized.wav"
            normalize_loudness(
                internal_output_path,
                delivery_input_path,
                target_lufs=loudness.target_lufs,
            )
        export_delivery_audio(delivery_input_path, output_path, source)

    if output_path.suffix.lower() == ".wav":
        output_duration_s = _resolve_wav_duration_s(output_path)
    else:
        output_duration_s = probe_source_media(output_path).duration_s
    return RenderSummary(
        input_duration_s=source.duration_s,
        output_duration_s=output_duration_s,
        removed_duration_s=0.0,
        kept_segment_count=1,
    )
