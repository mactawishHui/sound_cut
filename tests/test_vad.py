from pathlib import Path

import pytest

from sound_cut.errors import MediaError
from sound_cut.models import AnalysisTrack, TimeRange
from sound_cut import vad as vad_module
from sound_cut.vad import (
    WebRtcSpeechAnalyzer,
    collapse_speech_flags,
    frame_duration_bytes,
    split_frames,
)

from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def test_frame_duration_bytes_matches_30ms_mono_16bit_audio() -> None:
    assert frame_duration_bytes(sample_rate_hz=16000, frame_ms=30) == 960


def test_split_frames_discards_partial_tail() -> None:
    data = b"x" * (960 * 2 + 100)

    frames = split_frames(data, sample_rate_hz=16000, frame_ms=30)

    assert len(frames) == 2
    assert all(len(frame) == 960 for frame in frames)


def test_collapse_speech_flags_converts_frames_to_ranges() -> None:
    flags = [False, True, True, False, False, True, True, True]

    ranges = collapse_speech_flags(flags, frame_ms=30, merge_gap_ms=0)

    assert ranges == (
        TimeRange(0.03, 0.09),
        TimeRange(0.15, 0.24),
    )


def test_collapse_speech_flags_merges_ranges_within_gap() -> None:
    flags = [False, True, True, False, True, True]

    ranges = collapse_speech_flags(flags, frame_ms=30, merge_gap_ms=30)

    assert ranges == (TimeRange(0.03, 0.18),)


def test_webrtc_speech_analyzer_analyze_returns_track_for_valid_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[object] = []

    class FakeVad:
        def __init__(self, mode: int) -> None:
            self.mode = mode
            self.calls: list[tuple[bytes, int]] = []

        def is_speech(self, frame: bytes, sample_rate_hz: int) -> bool:
            self.calls.append((frame, sample_rate_hz))
            return any(frame)

    monkeypatch.setattr(
        vad_module.webrtcvad,
        "Vad",
        lambda mode: created.append(FakeVad(mode)) or created[-1],
    )

    wav_path = tmp_path / "valid.wav"
    samples = tone_samples(sample_rate_hz=16000, duration_s=0.03) + silence_samples(
        sample_rate_hz=16000, duration_s=0.03
    )
    write_pcm_wave(wav_path, sample_rate_hz=16000, samples=samples)

    analyzer = WebRtcSpeechAnalyzer(vad_mode=2)
    track = analyzer.analyze(wav_path)

    assert track == AnalysisTrack(
        name="speech",
        ranges=(TimeRange(0.00, 0.03),),
        metadata={"frame_ms": "30"},
    )
    assert len(created) == 1
    fake_vad = created[0]
    assert isinstance(fake_vad, FakeVad)
    assert fake_vad.mode == 2
    assert fake_vad.calls and all(sample_rate == 16000 for _, sample_rate in fake_vad.calls)


def test_webrtc_speech_analyzer_rejects_stereo_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[object] = []

    class FakeVad:
        def __init__(self, mode: int) -> None:
            self.mode = mode
            self.calls: list[tuple[bytes, int]] = []

        def is_speech(self, frame: bytes, sample_rate_hz: int) -> bool:
            self.calls.append((frame, sample_rate_hz))
            return True

    monkeypatch.setattr(
        vad_module.webrtcvad,
        "Vad",
        lambda mode: created.append(FakeVad(mode)) or created[-1],
    )

    wav_path = tmp_path / "stereo.wav"
    samples = tone_samples(sample_rate_hz=16000, duration_s=0.03) * 2
    write_pcm_wave(wav_path, sample_rate_hz=16000, samples=samples, channels=2)

    analyzer = WebRtcSpeechAnalyzer(vad_mode=2)

    with pytest.raises(MediaError, match="mono"):
        analyzer.analyze(wav_path)

    fake_vad = created[0]
    assert isinstance(fake_vad, FakeVad)
    assert fake_vad.calls == []


def test_webrtc_speech_analyzer_rejects_unsupported_sample_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[object] = []

    class FakeVad:
        def __init__(self, mode: int) -> None:
            self.mode = mode
            self.calls: list[tuple[bytes, int]] = []

        def is_speech(self, frame: bytes, sample_rate_hz: int) -> bool:
            self.calls.append((frame, sample_rate_hz))
            return True

    monkeypatch.setattr(
        vad_module.webrtcvad,
        "Vad",
        lambda mode: created.append(FakeVad(mode)) or created[-1],
    )

    wav_path = tmp_path / "unsupported_rate.wav"
    samples = tone_samples(sample_rate_hz=44100, duration_s=0.03)
    write_pcm_wave(wav_path, sample_rate_hz=44100, samples=samples)

    analyzer = WebRtcSpeechAnalyzer(vad_mode=2)

    with pytest.raises(MediaError, match="sample rate"):
        analyzer.analyze(wav_path)

    fake_vad = created[0]
    assert isinstance(fake_vad, FakeVad)
    assert fake_vad.calls == []


def test_webrtc_speech_analyzer_rejects_invalid_frame_ms() -> None:
    with pytest.raises(ValueError, match="frame_ms"):
        WebRtcSpeechAnalyzer(vad_mode=2, frame_ms=25)
