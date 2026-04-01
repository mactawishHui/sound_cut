from __future__ import annotations

import math
import wave
from pathlib import Path

import webrtcvad

from sound_cut.errors import MediaError
from sound_cut.models import AnalysisTrack, TimeRange

_SUPPORTED_FRAME_MS = {10, 20, 30}
_SUPPORTED_SAMPLE_RATES = {8000, 16000, 32000, 48000}


def _validate_frame_ms(frame_ms: int) -> None:
    if frame_ms not in _SUPPORTED_FRAME_MS:
        raise ValueError(
            f"frame_ms must be one of {sorted(_SUPPORTED_FRAME_MS)} milliseconds for WebRTC VAD"
        )


def _merge_ranges(ranges: tuple[TimeRange, ...], *, merge_gap_ms: int) -> tuple[TimeRange, ...]:
    if not ranges:
        return ()

    merged = [ranges[0]]
    merge_gap_s = merge_gap_ms / 1000
    for current in ranges[1:]:
        previous = merged[-1]
        if current.start_s - previous.end_s <= merge_gap_s:
            merged[-1] = TimeRange(previous.start_s, max(previous.end_s, current.end_s))
        else:
            merged.append(current)
    return tuple(merged)


def frame_duration_bytes(*, sample_rate_hz: int, frame_ms: int) -> int:
    _validate_frame_ms(frame_ms)
    return (sample_rate_hz * frame_ms * 2) // 1000


def split_frames(data: bytes, *, sample_rate_hz: int, frame_ms: int) -> list[bytes]:
    frame_size = frame_duration_bytes(sample_rate_hz=sample_rate_hz, frame_ms=frame_ms)
    usable_length = len(data) - (len(data) % frame_size)
    return [data[index : index + frame_size] for index in range(0, usable_length, frame_size)]


def collapse_speech_flags(
    flags: list[bool], *, frame_ms: int, merge_gap_ms: int
) -> tuple[TimeRange, ...]:
    _validate_frame_ms(frame_ms)
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

    return _merge_ranges(tuple(ranges), merge_gap_ms=merge_gap_ms)


def collect_speech_ranges(
    flags: list[bool], *, frame_ms: int, boundary_padding_ms: int
) -> tuple[TimeRange, ...]:
    _validate_frame_ms(frame_ms)
    if boundary_padding_ms < 0:
        raise ValueError("boundary_padding_ms must be greater than or equal to 0")

    if not flags:
        return ()

    padding_frames = math.ceil(boundary_padding_ms / frame_ms)
    collected: list[TimeRange] = []
    start_index: int | None = None
    last_speech_index: int | None = None

    for index, is_speech in enumerate(flags):
        if is_speech:
            if start_index is None:
                start_index = max(0, index - padding_frames)
            last_speech_index = index
            continue

        if start_index is None or last_speech_index is None:
            continue

        if index - last_speech_index > padding_frames:
            end_index = min(len(flags), last_speech_index + 1 + padding_frames)
            collected.append(TimeRange(start_index * frame_ms / 1000, end_index * frame_ms / 1000))
            start_index = None
            last_speech_index = None

    if start_index is not None and last_speech_index is not None:
        end_index = min(len(flags), last_speech_index + 1 + padding_frames)
        collected.append(TimeRange(start_index * frame_ms / 1000, end_index * frame_ms / 1000))

    return _merge_ranges(tuple(collected), merge_gap_ms=0)


class WebRtcSpeechAnalyzer:
    def __init__(self, *, vad_mode: int, frame_ms: int = 30, boundary_padding_ms: int = 150) -> None:
        _validate_frame_ms(frame_ms)
        if boundary_padding_ms < 0:
            raise ValueError("boundary_padding_ms must be greater than or equal to 0")
        self._vad = webrtcvad.Vad(vad_mode)
        self._frame_ms = frame_ms
        self._boundary_padding_ms = boundary_padding_ms

    def analyze(self, wav_path: Path) -> AnalysisTrack:
        with wave.open(str(wav_path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate_hz = handle.getframerate()
            comptype = handle.getcomptype()

            if channels != 1:
                raise MediaError("WAV input must be mono for WebRTC VAD")
            if sample_width != 2:
                raise MediaError("WAV input must be 16-bit PCM for WebRTC VAD")
            if comptype != "NONE":
                raise MediaError("WAV input must be uncompressed PCM for WebRTC VAD")
            if sample_rate_hz not in _SUPPORTED_SAMPLE_RATES:
                raise MediaError(
                    "WAV sample rate must be one of 8000, 16000, 32000, or 48000 Hz for WebRTC VAD"
                )

            pcm = handle.readframes(handle.getnframes())

        frames = split_frames(pcm, sample_rate_hz=sample_rate_hz, frame_ms=self._frame_ms)
        flags = [self._vad.is_speech(frame, sample_rate_hz) for frame in frames]
        return AnalysisTrack(
            name="speech",
            ranges=collect_speech_ranges(
                flags,
                frame_ms=self._frame_ms,
                boundary_padding_ms=self._boundary_padding_ms,
            ),
            metadata={"frame_ms": str(self._frame_ms)},
        )
