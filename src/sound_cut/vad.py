from __future__ import annotations

import wave
from pathlib import Path

import webrtcvad

from sound_cut.models import AnalysisTrack, TimeRange


def frame_duration_bytes(*, sample_rate_hz: int, frame_ms: int) -> int:
    return (sample_rate_hz * frame_ms * 2) // 1000


def split_frames(data: bytes, *, sample_rate_hz: int, frame_ms: int) -> list[bytes]:
    frame_size = frame_duration_bytes(sample_rate_hz=sample_rate_hz, frame_ms=frame_ms)
    usable_length = len(data) - (len(data) % frame_size)
    return [data[index : index + frame_size] for index in range(0, usable_length, frame_size)]


def collapse_speech_flags(
    flags: list[bool], *, frame_ms: int, merge_gap_ms: int
) -> tuple[TimeRange, ...]:
    ranges: list[TimeRange] = []
    start_index: int | None = None

    for index, is_speech in enumerate(flags):
        if is_speech and start_index is None:
            start_index = index
        elif not is_speech and start_index is not None:
            ranges.append(
                TimeRange(start_index * frame_ms / 1000, index * frame_ms / 1000)
            )
            start_index = None

    if start_index is not None:
        ranges.append(
            TimeRange(start_index * frame_ms / 1000, len(flags) * frame_ms / 1000)
        )

    return tuple(ranges)


class WebRtcSpeechAnalyzer:
    def __init__(self, *, vad_mode: int, frame_ms: int = 30) -> None:
        self._vad = webrtcvad.Vad(vad_mode)
        self._frame_ms = frame_ms

    def analyze(self, wav_path: Path) -> AnalysisTrack:
        with wave.open(str(wav_path), "rb") as handle:
            sample_rate_hz = handle.getframerate()
            pcm = handle.readframes(handle.getnframes())

        frames = split_frames(pcm, sample_rate_hz=sample_rate_hz, frame_ms=self._frame_ms)
        flags = [self._vad.is_speech(frame, sample_rate_hz) for frame in frames]
        return AnalysisTrack(
            name="speech",
            ranges=collapse_speech_flags(flags, frame_ms=self._frame_ms, merge_gap_ms=0),
            metadata={"frame_ms": str(self._frame_ms)},
        )
