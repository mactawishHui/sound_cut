from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CutProfile:
    name: str
    vad_mode: int
    merge_gap_ms: int
    min_silence_ms: int
    padding_ms: int
    crossfade_ms: int


_PROFILES = {
    "natural": CutProfile(
        "natural",
        vad_mode=1,
        merge_gap_ms=180,
        min_silence_ms=700,
        padding_ms=120,
        crossfade_ms=12,
    ),
    "balanced": CutProfile(
        "balanced",
        vad_mode=2,
        merge_gap_ms=200,
        min_silence_ms=550,
        padding_ms=100,
        crossfade_ms=10,
    ),
    "dense": CutProfile(
        "dense",
        vad_mode=3,
        merge_gap_ms=220,
        min_silence_ms=380,
        padding_ms=80,
        crossfade_ms=8,
    ),
}


def build_profile(name: str) -> CutProfile:
    return _PROFILES[name]
