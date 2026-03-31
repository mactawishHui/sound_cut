from __future__ import annotations

import wave

import pytest

from sound_cut.models import EditDecisionList, EditOperation, RenderPlan, SourceMedia, TimeRange
from sound_cut.render import render_audio_from_edl
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def _wave_duration_s(path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


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

    output_duration_s = _wave_duration_s(output_path)

    assert output_duration_s == pytest.approx(1.0, abs=1e-9)
    assert summary.output_duration_s == pytest.approx(output_duration_s, abs=1e-9)
    assert summary.kept_segment_count == 2
    assert summary.removed_duration_s == pytest.approx(summary.input_duration_s - summary.output_duration_s, abs=1e-9)


def test_render_audio_from_edl_handles_empty_keep_set(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    samples = tone_samples(sample_rate_hz=16_000, duration_s=1.0)
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=samples)
    source = SourceMedia(
        input_path=input_path,
        duration_s=1.0,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        has_video=False,
    )
    plan = RenderPlan(
        source=source,
        edl=EditDecisionList(operations=()),
        output_path=output_path,
        target="audio",
        crossfade_ms=10,
    )

    summary = render_audio_from_edl(plan)

    with wave.open(str(output_path), "rb") as handle:
        assert handle.getnframes() == 0
        assert handle.getframerate() == 16_000
        assert handle.getnchannels() == 1

    assert summary.kept_segment_count == 0
    assert summary.output_duration_s == 0.0
    assert summary.removed_duration_s == pytest.approx(1.0, abs=1e-9)


def test_render_audio_from_edl_preserves_submillisecond_boundaries(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    sample_rate_hz = 48_000
    samples = (
        tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.75)
        + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.50)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.75)
    )
    write_pcm_wave(input_path, sample_rate_hz=sample_rate_hz, samples=samples)
    source = SourceMedia(
        input_path=input_path,
        duration_s=2.0,
        audio_codec="pcm_s16le",
        sample_rate_hz=sample_rate_hz,
        channels=1,
        has_video=False,
    )
    edl = EditDecisionList(
        operations=(
            EditOperation("keep", TimeRange(0.1234, 0.4567), "speech"),
            EditOperation("keep", TimeRange(1.2345, 1.7891), "speech"),
        )
    )
    plan = RenderPlan(source=source, edl=edl, output_path=output_path, target="audio", crossfade_ms=9)

    summary = render_audio_from_edl(plan)
    output_duration_s = _wave_duration_s(output_path)

    assert output_duration_s == pytest.approx(summary.output_duration_s, abs=1e-9)
    assert summary.kept_segment_count == 2
    assert summary.removed_duration_s == pytest.approx(summary.input_duration_s - summary.output_duration_s, abs=1e-9)
