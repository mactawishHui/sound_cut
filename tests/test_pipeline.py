from __future__ import annotations

from dataclasses import replace
import json
import math
import re
import struct
import subprocess
import types
import wave
from pathlib import Path

import pytest

from sound_cut.core import AnalysisTrack, MediaError, RenderSummary, TimeRange, build_profile
from sound_cut.core.models import (
    DEFAULT_TARGET_LUFS,
    EnhancementConfig,
    LoudnessNormalizationConfig,
    SourceMedia,
)
from sound_cut.editing.pipeline import process_audio
from sound_cut.enhancement.pipeline import enhance_audio
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
        enable_cut=True,
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
        enable_cut=True,
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
        enable_cut=True,
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
        enable_cut=True,
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
        enable_cut=True,
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
            enable_cut=True,
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
        enable_cut=True,
        analyzer=analyzer,
        loudness=loudness,
    )

    assert captured["plan"].loudness == loudness


def test_process_audio_skips_analyzer_when_cut_disabled(
    tmp_path: Path, ffmpeg_available
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5))

    def fail_analyze(_wav_path: Path) -> AnalysisTrack:
        raise AssertionError("analyzer should not be used when cut is disabled")

    analyzer = types.SimpleNamespace(analyze=fail_analyze)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enable_cut=False,
        analyzer=analyzer,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-14.0),
    )

    assert summary.input_duration_s == pytest.approx(0.5, abs=1e-9)
    assert summary.output_duration_s == pytest.approx(0.5, abs=0.02)
    assert summary.removed_duration_s == pytest.approx(0.0, abs=0.02)
    assert summary.kept_segment_count == 1


def test_process_audio_routes_video_without_cut_to_full_video_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"video")
    enhanced_audio_path = tmp_path / "enhanced.wav"
    enhanced_audio_path.write_bytes(b"audio")
    captured: dict[str, object] = {}

    source = SourceMedia(
        input_path=input_path,
        duration_s=2.0,
        audio_codec="aac",
        sample_rate_hz=48_000,
        channels=2,
        bit_rate_bps=96_000,
        has_video=True,
    )

    monkeypatch.setattr("sound_cut.editing.pipeline.probe_source_media", lambda _path: source)
    monkeypatch.setattr(
        "sound_cut.editing.pipeline.enhance_audio",
        lambda *, input_path, enhancement, working_dir: enhanced_audio_path,
    )

    def fake_render_full_video(*, video_source, audio_source, output_path, loudness):
        captured["video_source"] = video_source
        captured["audio_source"] = audio_source
        captured["output_path"] = output_path
        captured["loudness"] = loudness
        return RenderSummary(
            input_duration_s=2.0,
            output_duration_s=2.0,
            removed_duration_s=0.0,
            kept_segment_count=1,
        )

    monkeypatch.setattr("sound_cut.editing.pipeline.render_full_video", fake_render_full_video)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=build_profile("balanced"),
        enable_cut=False,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-14.0),
    )

    assert summary.kept_segment_count == 1
    assert captured["video_source"] == source
    assert captured["audio_source"].input_path == enhanced_audio_path
    assert captured["audio_source"].has_video is True
    assert captured["output_path"] == output_path


def test_process_audio_routes_video_with_cut_to_video_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"video")
    enhanced_audio_path = tmp_path / "enhanced.wav"
    enhanced_audio_path.write_bytes(b"audio")
    captured: dict[str, object] = {}

    source = SourceMedia(
        input_path=input_path,
        duration_s=3.0,
        audio_codec="aac",
        sample_rate_hz=48_000,
        channels=2,
        bit_rate_bps=96_000,
        has_video=True,
    )
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 1.0),))
    profile = replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0)

    monkeypatch.setattr("sound_cut.editing.pipeline.probe_source_media", lambda _path: source)
    monkeypatch.setattr(
        "sound_cut.editing.pipeline.enhance_audio",
        lambda *, input_path, enhancement, working_dir: enhanced_audio_path,
    )

    def fake_process_cut_video(
        *,
        input_path,
        output_path,
        profile,
        video_source,
        audio_source,
        analyzer,
        keep_temp,
        loudness,
    ):
        captured["input_path"] = input_path
        captured["output_path"] = output_path
        captured["profile"] = profile
        captured["video_source"] = video_source
        captured["audio_source"] = audio_source
        captured["analyzer"] = analyzer
        captured["keep_temp"] = keep_temp
        captured["loudness"] = loudness
        return RenderSummary(
            input_duration_s=3.0,
            output_duration_s=2.0,
            removed_duration_s=1.0,
            kept_segment_count=2,
        )

    monkeypatch.setattr("sound_cut.editing.pipeline._process_cut_video", fake_process_cut_video)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=profile,
        enable_cut=True,
        analyzer=analyzer,
        keep_temp=True,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-15.0),
    )

    assert summary.kept_segment_count == 2
    assert captured["input_path"] == enhanced_audio_path
    assert captured["output_path"] == output_path
    assert captured["profile"] == profile
    assert captured["video_source"] == source
    assert captured["audio_source"].input_path == enhanced_audio_path
    assert captured["analyzer"] is analyzer
    assert captured["keep_temp"] is True


def test_process_audio_can_normalize_full_source_without_cut(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=48_000,
        samples=tone_samples(sample_rate_hz=48_000, duration_s=1.0, amplitude=400),
    )

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enable_cut=False,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-14.0),
    )

    assert summary.input_duration_s == pytest.approx(1.0, abs=1e-9)
    assert summary.output_duration_s == pytest.approx(1.0, abs=0.02)
    assert summary.removed_duration_s == pytest.approx(0.0, abs=0.02)
    assert summary.kept_segment_count == 1
    assert _integrated_lufs(output_path, target_lufs=-14.0) == pytest.approx(-14.0, abs=1.0)


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
        enable_cut=True,
        analyzer=FakeSpeechAnalyzer(speech_ranges),
    )
    normalized_summary = process_audio(
        input_path=input_path,
        output_path=normalized_output_path,
        profile=profile,
        enable_cut=True,
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
        enable_cut=True,
        analyzer=analyzer,
    )

    assert captured["plan"].loudness == LoudnessNormalizationConfig(enabled=False, target_lufs=DEFAULT_TARGET_LUFS)


def test_process_audio_runs_enhancement_before_cut_analysis(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    enhanced_path = tmp_path / "enhanced.wav"
    calls: dict[str, object] = {}
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))

    def fake_enhance_audio(*, input_path: Path, enhancement: EnhancementConfig, working_dir: Path) -> Path:
        calls["enhance_input"] = input_path
        calls["working_dir"] = working_dir
        calls["enhancement"] = enhancement
        write_pcm_wave(
            enhanced_path,
            sample_rate_hz=16_000,
            samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5),
        )
        return enhanced_path

    def fake_normalize_audio_for_analysis(
        source_path: Path, normalized_path: Path, *, sample_rate_hz: int
    ) -> None:
        calls["analysis_input"] = source_path
        calls["analysis_output"] = normalized_path
        calls["analysis_sample_rate_hz"] = sample_rate_hz
        write_pcm_wave(
            normalized_path,
            sample_rate_hz=sample_rate_hz,
            samples=tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.5),
        )

    monkeypatch.setattr("sound_cut.editing.pipeline.enhance_audio", fake_enhance_audio)
    monkeypatch.setattr("sound_cut.editing.pipeline.normalize_audio_for_analysis", fake_normalize_audio_for_analysis)

    process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enhancement=EnhancementConfig(enabled=True),
        enable_cut=True,
        analyzer=analyzer,
    )

    assert calls["enhance_input"] == input_path
    assert calls["enhancement"] == EnhancementConfig(enabled=True)
    assert calls["analysis_input"] == enhanced_path
    assert calls["analysis_sample_rate_hz"] == 16_000
    assert analyzer.calls == [calls["analysis_output"]]


def test_process_audio_preserves_original_source_metadata_for_cut_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    enhanced_path = tmp_path / "enhanced.wav"
    calls: dict[str, object] = {}
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=tone_samples(sample_rate_hz=48_000, duration_s=0.1))
    original_source = SourceMedia(
        input_path=input_path,
        duration_s=10.0,
        audio_codec="aac",
        sample_rate_hz=48_000,
        channels=2,
        bit_rate_bps=192_000,
    )
    enhanced_source = SourceMedia(
        input_path=enhanced_path,
        duration_s=6.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        bit_rate_bps=256_000,
    )
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 4.0),))

    def fake_enhance_audio(*, input_path: Path, enhancement: EnhancementConfig, working_dir: Path) -> Path:
        calls["enhance_input"] = input_path
        calls["enhancement"] = enhancement
        return enhanced_path

    def fake_probe_source_media(path: Path) -> SourceMedia:
        if path == input_path:
            return original_source
        if path == enhanced_path:
            return enhanced_source
        raise AssertionError(f"unexpected probe path: {path}")

    def fake_normalize_audio_for_analysis(
        source_path: Path, normalized_path: Path, *, sample_rate_hz: int
    ) -> None:
        calls["analysis_input"] = source_path
        write_pcm_wave(
            normalized_path,
            sample_rate_hz=sample_rate_hz,
            samples=tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.1),
        )

    def fake_render_audio_from_edl(plan) -> RenderSummary:
        calls["render_plan_source"] = plan.source
        return RenderSummary(
            input_duration_s=plan.source.duration_s,
            output_duration_s=4.0,
            removed_duration_s=plan.source.duration_s - 4.0,
            kept_segment_count=1,
        )

    monkeypatch.setattr("sound_cut.editing.pipeline.enhance_audio", fake_enhance_audio)
    monkeypatch.setattr("sound_cut.editing.pipeline.probe_source_media", fake_probe_source_media)
    monkeypatch.setattr("sound_cut.editing.pipeline.normalize_audio_for_analysis", fake_normalize_audio_for_analysis)
    monkeypatch.setattr("sound_cut.editing.pipeline.render_audio_from_edl", fake_render_audio_from_edl)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enhancement=EnhancementConfig(enabled=True),
        enable_cut=True,
        analyzer=analyzer,
    )

    assert calls["enhance_input"] == input_path
    assert calls["analysis_input"] == enhanced_path
    assert calls["render_plan_source"] == replace(original_source, input_path=enhanced_path)
    assert summary.input_duration_s == pytest.approx(10.0, abs=1e-9)
    assert summary.removed_duration_s == pytest.approx(6.0, abs=1e-9)


def test_process_audio_uses_enhanced_source_for_full_audio_render(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    enhanced_path = tmp_path / "enhanced.wav"
    calls: dict[str, object] = {}
    write_pcm_wave(
        input_path,
        sample_rate_hz=48_000,
        samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5, amplitude=400),
    )
    write_pcm_wave(
        enhanced_path,
        sample_rate_hz=48_000,
        samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5, amplitude=2_000),
    )

    def fake_enhance_audio(*, input_path: Path, enhancement: EnhancementConfig, working_dir: Path) -> Path:
        calls["enhance_input"] = input_path
        calls["enhancement"] = enhancement
        calls["working_dir"] = working_dir
        return enhanced_path

    monkeypatch.setattr("sound_cut.editing.pipeline.enhance_audio", fake_enhance_audio)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enhancement=EnhancementConfig(enabled=True),
        enable_cut=False,
    )

    assert calls["enhance_input"] == input_path
    assert calls["enhancement"] == EnhancementConfig(enabled=True)
    assert isinstance(calls["working_dir"], Path)
    assert summary.input_duration_s == pytest.approx(0.5, abs=1e-9)
    assert summary.output_duration_s == pytest.approx(0.5, abs=0.02)
    assert summary.removed_duration_s == pytest.approx(0.0, abs=0.02)
    assert summary.kept_segment_count == 1
    assert _window_rms(output_path, start_s=0.1, duration_s=0.2) > _window_rms(
        input_path,
        start_s=0.1,
        duration_s=0.2,
    )


def test_process_audio_preserves_original_source_metadata_for_full_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    enhanced_path = tmp_path / "enhanced.wav"
    calls: dict[str, object] = {}
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=tone_samples(sample_rate_hz=48_000, duration_s=0.1))
    original_source = SourceMedia(
        input_path=input_path,
        duration_s=8.0,
        audio_codec="aac",
        sample_rate_hz=48_000,
        channels=2,
        bit_rate_bps=256_000,
    )
    enhanced_source = SourceMedia(
        input_path=enhanced_path,
        duration_s=5.0,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        bit_rate_bps=128_000,
    )

    def fake_enhance_audio(*, input_path: Path, enhancement: EnhancementConfig, working_dir: Path) -> Path:
        calls["enhance_input"] = input_path
        calls["enhancement"] = enhancement
        return enhanced_path

    def fake_probe_source_media(path: Path) -> SourceMedia:
        if path == input_path:
            return original_source
        if path == enhanced_path:
            return enhanced_source
        raise AssertionError(f"unexpected probe path: {path}")

    def fake_render_full_audio(*, source: SourceMedia, output_path: Path, loudness: LoudnessNormalizationConfig) -> RenderSummary:
        calls["render_source"] = source
        return RenderSummary(
            input_duration_s=source.duration_s,
            output_duration_s=source.duration_s,
            removed_duration_s=0.0,
            kept_segment_count=1,
        )

    monkeypatch.setattr("sound_cut.editing.pipeline.enhance_audio", fake_enhance_audio)
    monkeypatch.setattr("sound_cut.editing.pipeline.probe_source_media", fake_probe_source_media)
    monkeypatch.setattr("sound_cut.editing.pipeline.render_full_audio", fake_render_full_audio)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enhancement=EnhancementConfig(enabled=True),
        enable_cut=False,
    )

    assert calls["enhance_input"] == input_path
    assert calls["render_source"] == replace(original_source, input_path=enhanced_path)
    assert summary.input_duration_s == pytest.approx(8.0, abs=1e-9)
    assert summary.output_duration_s == pytest.approx(8.0, abs=1e-9)


def test_enhance_audio_requires_backend_to_create_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.1))
    enhancement = EnhancementConfig(enabled=True)

    class FakeEnhancer:
        backend_name = "fake"

        def validate(self) -> None:
            return None

        def enhance(self, input_path: Path, output_path: Path) -> None:
            _ = input_path, output_path

    monkeypatch.setattr("sound_cut.enhancement.pipeline.select_enhancer", lambda config: FakeEnhancer())

    with pytest.raises(MediaError, match="did not create"):
        enhance_audio(
            input_path=input_path,
            enhancement=enhancement,
            working_dir=tmp_path / "work",
        )


def test_enhance_audio_falls_back_to_original_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.1))
    enhancement = EnhancementConfig(enabled=True, backend="demucs-vocals", fallback="original")

    class FakeEnhancer:
        backend_name = "demucs-vocals"

        def validate(self) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr("sound_cut.enhancement.pipeline.select_enhancer", lambda config: FakeEnhancer())

    resolved = enhance_audio(
        input_path=input_path,
        enhancement=enhancement,
        working_dir=tmp_path / "work",
    )

    assert resolved == input_path


def test_enhance_audio_falls_back_to_secondary_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    fallback_output = tmp_path / "work" / "enhanced.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.1))
    enhancement = EnhancementConfig(enabled=True, backend="demucs-vocals", fallback="deepfilternet3")

    class PrimaryEnhancer:
        backend_name = "demucs-vocals"

        def validate(self) -> None:
            raise RuntimeError("boom")

    class FallbackEnhancer:
        backend_name = "deepfilternet3"

        def validate(self) -> None:
            return None

        def enhance(self, input_path: Path, output_path: Path) -> None:
            assert input_path.name == "input.wav"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"enhanced")

    def fake_select_enhancer(config: EnhancementConfig):
        if config.backend == "demucs-vocals":
            return PrimaryEnhancer()
        if config.backend == "deepfilternet3":
            assert config.model_path is None
            assert config.fallback == "fail"
            return FallbackEnhancer()
        raise AssertionError(config.backend)

    monkeypatch.setattr("sound_cut.enhancement.pipeline.select_enhancer", fake_select_enhancer)

    resolved = enhance_audio(
        input_path=input_path,
        enhancement=enhancement,
        working_dir=tmp_path / "work",
    )

    assert resolved == fallback_output
    assert resolved.read_bytes() == b"enhanced"


def test_process_audio_defaults_enable_cut_to_true_for_backward_compatibility(
    tmp_path: Path, ffmpeg_available
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        analyzer=analyzer,
    )

    assert analyzer.calls
    assert summary.kept_segment_count == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_loudness_normalization_config_rejects_non_finite_target_lufs(value: float) -> None:
    with pytest.raises(ValueError, match="target_lufs must be finite"):
        LoudnessNormalizationConfig(enabled=True, target_lufs=value)


# --- subtitle integration tests ---

from sound_cut.core.models import SubtitleConfig
from sound_cut.editing.pipeline import _apply_subtitles


def test_process_audio_subtitle_path_is_none_when_subtitle_not_enabled(
    tmp_path: Path, ffmpeg_available
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5),
    )
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enable_cut=True,
        analyzer=analyzer,
    )

    assert summary.subtitle_path is None


def test_process_audio_returns_subtitle_path_in_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    fake_subtitle_path = tmp_path / "output.srt"
    fake_subtitle_path.write_text("fake srt content")

    source = SourceMedia(
        input_path=input_path,
        duration_s=0.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        bit_rate_bps=256_000,
    )

    monkeypatch.setattr("sound_cut.editing.pipeline.probe_source_media", lambda _path: source)
    monkeypatch.setattr(
        "sound_cut.editing.pipeline.enhance_audio",
        lambda *, input_path, enhancement, working_dir: input_path,
    )

    def fake_normalize_audio_for_analysis(source_path, normalized_path, *, sample_rate_hz):
        write_pcm_wave(normalized_path, sample_rate_hz=sample_rate_hz, samples=tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.5))

    monkeypatch.setattr("sound_cut.editing.pipeline.normalize_audio_for_analysis", fake_normalize_audio_for_analysis)

    def fake_apply_subtitles(rendered_path, subtitle_config, *, has_video):
        return fake_subtitle_path

    monkeypatch.setattr("sound_cut.editing.pipeline._apply_subtitles", fake_apply_subtitles)

    def fake_render_audio_from_edl(plan) -> RenderSummary:
        return RenderSummary(
            input_duration_s=plan.source.duration_s,
            output_duration_s=plan.source.duration_s,
            removed_duration_s=0.0,
            kept_segment_count=1,
        )

    monkeypatch.setattr("sound_cut.editing.pipeline.render_audio_from_edl", fake_render_audio_from_edl)

    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))
    subtitle_config = SubtitleConfig(enabled=True)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enable_cut=True,
        analyzer=analyzer,
        subtitle=subtitle_config,
    )

    assert summary.subtitle_path == fake_subtitle_path


def test_apply_subtitles_writes_srt_for_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "output.wav"
    write_pcm_wave(audio_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    expected_srt_path = audio_path.with_suffix(".srt")
    embed_calls: list = []

    def fake_generate_subtitles(audio_path, output_path, config):
        output_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        return output_path

    def fake_burn_subtitle_track(video_path, srt_path, output_path):
        embed_calls.append((video_path, srt_path, output_path))

    monkeypatch.setattr("sound_cut.editing.pipeline.generate_subtitles", fake_generate_subtitles)
    monkeypatch.setattr("sound_cut.editing.pipeline.burn_subtitle_track", fake_burn_subtitle_track)

    result = _apply_subtitles(
        rendered_path=audio_path,
        subtitle_config=SubtitleConfig(enabled=True),
        has_video=False,
    )

    assert result == expected_srt_path
    assert expected_srt_path.exists()
    assert embed_calls == []


def test_apply_subtitles_video_default_embeds_mp4_and_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default (embed_mode='mp4', sidecar_only=False) for video: soft mov_text track in-place, return None."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"fake video content")
    generate_calls: list = []
    embed_calls: list = []

    def fake_generate_subtitles(audio_path, output_path, config):
        output_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        generate_calls.append((output_path, config.format))
        return output_path

    def fake_embed_subtitle_track(video_path_arg, srt_path, output_path):
        output_path.write_bytes(b"mp4 with subs")
        embed_calls.append((video_path_arg, srt_path, output_path))

    monkeypatch.setattr("sound_cut.editing.pipeline.generate_subtitles", fake_generate_subtitles)
    monkeypatch.setattr("sound_cut.editing.pipeline.embed_subtitle_track", fake_embed_subtitle_track)

    result = _apply_subtitles(
        rendered_path=video_path,
        subtitle_config=SubtitleConfig(enabled=True),  # embed_mode="mp4" by default
        has_video=True,
    )

    # Default: no permanent sidecar, output stays as .mp4 → returns None
    assert result is None
    assert not video_path.with_suffix(".srt").exists()
    assert len(embed_calls) == 1
    called_video, called_srt, _ = embed_calls[0]
    assert called_video == video_path
    assert called_srt.suffix == ".srt"
    assert len(generate_calls) == 1
    assert generate_calls[0][1] == "srt"


def test_apply_subtitles_video_mkv_mode_produces_mkv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """embed_mode='mkv': mux into MKV container, return .mkv path."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"fake video content")
    mkv_calls: list = []

    def fake_generate_subtitles(audio_path, output_path, config):
        output_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        return output_path

    def fake_embed_mkv(video_path_arg, srt_path, mkv_path, *, language=None):
        mkv_path.write_bytes(b"mkv with subs")
        mkv_calls.append((video_path_arg, srt_path, mkv_path))

    monkeypatch.setattr("sound_cut.editing.pipeline.generate_subtitles", fake_generate_subtitles)
    monkeypatch.setattr("sound_cut.editing.pipeline.embed_subtitle_track_mkv", fake_embed_mkv)

    result = _apply_subtitles(
        rendered_path=video_path,
        subtitle_config=SubtitleConfig(enabled=True, embed_mode="mkv"),
        has_video=True,
    )

    assert result is not None
    assert result.suffix == ".mkv"
    assert not video_path.exists()
    assert len(mkv_calls) == 1


def test_apply_subtitles_video_burn_embeds_and_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """embed_mode='burn': hard-burn subtitle into video frames and return None."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"fake video content")
    generate_calls: list = []
    burn_calls: list = []

    def fake_generate_subtitles(audio_path, output_path, config):
        output_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        generate_calls.append((output_path, config.format))
        return output_path

    def fake_burn_subtitle_track(video_path_arg, srt_path, output_path):
        output_path.write_bytes(b"video with subs")
        burn_calls.append((video_path_arg, srt_path, output_path))

    monkeypatch.setattr("sound_cut.editing.pipeline.generate_subtitles", fake_generate_subtitles)
    monkeypatch.setattr("sound_cut.editing.pipeline.burn_subtitle_track", fake_burn_subtitle_track)

    result = _apply_subtitles(
        rendered_path=video_path,
        subtitle_config=SubtitleConfig(enabled=True, embed_mode="burn"),
        has_video=True,
    )

    assert result is None
    assert len(burn_calls) == 1
    called_video, called_srt, _ = burn_calls[0]
    assert called_video == video_path
    assert called_srt.suffix == ".srt"
    assert len(generate_calls) == 1
    assert generate_calls[0][1] == "srt"


def test_apply_subtitles_sidecar_only_video_writes_srt_no_embed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With sidecar_only=True, write .srt sidecar and skip embedding even for video."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"fake video content")
    embed_calls: list = []

    def fake_generate_subtitles(audio_path, output_path, config):
        output_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        return output_path

    monkeypatch.setattr("sound_cut.editing.pipeline.generate_subtitles", fake_generate_subtitles)
    monkeypatch.setattr(
        "sound_cut.editing.pipeline.burn_subtitle_track",
        lambda *a: embed_calls.append(a),
    )

    result = _apply_subtitles(
        rendered_path=video_path,
        subtitle_config=SubtitleConfig(enabled=True, sidecar_only=True),
        has_video=True,
    )

    assert result == video_path.with_suffix(".srt")
    assert result.exists()
    assert embed_calls == []


def test_apply_subtitles_video_vtt_format_always_uses_srt_internally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with format=vtt, video embedding always uses SRT internally."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"fake video content")
    generate_calls: list = []
    embed_calls: list = []

    def fake_generate_subtitles(audio_path, output_path, config):
        output_path.write_text("fake subtitle content")
        generate_calls.append(config.format)
        return output_path

    def fake_embed_subtitle_track(video_path_arg, srt_path, output_path):
        output_path.write_bytes(b"mp4 with subs")
        embed_calls.append(srt_path)

    monkeypatch.setattr("sound_cut.editing.pipeline.generate_subtitles", fake_generate_subtitles)
    monkeypatch.setattr("sound_cut.editing.pipeline.embed_subtitle_track", fake_embed_subtitle_track)

    result = _apply_subtitles(
        rendered_path=video_path,
        subtitle_config=SubtitleConfig(enabled=True, format="vtt"),  # default embed_mode="mp4"
        has_video=True,
    )

    # Default mp4 mode → in-place, returns None
    assert result is None
    assert len(embed_calls) == 1
    assert embed_calls[0].suffix == ".srt"
    assert generate_calls == ["srt"]
