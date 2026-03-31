from __future__ import annotations

import wave

from sound_cut.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def test_probe_source_media_reads_basic_wave_metadata(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=48_000,
        samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5)
        + silence_samples(sample_rate_hz=48_000, duration_s=0.5),
    )

    media = probe_source_media(input_path)

    assert media.input_path == input_path
    assert round(media.duration_s, 2) == 1.00
    assert media.sample_rate_hz == 48_000
    assert media.channels == 1
    assert media.has_video is False


def test_normalize_audio_for_analysis_outputs_mono_16k_wave(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "normalized.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=48_000,
        samples=tone_samples(sample_rate_hz=48_000, duration_s=0.25)
        + silence_samples(sample_rate_hz=48_000, duration_s=0.25),
    )

    normalize_audio_for_analysis(input_path, output_path, sample_rate_hz=16_000)

    with wave.open(str(output_path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 16_000
        assert handle.getsampwidth() == 2
