from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sound_cut.core import DependencyError
from sound_cut.models.installer import has_model_assets, verify_model

from .base import BaseEnhancer


@dataclass(frozen=True)
class DeepFilterNetEnhancer(BaseEnhancer):
    backend_name = "deepfilternet3"

    def validate(self) -> None:
        model_dir = self.resolve_model_dir()
        if not model_dir.is_dir():
            raise DependencyError(
                f"{self.backend_name} model dir not found: {model_dir}. "
                "Download or configure the backend model directory before enabling enhancement."
            )
        if self.config.model_path is not None:
            if not has_model_assets(self.backend_name, model_dir):
                raise DependencyError(
                    f"{self.backend_name} model assets are not ready in {model_dir}. "
                    "Ensure the explicit --model-path directory contains backend model files."
                )
            return
        if not verify_model(self.backend_name, model_dir):
            raise DependencyError(
                f"{self.backend_name} model assets are not ready in {model_dir}. "
                "Run `sound-cut models import deepfilternet3 /path/to/model-dir` "
                "to install local model assets."
            )

    def enhance(self, input_path: Path, output_path: Path) -> None:
        self.validate()
        _run_deepfilternet(
            input_path=input_path,
            output_path=output_path,
            model_dir=self.resolve_model_dir(),
            profile=self.config.profile,
        )


def _run_deepfilternet(*, input_path: Path, output_path: Path, model_dir: Path, profile: str) -> None:
    try:
        from df.enhance import enhance, init_df, load_audio, save_audio
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise DependencyError(
            "deepfilternet3 runtime is unavailable. Install local runtime dependencies "
            "(for example: pip install deepfilternet) before enabling --enhance-speech."
        ) from exc

    post_filter = profile == "strong"
    atten_lim_db = 6.0 if profile == "natural" else None
    try:
        model, df_state, _ = init_df(model_base_dir=str(model_dir), post_filter=post_filter)
        audio, _ = load_audio(str(input_path), sr=df_state.sr())
        enhanced = enhance(model, df_state, audio, pad=True, atten_lim_db=atten_lim_db)
        save_audio(str(output_path), enhanced, df_state.sr())
    except Exception as exc:  # pragma: no cover - dependent on external runtime behavior
        raise DependencyError(f"deepfilternet3 enhancement failed: {exc}") from exc
