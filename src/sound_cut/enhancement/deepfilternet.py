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


def _to_wav_if_needed(input_path: Path, working_dir: Path) -> Path:
    """Return a WAV version of *input_path* that torchaudio/sox can read.

    torchaudio's sox_io backend cannot handle M4A/AAC streams wrapped in an
    .mp3 container (a common Bilibili download artefact).  We use ffmpeg to
    decode to 16-bit PCM WAV before handing the file to DeepFilterNet.
    """
    import subprocess, shutil  # noqa: E401 - local import keeps module-level deps minimal

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return input_path  # let torchaudio try and fail with its own error

    wav_path = working_dir / (input_path.stem + "_dfn_in.wav")
    result = subprocess.run(
        [
            ffmpeg, "-y", "-i", str(input_path),
            "-vn",                  # drop video stream if any
            "-ar", "48000",         # DeepFilterNet operates at 48 kHz
            "-ac", "1",
            "-sample_fmt", "s16",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not wav_path.exists():
        # ffmpeg failed for some reason — fall back to original and let torchaudio handle it
        return input_path
    return wav_path


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
        import tempfile
        with tempfile.TemporaryDirectory(prefix="dfn-in-") as tmp:
            wav_input = _to_wav_if_needed(input_path, Path(tmp))
            model, df_state, _ = init_df(model_base_dir=str(model_dir), post_filter=post_filter)
            audio, _ = load_audio(str(wav_input), sr=df_state.sr())
        enhanced = enhance(model, df_state, audio, pad=True, atten_lim_db=atten_lim_db)
        save_audio(str(output_path), enhanced, df_state.sr())
    except Exception as exc:  # pragma: no cover - dependent on external runtime behavior
        raise DependencyError(f"deepfilternet3 enhancement failed: {exc}") from exc
