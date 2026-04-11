from __future__ import annotations

from pathlib import Path

from sound_cut.core.models import SubtitleSegment


def _ts_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round(seconds % 1 * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round(seconds % 1 * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def write_srt(segments: list[SubtitleSegment], path: Path) -> None:
    if not segments:
        path.write_text("", encoding="utf-8")
        return
    blocks = []
    for seg in segments:
        blocks.append(
            f"{seg.index}\n{_ts_srt(seg.start_s)} --> {_ts_srt(seg.end_s)}\n{seg.text}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_vtt(segments: list[SubtitleSegment], path: Path) -> None:
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_ts_vtt(seg.start_s)} --> {_ts_vtt(seg.end_s)}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
