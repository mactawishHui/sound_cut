from sound_cut.config import build_profile
from sound_cut.models import TimeRange
from sound_cut.vad import collapse_speech_flags, frame_duration_bytes, split_frames


def test_frame_duration_bytes_matches_30ms_mono_16bit_audio() -> None:
    assert frame_duration_bytes(sample_rate_hz=16000, frame_ms=30) == 960


def test_split_frames_discards_partial_tail() -> None:
    data = b"x" * (960 * 2 + 100)

    frames = split_frames(data, sample_rate_hz=16000, frame_ms=30)

    assert len(frames) == 2
    assert all(len(frame) == 960 for frame in frames)


def test_collapse_speech_flags_converts_frames_to_ranges() -> None:
    profile = build_profile("balanced")
    flags = [False, True, True, False, False, True, True, True]

    ranges = collapse_speech_flags(flags, frame_ms=30, merge_gap_ms=profile.merge_gap_ms)

    assert ranges == (
        TimeRange(0.03, 0.09),
        TimeRange(0.15, 0.24),
    )
