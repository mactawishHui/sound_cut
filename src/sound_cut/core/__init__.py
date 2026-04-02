from importlib import import_module

__all__ = [
    "AnalysisTrack",
    "CutProfile",
    "DependencyError",
    "EditDecisionList",
    "EditOperation",
    "MediaError",
    "NoSpeechDetectedError",
    "PauseSplitConfig",
    "RenderPlan",
    "RenderSummary",
    "SoundCutError",
    "SourceMedia",
    "TimeRange",
    "build_profile",
]

_EXPORTS = {
    "AnalysisTrack": ("sound_cut.core.models", "AnalysisTrack"),
    "CutProfile": ("sound_cut.core.config", "CutProfile"),
    "DependencyError": ("sound_cut.core.errors", "DependencyError"),
    "EditDecisionList": ("sound_cut.core.models", "EditDecisionList"),
    "EditOperation": ("sound_cut.core.models", "EditOperation"),
    "MediaError": ("sound_cut.core.errors", "MediaError"),
    "NoSpeechDetectedError": ("sound_cut.core.errors", "NoSpeechDetectedError"),
    "PauseSplitConfig": ("sound_cut.core.models", "PauseSplitConfig"),
    "RenderPlan": ("sound_cut.core.models", "RenderPlan"),
    "RenderSummary": ("sound_cut.core.models", "RenderSummary"),
    "SoundCutError": ("sound_cut.core.errors", "SoundCutError"),
    "SourceMedia": ("sound_cut.core.models", "SourceMedia"),
    "TimeRange": ("sound_cut.core.models", "TimeRange"),
    "build_profile": ("sound_cut.core.config", "build_profile"),
}


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
