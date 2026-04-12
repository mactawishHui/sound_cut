from __future__ import annotations

MODEL_REGISTRY = {
    "deepfilternet3": {
        "relative_dir": "deepfilternet3",
        "asset_globs": ("*.safetensors", "*.ckpt", "*.pt", "*.pth", "*.onnx"),
    },
    "metricgan-plus": {
        "relative_dir": "metricgan-plus",
        "asset_globs": ("hyperparams.yaml", "*.ckpt", "*.pt", "*.bin"),
    },
    "demucs-vocals": {
        "relative_dir": "demucs-vocals",
        "asset_globs": ("*.th", "*.ckpt", "*.pt", "*.bin"),
    },
    "resemble-enhance": {
        "relative_dir": "resemble-enhance",
        "asset_globs": ("*.safetensors", "*.ckpt", "*.pt", "*.pth", "*.onnx"),
    },
}
