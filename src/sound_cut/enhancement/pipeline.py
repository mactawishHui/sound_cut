from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sound_cut.core.errors import MediaError
from sound_cut.core.models import EnhancementConfig
from sound_cut.enhancement import select_enhancer


def enhance_audio(*, input_path: Path, enhancement: EnhancementConfig, working_dir: Path) -> Path:
    if not enhancement.enabled:
        return input_path

    return _enhance_audio_once(
        input_path=input_path,
        enhancement=enhancement,
        working_dir=working_dir,
        allow_fallback=True,
    )


def _enhance_audio_once(
    *,
    input_path: Path,
    enhancement: EnhancementConfig,
    working_dir: Path,
    allow_fallback: bool,
) -> Path:
    enhancer = select_enhancer(enhancement)
    try:
        enhancer.validate()

        output_path = working_dir / "enhanced.wav"
        enhancer.enhance(input_path, output_path)
        if not output_path.exists():
            raise MediaError(f"Enhancer {enhancer.backend_name!r} did not create output: {output_path}")
        return output_path
    except Exception as exc:
        if not allow_fallback:
            raise
        return _apply_enhancement_fallback(
            input_path=input_path,
            enhancement=enhancement,
            working_dir=working_dir,
            cause=exc,
        )


def _apply_enhancement_fallback(
    *,
    input_path: Path,
    enhancement: EnhancementConfig,
    working_dir: Path,
    cause: Exception,
) -> Path:
    if enhancement.fallback == "fail":
        raise cause
    if enhancement.fallback == "original":
        return input_path

    fallback_config = replace(
        enhancement,
        backend=enhancement.fallback,
        model_path=None,
        fallback="fail",
    )
    return _enhance_audio_once(
        input_path=input_path,
        enhancement=fallback_config,
        working_dir=working_dir,
        allow_fallback=False,
    )
