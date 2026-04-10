from importlib import import_module

__all__ = [
    "delivery_codec_for_suffix",
    "export_delivery_audio",
    "normalize_audio_for_analysis",
    "probe_source_media",
    "render_audio_from_edl",
    "render_full_video",
    "render_video_from_edl",
    "resolve_delivery_bitrate_bps",
]

_EXPORTS = {
    "delivery_codec_for_suffix": ("sound_cut.media.ffmpeg_tools", "delivery_codec_for_suffix"),
    "export_delivery_audio": ("sound_cut.media.ffmpeg_tools", "export_delivery_audio"),
    "normalize_audio_for_analysis": ("sound_cut.media.ffmpeg_tools", "normalize_audio_for_analysis"),
    "probe_source_media": ("sound_cut.media.ffmpeg_tools", "probe_source_media"),
    "render_audio_from_edl": ("sound_cut.media.render", "render_audio_from_edl"),
    "render_full_video": ("sound_cut.media.render", "render_full_video"),
    "render_video_from_edl": ("sound_cut.media.render", "render_video_from_edl"),
    "resolve_delivery_bitrate_bps": ("sound_cut.media.ffmpeg_tools", "resolve_delivery_bitrate_bps"),
}


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
