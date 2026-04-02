from __future__ import annotations

from dataclasses import replace
import tempfile
from pathlib import Path

from sound_cut.analysis.pause_splitter import refine_speech_ranges
from sound_cut.core.config import CutProfile
from sound_cut.core.errors import MediaError, NoSpeechDetectedError
from sound_cut.core.models import RenderPlan, RenderSummary
from sound_cut.editing.timeline import build_edit_decision_list
from sound_cut.media.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from sound_cut.media.render import render_audio_from_edl


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


def process_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    analyzer=None,
    keep_temp: bool = False,
) -> RenderSummary:
    if input_path.resolve(strict=False) == output_path.resolve(strict=False):
        raise MediaError(f"Input and output paths must be different: {input_path}")

    if not input_path.exists():
        raise MediaError(f"Input media not found: {input_path}")

    source = probe_source_media(input_path)

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

    if not analysis.ranges:
        raise NoSpeechDetectedError(f"No speech detected in {input_path}")

    edl = build_edit_decision_list(
        duration_s=source.duration_s,
        speech_ranges=analysis.ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )
    plan = RenderPlan(
        source=source,
        edl=edl,
        output_path=output_path,
        target="audio",
        crossfade_ms=profile.crossfade_ms,
    )
    return render_audio_from_edl(plan)
