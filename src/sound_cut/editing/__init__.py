from importlib import import_module

__all__ = [
    "build_edit_decision_list",
    "kept_ranges",
    "process_audio",
    "source_to_output_time",
]

_EXPORTS = {
    "build_edit_decision_list": ("sound_cut.editing.timeline", "build_edit_decision_list"),
    "kept_ranges": ("sound_cut.editing.timeline", "kept_ranges"),
    "process_audio": ("sound_cut.editing.pipeline", "process_audio"),
    "source_to_output_time": ("sound_cut.editing.timeline", "source_to_output_time"),
}


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
