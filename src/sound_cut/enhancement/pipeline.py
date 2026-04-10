from __future__ import annotations

from pathlib import Path

from sound_cut.core.errors import MediaError
from sound_cut.core.models import EnhancementConfig
from sound_cut.enhancement import select_enhancer


def enhance_audio(*, input_path: Path, enhancement: EnhancementConfig, working_dir: Path) -> Path:
    if not enhancement.enabled:
        return input_path

    enhancer = select_enhancer(enhancement)
    enhancer.validate()

    output_path = working_dir / "enhanced.wav"
    enhancer.enhance(input_path, output_path)
    if not output_path.exists():
        raise MediaError(f"Enhancer {enhancer.backend_name!r} did not create output: {output_path}")
    return output_path
