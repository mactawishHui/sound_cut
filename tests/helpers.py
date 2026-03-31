from __future__ import annotations

import math
import wave
from pathlib import Path


def write_pcm_wave(path: Path, *, sample_rate_hz: int, samples: list[int], channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(
            b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples)
        )


def tone_samples(
    *, sample_rate_hz: int, duration_s: float, frequency_hz: float = 220.0, amplitude: int = 6000
) -> list[int]:
    frame_count = int(sample_rate_hz * duration_s)
    return [
        int(amplitude * math.sin(2 * math.pi * frequency_hz * index / sample_rate_hz))
        for index in range(frame_count)
    ]


def silence_samples(*, sample_rate_hz: int, duration_s: float) -> list[int]:
    return [0] * int(sample_rate_hz * duration_s)
