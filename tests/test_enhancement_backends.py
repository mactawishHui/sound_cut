from __future__ import annotations

import builtins
from pathlib import Path
import sys
import types

import pytest

from sound_cut.core import DependencyError, EnhancementConfig
from sound_cut.enhancement import (
    DeepFilterNetEnhancer,
    DemucsVocalsEnhancer,
    MetricGanPlusEnhancer,
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


def test_select_enhancer_returns_metricgan_plus_backend() -> None:
    enhancer = select_enhancer(EnhancementConfig(enabled=True, backend="metricgan-plus"))

    assert isinstance(enhancer, MetricGanPlusEnhancer)
    assert enhancer.backend_name == "metricgan-plus"


def test_select_enhancer_returns_demucs_vocals_backend() -> None:
    enhancer = select_enhancer(EnhancementConfig(enabled=True, backend="demucs-vocals"))

    assert isinstance(enhancer, DemucsVocalsEnhancer)
    assert enhancer.backend_name == "demucs-vocals"


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


def test_metricgan_plus_validate_reports_runtime_unavailable() -> None:
    enhancer = MetricGanPlusEnhancer(EnhancementConfig(enabled=True, backend="metricgan-plus"))

    monkeypatch = pytest.MonkeyPatch()
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"speechbrain", "torch", "torchaudio"}:
            raise ImportError(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        with pytest.raises(DependencyError, match="metricgan-plus runtime is unavailable"):
            enhancer.validate()
    finally:
        monkeypatch.undo()


def test_demucs_vocals_validate_reports_runtime_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    enhancer = DemucsVocalsEnhancer(EnhancementConfig(enabled=True, backend="demucs-vocals"))
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None if name == "demucs" else object())

    with pytest.raises(DependencyError, match="demucs-vocals runtime is unavailable"):
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


def test_metricgan_plus_enhance_exposes_common_contract(tmp_path: Path) -> None:
    model_dir = tmp_path / "metricgan-plus"
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    input_path.write_bytes(b"wav")
    enhancer = MetricGanPlusEnhancer(
        EnhancementConfig(enabled=True, backend="metricgan-plus", model_path=model_dir)
    )

    calls: dict[str, object] = {}

    def fake_run_metricgan_plus(*, input_path: Path, output_path: Path, model_dir: Path) -> None:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        calls["model_dir"] = model_dir
        output_path.write_bytes(b"enhanced")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(MetricGanPlusEnhancer, "validate", lambda self: None)
    monkeypatch.setattr(
        "sound_cut.enhancement.metricgan_plus._run_metricgan_plus",
        fake_run_metricgan_plus,
    )
    try:
        enhancer.enhance(input_path, output_path)
    finally:
        monkeypatch.undo()

    assert calls["input_path"] == input_path
    assert calls["output_path"] == output_path
    assert calls["model_dir"] == model_dir
    assert output_path.exists()


def test_demucs_vocals_enhance_exposes_common_contract(tmp_path: Path) -> None:
    model_dir = tmp_path / "demucs-vocals"
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    input_path.write_bytes(b"wav")
    enhancer = DemucsVocalsEnhancer(
        EnhancementConfig(enabled=True, backend="demucs-vocals", model_path=model_dir)
    )

    calls: dict[str, object] = {}

    def fake_run_demucs_vocals(*, input_path: Path, output_path: Path, model_dir: Path) -> None:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        calls["model_dir"] = model_dir
        output_path.write_bytes(b"speech")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(DemucsVocalsEnhancer, "validate", lambda self: None)
    monkeypatch.setattr(
        "sound_cut.enhancement.demucs_vocals._run_demucs_vocals",
        fake_run_demucs_vocals,
    )
    try:
        enhancer.enhance(input_path, output_path)
    finally:
        monkeypatch.undo()

    assert calls["input_path"] == input_path
    assert calls["output_path"] == output_path
    assert calls["model_dir"] == model_dir
    assert output_path.exists()


def test_run_metricgan_plus_uses_speechbrain_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sound_cut.enhancement.metricgan_plus import _run_metricgan_plus

    calls: dict[str, object] = {}

    class _FakeTensor:
        def __init__(self, shape: tuple[int, ...]) -> None:
            self.shape = shape
            self.ndim = len(shape)

        def unsqueeze(self, dim: int):
            if dim == 0:
                return _FakeTensor((1, *self.shape))
            raise AssertionError(f"unexpected unsqueeze dim: {dim}")

        def squeeze(self, dim: int = 0):
            if dim == 0 and self.shape and self.shape[0] == 1:
                return _FakeTensor(self.shape[1:])
            raise AssertionError(f"unexpected squeeze dim: {dim}")

        def detach(self):
            return self

        def cpu(self):
            return self

    fake_torch = types.SimpleNamespace(
        tensor=lambda values: types.SimpleNamespace(tolist=lambda: list(values)),
    )
    fake_torchaudio = types.SimpleNamespace()

    class _FakeEnhancer:
        def __init__(self) -> None:
            self.hparams = types.SimpleNamespace(sample_rate=16_000)

        @classmethod
        def from_hparams(cls, *, source: str, savedir: str):
            calls["source"] = source
            calls["savedir"] = savedir
            return cls()

        def load_audio(self, path: str):
            calls["load_path"] = path
            return _FakeTensor((16_000,))

        def enhance_batch(self, noisy, *, lengths):
            calls["lengths"] = lengths.tolist()
            return noisy.unsqueeze(0)

    fake_module = types.SimpleNamespace(SpectralMaskEnhancement=_FakeEnhancer)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.enhancement", fake_module)

    def fake_save(path: str, audio, sample_rate_hz: int) -> None:
        calls["save_sample_rate_hz"] = sample_rate_hz
        calls["save_shape"] = tuple(audio.shape)
        Path(path).write_bytes(b"ok")

    monkeypatch.setattr(fake_torchaudio, "save", fake_save, raising=False)

    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    model_dir = tmp_path / "metricgan-plus"
    input_path.write_bytes(b"wav")

    _run_metricgan_plus(
        input_path=input_path,
        output_path=output_path,
        model_dir=model_dir,
    )

    assert calls["source"] == "speechbrain/metricgan-plus-voicebank"
    assert calls["savedir"] == str(model_dir)
    assert calls["load_path"] == str(input_path)
    assert calls["lengths"] == [1.0]
    assert calls["save_sample_rate_hz"] == 16_000
    assert calls["save_shape"] == (1, 16_000)
    assert output_path.exists()


def test_run_demucs_vocals_uses_subprocess_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sound_cut.enhancement.demucs_vocals import _run_demucs_vocals

    calls: dict[str, object] = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["env"] = kwargs["env"]
        output_root = Path(command[command.index("-o") + 1])
        vocals_path = output_root / "htdemucs" / "input" / "vocals.wav"
        vocals_path.parent.mkdir(parents=True, exist_ok=True)
        vocals_path.write_bytes(b"vocals")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    model_dir = tmp_path / "demucs-vocals"
    input_path.write_bytes(b"wav")

    _run_demucs_vocals(
        input_path=input_path,
        output_path=output_path,
        model_dir=model_dir,
    )

    assert calls["command"][:3] == [sys.executable, "-m", "demucs.separate"]
    assert "--two-stems=vocals" in calls["command"]
    assert calls["env"]["TORCH_HOME"] == str(model_dir.parent)
    assert output_path.read_bytes() == b"vocals"


def test_locate_vocals_output_falls_back_to_recursive_search(tmp_path: Path) -> None:
    from sound_cut.enhancement.demucs_vocals import _locate_vocals_output

    separation_dir = tmp_path / "separated"
    fallback = separation_dir / "custom-model" / "sample" / "vocals.wav"
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b"vocals")

    resolved = _locate_vocals_output(
        separation_dir=separation_dir,
        input_path=tmp_path / "sample.mp3",
    )

    assert resolved == fallback


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
        return object(), object()

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
