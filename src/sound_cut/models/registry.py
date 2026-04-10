from __future__ import annotations

MODEL_REGISTRY = {
    "deepfilternet3": {
        "relative_dir": "deepfilternet3",
        "asset_globs": ("*.safetensors", "*.ckpt", "*.pt", "*.pth", "*.onnx"),
    },
    "resemble-enhance": {
        "relative_dir": "resemble-enhance",
        "asset_globs": ("*.safetensors", "*.ckpt", "*.pt", "*.pth", "*.onnx"),
    },
}
