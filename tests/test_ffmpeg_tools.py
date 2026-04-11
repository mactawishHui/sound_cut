from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

import sound_cut.media.ffmpeg_tools as ffmpeg_tools
from sound_cut.core import MediaError, SourceMedia
from sound_cut.media.ffmpeg_tools import (
    delivery_codec_for_suffix,
    embed_subtitle_track,
    export_delivery_audio,
    normalize_loudness,
    normalize_audio_for_analysis,
    _parse_source_media,
    probe_source_media,
    resolve_delivery_bitrate_bps,
)
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def _source_media_with_bitrate(bit_rate_bps: int | None) -> SourceMedia:
    return SourceMedia(
        input_path=Path("input.mp3"),
        duration_s=10.0,
        audio_codec="mp3",
        sample_rate_hz=44_100,
        channels=1,
        bit_rate_bps=bit_rate_bps,
        has_video=False,
    )


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


def test_parse_source_media_prefers_format_bit_rate(tmp_path: Path) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 1,
                "bit_rate": "64000",
            }
        ],
        "format": {
            "duration": "12.5",
            "bit_rate": "96000",
        },
    }

    source = _parse_source_media(payload, input_path=tmp_path / "sample.mp3")

    assert source.bit_rate_bps == 96_000


def test_parse_source_media_prefers_audio_stream_bit_rate_for_muxed_input(tmp_path: Path) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "bit_rate": "88000",
            },
            {
                "codec_type": "video",
                "codec_name": "h264",
            },
        ],
        "format": {
            "duration": "8.0",
            "bit_rate": "96000",
        },
    }

    source = _parse_source_media(payload, input_path=tmp_path / "sample.m4a")

    assert source.bit_rate_bps == 88_000


def test_parse_source_media_does_not_infer_audio_bitrate_from_muxed_container_metadata(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp4"
    input_path.write_bytes(b"x" * 100_000)
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
            {
                "codec_type": "video",
                "codec_name": "h264",
            },
        ],
        "format": {
            "duration": "8.0",
            "bit_rate": "96000",
        },
    }

    source = _parse_source_media(payload, input_path=input_path)

    assert source.bit_rate_bps is None


def test_parse_source_media_uses_stream_bit_rate_when_format_bit_rate_missing(tmp_path: Path) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "bit_rate": "88000",
            }
        ],
        "format": {
            "duration": "8.0",
        },
    }

    source = _parse_source_media(payload, input_path=tmp_path / "sample.m4a")

    assert source.bit_rate_bps == 88_000


def test_parse_source_media_estimates_bit_rate_from_file_size_when_metadata_missing(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"
    input_path.write_bytes(b"x" * 20_000)
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 1,
            }
        ],
        "format": {
            "duration": "2.0",
        },
    }

    source = _parse_source_media(payload, input_path=input_path)

    assert source.bit_rate_bps == 80_000


def test_resolve_delivery_bitrate_caps_high_bitrates() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(192_000), ".mp3") == 128_000


def test_resolve_delivery_bitrate_preserves_midrange_bitrates() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(96_000), ".m4a") == 96_000


def test_resolve_delivery_bitrate_raises_low_bitrates_to_floor() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(48_000), ".mp3") == 64_000


def test_resolve_delivery_bitrate_uses_default_cap_when_unknown() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(None), ".m4a") == 128_000


def test_resolve_delivery_bitrate_returns_none_for_wav() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(96_000), ".wav") is None


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


def test_normalize_loudness_builds_loudnorm_pcm_wave_command(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "normalized.wav"
    recorded_command: list[str] = []
    write_pcm_wave(
        input_path,
        sample_rate_hz=48_000,
        samples=[
            sample
            for mono_sample in tone_samples(sample_rate_hz=48_000, duration_s=0.25, amplitude=1200)
            for sample in (mono_sample, mono_sample)
        ],
        channels=2,
    )

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "probe_source_media",
        lambda path: SourceMedia(
            input_path=path,
            duration_s=0.25,
            audio_codec="pcm_s16le",
            sample_rate_hz=48_000,
            channels=2,
            has_video=False,
        ),
    )
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )

    normalize_loudness(input_path, output_path, target_lufs=-14.0)

    assert recorded_command[0] == "ffmpeg"
    assert "-af" in recorded_command
    assert "loudnorm=I=-14.0" in recorded_command
    assert "-c:a" in recorded_command
    assert "pcm_s16le" in recorded_command
    assert "-ar" in recorded_command
    assert "48000" in recorded_command
    assert "-ac" in recorded_command
    assert "2" in recorded_command
    assert "-f" in recorded_command
    assert "wav" in recorded_command


def test_normalize_loudness_preserves_rate_and_channels_when_wave_module_cannot_read_input(
    monkeypatch, tmp_path
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "normalized.wav"
    recorded_command: list[str] = []
    input_path.write_bytes(b"riff")

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "probe_source_media",
        lambda path: SourceMedia(
            input_path=path,
            duration_s=1.0,
            audio_codec="pcm_s16le",
            sample_rate_hz=96_000,
            channels=6,
            has_video=False,
        ),
    )
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )

    normalize_loudness(input_path, output_path, target_lufs=-14.0)

    assert "-ar" in recorded_command
    assert "96000" in recorded_command
    assert "-ac" in recorded_command
    assert "6" in recorded_command


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


def test_delivery_codec_for_suffix_maps_supported_formats() -> None:
    assert delivery_codec_for_suffix(".mp3") == ("libmp3lame", "128k")
    assert delivery_codec_for_suffix(".m4a") == ("aac", "128k")
    assert delivery_codec_for_suffix(".wav") == ("pcm_s16le", None)


def test_delivery_codec_for_suffix_rejects_unsupported_formats() -> None:
    with pytest.raises(MediaError, match="Unsupported output format"):
        delivery_codec_for_suffix(".ogg")


def test_export_delivery_audio_uses_resolved_bitrate_for_mp3(monkeypatch, tmp_path) -> None:
    source_wav = tmp_path / "source.wav"
    output_mp3 = tmp_path / "output.mp3"
    source = _source_media_with_bitrate(96_000)
    recorded_command: list[str] = []
    recorded_calls: list[tuple[SourceMedia, str]] = []

    source_wav.write_bytes(b"wave")

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "resolve_delivery_bitrate_bps",
        lambda received_source, suffix: recorded_calls.append((received_source, suffix)) or 72_000,
    )
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )

    export_delivery_audio(source_wav, output_mp3, source)

    assert recorded_calls == [(source, ".mp3")]
    assert "-b:a" in recorded_command
    assert "72000" in recorded_command


def test_export_delivery_audio_writes_mp3_output(tmp_path, ffmpeg_available) -> None:
    source_wav = tmp_path / "source.wav"
    output_mp3 = tmp_path / "nested" / "output.mp3"
    write_pcm_wave(
        source_wav,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=0.50),
    )

    export_delivery_audio(source_wav, output_mp3, _source_media_with_bitrate(128_000))

    assert output_mp3.exists()
    exported = probe_source_media(output_mp3)
    assert exported.audio_codec == "mp3"


@pytest.mark.parametrize(
    ("suffix", "expected_codec", "expected_format"),
    [
        (".m4a", "aac", "ipod"),
        (".wav", "pcm_s16le", "wav"),
    ],
)
def test_export_delivery_audio_adds_expected_format_flags_for_other_supported_outputs(
    monkeypatch, tmp_path, suffix: str, expected_codec: str, expected_format: str
) -> None:
    source_wav = tmp_path / "source.wav"
    output_path = tmp_path / f"output{suffix}"
    recorded_command: list[str] = []

    source_wav.write_bytes(b"wave")

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )

    export_delivery_audio(source_wav, output_path, _source_media_with_bitrate(128_000))

    assert recorded_command[0] == "ffmpeg"
    assert str(source_wav) in recorded_command
    assert str(output_path) in recorded_command
    assert expected_codec in recorded_command
    assert "-f" in recorded_command
    assert expected_format in recorded_command


def test_run_wraps_subprocess_errors_as_media_error(monkeypatch) -> None:
    def raise_called_process_error(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["ffmpeg"], output="", stderr="boom")

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", raise_called_process_error)

    with pytest.raises(MediaError, match="boom"):
        ffmpeg_tools._run(["ffmpeg"])


def test_embed_subtitle_track_calls_ffmpeg_with_correct_args(monkeypatch, tmp_path) -> None:
    video_path = tmp_path / "input.mp4"
    srt_path = tmp_path / "subs.srt"
    output_path = tmp_path / "output.mp4"
    recorded_command: list[str] = []

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )

    embed_subtitle_track(video_path, srt_path, output_path)

    assert recorded_command[0] == "ffmpeg"
    first_i = recorded_command.index("-i")
    second_i = recorded_command.index("-i", first_i + 1)
    assert recorded_command[first_i + 1] == str(video_path)
    assert recorded_command[second_i + 1] == str(srt_path)
    assert "-c:s" in recorded_command
    assert "mov_text" in recorded_command
    assert "-map" in recorded_command
    assert "0:v" in recorded_command
    assert "1:s" in recorded_command
    assert str(output_path) == recorded_command[-1]


def test_embed_subtitle_track_rejects_unsupported_container(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    with pytest.raises(MediaError, match="Unsupported video container"):
        embed_subtitle_track(tmp_path / "input.mp4", tmp_path / "subs.srt", tmp_path / "output.avi")


def test_embed_subtitle_track_uses_srt_codec_for_mkv(monkeypatch, tmp_path) -> None:
    recorded_command: list[str] = []
    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(
        ffmpeg_tools,
        "_run",
        lambda command: recorded_command.extend(command),
    )
    embed_subtitle_track(tmp_path / "input.mkv", tmp_path / "subs.srt", tmp_path / "output.mkv")
    assert "srt" in recorded_command


def test_embed_subtitle_track_creates_parent_directory(monkeypatch, tmp_path) -> None:
    video_path = tmp_path / "input.mp4"
    srt_path = tmp_path / "subs.srt"
    output_path = tmp_path / "nested" / "deep" / "output.mp4"

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(ffmpeg_tools, "_run", lambda command: None)

    embed_subtitle_track(video_path, srt_path, output_path)

    assert output_path.parent.exists()


def test_embed_subtitle_track_propagates_media_error(monkeypatch, tmp_path) -> None:
    video_path = tmp_path / "input.mp4"
    srt_path = tmp_path / "subs.srt"
    output_path = tmp_path / "output.mp4"

    def raise_media_error(command):
        raise MediaError("subtitle mux failed")

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(ffmpeg_tools, "_run", raise_media_error)

    with pytest.raises(MediaError, match="subtitle mux failed"):
        embed_subtitle_track(video_path, srt_path, output_path)
