from __future__ import annotations

import wave

from sound_cut.models import EditDecisionList, EditOperation, RenderPlan, SourceMedia, TimeRange
from sound_cut.render import render_audio_from_edl
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def test_render_audio_from_edl_keeps_only_requested_ranges(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    samples = (
        tone_samples(sample_rate_hz=16_000, duration_s=0.5)
        + silence_samples(sample_rate_hz=16_000, duration_s=0.5)
        + tone_samples(sample_rate_hz=16_000, duration_s=0.5)
    )
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=samples)
    source = SourceMedia(
        input_path=input_path,
        duration_s=1.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        has_video=False,
    )
    edl = EditDecisionList(
        operations=(
            EditOperation("keep", TimeRange(0.0, 0.5), "speech"),
            EditOperation("keep", TimeRange(1.0, 1.5), "speech"),
        )
    )
    plan = RenderPlan(source=source, edl=edl, output_path=output_path, target="audio", crossfade_ms=10)

    summary = render_audio_from_edl(plan)

    with wave.open(str(output_path), "rb") as handle:
        output_duration_s = round(handle.getnframes() / handle.getframerate(), 2)

    assert output_duration_s == 1.00
    assert summary.kept_segment_count == 2
    assert summary.removed_duration_s == 0.50
