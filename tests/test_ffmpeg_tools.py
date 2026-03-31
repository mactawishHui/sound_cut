from __future__ import annotations

import subprocess
import wave

import pytest

import sound_cut.ffmpeg_tools as ffmpeg_tools
from sound_cut.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from sound_cut.errors import MediaError
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


def test_normalize_audio_for_analysis_explicitly_forces_wav_pcm16(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "normalized.wav"
    recorded_command: list[str] = []

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )

    normalize_audio_for_analysis(input_path, output_path, sample_rate_hz=16_000)

    assert "-f" in recorded_command
    assert "wav" in recorded_command
    assert "-c:a" in recorded_command
    assert "pcm_s16le" in recorded_command


def test_probe_source_media_wraps_malformed_json_as_media_error(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "input.wav"

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: subprocess.CompletedProcess(command, 0, stdout="{not json", stderr=""),
    )

    with pytest.raises(MediaError):
        probe_source_media(input_path)


def test_probe_source_media_wraps_incomplete_json_as_media_error(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "input.wav"

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: subprocess.CompletedProcess(command, 0, stdout='{"streams": []}', stderr=""),
    )

    with pytest.raises(MediaError):
        probe_source_media(input_path)


def test_normalize_audio_for_analysis_includes_log_suppression_flags(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "normalized.wav"
    recorded_command: list[str] = []

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )

    normalize_audio_for_analysis(input_path, output_path, sample_rate_hz=16_000)

    assert "-loglevel" in recorded_command
    assert "error" in recorded_command
    assert "-nostats" in recorded_command


def test_run_wraps_subprocess_errors_as_media_error(monkeypatch) -> None:
    def raise_called_process_error(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["ffmpeg"], output="", stderr="boom")

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", raise_called_process_error)

    with pytest.raises(MediaError, match="boom"):
        ffmpeg_tools._run(["ffmpeg"])
