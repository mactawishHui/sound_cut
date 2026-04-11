from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sound_cut.core.errors import DependencyError
from sound_cut.core.models import SubtitleConfig, SubtitleSegment

if TYPE_CHECKING:
    pass


def _require_faster_whisper():
    try:
        import faster_whisper  # noqa: F401
        return faster_whisper
    except ImportError as exc:
        raise DependencyError(
            "faster-whisper is required for subtitle generation. "
            "Install it with: pip install 'sound-cut[subtitle]'"
        ) from exc


class WhisperBackend:
    """Transcribes audio using faster-whisper (offline, local)."""

    def __init__(self, config: SubtitleConfig) -> None:
        self._config = config

    def transcribe(self, audio_path: Path) -> list[SubtitleSegment]:
        fw = _require_faster_whisper()
        model_kwargs: dict = {"model_size_or_path": self._config.model_size}
        if self._config.model_path is not None:
            model_kwargs["model_size_or_path"] = str(self._config.model_path)
        model = fw.WhisperModel(**model_kwargs)
        transcribe_kwargs: dict = {"audio": str(audio_path)}
        if self._config.language is not None:
            transcribe_kwargs["language"] = self._config.language
        segments, _info = model.transcribe(**transcribe_kwargs)
        result: list[SubtitleSegment] = []
        for i, seg in enumerate(segments, start=1):
            result.append(
                SubtitleSegment(
                    index=i,
                    start_s=seg.start,
                    end_s=seg.end,
                    text=seg.text.strip(),
                )
            )
        return result
