from importlib import import_module

__all__ = [
    "WebRtcSpeechAnalyzer",
    "collect_speech_ranges",
    "collapse_speech_flags",
    "frame_duration_bytes",
    "refine_speech_ranges",
    "split_frames",
]

_EXPORTS = {
    "WebRtcSpeechAnalyzer": ("sound_cut.analysis.vad", "WebRtcSpeechAnalyzer"),
    "collect_speech_ranges": ("sound_cut.analysis.vad", "collect_speech_ranges"),
    "collapse_speech_flags": ("sound_cut.analysis.vad", "collapse_speech_flags"),
    "frame_duration_bytes": ("sound_cut.analysis.vad", "frame_duration_bytes"),
    "refine_speech_ranges": ("sound_cut.analysis.pause_splitter", "refine_speech_ranges"),
    "split_frames": ("sound_cut.analysis.vad", "split_frames"),
}


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
