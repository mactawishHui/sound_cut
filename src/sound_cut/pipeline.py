from __future__ import annotations

import tempfile
from pathlib import Path

from sound_cut.config import CutProfile
from sound_cut.errors import MediaError, NoSpeechDetectedError
from sound_cut.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from sound_cut.models import RenderPlan, RenderSummary
from sound_cut.render import render_audio_from_edl
from sound_cut.timeline import build_edit_decision_list
from sound_cut.vad import WebRtcSpeechAnalyzer


def process_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    analyzer=None,
) -> RenderSummary:
    if not input_path.exists():
        raise MediaError(f"Input media not found: {input_path}")

    source = probe_source_media(input_path)

    with tempfile.TemporaryDirectory(prefix="sound-cut-analysis-") as temp_dir_name:
        normalized_path = Path(temp_dir_name) / "analysis.wav"
        normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16_000)
        speech_analyzer = analyzer or WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
        analysis = speech_analyzer.analyze(normalized_path)

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
