from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest
import torch

from sound_cut.core import DependencyError, EnhancementConfig
from sound_cut.enhancement import (
    DeepFilterNetEnhancer,
    ResembleEnhancer,
    select_enhancer,
)
from sound_cut.models.manifest import ModelManifest, write_manifest


def test_select_enhancer_returns_deepfilternet_backend() -> None:
    enhancer = select_enhancer(EnhancementConfig(enabled=True, backend="deepfilternet3"))

    assert isinstance(enhancer, DeepFilterNetEnhancer)
    assert enhancer.backend_name == "deepfilternet3"


def test_select_enhancer_returns_resemble_backend() -> None:
    enhancer = select_enhancer(EnhancementConfig(enabled=True, backend="resemble-enhance"))

    assert isinstance(enhancer, ResembleEnhancer)
    assert enhancer.backend_name == "resemble-enhance"


def test_deepfilternet_validate_requires_model_dir(tmp_path: Path) -> None:
    missing_model_dir = tmp_path / "missing-model"
    enhancer = DeepFilterNetEnhancer(
        EnhancementConfig(enabled=True, backend="deepfilternet3", model_path=missing_model_dir)
    )

    with pytest.raises(DependencyError, match="deepfilternet3.*model dir.*missing-model"):
        enhancer.validate()


def test_resemble_validate_reports_runtime_unavailable() -> None:
    enhancer = ResembleEnhancer(EnhancementConfig(enabled=True, backend="resemble-enhance"))

    with pytest.raises(DependencyError, match="resemble-enhance.*not installed|unavailable"):
        enhancer.validate()


def test_resolve_model_dir_uses_concrete_backend_name() -> None:
    enhancer = DeepFilterNetEnhancer(
        EnhancementConfig(enabled=True, backend="resemble-enhance")
    )

    assert enhancer.resolve_model_dir().name == "deepfilternet3"


def test_deepfilternet_enhance_exposes_common_contract(tmp_path: Path) -> None:
    model_dir = tmp_path / "deepfilternet3"
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    model_dir.mkdir()
    input_path.write_bytes(b"wav")
    (model_dir / "model.safetensors").write_bytes(b"weights")
    write_manifest(model_dir, ModelManifest(backend="deepfilternet3", installed=True))
    enhancer = DeepFilterNetEnhancer(
        EnhancementConfig(enabled=True, backend="deepfilternet3", model_path=model_dir)
    )

    calls: dict[str, object] = {}

    def fake_run_deepfilternet(*, input_path: Path, output_path: Path, model_dir: Path, profile: str) -> None:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        calls["model_dir"] = model_dir
        calls["profile"] = profile
        output_path.write_bytes(b"enhanced")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "sound_cut.enhancement.deepfilternet._run_deepfilternet",
        fake_run_deepfilternet,
    )
    try:
        enhancer.enhance(input_path, output_path)
    finally:
        monkeypatch.undo()

    assert calls["input_path"] == input_path
    assert calls["output_path"] == output_path
    assert calls["model_dir"] == model_dir
    assert calls["profile"] == "natural"
    assert output_path.exists()


def test_deepfilternet_validate_rejects_manifest_only_model_dir(tmp_path: Path) -> None:
    model_dir = tmp_path / "deepfilternet3"
    model_dir.mkdir()
    write_manifest(model_dir, ModelManifest(backend="deepfilternet3", installed=True))
    enhancer = DeepFilterNetEnhancer(
        EnhancementConfig(enabled=True, backend="deepfilternet3", model_path=model_dir)
    )

    with pytest.raises(DependencyError, match="model assets are not ready"):
        enhancer.validate()


def test_deepfilternet_validate_rejects_unrelated_model_files(tmp_path: Path) -> None:
    model_dir = tmp_path / "deepfilternet3"
    model_dir.mkdir()
    (model_dir / "README.txt").write_text("not a model")
    write_manifest(model_dir, ModelManifest(backend="deepfilternet3", installed=True))
    enhancer = DeepFilterNetEnhancer(
        EnhancementConfig(enabled=True, backend="deepfilternet3", model_path=model_dir)
    )

    with pytest.raises(DependencyError, match="model assets are not ready"):
        enhancer.validate()


def test_deepfilternet_validate_accepts_explicit_model_path_without_manifest(tmp_path: Path) -> None:
    model_dir = tmp_path / "explicit-model-dir"
    model_dir.mkdir()
    (model_dir / "model.safetensors").write_text("weights")
    enhancer = DeepFilterNetEnhancer(
        EnhancementConfig(enabled=True, backend="deepfilternet3", model_path=model_dir)
    )

    enhancer.validate()


def test_deepfilternet_defines_its_own_enhance_method() -> None:
    assert "enhance" in DeepFilterNetEnhancer.__dict__


def test_resemble_enhance_exposes_common_contract(tmp_path: Path) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    input_path.write_bytes(b"wav")
    enhancer = ResembleEnhancer(EnhancementConfig(enabled=True, backend="resemble-enhance"))

    with pytest.raises(DependencyError, match="resemble-enhance.*not installed|unavailable"):
        enhancer.enhance(input_path, output_path)


@pytest.mark.parametrize(
    ("profile", "expected_atten_lim_db"),
    [("natural", 6.0), ("strong", None)],
)
def test_run_deepfilternet_maps_profile_to_attenuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str, expected_atten_lim_db: float | None
) -> None:
    from sound_cut.enhancement.deepfilternet import _run_deepfilternet

    calls: dict[str, object] = {}

    class _FakeDfState:
        @staticmethod
        def sr() -> int:
            return 48_000

    def fake_init_df(*, model_base_dir: str, post_filter: bool):
        calls["post_filter"] = post_filter
        calls["model_base_dir"] = model_base_dir
        return object(), _FakeDfState(), "suffix"

    def fake_load_audio(path: str, *, sr: int):
        calls["load_sr"] = sr
        return torch.zeros((1, 48_000), dtype=torch.float32), object()

    def fake_enhance(model, df_state, audio, *, pad: bool, atten_lim_db: float | None):
        calls["pad"] = pad
        calls["atten_lim_db"] = atten_lim_db
        return audio

    def fake_save_audio(path: str, audio, sr: int):
        calls["save_sr"] = sr
        Path(path).write_bytes(b"ok")

    fake_df_enhance_module = types.SimpleNamespace(
        init_df=fake_init_df,
        load_audio=fake_load_audio,
        enhance=fake_enhance,
        save_audio=fake_save_audio,
    )
    monkeypatch.setitem(sys.modules, "df.enhance", fake_df_enhance_module)

    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    input_path.write_bytes(b"wav")

    _run_deepfilternet(
        input_path=input_path,
        output_path=output_path,
        model_dir=tmp_path,
        profile=profile,
    )

    assert calls["post_filter"] is (profile == "strong")
    assert calls["atten_lim_db"] == expected_atten_lim_db
    assert output_path.exists()
