from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


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
    has_video: bool = False


@dataclass(frozen=True)
class AnalysisTrack:
    name: str
    ranges: tuple[TimeRange, ...]
    metadata: dict[str, str] = field(default_factory=dict)


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


@dataclass(frozen=True)
class RenderSummary:
    input_duration_s: float
    output_duration_s: float
    removed_duration_s: float
    kept_segment_count: int
