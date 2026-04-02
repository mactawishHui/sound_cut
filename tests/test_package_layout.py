import importlib
import os
import subprocess
import sys
from pathlib import Path

from sound_cut.analysis import WebRtcSpeechAnalyzer, refine_speech_ranges
from sound_cut.core import (
    AnalysisTrack,
    CutProfile,
    RenderPlan,
    SoundCutError,
    TimeRange,
    build_profile,
)
from sound_cut.cli import main
from sound_cut.editing import build_edit_decision_list, kept_ranges, process_audio
from sound_cut.media import (
    delivery_codec_for_suffix,
    normalize_audio_for_analysis,
    probe_source_media,
    render_audio_from_edl,
)


def test_package_roots_export_current_entrypoints() -> None:
    assert AnalysisTrack
    assert build_profile
    assert CutProfile
    assert RenderPlan
    assert SoundCutError
    assert TimeRange
    assert main
    assert WebRtcSpeechAnalyzer
    assert refine_speech_ranges
    assert build_edit_decision_list
    assert kept_ranges
    assert process_audio
    assert delivery_codec_for_suffix
    assert normalize_audio_for_analysis
    assert probe_source_media
    assert render_audio_from_edl


def test_package_root_cold_imports_work_in_fresh_interpreter() -> None:
    env = os.environ.copy()
    src_dir = Path(__file__).resolve().parents[1] / "src"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_dir) if not existing_pythonpath else f"{src_dir}{os.pathsep}{existing_pythonpath}"

    checks = [
        ("from sound_cut.core import build_profile; print(build_profile('balanced').name)", "balanced"),
        (
            "from sound_cut.analysis import WebRtcSpeechAnalyzer; print(WebRtcSpeechAnalyzer.__name__)",
            "WebRtcSpeechAnalyzer",
        ),
        (
            "from sound_cut.editing import build_edit_decision_list; print(build_edit_decision_list.__name__)",
            "build_edit_decision_list",
        ),
        ("from sound_cut.media import delivery_codec_for_suffix; print(delivery_codec_for_suffix('.wav'))", "('pcm_s16le', None)"),
    ]

    for command, expected_stdout in checks:
        result = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.stdout.strip() == expected_stdout


def test_flat_module_cold_imports_work_in_fresh_interpreter() -> None:
    env = os.environ.copy()
    src_dir = Path(__file__).resolve().parents[1] / "src"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_dir) if not existing_pythonpath else f"{src_dir}{os.pathsep}{existing_pythonpath}"

    checks = [
        ("from sound_cut.config import build_profile; print(build_profile('balanced').name)", "balanced"),
        ("from sound_cut.pipeline import process_audio; print(process_audio.__name__)", "process_audio"),
        ("from sound_cut.render import render_audio_from_edl; print(render_audio_from_edl.__name__)", "render_audio_from_edl"),
        ("from sound_cut.ffmpeg_tools import delivery_codec_for_suffix; print(delivery_codec_for_suffix('.wav'))", "('pcm_s16le', None)"),
    ]

    for command, expected_stdout in checks:
        result = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.stdout.strip() == expected_stdout


def test_flat_module_paths_alias_real_modules() -> None:
    assert importlib.import_module("sound_cut.config") is importlib.import_module("sound_cut.core.config")
    assert importlib.import_module("sound_cut.errors") is importlib.import_module("sound_cut.core.errors")
    assert importlib.import_module("sound_cut.models") is importlib.import_module("sound_cut.core.models")
    assert importlib.import_module("sound_cut.vad") is importlib.import_module("sound_cut.analysis.vad")
    assert importlib.import_module("sound_cut.pause_splitter") is importlib.import_module(
        "sound_cut.analysis.pause_splitter"
    )
    assert importlib.import_module("sound_cut.timeline") is importlib.import_module("sound_cut.editing.timeline")
    assert importlib.import_module("sound_cut.pipeline") is importlib.import_module("sound_cut.editing.pipeline")
    assert importlib.import_module("sound_cut.ffmpeg_tools") is importlib.import_module(
        "sound_cut.media.ffmpeg_tools"
    )
    assert importlib.import_module("sound_cut.render") is importlib.import_module("sound_cut.media.render")


def test_flat_module_paths_preserve_old_entrypoints_and_private_helpers() -> None:
    assert importlib.import_module("sound_cut.config").build_profile is build_profile
    assert importlib.import_module("sound_cut.errors").SoundCutError is SoundCutError
    assert importlib.import_module("sound_cut.models").RenderPlan is RenderPlan
    assert importlib.import_module("sound_cut.vad").WebRtcSpeechAnalyzer is WebRtcSpeechAnalyzer
    assert importlib.import_module("sound_cut.pause_splitter").refine_speech_ranges is refine_speech_ranges
    assert importlib.import_module("sound_cut.timeline").kept_ranges is kept_ranges
    assert importlib.import_module("sound_cut.pipeline").process_audio is process_audio
    assert importlib.import_module("sound_cut.ffmpeg_tools").probe_source_media is probe_source_media
    assert importlib.import_module("sound_cut.ffmpeg_tools")._parse_source_media
    assert importlib.import_module("sound_cut.ffmpeg_tools")._require_binary
    assert importlib.import_module("sound_cut.ffmpeg_tools")._run
    assert importlib.import_module("sound_cut.render").render_audio_from_edl is render_audio_from_edl
