from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from sound_cut.core.errors import DependencyError, MediaError
from sound_cut.core.models import SourceMedia

_MIN_DELIVERY_BIT_RATE_BPS = 64_000
_MAX_DELIVERY_BIT_RATE_BPS = 128_000


def _require_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise DependencyError(f"Required dependency '{name}' is not installed or not on PATH")
    return binary


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or "ffmpeg command failed"
        raise MediaError(message) from exc


def _parse_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _estimate_bit_rate_bps(input_path: Path, *, duration_s: float) -> int | None:
    if duration_s <= 0:
        return None
    try:
        size_bytes = input_path.stat().st_size
    except OSError:
        return None
    return round(size_bytes * 8 / duration_s)


def _parse_source_media(payload: dict, *, input_path: Path) -> SourceMedia:
    streams = payload["streams"]
    format_data = payload["format"]
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    duration_s = float(format_data["duration"])
    if video_stream is not None:
        bit_rate_bps = _parse_int(audio_stream.get("bit_rate"))
    else:
        bit_rate_bps = _parse_int(format_data.get("bit_rate"))
        if bit_rate_bps is None:
            bit_rate_bps = _parse_int(audio_stream.get("bit_rate"))
        if bit_rate_bps is None:
            bit_rate_bps = _estimate_bit_rate_bps(input_path, duration_s=duration_s)
    return SourceMedia(
        input_path=input_path,
        duration_s=duration_s,
        audio_codec=audio_stream.get("codec_name"),
        sample_rate_hz=_parse_int(audio_stream.get("sample_rate")),
        channels=_parse_int(audio_stream.get("channels")),
        bit_rate_bps=bit_rate_bps,
        has_video=video_stream is not None,
    )


def probe_source_media(input_path: Path) -> SourceMedia:
    ffprobe = _require_binary("ffprobe")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(input_path),
        ]
    )
    try:
        payload = json.loads(result.stdout)
        return _parse_source_media(payload, input_path=input_path)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MediaError(f"Invalid ffprobe JSON for {input_path}") from exc


def normalize_audio_for_analysis(input_path: Path, output_path: Path, *, sample_rate_hz: int) -> None:
    ffmpeg = _require_binary("ffmpeg")
    _run(
        [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate_hz),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(output_path),
        ]
    )


def normalize_loudness(source_wav: Path, output_wav: Path, *, target_lufs: float) -> None:
    ffmpeg = _require_binary("ffmpeg")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    sample_rate_hz: int | None = None
    channels: int | None = None
    try:
        source_media = probe_source_media(source_wav)
        sample_rate_hz = source_media.sample_rate_hz
        channels = source_media.channels
    except (DependencyError, MediaError):
        pass

    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(source_wav),
        "-vn",
        "-af",
        f"loudnorm=I={target_lufs}",
        "-c:a",
        "pcm_s16le",
    ]
    if sample_rate_hz is not None:
        command.extend(["-ar", str(sample_rate_hz)])
    if channels is not None:
        command.extend(["-ac", str(channels)])
    command.extend(
        [
            "-f",
            "wav",
            str(output_wav),
        ]
    )
    _run(
        command
    )


def _subtitle_codec_for_suffix(suffix: str) -> str:
    mapping = {
        ".mp4": "mov_text",
        ".mov": "mov_text",
        ".m4v": "mov_text",
        ".mkv": "srt",
    }
    try:
        return mapping[suffix.lower()]
    except KeyError as exc:
        raise MediaError(f"Unsupported video container for subtitle embedding: {suffix}") from exc


def delivery_codec_for_suffix(suffix: str) -> tuple[str, str | None]:
    mapping = {
        ".mp3": ("libmp3lame", "128k"),
        ".m4a": ("aac", "128k"),
        ".wav": ("pcm_s16le", None),
    }
    try:
        return mapping[suffix.lower()]
    except KeyError as exc:
        raise MediaError(f"Unsupported output format: {suffix}") from exc


def resolve_delivery_bitrate_bps(source: SourceMedia, suffix: str) -> int | None:
    suffix = suffix.lower()
    if suffix == ".wav":
        return None
    if suffix not in {".mp3", ".m4a"}:
        raise MediaError(f"Unsupported output format: {suffix}")
    if source.bit_rate_bps is None:
        return _MAX_DELIVERY_BIT_RATE_BPS
    return min(
        max(source.bit_rate_bps, _MIN_DELIVERY_BIT_RATE_BPS),
        _MAX_DELIVERY_BIT_RATE_BPS,
    )


def export_delivery_audio(source_wav: Path, output_path: Path, source: SourceMedia) -> None:
    ffmpeg = _require_binary("ffmpeg")
    codec_name, _ = delivery_codec_for_suffix(output_path.suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(source_wav),
        "-c:a",
        codec_name,
    ]
    audio_bitrate_bps = resolve_delivery_bitrate_bps(source, output_path.suffix)
    if audio_bitrate_bps is not None:
        command.extend(["-b:a", str(audio_bitrate_bps)])
    if output_path.suffix.lower() == ".m4a":
        command.extend(["-f", "ipod"])
    elif output_path.suffix.lower() == ".wav":
        command.extend(["-f", "wav"])
    command.append(str(output_path))
    _run(command)


def embed_subtitle_track_mkv(
    video_path: Path, srt_path: Path, mkv_path: Path, *, language: str | None = None
) -> None:
    """Mux video + SRT into an MKV file using pure stream copy (no re-encode).

    MKV is the recommended soft-subtitle container: virtually all major players
    (VLC, mpv, most smart TVs and mobile apps) auto-display subtitle tracks
    embedded in MKV without any extra configuration.

    The original video and audio streams are copied without quality loss.
    """
    ffmpeg = _require_binary("ffmpeg")
    mkv_path.parent.mkdir(parents=True, exist_ok=True)
    # ISO 639-2 three-letter language code for the subtitle stream metadata.
    # Defaults to "und" (undetermined) when language is None or unrecognised.
    _LANG_MAP = {
        "zh": "chi", "zh-cn": "chi", "zh-tw": "chi",
        "en": "eng", "ja": "jpn", "ko": "kor",
        "fr": "fre", "de": "ger", "es": "spa",
    }
    lang3 = _LANG_MAP.get((language or "").lower(), "und")
    _run(
        [
            ffmpeg, "-y", "-nostats", "-loglevel", "error",
            "-i", str(video_path),
            "-i", str(srt_path),
            "-c:v", "copy",
            "-c:a", "copy",
            "-c:s", "subrip",
            "-map", "0:v",
            "-map", "0:a",
            "-map", "1:s",
            "-metadata:s:s:0", f"language={lang3}",
            str(mkv_path),
        ]
    )


def embed_subtitle_track(video_path: Path, srt_path: Path, output_path: Path) -> None:
    ffmpeg = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subtitle_codec = _subtitle_codec_for_suffix(output_path.suffix)
    _run(
        [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(srt_path),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            subtitle_codec,
            "-map",
            "0:v",
            "-map",
            "0:a",
            "-map",
            "1:s",
            str(output_path),
        ]
    )


# ---------------------------------------------------------------------------
# Subtitle burn-in helpers
# ---------------------------------------------------------------------------

_SRT_TS_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def _srt_ts_to_s(ts: str) -> float:
    ts = ts.replace(",", ".")
    h, m, rest = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def _parse_srt_file(srt_path: Path) -> list[tuple[float, float, str]]:
    """Parse an SRT file into a list of (start_s, end_s, text) tuples."""
    text = srt_path.read_text(encoding="utf-8", errors="replace")
    segments: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        ts_match = next(
            (m for line in lines for m in [_SRT_TS_RE.match(line.strip())] if m),
            None,
        )
        if ts_match is None:
            continue
        ts_line = next(i for i, l in enumerate(lines) if _SRT_TS_RE.match(l.strip()))
        sub_text = re.sub(r"<[^>]+>", "", " ".join(lines[ts_line + 1:])).strip()
        if sub_text:
            segments.append((_srt_ts_to_s(ts_match.group(1)), _srt_ts_to_s(ts_match.group(2)), sub_text))
    return segments


def _find_cjk_font() -> str | None:
    """Return the first available CJK-capable font path, or None."""
    candidates = [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode MS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    return next((p for p in candidates if Path(p).exists()), None)


def _get_video_wh(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream."""
    ffprobe = _require_binary("ffprobe")
    result = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(video_path),
    ])
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _burn_subtitles_pillow(
    ffmpeg: str,
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    codec_candidates: list[list[str]],
) -> None:
    """Burn subtitles using Pillow image rendering + ffmpeg overlay.

    Falls back to this when the local ffmpeg binary is not compiled with
    ``--enable-libass`` (no ``subtitles`` filter available).
    Requires the Pillow library (``pip install Pillow``).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore[import]
    except ImportError:
        raise MediaError(
            "Burning subtitles requires either ffmpeg with --enable-libass "
            "or the Pillow library. Install with: pip install Pillow"
        )

    segments = _parse_srt_file(srt_path)
    if not segments:
        raise MediaError("No subtitle segments found in SRT file for burning")

    width, height = _get_video_wh(video_path)
    duration_s = probe_source_media(video_path).duration_s

    sub_h = max(60, height // 12)
    font_size = max(20, height // 28)
    font_path = _find_cjk_font()
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    with tempfile.TemporaryDirectory(prefix="sound-cut-subtpng-") as tmp_name:
        tmp = Path(tmp_name)

        # Transparent blank image (shown when no subtitle is active)
        blank = Image.new("RGBA", (width, sub_h), (0, 0, 0, 0))
        blank_path = tmp / "blank.png"
        blank.save(blank_path)

        # One PNG per subtitle segment
        for i, (_, _, text) in enumerate(segments):
            img = Image.new("RGBA", (width, sub_h), (0, 0, 0, 160))
            draw = ImageDraw.Draw(img)
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except AttributeError:
                tw, th = draw.textsize(text, font=font)  # type: ignore[attr-defined]
            x, y = max(0.0, (width - tw) / 2), max(0.0, (sub_h - th) / 2)
            for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
            img.save(tmp / f"sub_{i:04d}.png")

        # Build ffmpeg concat script with correct per-segment durations
        concat_lines: list[str] = []
        prev_end = 0.0
        for i, (start_s, end_s, _) in enumerate(segments):
            gap = start_s - prev_end
            if gap > 0.001:
                concat_lines += [f"file '{blank_path}'", f"duration {gap:.3f}"]
            sub_dur = max(0.001, end_s - start_s)
            concat_lines += [f"file '{tmp / f'sub_{i:04d}.png'}'", f"duration {sub_dur:.3f}"]
            prev_end = end_s
        final_gap = duration_s - prev_end
        if final_gap > 0.001:
            concat_lines += [f"file '{blank_path}'", f"duration {final_gap:.3f}"]
        # Concat demuxer needs the last file repeated to flush the final frame
        last_file = next(l for l in reversed(concat_lines) if l.startswith("file "))
        concat_lines.append(last_file)

        concat_path = tmp / "subtitle_overlay.txt"
        concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        last_err: MediaError | None = None
        for codec_args in codec_candidates:
            try:
                # NOTE: do NOT pass -r to the concat input — that overrides the
                # per-entry "duration" values and collapses all frames to 1/r
                # seconds each, causing all subtitles to appear in the first
                # few seconds.  Without -r the concat demuxer uses the explicit
                # duration values and produces correctly-timed pts.
                _run([
                    ffmpeg, "-y", "-nostats", "-loglevel", "error",
                    "-i", str(video_path),
                    "-f", "concat", "-safe", "0", "-i", str(concat_path),
                    "-filter_complex",
                    "[1:v]setpts=PTS-STARTPTS[subs];[0:v][subs]overlay=(W-w)/2:H-h-20:eof_action=endall,format=yuv420p[out]",
                    "-map", "[out]",
                    "-map", "0:a",
                    *codec_args,
                    "-movflags", "+faststart",
                    str(output_path),
                ])
                return
            except MediaError as exc:
                last_err = exc
        raise last_err  # type: ignore[misc]


def _detect_video_codec(video_path: Path) -> str | None:
    """Return the codec_name of the first video stream, or None."""
    try:
        ffprobe = _require_binary("ffprobe")
        result = _run([
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "json", str(video_path),
        ])
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        return streams[0].get("codec_name") if streams else None
    except Exception:
        return None


def _probe_video_bitrate(video_path: Path) -> int | None:
    """Return the video stream bitrate in bits/s, or None if unavailable."""
    try:
        ffprobe = _require_binary("ffprobe")
        result = _run([
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate",
            "-of", "json", str(video_path),
        ])
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        br = streams[0].get("bit_rate") if streams else None
        return int(br) if br and str(br).isdigit() else None
    except Exception:
        return None


def _codec_candidates_for_video(video_path: Path) -> list[list[str]]:
    """Return ffmpeg codec arg lists to try in order.

    Prefer matching the source codec so the output size stays close to
    the original.  Target bitrate is set to match the source so the
    re-encoded file stays the same size.
    """
    src_codec = _detect_video_codec(video_path) or ""
    src_br = _probe_video_bitrate(video_path)
    # Add 5 % headroom for subtitle overlay pixels; fall back to 800 kbps if unknown.
    # src_br is already in bits/s; pass it directly to ffmpeg -b:v (also bits/s).
    target_br_val = str(int((src_br or 800_000) * 1.05))

    if src_codec in ("hevc", "h265"):
        return [
            ["-c:v", "hevc_videotoolbox", "-b:v", target_br_val],   # macOS HW HEVC
            ["-c:v", "libx265", "-b:v", target_br_val, "-preset", "fast"],  # SW HEVC
            ["-c:v", "h264_videotoolbox", "-b:v", target_br_val],   # macOS HW H.264
            ["-c:v", "libx264", "-b:v", target_br_val, "-preset", "fast"],  # SW H.264
        ]
    return [
        ["-c:v", "h264_videotoolbox", "-b:v", target_br_val],
        ["-c:v", "libx264", "-b:v", target_br_val, "-preset", "fast"],
        ["-c:v", "hevc_videotoolbox", "-b:v", target_br_val],
        ["-c:v", "libx265", "-b:v", target_br_val, "-preset", "fast"],
    ]


def burn_subtitle_track(video_path: Path, srt_path: Path, output_path: Path) -> None:
    """Hard-burn subtitles into the video frames (always visible in any player).

    Tries the ffmpeg ``subtitles`` filter first (requires libass).  If that
    filter is not available in the local binary, falls back to a Pillow-based
    image overlay (requires ``pip install Pillow``).

    Re-encodes using the same codec as the source video to avoid inflating
    the file size (e.g. HEVC source → HEVC output via hevc_videotoolbox).
    """
    ffmpeg = _require_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    codec_candidates = _codec_candidates_for_video(video_path)

    # --- Primary path: libass subtitles filter ---
    srt_filter_path = (
        str(srt_path.absolute())
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
    vf = f"subtitles=filename={srt_filter_path}"

    use_pillow_fallback = False
    last_err: MediaError | None = None
    for codec_args in codec_candidates:
        try:
            _run([
                ffmpeg, "-y", "-nostats", "-loglevel", "error",
                "-i", str(video_path),
                "-vf", vf, *codec_args,
                "-c:a", "copy", "-movflags", "+faststart",
                str(output_path),
            ])
            return
        except MediaError as exc:
            err_str = str(exc)
            if "No such filter" in err_str or "Filter not found" in err_str:
                use_pillow_fallback = True
                break
            last_err = exc

    if last_err is not None and not use_pillow_fallback:
        raise last_err

    # --- Fallback: Pillow-based PNG overlay (no libass needed) ---
    _burn_subtitles_pillow(ffmpeg, video_path, srt_path, output_path, codec_candidates)
