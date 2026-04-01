from __future__ import annotations

from dataclasses import dataclass

from sound_cut.models import PauseSplitConfig


@dataclass(frozen=True)
class CutProfile:
    name: str
    vad_mode: int
    merge_gap_ms: int
    min_silence_ms: int
    padding_ms: int
    crossfade_ms: int
    pause_split: PauseSplitConfig


_DISABLED_PAUSE_SPLIT = PauseSplitConfig(
    enabled=False,
    min_envelope_s=999.0,
    window_ms=30,
    low_energy_ratio=0.0,
    min_pause_ms=999_999,
    context_ms=0,
)


_PROFILES = {
    "natural": CutProfile(
        "natural",
        vad_mode=1,
        merge_gap_ms=180,
        min_silence_ms=700,
        padding_ms=120,
        crossfade_ms=12,
        pause_split=_DISABLED_PAUSE_SPLIT,
    ),
    "balanced": CutProfile(
        "balanced",
        vad_mode=2,
        merge_gap_ms=200,
        min_silence_ms=550,
        padding_ms=100,
        crossfade_ms=10,
        pause_split=_DISABLED_PAUSE_SPLIT,
    ),
    "dense": CutProfile(
        "dense",
        vad_mode=3,
        merge_gap_ms=220,
        min_silence_ms=140,
        padding_ms=40,
        crossfade_ms=5,
        pause_split=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.2,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=150,
            context_ms=180,
        ),
    ),
}


def build_profile(name: str) -> CutProfile:
    return _PROFILES[name]
