from pathlib import Path

from sound_cut.config import build_profile
from sound_cut.models import PauseSplitConfig, TimeRange
from sound_cut.pause_splitter import refine_speech_ranges
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def test_refine_speech_ranges_splits_long_envelope_around_internal_pause(tmp_path: Path) -> None:
    wav_path = tmp_path / "analysis.wav"
    sample_rate_hz = 16_000
    samples = (
        tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
        + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.30)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
    )
    write_pcm_wave(wav_path, sample_rate_hz=sample_rate_hz, samples=samples)

    ranges = refine_speech_ranges(
        wav_path,
        coarse_ranges=(TimeRange(0.0, 1.5),),
        config=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.0,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=180,
            context_ms=150,
        ),
    )

    assert ranges == (
        TimeRange(0.0, 0.60),
        TimeRange(0.90, 1.50),
    )


def test_refine_speech_ranges_does_not_split_when_pause_is_too_short(tmp_path: Path) -> None:
    wav_path = tmp_path / "analysis.wav"
    sample_rate_hz = 16_000
    samples = (
        tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
        + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.09)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
    )
    write_pcm_wave(wav_path, sample_rate_hz=sample_rate_hz, samples=samples)

    ranges = refine_speech_ranges(
        wav_path,
        coarse_ranges=(TimeRange(0.0, 1.29),),
        config=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.0,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=180,
            context_ms=150,
        ),
    )

    assert ranges == (TimeRange(0.0, 1.29),)


def test_refine_speech_ranges_does_not_split_when_gap_is_too_close_to_edge(tmp_path: Path) -> None:
    wav_path = tmp_path / "analysis.wav"
    sample_rate_hz = 16_000
    samples = (
        silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.18)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.50)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
    )
    write_pcm_wave(wav_path, sample_rate_hz=sample_rate_hz, samples=samples)

    ranges = refine_speech_ranges(
        wav_path,
        coarse_ranges=(TimeRange(0.0, 1.28),),
        config=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.0,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=150,
            context_ms=200,
        ),
    )

    assert ranges == (TimeRange(0.0, 1.28),)


def test_refine_speech_ranges_only_splits_on_first_qualifying_internal_pause(tmp_path: Path) -> None:
    wav_path = tmp_path / "analysis.wav"
    sample_rate_hz = 16_000
    samples = (
        tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.50)
        + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.24)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.50)
        + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.24)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.50)
    )
    write_pcm_wave(wav_path, sample_rate_hz=sample_rate_hz, samples=samples)

    ranges = refine_speech_ranges(
        wav_path,
        coarse_ranges=(TimeRange(0.0, 1.98),),
        config=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.0,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=180,
            context_ms=150,
        ),
    )

    assert ranges == (
        TimeRange(0.0, 0.51),
        TimeRange(0.72, 1.98),
    )


def test_build_profile_enables_pause_split_only_for_dense() -> None:
    natural = build_profile("natural")
    balanced = build_profile("balanced")
    dense = build_profile("dense")

    assert natural.pause_split.enabled is False
    assert balanced.pause_split.enabled is False
    assert dense.pause_split.enabled is True


def test_build_profile_dense_uses_tight_dense_defaults() -> None:
    dense = build_profile("dense")

    assert dense.min_silence_ms == 140
    assert dense.padding_ms == 40
    assert dense.crossfade_ms == 5
