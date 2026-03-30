class SoundCutError(Exception):
    """Base exception for expected CLI-facing failures."""


class DependencyError(SoundCutError):
    """Raised when ffmpeg or ffprobe is unavailable."""


class MediaError(SoundCutError):
    """Raised when input media cannot be read or written."""


class NoSpeechDetectedError(SoundCutError):
    """Raised when the analyzer finds no usable speech."""
