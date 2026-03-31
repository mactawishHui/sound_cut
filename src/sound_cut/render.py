from __future__ import annotations

import tempfile
from pathlib import Path

from sound_cut.ffmpeg_tools import _require_binary, _run
from sound_cut.models import RenderPlan, RenderSummary
from sound_cut.timeline import kept_ranges


def _format_seconds(value: float) -> str:
    return f"{value:.3f}"


def render_audio_from_edl(plan: RenderPlan) -> RenderSummary:
    ffmpeg = _require_binary("ffmpeg")
    input_path = plan.source.input_path
    output_path = plan.output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ranges = kept_ranges(plan.edl)
    fade_seconds = max(plan.crossfade_ms / 1000, 0.0)
    kept_duration_s = sum(item.duration_s for item in ranges)

    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
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
                "-ss",
                _format_seconds(item.start_s),
                "-t",
                _format_seconds(item.duration_s),
            ]

            filters: list[str] = []
            if fade_seconds > 0 and item.duration_s > fade_seconds * 2:
                filters.append(f"afade=t=in:st=0:d={_format_seconds(fade_seconds)}")
                filters.append(
                    f"afade=t=out:st={_format_seconds(item.duration_s - fade_seconds)}:d={_format_seconds(fade_seconds)}"
                )
            if filters:
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

        concat_list = temp_dir / "segments.txt"
        concat_list.write_text(
            "".join(f"file '{path.as_posix()}'\n" for path in segment_paths),
            encoding="utf-8",
        )

        _run(
            [
                ffmpeg,
                "-y",
                "-nostats",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(output_path),
            ]
        )

    return RenderSummary(
        input_duration_s=round(plan.source.duration_s, 3),
        output_duration_s=round(kept_duration_s, 3),
        removed_duration_s=round(max(0.0, plan.source.duration_s - kept_duration_s), 3),
        kept_segment_count=len(ranges),
    )
