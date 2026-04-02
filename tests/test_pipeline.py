from __future__ import annotations

from dataclasses import replace
import json
import math
import re
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from sound_cut.core import AnalysisTrack, MediaError, RenderSummary, TimeRange, build_profile
from sound_cut.core.models import DEFAULT_TARGET_LUFS, LoudnessNormalizationConfig
from sound_cut.editing.pipeline import process_audio
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


class FakeSpeechAnalyzer:
    def __init__(self, ranges: tuple[TimeRange, ...]) -> None:
        self._ranges = ranges
        self.calls: list[Path] = []

    def analyze(self, wav_path: Path) -> AnalysisTrack:
        self.calls.append(wav_path)
        return AnalysisTrack(name="speech", ranges=self._ranges)


class FalseySpeechAnalyzer(FakeSpeechAnalyzer):
    def __bool__(self) -> bool:
        return False


def _fake_render_audio_from_edl(plan) -> RenderSummary:
    return RenderSummary(
        input_duration_s=plan.source.duration_s,
        output_duration_s=plan.source.duration_s,
        removed_duration_s=0.0,
        kept_segment_count=sum(1 for operation in plan.edl.operations if operation.action == "keep"),
    )


def _wave_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def _window_rms(path: Path, *, start_s: float, duration_s: float, channel_index: int = 0) -> float:
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


def _integrated_lufs(path: Path, *, target_lufs: float = -16.0) -> float:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"loudnorm=I={target_lufs}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"\{\s*\"input_i\".*?\}", completed.stderr, re.DOTALL)
    if match is None:
        raise AssertionError(f"Could not parse ffmpeg loudnorm output for {path}:\n{completed.stderr}")

    stats = json.loads(match.group(0))
    return float(stats["input_i"])


def test_process_audio_writes_output_and_returns_summary(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    samples = (
        tone_samples(sample_rate_hz=48_000, duration_s=0.40)
        + silence_samples(sample_rate_hz=48_000, duration_s=0.20)
        + tone_samples(sample_rate_hz=48_000, duration_s=0.40)
    )
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=samples)
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.4), TimeRange(0.6, 1.0)))
    profile = replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=profile,
        analyzer=analyzer,
    )

    assert output_path.exists()
    assert analyzer.calls
    assert analyzer.calls[0].suffix == ".wav"
    assert analyzer.calls[0] != input_path
    assert summary.input_duration_s == pytest.approx(1.0, abs=1e-9)
    assert summary.output_duration_s == pytest.approx(_wave_duration_s(output_path), abs=1e-9)
    assert summary.kept_segment_count == 2
    assert summary.removed_duration_s == pytest.approx(
        summary.input_duration_s - summary.output_duration_s,
        abs=1e-9,
    )


def test_process_audio_refines_dense_profile_speech_ranges(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=16_000,
        samples=(
            tone_samples(sample_rate_hz=16_000, duration_s=0.60)
            + silence_samples(sample_rate_hz=16_000, duration_s=0.30)
            + tone_samples(sample_rate_hz=16_000, duration_s=0.60)
        ),
    )
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 1.50),))
    profile = replace(build_profile("dense"), merge_gap_ms=0, min_silence_ms=150, padding_ms=0)

    monkeypatch.setattr("sound_cut.editing.pipeline.render_audio_from_edl", _fake_render_audio_from_edl)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=profile,
        analyzer=analyzer,
    )

    assert summary.kept_segment_count == 2


def test_process_audio_does_not_refine_balanced_profile_speech_ranges(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=16_000,
        samples=(
            tone_samples(sample_rate_hz=16_000, duration_s=0.60)
            + silence_samples(sample_rate_hz=16_000, duration_s=0.30)
            + tone_samples(sample_rate_hz=16_000, duration_s=0.60)
        ),
    )
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 1.50),))
    profile = replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=150, padding_ms=0)

    monkeypatch.setattr("sound_cut.editing.pipeline.render_audio_from_edl", _fake_render_audio_from_edl)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=profile,
        analyzer=analyzer,
    )

    assert summary.kept_segment_count == 1


def test_process_audio_preserves_normalized_analysis_wav_when_keep_temp_true(
    tmp_path: Path, ffmpeg_available
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))

    process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        analyzer=analyzer,
        keep_temp=True,
    )

    normalized_path = output_path.with_name(f"{output_path.stem}.analysis.wav")
    assert normalized_path.exists()
    assert analyzer.calls == [normalized_path]


def test_process_audio_honors_falsey_analyzer_injection(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    analyzer = FalseySpeechAnalyzer((TimeRange(0.0, 0.5),))

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        analyzer=analyzer,
    )

    assert analyzer.calls
    assert summary.kept_segment_count == 1


def test_process_audio_rejects_in_place_output(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))

    with pytest.raises(MediaError, match="must be different"):
        process_audio(
            input_path=input_path,
            output_path=input_path,
            profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
            analyzer=FakeSpeechAnalyzer((TimeRange(0.0, 0.5),)),
        )


def test_process_audio_passes_loudness_config_into_render_plan(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    captured: dict[str, object] = {}
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))
    loudness = LoudnessNormalizationConfig(enabled=True, target_lufs=-14.0)

    def fake_render_audio_from_edl(plan) -> RenderSummary:
        captured["plan"] = plan
        return RenderSummary(
            input_duration_s=plan.source.duration_s,
            output_duration_s=plan.source.duration_s,
            removed_duration_s=0.0,
            kept_segment_count=1,
        )

    monkeypatch.setattr("sound_cut.editing.pipeline.render_audio_from_edl", fake_render_audio_from_edl)

    process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        analyzer=analyzer,
        loudness=loudness,
    )

    assert captured["plan"].loudness == loudness


def test_process_audio_can_cut_and_normalize_in_one_command(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    raw_output_path = tmp_path / "raw.wav"
    normalized_output_path = tmp_path / "normalized.wav"
    sample_rate_hz = 48_000
    target_lufs = -14.0
    quiet_amplitude = 400
    samples = [
        sample
        for mono_sample in (
            tone_samples(sample_rate_hz=sample_rate_hz, duration_s=1.20, amplitude=quiet_amplitude)
            + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.40)
            + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=1.20, amplitude=quiet_amplitude)
        )
        for sample in (mono_sample, mono_sample)
    ]
    write_pcm_wave(input_path, sample_rate_hz=sample_rate_hz, samples=samples, channels=2)
    profile = replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0, crossfade_ms=0)
    speech_ranges = (TimeRange(0.0, 1.2), TimeRange(1.6, 2.8))

    raw_summary = process_audio(
        input_path=input_path,
        output_path=raw_output_path,
        profile=profile,
        analyzer=FakeSpeechAnalyzer(speech_ranges),
    )
    normalized_summary = process_audio(
        input_path=input_path,
        output_path=normalized_output_path,
        profile=profile,
        analyzer=FakeSpeechAnalyzer(speech_ranges),
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=target_lufs),
    )

    raw_rms = _window_rms(raw_output_path, start_s=0.1, duration_s=0.5)
    normalized_rms = _window_rms(normalized_output_path, start_s=0.1, duration_s=0.5)
    raw_lufs = _integrated_lufs(raw_output_path, target_lufs=target_lufs)
    normalized_lufs = _integrated_lufs(normalized_output_path, target_lufs=target_lufs)

    assert raw_summary.input_duration_s == pytest.approx(2.8, abs=1e-9)
    assert raw_summary.kept_segment_count == 2
    assert raw_summary.output_duration_s < raw_summary.input_duration_s
    assert raw_summary.output_duration_s == pytest.approx(2.4, abs=0.01)
    assert normalized_summary.kept_segment_count == 2
    assert normalized_summary.output_duration_s == pytest.approx(raw_summary.output_duration_s, abs=0.01)
    assert normalized_rms > raw_rms * 2
    assert normalized_lufs == pytest.approx(target_lufs, abs=1.0)
    assert abs(normalized_lufs - target_lufs) < abs(raw_lufs - target_lufs)


def test_process_audio_defaults_loudness_config_when_omitted(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    captured: dict[str, object] = {}
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))

    def fake_render_audio_from_edl(plan) -> RenderSummary:
        captured["plan"] = plan
        return RenderSummary(
            input_duration_s=plan.source.duration_s,
            output_duration_s=plan.source.duration_s,
            removed_duration_s=0.0,
            kept_segment_count=1,
        )

    monkeypatch.setattr("sound_cut.editing.pipeline.render_audio_from_edl", fake_render_audio_from_edl)

    process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        analyzer=analyzer,
    )

    assert captured["plan"].loudness == LoudnessNormalizationConfig(enabled=False, target_lufs=DEFAULT_TARGET_LUFS)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_loudness_normalization_config_rejects_non_finite_target_lufs(value: float) -> None:
    with pytest.raises(ValueError, match="target_lufs must be finite"):
        LoudnessNormalizationConfig(enabled=True, target_lufs=value)
