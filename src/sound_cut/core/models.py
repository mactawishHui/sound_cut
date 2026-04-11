from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

DEFAULT_TARGET_LUFS = -16.0
SUPPORTED_ENHANCEMENT_BACKENDS = ("deepfilternet3", "resemble-enhance")
SUPPORTED_ENHANCEMENT_PROFILES = ("natural", "strong")


@dataclass(frozen=True, order=True)
class TimeRange:
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError("end_s must be >= start_s")

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class SourceMedia:
    input_path: Path
    duration_s: float
    audio_codec: str | None
    sample_rate_hz: int | None
    channels: int | None
    bit_rate_bps: int | None = None
    has_video: bool = False


@dataclass(frozen=True)
class PauseSplitConfig:
    enabled: bool
    min_envelope_s: float
    window_ms: int
    low_energy_ratio: float
    min_pause_ms: int
    context_ms: int


@dataclass(frozen=True)
class LoudnessNormalizationConfig:
    enabled: bool
    target_lufs: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_lufs):
            raise ValueError("target_lufs must be finite")


@dataclass(frozen=True)
class EnhancementConfig:
    enabled: bool
    backend: str = "deepfilternet3"
    profile: str = "natural"
    model_path: Path | None = None

    def __post_init__(self) -> None:
        if self.model_path is not None and not isinstance(self.model_path, Path):
            object.__setattr__(self, "model_path", Path(self.model_path))
        if self.backend not in SUPPORTED_ENHANCEMENT_BACKENDS:
            raise ValueError(f"backend must be one of {SUPPORTED_ENHANCEMENT_BACKENDS!r}")
        if self.profile not in SUPPORTED_ENHANCEMENT_PROFILES:
            raise ValueError(f"profile must be one of {SUPPORTED_ENHANCEMENT_PROFILES!r}")


SUPPORTED_SUBTITLE_FORMATS = ("srt", "vtt")
SUPPORTED_SUBTITLE_MODELS = ("tiny", "base", "small", "medium", "large")


@dataclass(frozen=True)
class SubtitleSegment:
    index: int        # 1-based, per SRT spec
    start_s: float
    end_s: float
    text: str

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ValueError("index must be >= 1 (SRT is 1-based)")
        if self.end_s < self.start_s:
            raise ValueError("end_s must be >= start_s")


@dataclass(frozen=True)
class SubtitleConfig:
    enabled: bool
    language: str | None = None      # None = faster-whisper auto-detect
    format: str = "srt"              # "srt" | "vtt"
    model_size: str = "base"         # tiny | base | small | medium | large
    model_path: Path | None = None   # overrides HuggingFace cache dir

    def __post_init__(self) -> None:
        if self.format not in SUPPORTED_SUBTITLE_FORMATS:
            raise ValueError(f"format must be one of {SUPPORTED_SUBTITLE_FORMATS!r}")
        if self.model_size not in SUPPORTED_SUBTITLE_MODELS:
            raise ValueError(f"model_size must be one of {SUPPORTED_SUBTITLE_MODELS!r}")
        if self.model_path is not None and not isinstance(self.model_path, Path):
            object.__setattr__(self, "model_path", Path(self.model_path))


@dataclass(frozen=True)
class AnalysisTrack:
    name: str
    ranges: tuple[TimeRange, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class EditOperation:
    action: Literal["keep", "discard"]
    range: TimeRange
    reason: str | None = None


@dataclass(frozen=True)
class EditDecisionList:
    operations: tuple[EditOperation, ...]


@dataclass(frozen=True)
class RenderPlan:
    source: SourceMedia
    edl: EditDecisionList
    output_path: Path
    target: Literal["audio"]
    crossfade_ms: int
    loudness: LoudnessNormalizationConfig = field(
        default_factory=lambda: LoudnessNormalizationConfig(enabled=False, target_lufs=DEFAULT_TARGET_LUFS)
    )


@dataclass(frozen=True)
class RenderSummary:
    input_duration_s: float
    output_duration_s: float
    removed_duration_s: float
    kept_segment_count: int
    subtitle_path: Path | None = None
