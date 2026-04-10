# Offline Speech Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fully offline speech enhancement with local model management, make it composable with cut and loudness normalization, and keep the project installable across Windows, Linux, and macOS.

**Architecture:** Introduce a dedicated enhancement stage before optional cutting, backed by a local model-management layer. Ship `DeepFilterNet3` as the first working backend behind a stable enhancement interface, keep `Resemble Enhance` as a selectable backend placeholder with explicit install/discovery hooks, and preserve the existing `cut` and `auto-volume` feature independence.

**Tech Stack:** Python 3.11, argparse, ffmpeg/ffprobe, pytest, local model cache management, DeepFilterNet3 Python integration

---

### Task 1: Add Core Enhancement Models And Path Utilities

**Files:**
- Create: `src/sound_cut/core/paths.py`
- Modify: `src/sound_cut/core/models.py`
- Modify: `src/sound_cut/core/__init__.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing model/path tests**

```python
from pathlib import Path

from sound_cut.core.models import EnhancementConfig
from sound_cut.core.paths import default_model_cache_dir


def test_enhancement_config_defaults_to_deepfilternet3_natural() -> None:
    config = EnhancementConfig(enabled=True)

    assert config.backend == "deepfilternet3"
    assert config.profile == "natural"
    assert config.model_path is None


def test_enhancement_config_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported enhancement backend"):
        EnhancementConfig(enabled=True, backend="unknown")


def test_default_model_cache_dir_uses_platform_conventions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")

    cache_dir = default_model_cache_dir(platform_name="linux")

    assert cache_dir == Path("/tmp/example-home/.cache/sound-cut/models")
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_models.py -q`

Expected: FAIL because `EnhancementConfig` and `default_model_cache_dir()` do not exist yet.

- [ ] **Step 3: Implement the minimal core model and path utilities**

```python
@dataclass(frozen=True)
class EnhancementConfig:
    enabled: bool
    backend: str = "deepfilternet3"
    profile: str = "natural"
    model_path: Path | None = None

    def __post_init__(self) -> None:
        supported_backends = {"deepfilternet3", "resemble-enhance"}
        supported_profiles = {"natural", "strong"}
        if self.backend not in supported_backends:
            raise ValueError(f"Unsupported enhancement backend: {self.backend}")
        if self.profile not in supported_profiles:
            raise ValueError(f"Unsupported enhancement profile: {self.profile}")
```

```python
def default_model_cache_dir(*, platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        base = Path(os.environ["LOCALAPPDATA"])
        return base / "sound-cut" / "models"
    home = Path(os.environ["HOME"]).expanduser()
    return home / ".cache" / "sound-cut" / "models"
```

- [ ] **Step 4: Run the focused tests again and verify they pass**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_models.py -q`

Expected: PASS

- [ ] **Step 5: Commit the core enhancement config layer**

```bash
git add src/sound_cut/core/paths.py src/sound_cut/core/models.py src/sound_cut/core/__init__.py tests/test_models.py
git commit -m "feat: add enhancement config and model cache paths"
```

### Task 2: Add Model Registry, Locator, And CLI Parsing For Enhancement

**Files:**
- Create: `src/sound_cut/models/registry.py`
- Create: `src/sound_cut/models/locator.py`
- Create: `src/sound_cut/models/__init__.py`
- Modify: `src/sound_cut/cli.py`
- Modify: `src/sound_cut/core/errors.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_model_locator.py`

- [ ] **Step 1: Write the failing CLI and locator tests**

```python
def test_build_parser_parses_enhancement_flags(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args(
        [
            str(tmp_path / "input.wav"),
            "--enhance-speech",
            "--enhancer-backend",
            "deepfilternet3",
            "--enhancer-profile",
            "natural",
            "--model-path",
            str(tmp_path / "models"),
        ]
    )

    assert args.enhance_speech is True
    assert args.enhancer_backend == "deepfilternet3"
    assert args.enhancer_profile == "natural"
    assert args.model_path == tmp_path / "models"


def test_cli_passes_enhancement_config_to_process_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(input_path, output_path, profile, *, enhancement, **kwargs):
        captured["enhancement"] = enhancement
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 1.0, 0.0, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--enhance-speech"])

    assert exit_code == 0
    assert captured["enhancement"].enabled is True
    assert captured["enhancement"].backend == "deepfilternet3"


def test_locate_model_dir_prefers_explicit_model_path(tmp_path: Path) -> None:
    explicit = tmp_path / "models" / "deepfilternet3"
    explicit.mkdir(parents=True)

    resolved = locate_model_dir("deepfilternet3", explicit)

    assert resolved == explicit
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py tests/test_model_locator.py -q`

Expected: FAIL because enhancement flags are not parsed and locator modules do not exist.

- [ ] **Step 3: Implement minimal enhancement parsing and location**

```python
def _resolve_enhancement_config(args: argparse.Namespace) -> EnhancementConfig:
    return EnhancementConfig(
        enabled=args.enhance_speech,
        backend=args.enhancer_backend,
        profile=args.enhancer_profile,
        model_path=args.model_path,
    )


parser.add_argument("--enhance-speech", action="store_true")
parser.add_argument("--enhancer-backend", choices=("deepfilternet3", "resemble-enhance"), default="deepfilternet3")
parser.add_argument("--enhancer-profile", choices=("natural", "strong"), default="natural")
parser.add_argument("--model-path", type=Path)
```

```python
MODEL_REGISTRY = {
    "deepfilternet3": {"relative_dir": "deepfilternet3"},
    "resemble-enhance": {"relative_dir": "resemble-enhance"},
}


def locate_model_dir(backend: str, explicit_model_path: Path | None = None) -> Path:
    if explicit_model_path is not None:
        return explicit_model_path
    cache_dir = default_model_cache_dir()
    return cache_dir / MODEL_REGISTRY[backend]["relative_dir"]
```

- [ ] **Step 4: Run the focused tests again and verify they pass**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py tests/test_model_locator.py -q`

Expected: PASS

- [ ] **Step 5: Commit CLI enhancement parsing and model discovery**

```bash
git add src/sound_cut/models/registry.py src/sound_cut/models/locator.py src/sound_cut/models/__init__.py src/sound_cut/cli.py src/sound_cut/core/errors.py tests/test_cli.py tests/test_model_locator.py
git commit -m "feat: add enhancement CLI and model discovery"
```

### Task 3: Add Enhancement Backend Interfaces And DeepFilterNet3 Adapter

**Files:**
- Create: `src/sound_cut/enhancement/base.py`
- Create: `src/sound_cut/enhancement/deepfilternet.py`
- Create: `src/sound_cut/enhancement/resemble_enhance.py`
- Create: `src/sound_cut/enhancement/__init__.py`
- Test: `tests/test_enhancement_backends.py`

- [ ] **Step 1: Write the failing backend adapter tests**

```python
def test_select_enhancer_returns_deepfilternet_backend(tmp_path: Path) -> None:
    config = EnhancementConfig(enabled=True, backend="deepfilternet3", model_path=tmp_path)

    enhancer = select_enhancer(config)

    assert enhancer.backend_name == "deepfilternet3"


def test_deepfilternet_backend_raises_when_model_dir_is_missing(tmp_path: Path) -> None:
    backend = DeepFilterNetEnhancer(model_dir=tmp_path / "missing", profile="natural")

    with pytest.raises(ModelNotInstalledError):
        backend.validate()


def test_resemble_backend_reports_not_implemented_without_runtime(tmp_path: Path) -> None:
    backend = ResembleEnhancer(model_dir=tmp_path, profile="natural")

    with pytest.raises(EnhancementRuntimeUnavailableError):
        backend.validate()
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_enhancement_backends.py -q`

Expected: FAIL because the enhancement adapter layer does not exist yet.

- [ ] **Step 3: Implement the minimal backend abstraction**

```python
class SpeechEnhancer(Protocol):
    backend_name: str

    def validate(self) -> None:
        pass

    def enhance(self, input_path: Path, output_path: Path) -> None:
        pass
```

```python
@dataclass
class DeepFilterNetEnhancer:
    model_dir: Path
    profile: str
    backend_name: str = "deepfilternet3"

    def validate(self) -> None:
        if not self.model_dir.exists():
            raise ModelNotInstalledError(f"Model not installed: {self.model_dir}")
```

```python
@dataclass
class ResembleEnhancer:
    model_dir: Path
    profile: str
    backend_name: str = "resemble-enhance"

    def validate(self) -> None:
        raise EnhancementRuntimeUnavailableError("resemble-enhance backend is not installed yet")
```

- [ ] **Step 4: Run the focused tests again and verify they pass**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_enhancement_backends.py -q`

Expected: PASS

- [ ] **Step 5: Commit the enhancement backend abstraction**

```bash
git add src/sound_cut/enhancement/base.py src/sound_cut/enhancement/deepfilternet.py src/sound_cut/enhancement/resemble_enhance.py src/sound_cut/enhancement/__init__.py tests/test_enhancement_backends.py
git commit -m "feat: add offline enhancement backend adapters"
```

### Task 4: Add Enhancement Stage Composition To The Audio Pipeline

**Files:**
- Create: `src/sound_cut/enhancement/pipeline.py`
- Modify: `src/sound_cut/editing/pipeline.py`
- Modify: `src/sound_cut/media/render.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing pipeline tests for enhancement composition**

```python
def test_process_audio_runs_enhancement_before_cut_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ffmpeg_available
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    enhanced_path = tmp_path / "enhanced.wav"
    calls: dict[str, object] = {}

    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))

    def fake_enhance_audio(*, input_path: Path, enhancement, working_dir: Path) -> Path:
        calls["enhance_input"] = input_path
        write_pcm_wave(enhanced_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
        return enhanced_path

    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))
    monkeypatch.setattr("sound_cut.editing.pipeline.enhance_audio", fake_enhance_audio)

    process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enhancement=EnhancementConfig(enabled=True),
        enable_cut=True,
        analyzer=analyzer,
    )

    assert calls["enhance_input"] == input_path
    assert analyzer.calls[0] != input_path


def test_process_audio_can_enhance_without_cutting(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5))

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=build_profile("balanced"),
        enhancement=EnhancementConfig(enabled=True),
        enable_cut=False,
    )

    assert summary.kept_segment_count == 1
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py -q`

Expected: FAIL because `process_audio()` does not yet accept or apply enhancement configuration.

- [ ] **Step 3: Implement the minimal enhancement stage**

```python
def enhance_audio(*, input_path: Path, enhancement: EnhancementConfig, working_dir: Path) -> Path:
    if not enhancement.enabled:
        return input_path
    enhancer = select_enhancer(enhancement)
    enhancer.validate()
    output_path = working_dir / "enhanced.wav"
    enhancer.enhance(input_path, output_path)
    return output_path
```

```python
def process_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    *,
    enhancement: EnhancementConfig | None = None,
    enable_cut: bool = True,
    analyzer=None,
    keep_temp: bool = False,
    loudness: LoudnessNormalizationConfig | None = None,
) -> RenderSummary:
    enhancement = enhancement or EnhancementConfig(enabled=False)
    with tempfile.TemporaryDirectory(prefix="sound-cut-enhance-") as temp_dir_name:
        working_input_path = enhance_audio(
            input_path=input_path,
            enhancement=enhancement,
            working_dir=Path(temp_dir_name),
        )
        loudness_config = loudness or LoudnessNormalizationConfig(enabled=False, target_lufs=DEFAULT_TARGET_LUFS)
        if enable_cut:
            return _process_cut_audio(
                input_path=working_input_path,
                output_path=output_path,
                profile=profile,
                analyzer=analyzer,
                keep_temp=keep_temp,
                loudness=loudness_config,
            )
        source = probe_source_media(working_input_path)
        return render_full_audio(source=source, output_path=output_path, loudness=loudness_config)
```

- [ ] **Step 4: Run the focused tests again and verify they pass**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py -q`

Expected: PASS

- [ ] **Step 5: Commit enhancement stage composition**

```bash
git add src/sound_cut/enhancement/pipeline.py src/sound_cut/editing/pipeline.py src/sound_cut/media/render.py tests/test_pipeline.py
git commit -m "feat: compose offline speech enhancement into pipeline"
```

### Task 5: Add Local Model Commands And Verification Flow

**Files:**
- Create: `src/sound_cut/models/installer.py`
- Create: `src/sound_cut/models/manifest.py`
- Modify: `src/sound_cut/cli.py`
- Test: `tests/test_model_installer.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing installer and CLI subcommand tests**

```python
def test_install_model_creates_backend_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    installed_path = install_model("deepfilternet3")

    assert installed_path.exists()
    assert installed_path.name == "deepfilternet3"


def test_cli_models_list_prints_registered_backends(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["models", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "deepfilternet3" in captured.out
    assert "resemble-enhance" in captured.out
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_model_installer.py tests/test_cli.py -q`

Expected: FAIL because model installer helpers and `models` subcommands do not exist yet.

- [ ] **Step 3: Implement the minimal model management commands**

```python
def install_model(backend: str, destination: Path | None = None) -> Path:
    target_dir = destination or locate_model_dir(backend)
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "sound-cut-model.json"
    manifest_path.write_text(json.dumps({"backend": backend, "installed": True}))
    return target_dir
```

```python
models_parser = subparsers.add_parser("models")
models_subparsers = models_parser.add_subparsers(dest="models_command", required=True)
models_subparsers.add_parser("list")
install_parser = models_subparsers.add_parser("install")
install_parser.add_argument("backend", choices=("deepfilternet3", "resemble-enhance"))
```

- [ ] **Step 4: Run the focused tests again and verify they pass**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_model_installer.py tests/test_cli.py -q`

Expected: PASS

- [ ] **Step 5: Commit model management commands**

```bash
git add src/sound_cut/models/installer.py src/sound_cut/models/manifest.py src/sound_cut/cli.py tests/test_model_installer.py tests/test_cli.py
git commit -m "feat: add local model management commands"
```

### Task 6: Wire DeepFilterNet3 Runtime, Docs, And Full Verification

**Files:**
- Modify: `src/sound_cut/enhancement/deepfilternet.py`
- Modify: `README.md`
- Modify: `README_cn.md`
- Test: `tests/test_enhancement_backends.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing runtime integration test**

```python
def test_deepfilternet_enhance_writes_output_when_runtime_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5))

    backend = DeepFilterNetEnhancer(model_dir=tmp_path, profile="natural")

    monkeypatch.setattr("sound_cut.enhancement.deepfilternet._run_deepfilternet", lambda *args, **kwargs: write_pcm_wave(output_path, sample_rate_hz=48_000, samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5)))

    backend.enhance(input_path, output_path)

    assert output_path.exists()
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_enhancement_backends.py tests/test_pipeline.py -q`

Expected: FAIL because the backend does not yet invoke a real runtime path.

- [ ] **Step 3: Implement the minimal DeepFilterNet3 runtime hook and update docs**

```python
def enhance(self, input_path: Path, output_path: Path) -> None:
    self.validate()
    _run_deepfilternet(
        input_path=input_path,
        output_path=output_path,
        model_dir=self.model_dir,
        profile=self.profile,
    )
```

```markdown
python3.11 -m sound_cut input.mp3 --enhance-speech
python3.11 -m sound_cut input.mp3 --enhance-speech --cut --auto-volume
python3.11 -m sound_cut models install deepfilternet3
```

- [ ] **Step 4: Run the full verification suite**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q`

Expected: PASS

- [ ] **Step 5: Commit the default offline enhancement backend**

```bash
git add src/sound_cut/enhancement/deepfilternet.py README.md README_cn.md tests/test_enhancement_backends.py tests/test_pipeline.py
git commit -m "feat: wire offline speech enhancement backend"
```
