from __future__ import annotations

import json
from pathlib import Path

import pytest

from sound_cut.models.installer import import_model, install_model, verify_model
from sound_cut.models.manifest import load_manifest


def test_install_model_creates_backend_directory_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    installed_path = install_model("deepfilternet3")

    manifest_path = installed_path / "sound-cut-model.json"
    assert installed_path == tmp_path / ".cache" / "sound-cut" / "models" / "deepfilternet3"
    assert installed_path.is_dir()
    assert json.loads(manifest_path.read_text()) == {"backend": "deepfilternet3", "installed": False}


def test_import_model_copies_source_tree_and_writes_manifest(tmp_path: Path) -> None:
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "weights.bin").write_text("weights")

    destination = tmp_path / "installed" / "resemble-enhance"
    imported_path = import_model("resemble-enhance", source_dir, destination=destination)

    assert imported_path == destination
    assert (imported_path / "weights.bin").read_text() == "weights"
    assert json.loads((imported_path / "sound-cut-model.json").read_text()) == {
        "backend": "resemble-enhance",
        "installed": True,
        "source": str(source_dir),
    }


def test_verify_model_reports_installed_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "model.safetensors").write_text("weights")
    installed_path = import_model("deepfilternet3", source_dir, destination=tmp_path / "installed-model")

    assert verify_model("deepfilternet3", installed_path) is True


def test_load_manifest_returns_none_for_malformed_manifest(tmp_path: Path) -> None:
    model_dir = tmp_path / "broken-model"
    model_dir.mkdir()
    (model_dir / "sound-cut-model.json").write_text("{")

    assert load_manifest(model_dir) is None


def test_load_manifest_returns_none_for_unreadable_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_dir = tmp_path / "broken-model"
    model_dir.mkdir()
    manifest_path = model_dir / "sound-cut-model.json"
    manifest_path.write_text(json.dumps({"backend": "deepfilternet3", "installed": True}))

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):
        if self == manifest_path:
            raise PermissionError("unreadable manifest")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert load_manifest(model_dir) is None


def test_load_manifest_returns_none_for_invalid_installed_type(tmp_path: Path) -> None:
    model_dir = tmp_path / "invalid-model"
    model_dir.mkdir()
    (model_dir / "sound-cut-model.json").write_text(
        json.dumps({"backend": "deepfilternet3", "installed": "yes"})
    )

    assert load_manifest(model_dir) is None


def test_verify_model_returns_false_for_partial_manifest(tmp_path: Path) -> None:
    model_dir = tmp_path / "partial-model"
    model_dir.mkdir()
    (model_dir / "sound-cut-model.json").write_text(json.dumps({"installed": True}))

    assert verify_model("deepfilternet3", model_dir) is False


def test_verify_model_returns_false_for_unreadable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_dir = tmp_path / "broken-model"
    model_dir.mkdir()
    manifest_path = model_dir / "sound-cut-model.json"
    manifest_path.write_text(json.dumps({"backend": "deepfilternet3", "installed": True}))

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):
        if self == manifest_path:
            raise PermissionError("unreadable manifest")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert verify_model("deepfilternet3", model_dir) is False


def test_verify_model_returns_false_for_manifest_only_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    installed_path = install_model("deepfilternet3")

    assert verify_model("deepfilternet3", installed_path) is False


def test_import_model_rejects_non_directory_source(tmp_path: Path) -> None:
    source_file = tmp_path / "weights.bin"
    source_file.write_text("weights")

    with pytest.raises(NotADirectoryError):
        import_model("deepfilternet3", source_file, destination=tmp_path / "installed")


def test_verify_model_returns_false_for_unrelated_assets(tmp_path: Path) -> None:
    model_dir = tmp_path / "deepfilternet3"
    model_dir.mkdir()
    (model_dir / "README.txt").write_text("not a model")
    (model_dir / "sound-cut-model.json").write_text(
        json.dumps({"backend": "deepfilternet3", "installed": True})
    )

    assert verify_model("deepfilternet3", model_dir) is False


def test_verify_model_returns_false_for_unrelated_resemble_assets(tmp_path: Path) -> None:
    model_dir = tmp_path / "resemble-enhance"
    model_dir.mkdir()
    (model_dir / "README.txt").write_text("not a model")
    (model_dir / "sound-cut-model.json").write_text(
        json.dumps({"backend": "resemble-enhance", "installed": True})
    )

    assert verify_model("resemble-enhance", model_dir) is False


def test_verify_model_accepts_resemble_checkpoint_asset(tmp_path: Path) -> None:
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "model.safetensors").write_text("weights")
    installed_path = import_model(
        "resemble-enhance",
        source_dir,
        destination=tmp_path / "installed-resemble-model",
    )

    assert verify_model("resemble-enhance", installed_path) is True


def test_install_model_preserves_existing_ready_model(tmp_path: Path) -> None:
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "model.safetensors").write_text("weights")
    destination = tmp_path / "installed-model"
    import_model("deepfilternet3", source_dir, destination=destination)

    install_model("deepfilternet3", destination=destination)

    assert verify_model("deepfilternet3", destination) is True
    assert json.loads((destination / "sound-cut-model.json").read_text())["installed"] is True


def test_import_model_replaces_stale_assets(tmp_path: Path) -> None:
    valid_source = tmp_path / "valid-source"
    valid_source.mkdir()
    (valid_source / "model.safetensors").write_text("weights")
    destination = tmp_path / "installed-model"
    import_model("deepfilternet3", valid_source, destination=destination)
    assert verify_model("deepfilternet3", destination) is True

    invalid_source = tmp_path / "invalid-source"
    invalid_source.mkdir()
    (invalid_source / "README.txt").write_text("not a model")
    import_model("deepfilternet3", invalid_source, destination=destination)

    assert verify_model("deepfilternet3", destination) is False


def test_import_model_rejects_overlapping_source_and_destination(tmp_path: Path) -> None:
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "model.safetensors").write_text("weights")

    with pytest.raises(OSError, match="must not overlap"):
        import_model("deepfilternet3", source_dir, destination=source_dir)
