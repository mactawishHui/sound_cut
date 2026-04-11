from __future__ import annotations

from pathlib import Path

from sound_cut.core.models import SubtitleConfig, SubtitleSegment
from sound_cut.subtitles.formatter import write_srt, write_vtt
from sound_cut.subtitles.whisper import WhisperBackend


def generate_subtitles(audio_path: Path, output_path: Path, config: SubtitleConfig) -> Path:
    """Transcribe audio and write subtitle file; return the subtitle file path."""
    backend = WhisperBackend(config)
    segments = backend.transcribe(audio_path)
    if config.format == "vtt":
        write_vtt(segments, output_path)
    else:
        write_srt(segments, output_path)
    return output_path
