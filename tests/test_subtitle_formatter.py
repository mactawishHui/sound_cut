from __future__ import annotations

from pathlib import Path

import pytest

from sound_cut.core.models import SubtitleSegment
from sound_cut.subtitles.formatter import write_srt, write_vtt


def test_write_srt_formats_single_segment(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.5, text="Hello")]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert "1\n" in content
    assert "00:00:00,000 --> 00:00:01,500" in content
    assert "Hello" in content


def test_write_srt_timestamp_with_hours(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=3661.5, end_s=3662.0, text="Late")]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert "01:01:01,500 --> 01:01:02,000" in content


def test_write_srt_multiple_segments_separated_by_blank_line(tmp_path: Path) -> None:
    segments = [
        SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="First"),
        SubtitleSegment(index=2, start_s=2.0, end_s=3.0, text="Second"),
    ]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert "First" in content
    assert "Second" in content
    assert "\n\n" in content


def test_write_srt_empty_segments_writes_empty_file(tmp_path: Path) -> None:
    srt_path = tmp_path / "out.srt"
    write_srt([], srt_path)
    assert srt_path.read_text(encoding="utf-8") == ""


def test_write_vtt_includes_webvtt_header(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="Hi")]
    vtt_path = tmp_path / "out.vtt"
    write_vtt(segments, vtt_path)
    content = vtt_path.read_text(encoding="utf-8")
    assert content.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in content
    assert "Hi" in content


def test_write_vtt_empty_segments_writes_header_only(tmp_path: Path) -> None:
    vtt_path = tmp_path / "out.vtt"
    write_vtt([], vtt_path)
    assert vtt_path.read_text(encoding="utf-8").strip() == "WEBVTT"


def test_write_srt_uses_utf8_encoding(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="你好世界")]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    assert "你好世界" in srt_path.read_text(encoding="utf-8")


def test_write_srt_timestamp_near_second_boundary_does_not_overflow(tmp_path: Path) -> None:
    # 1.9995 seconds: naive rounding of (seconds % 1) gives ms=1000 (bug)
    segments = [SubtitleSegment(index=1, start_s=1.9995, end_s=2.0, text="x")]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    # Must not contain ",1000"
    assert ",1000" not in content
