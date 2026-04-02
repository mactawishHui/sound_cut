from __future__ import annotations

import math
import struct
import wave
from types import SimpleNamespace

import pytest

from sound_cut.core import EditDecisionList, EditOperation, RenderPlan, SourceMedia, TimeRange
from sound_cut.media import export_delivery_audio, probe_source_media, render_audio_from_edl
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def _wave_duration_s(path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def _window_rms(path, *, start_s: float, duration_s: float, channel_index: int = 0) -> float:
    with wave.open(str(path), "rb") as handle:
        sample_rate_hz = handle.getframerate()
        channels = handle.getnchannels()
        start_frame = int(start_s * sample_rate_hz)
        frame_count = int(duration_s * sample_rate_hz)
        handle.setpos(start_frame)
        raw = handle.readframes(frame_count)

    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    channel_samples = samples[channel_index::channels]
    return math.sqrt(sum(sample * sample for sample in channel_samples) / len(channel_samples))


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


@pytest.mark.parametrize(
    ("suffix", "expected_codec"),
    [
        (".mp3", "mp3"),
        (".m4a", "aac"),
    ],
)
def test_render_audio_from_edl_writes_probeable_compressed_output_for_empty_keep_set(
    tmp_path, ffmpeg_available, suffix: str, expected_codec: str
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / f"output{suffix}"
    write_pcm_wave(
        input_path,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=1.0),
    )
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
    output_media = probe_source_media(output_path)

    assert output_path.exists()
    assert output_media.audio_codec == expected_codec
    assert output_media.duration_s > 0.0
    assert summary.kept_segment_count == 0
    assert summary.output_duration_s == pytest.approx(output_media.duration_s, abs=1e-6)
    assert summary.output_duration_s > 0.0
    assert summary.removed_duration_s == pytest.approx(summary.input_duration_s - summary.output_duration_s, abs=1e-9)


@pytest.mark.parametrize(
    ("suffix", "expected_codec"),
    [
        (".mp3", "mp3"),
        (".m4a", "aac"),
    ],
)
def test_render_audio_from_edl_writes_delivery_format_output(
    tmp_path, ffmpeg_available, suffix: str, expected_codec: str
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / f"output{suffix}"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    source = SourceMedia(
        input_path=input_path,
        duration_s=0.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        has_video=False,
    )
    plan = RenderPlan(
        source=source,
        edl=EditDecisionList(operations=(EditOperation("keep", TimeRange(0.0, 0.5), "speech"),)),
        output_path=output_path,
        target="audio",
        crossfade_ms=10,
    )

    summary = render_audio_from_edl(plan)

    output_media = probe_source_media(output_path)

    assert output_path.exists()
    assert output_media.audio_codec == expected_codec
    assert summary.output_duration_s == pytest.approx(output_media.duration_s, abs=1e-6)
    assert summary.output_duration_s == pytest.approx(source.duration_s, abs=0.1)


def test_render_audio_from_edl_passes_source_media_to_delivery_export(monkeypatch, tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.mp3"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    source = SourceMedia(
        input_path=input_path,
        duration_s=0.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        bit_rate_bps=64_000,
        has_video=False,
    )
    plan = RenderPlan(
        source=source,
        edl=EditDecisionList(operations=(EditOperation("keep", TimeRange(0.0, 0.5), "speech"),)),
        output_path=output_path,
        target="audio",
        crossfade_ms=10,
    )
    recorded_calls: list[tuple[object, object, object]] = []

    monkeypatch.setattr(
        "sound_cut.media.render.export_delivery_audio",
        lambda source_wav, delivered_path, received_source: recorded_calls.append(
            (source_wav, delivered_path, received_source)
        ),
    )
    monkeypatch.setattr(
        "sound_cut.media.render.probe_source_media",
        lambda path: SimpleNamespace(duration_s=source.duration_s),
    )

    render_audio_from_edl(plan)

    assert recorded_calls and recorded_calls[0][2] is source


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


def test_render_audio_from_edl_preserves_audio_near_end_of_stereo_multi_segment_output(
    tmp_path, ffmpeg_available
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    sample_rate_hz = 48_000
    speech_durations = (1.6, 0.7, 2.1, 1.0, 3.2, 0.9, 1.4)
    silence_durations = (0.4, 0.9, 0.5, 1.2, 0.6, 0.8)

    mono_samples: list[int] = []
    position_s = 0.0
    operations: list[EditOperation] = []
    for index, speech_duration_s in enumerate(speech_durations):
        mono_samples.extend(
            tone_samples(
                sample_rate_hz=sample_rate_hz,
                duration_s=speech_duration_s,
                frequency_hz=220 + index * 30,
            )
        )
        operations.append(
            EditOperation(
                "keep",
                TimeRange(position_s, position_s + speech_duration_s),
                "speech",
            )
        )
        position_s += speech_duration_s
        if index < len(silence_durations):
            silence_duration_s = silence_durations[index]
            mono_samples.extend(
                silence_samples(sample_rate_hz=sample_rate_hz, duration_s=silence_duration_s)
            )
            position_s += silence_duration_s

    stereo_samples: list[int] = []
    for sample in mono_samples:
        stereo_samples.extend((sample, sample))
    write_pcm_wave(input_path, sample_rate_hz=sample_rate_hz, samples=stereo_samples, channels=2)

    plan = RenderPlan(
        source=SourceMedia(
            input_path=input_path,
            duration_s=position_s,
            audio_codec="pcm_s16le",
            sample_rate_hz=sample_rate_hz,
            channels=2,
            has_video=False,
        ),
        edl=EditDecisionList(operations=tuple(operations)),
        output_path=output_path,
        target="audio",
        crossfade_ms=10,
    )

    summary = render_audio_from_edl(plan)

    assert summary.kept_segment_count == len(speech_durations)
    assert _window_rms(output_path, start_s=summary.output_duration_s - 0.5, duration_s=0.5) > 100.0


def test_render_audio_from_edl_keeps_short_range_from_mp3_input(tmp_path, ffmpeg_available) -> None:
    source_wav_path = tmp_path / "source.wav"
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.wav"
    sample_rate_hz = 48_000
    keep_start_s = 0.2
    keep_end_s = 0.25
    write_pcm_wave(
        source_wav_path,
        sample_rate_hz=sample_rate_hz,
        samples=(
            silence_samples(sample_rate_hz=sample_rate_hz, duration_s=keep_start_s)
            + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=keep_end_s - keep_start_s, frequency_hz=660)
            + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.75)
        ),
    )
    export_delivery_audio(
        source_wav_path,
        input_path,
        SourceMedia(
            input_path=source_wav_path,
            duration_s=1.0,
            audio_codec="pcm_s16le",
            sample_rate_hz=sample_rate_hz,
            channels=1,
            bit_rate_bps=128_000,
            has_video=False,
        ),
    )

    plan = RenderPlan(
        source=SourceMedia(
            input_path=input_path,
            duration_s=1.0,
            audio_codec="mp3",
            sample_rate_hz=sample_rate_hz,
            channels=1,
            has_video=False,
        ),
        edl=EditDecisionList(
            operations=(EditOperation("keep", TimeRange(keep_start_s, keep_end_s), "speech"),)
        ),
        output_path=output_path,
        target="audio",
        crossfade_ms=0,
    )

    summary = render_audio_from_edl(plan)

    assert summary.output_duration_s == pytest.approx(keep_end_s - keep_start_s, abs=1e-3)
    assert _window_rms(output_path, start_s=0.0, duration_s=summary.output_duration_s) > 1000.0
