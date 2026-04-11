from __future__ import annotations

from dataclasses import replace
import shutil
import tempfile
from pathlib import Path

from sound_cut.analysis.pause_splitter import refine_speech_ranges
from sound_cut.core.config import CutProfile
from sound_cut.core.errors import MediaError, NoSpeechDetectedError
from sound_cut.core.models import (
    DEFAULT_TARGET_LUFS,
    EnhancementConfig,
    LoudnessNormalizationConfig,
    RenderPlan,
    RenderSummary,
    SubtitleConfig,
)
from sound_cut.editing.timeline import build_edit_decision_list
from sound_cut.enhancement.pipeline import enhance_audio
from sound_cut.media.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media, embed_subtitle_track
from sound_cut.media.render import (
    render_audio_from_edl,
    render_full_audio,
    render_full_video,
    render_video_from_edl,
)
from sound_cut.subtitles.pipeline import generate_subtitles

_VIDEO_OUTPUT_SUFFIXES = {".mp4"}


def _apply_subtitles(
    rendered_path: Path,
    subtitle_config: SubtitleConfig,
    *,
    has_video: bool,
) -> Path | None:
    """Transcribe rendered output and embed/write subtitles.

    Default (sidecar_only=False):
      - Video: embed as soft subtitle track; no sidecar file kept → returns None.
      - Audio: write .srt/.vtt sidecar → returns sidecar path.

    With sidecar_only=True:
      - Write subtitle file only, skip embedding → returns sidecar path.
    """
    if has_video and not subtitle_config.sidecar_only:
        # Embed into video; keep everything in a temp dir (no permanent sidecar)
        with tempfile.TemporaryDirectory(prefix="sound-cut-subs-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            temp_srt = temp_dir / "subtitle.srt"
            # ffmpeg mov_text/srt codecs require SRT — always generate SRT for embedding
            generate_subtitles(rendered_path, temp_srt, replace(subtitle_config, format="srt"))
            temp_with_subs = temp_dir / rendered_path.name
            embed_subtitle_track(rendered_path, temp_srt, temp_with_subs)
            shutil.move(str(temp_with_subs), str(rendered_path))
        return None

    # Audio-only or explicit sidecar_only: write subtitle file beside the output
    subtitle_path = rendered_path.with_suffix(f".{subtitle_config.format}")
    generate_subtitles(rendered_path, subtitle_path, subtitle_config)
    return subtitle_path


def _refine_analysis_ranges(normalized_path: Path, analysis, profile: CutProfile):
    if not profile.pause_split.enabled:
        return analysis

    return replace(
        analysis,
        ranges=refine_speech_ranges(
            normalized_path,
            coarse_ranges=analysis.ranges,
            config=profile.pause_split,
        ),
    )


def _analyze_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    analyzer=None,
    keep_temp: bool = False,
) -> tuple[object, Path]:
    if keep_temp:
        normalized_path = output_path.with_name(f"{output_path.stem}.analysis.wav")
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16_000)
        if analyzer is None:
            from sound_cut.analysis.vad import WebRtcSpeechAnalyzer

            analyzer = WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
        analysis = analyzer.analyze(normalized_path)
        analysis = _refine_analysis_ranges(normalized_path, analysis, profile)
    else:
        with tempfile.TemporaryDirectory(prefix="sound-cut-analysis-") as temp_dir_name:
            normalized_path = Path(temp_dir_name) / "analysis.wav"
            normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16_000)
            if analyzer is None:
                from sound_cut.analysis.vad import WebRtcSpeechAnalyzer

                analyzer = WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
            analysis = analyzer.analyze(normalized_path)
            analysis = _refine_analysis_ranges(normalized_path, analysis, profile)

    return analysis, normalized_path


def _process_cut_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    *,
    source,
    analyzer,
    keep_temp: bool,
    loudness: LoudnessNormalizationConfig,
) -> RenderSummary:
    plan = _build_cut_plan(
        input_path=input_path,
        output_path=output_path,
        profile=profile,
        source=source,
        analyzer=analyzer,
        keep_temp=keep_temp,
        loudness=loudness,
    )
    return render_audio_from_edl(plan)


def _build_cut_plan(
    *,
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    source,
    analyzer,
    keep_temp: bool,
    loudness: LoudnessNormalizationConfig,
) -> RenderPlan:
    analysis, _ = _analyze_audio(
        input_path=input_path,
        output_path=output_path,
        profile=profile,
        analyzer=analyzer,
        keep_temp=keep_temp,
    )

    if not analysis.ranges:
        raise NoSpeechDetectedError(f"No speech detected in {input_path}")

    edl = build_edit_decision_list(
        duration_s=source.duration_s,
        speech_ranges=analysis.ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )
    return RenderPlan(
        source=source,
        edl=edl,
        output_path=output_path,
        target="audio",
        crossfade_ms=profile.crossfade_ms,
        loudness=loudness,
    )


def _process_cut_video(
    *,
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    video_source,
    audio_source,
    analyzer,
    keep_temp: bool,
    loudness: LoudnessNormalizationConfig,
) -> RenderSummary:
    audio_plan = _build_cut_plan(
        input_path=input_path,
        output_path=output_path,
        profile=profile,
        source=audio_source,
        analyzer=analyzer,
        keep_temp=keep_temp,
        loudness=loudness,
    )
    return render_video_from_edl(video_source=video_source, audio_plan=audio_plan)


def process_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    *,
    enable_cut: bool = True,
    analyzer=None,
    keep_temp: bool = False,
    loudness: LoudnessNormalizationConfig | None = None,
    enhancement: EnhancementConfig | None = None,
    subtitle: SubtitleConfig | None = None,
) -> RenderSummary:
    if input_path.resolve(strict=False) == output_path.resolve(strict=False):
        raise MediaError(f"Input and output paths must be different: {input_path}")

    if not input_path.exists():
        raise MediaError(f"Input media not found: {input_path}")

    original_source = probe_source_media(input_path)
    enhancement_config = enhancement
    if enhancement_config is None:
        enhancement_config = EnhancementConfig(enabled=False)

    loudness_config = loudness
    if loudness_config is None:
        loudness_config = LoudnessNormalizationConfig(enabled=False, target_lufs=DEFAULT_TARGET_LUFS)

    render_video_output = (
        original_source.has_video and output_path.suffix.lower() in _VIDEO_OUTPUT_SUFFIXES
    )

    with tempfile.TemporaryDirectory(prefix="sound-cut-enhance-") as temp_dir_name:
        working_input_path = enhance_audio(
            input_path=input_path,
            enhancement=enhancement_config,
            working_dir=Path(temp_dir_name),
        )
        processing_source = replace(original_source, input_path=working_input_path)

        if enable_cut:
            if render_video_output:
                summary = _process_cut_video(
                    input_path=working_input_path,
                    output_path=output_path,
                    profile=profile,
                    video_source=original_source,
                    audio_source=processing_source,
                    analyzer=analyzer,
                    keep_temp=keep_temp,
                    loudness=loudness_config,
                )
            else:
                summary = _process_cut_audio(
                    input_path=working_input_path,
                    output_path=output_path,
                    profile=profile,
                    source=processing_source,
                    analyzer=analyzer,
                    keep_temp=keep_temp,
                    loudness=loudness_config,
                )
        elif render_video_output:
            summary = render_full_video(
                video_source=original_source,
                audio_source=processing_source,
                output_path=output_path,
                loudness=loudness_config,
            )
        else:
            summary = render_full_audio(
                source=processing_source,
                output_path=output_path,
                loudness=loudness_config,
            )

    subtitle_path: Path | None = None
    if subtitle is not None and subtitle.enabled:
        subtitle_path = _apply_subtitles(
            rendered_path=output_path,
            subtitle_config=subtitle,
            has_video=render_video_output,
        )

    return replace(summary, subtitle_path=subtitle_path)
