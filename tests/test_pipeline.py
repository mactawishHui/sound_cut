from __future__ import annotations

from dataclasses import replace
import wave
from pathlib import Path

import pytest

from sound_cut.config import build_profile
from sound_cut.errors import MediaError
from sound_cut.models import AnalysisTrack, TimeRange
from sound_cut.pipeline import process_audio
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


def _wave_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


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
