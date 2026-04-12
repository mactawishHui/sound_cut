from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sound_cut.core import DependencyError

from .base import BaseEnhancer

_MODEL_SOURCE = "speechbrain/metricgan-plus-voicebank"
_DEFAULT_SAMPLE_RATE_HZ = 16_000


@dataclass(frozen=True)
class MetricGanPlusEnhancer(BaseEnhancer):
    backend_name = "metricgan-plus"

    def validate(self) -> None:
        try:
            import speechbrain  # noqa: F401
            import torch  # noqa: F401
            import torchaudio  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on optional runtime
            raise DependencyError(
                "metricgan-plus runtime is unavailable. Install optional runtime dependencies "
                '(for example: pip install sound-cut[speechbrain]) before enabling --enhance-speech.'
            ) from exc

    def enhance(self, input_path: Path, output_path: Path) -> None:
        self.validate()
        _run_metricgan_plus(
            input_path=input_path,
            output_path=output_path,
            model_dir=self.resolve_model_dir(),
        )


def _run_metricgan_plus(*, input_path: Path, output_path: Path, model_dir: Path) -> None:
    try:
        import torch
        import torchaudio
        from speechbrain.inference.enhancement import SpectralMaskEnhancement
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise DependencyError(
            "metricgan-plus runtime is unavailable. Install optional runtime dependencies "
            '(for example: pip install sound-cut[speechbrain]) before enabling --enhance-speech.'
        ) from exc

    try:
        model_dir.mkdir(parents=True, exist_ok=True)
        enhancer = SpectralMaskEnhancement.from_hparams(
            source=_MODEL_SOURCE,
            savedir=str(model_dir),
        )
        noisy = enhancer.load_audio(str(input_path)).unsqueeze(0)
        lengths = torch.tensor([1.0])
        enhanced = enhancer.enhance_batch(noisy, lengths=lengths)
        if enhanced.ndim == 3:
            enhanced = enhanced.squeeze(0)
        sample_rate_hz = getattr(getattr(enhancer, "hparams", object()), "sample_rate", _DEFAULT_SAMPLE_RATE_HZ)
        torchaudio.save(str(output_path), enhanced.detach().cpu(), sample_rate_hz)
    except Exception as exc:  # pragma: no cover - dependent on external runtime behavior
        raise DependencyError(f"metricgan-plus enhancement failed: {exc}") from exc
