from __future__ import annotations

import math
import wave
from pathlib import Path

from sound_cut.models import PauseSplitConfig, TimeRange


def _seconds_to_frames(seconds: float, sample_rate_hz: int) -> int:
    return int(round(seconds * sample_rate_hz))


def _frames_to_seconds(frame_index: int, sample_rate_hz: int) -> float:
    return round(frame_index / sample_rate_hz, 6)


def _window_rms(samples: memoryview, channels: int, start_frame: int, end_frame: int) -> float:
    start_sample = start_frame * channels
    end_sample = end_frame * channels
    if end_sample <= start_sample:
        return 0.0

    total = 0
    sample_count = 0
    for index in range(start_sample, end_sample):
        sample = int(samples[index])
        total += sample * sample
        sample_count += 1
    return math.sqrt(total / sample_count) if sample_count else 0.0


def refine_speech_ranges(
    wav_path: Path,
    *,
    coarse_ranges: tuple[TimeRange, ...],
    config: PauseSplitConfig,
) -> tuple[TimeRange, ...]:
    if not config.enabled or not coarse_ranges:
        return coarse_ranges

    with wave.open(str(wav_path), "rb") as handle:
        sample_rate_hz = handle.getframerate()
        channels = handle.getnchannels()
        frame_count = handle.getnframes()
        raw_samples = handle.readframes(frame_count)

    samples = memoryview(raw_samples).cast("h")
    window_frames = max(1, int(round(sample_rate_hz * config.window_ms / 1000)))
    min_pause_frames = max(1, _seconds_to_frames(config.min_pause_ms / 1000, sample_rate_hz))
    context_frames = max(1, _seconds_to_frames(config.context_ms / 1000, sample_rate_hz))

    refined_ranges: list[TimeRange] = []
    for coarse_range in coarse_ranges:
        start_frame = max(0, _seconds_to_frames(coarse_range.start_s, sample_rate_hz))
        end_frame = min(frame_count, _seconds_to_frames(coarse_range.end_s, sample_rate_hz))
        if coarse_range.duration_s < config.min_envelope_s or end_frame <= start_frame:
            refined_ranges.append(coarse_range)
            continue

        window_bounds: list[tuple[int, int]] = []
        window_energies: list[float] = []
        for window_start in range(start_frame, end_frame, window_frames):
            window_end = min(end_frame, window_start + window_frames)
            window_bounds.append((window_start, window_end))
            window_energies.append(_window_rms(samples, channels, window_start, window_end))

        if not window_energies:
            refined_ranges.append(coarse_range)
            continue

        energy_threshold = max(window_energies) * config.low_energy_ratio
        chosen_valley: tuple[int, int] | None = None
        index = 0
        while index < len(window_energies):
            if window_energies[index] > energy_threshold:
                index += 1
                continue

            valley_start_index = index
            while index < len(window_energies) and window_energies[index] <= energy_threshold:
                index += 1
            valley_end_index = index - 1

            valley_start_frame = window_bounds[valley_start_index][0]
            valley_end_frame = window_bounds[valley_end_index][1]
            valley_duration_frames = valley_end_frame - valley_start_frame
            if valley_duration_frames < min_pause_frames:
                continue
            if valley_start_frame - start_frame < context_frames:
                continue
            if end_frame - valley_end_frame < context_frames:
                continue
            chosen_valley = (valley_start_frame, valley_end_frame)
            break

        if chosen_valley is None:
            refined_ranges.append(coarse_range)
            continue

        valley_start_frame, valley_end_frame = chosen_valley
        if valley_start_frame > start_frame:
            refined_ranges.append(
                TimeRange(
                    _frames_to_seconds(start_frame, sample_rate_hz),
                    _frames_to_seconds(valley_start_frame, sample_rate_hz),
                )
            )
        if valley_end_frame < end_frame:
            refined_ranges.append(
                TimeRange(
                    _frames_to_seconds(valley_end_frame, sample_rate_hz),
                    _frames_to_seconds(end_frame, sample_rate_hz),
                )
            )

    return tuple(refined_ranges)
