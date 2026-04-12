"""JSON API backend for the SoundCut React frontend.

Endpoints
---------
POST  /api/jobs                     Upload file + config; starts async processing.
GET   /api/jobs/<job_id>            Poll job status / result.
GET   /api/jobs/<job_id>/download/<artifact>   Download output or subtitle.
GET   /                             Serve built React app (production).
"""

from __future__ import annotations

import os
import secrets
import tempfile
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from sound_cut.cli import _finite_float, _non_negative_int, resolve_output_path
from sound_cut.core import EnhancementConfig, SoundCutError, build_profile
from sound_cut.core.models import (
    DEFAULT_TARGET_LUFS,
    LoudnessNormalizationConfig,
    SubtitleConfig,
)
from sound_cut.editing.pipeline import process_audio

# ---------------------------------------------------------------------------
# In-memory job store  {job_id -> dict}
# ---------------------------------------------------------------------------
_jobs: dict[str, dict[str, Any]] = {}
_workspace = Path(tempfile.gettempdir()) / "sound-cut-api"

# Where the built React app lives (relative to this file)
_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


def _add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    _workspace.mkdir(parents=True, exist_ok=True)

    app.after_request(_add_cors)

    # ── CORS preflight ──────────────────────────────────────────────────────
    @app.route("/api/<path:path>", methods=["OPTIONS"])
    def _options(path: str):
        return "", 204

    # ── Serve built React app ───────────────────────────────────────────────
    @app.get("/")
    def index():
        dist = _FRONTEND_DIST
        if dist.exists():
            return send_from_directory(str(dist), "index.html")
        return jsonify({"info": "SoundCut API running. Build the frontend with `npm run build`."}), 200

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        return send_from_directory(str(_FRONTEND_DIST / "assets"), filename)

    # ── API: create job ─────────────────────────────────────────────────────
    @app.post("/api/jobs")
    def create_job():
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "No file uploaded"}), 400

        # Parse JSON config from form field
        import json
        try:
            cfg: dict[str, Any] = json.loads(request.form.get("config", "{}"))
        except Exception:
            return jsonify({"error": "Invalid config JSON"}), 400

        job_id = secrets.token_hex(8)
        job_dir = _workspace / job_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = secure_filename(f.filename) or "input.bin"
        input_path = input_dir / filename
        f.save(input_path)

        _jobs[job_id] = {"status": "processing", "result": None, "error": None,
                         "output_path": None, "subtitle_path": None}

        thread = threading.Thread(
            target=_run_job,
            args=(job_id, input_path, output_dir, cfg),
            daemon=True,
        )
        thread.start()
        return jsonify({"job_id": job_id}), 202

    # ── API: poll job ───────────────────────────────────────────────────────
    @app.get("/api/jobs/<job_id>")
    def get_job(job_id: str):
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({
            "status": job["status"],
            "result": job["result"],
            "error": job["error"],
        })

    # ── API: download artifact ──────────────────────────────────────────────
    @app.get("/api/jobs/<job_id>/download/<artifact>")
    def download(job_id: str, artifact: str):
        job = _jobs.get(job_id)
        if job is None:
            abort(404)
        if artifact == "output":
            path = job.get("output_path")
        elif artifact == "subtitle":
            path = job.get("subtitle_path")
        else:
            abort(404)
        if not path or not Path(path).exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=Path(path).name)

    return app


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_job(job_id: str, input_path: Path, output_dir: Path, cfg: dict) -> None:
    try:
        # Build profile
        aggressiveness = cfg.get("aggressiveness", "balanced")
        profile = build_profile(aggressiveness)
        overrides = {
            "min_silence_ms": _opt_int(cfg.get("min_silence_ms")),
            "padding_ms": _opt_int(cfg.get("padding_ms")),
            "crossfade_ms": _opt_int(cfg.get("crossfade_ms")),
        }
        profile = replace(profile, **{k: v for k, v in overrides.items() if v is not None})

        loudness = LoudnessNormalizationConfig(
            enabled=bool(cfg.get("auto_volume")),
            target_lufs=(
                DEFAULT_TARGET_LUFS
                if not cfg.get("target_lufs")
                else float(cfg["target_lufs"])
            ),
        )
        enhancement = EnhancementConfig(
            enabled=bool(cfg.get("enhance_speech")),
            backend=cfg.get("enhancer_backend", "deepfilternet3"),
            profile=cfg.get("enhancer_profile", "natural"),
            model_path=(
                Path(cfg["model_path"]) if cfg.get("model_path") else None
            ),
            fallback=cfg.get("enhancer_fallback", "fail"),
        )
        subtitle = SubtitleConfig(
            enabled=bool(cfg.get("subtitle")),
            language=cfg.get("subtitle_language") or None,
            format=cfg.get("subtitle_format", "srt"),
            api_key=cfg.get("subtitle_api_key") or os.environ.get("DASHSCOPE_API_KEY"),
            sidecar_only=bool(cfg.get("subtitle_sidecar")),
            max_chars_per_subtitle=int(cfg.get("subtitle_max_chars") or 25),
            embed_mode=(
                "burn" if cfg.get("subtitle_burn")
                else "mkv" if cfg.get("subtitle_mkv")
                else "mp4"
            ),
        )

        output_path = output_dir / resolve_output_path(input_path, None).name
        summary = process_audio(
            input_path, output_path, profile,
            keep_temp=bool(cfg.get("keep_temp")),
            loudness=loudness,
            enable_cut=bool(cfg.get("cut")),
            enhancement=enhancement,
            subtitle=subtitle,
        )
        effective = summary.output_path or output_path
        _jobs[job_id].update({
            "status": "done",
            "output_path": str(effective),
            "subtitle_path": str(summary.subtitle_path) if summary.subtitle_path else None,
            "result": {
                "input_duration_s": summary.input_duration_s,
                "output_duration_s": summary.output_duration_s,
                "removed_duration_s": summary.removed_duration_s,
                "kept_segment_count": summary.kept_segment_count,
                "has_subtitle": summary.subtitle_path is not None and summary.subtitle_path.exists(),
                "output_filename": Path(effective).name,
                "subtitle_filename": summary.subtitle_path.name if summary.subtitle_path else None,
            },
        })
    except (SoundCutError, Exception) as exc:
        _jobs[job_id].update({"status": "error", "error": str(exc)})


def _opt_int(v: Any) -> int | None:
    if v is None or v == "" or v is False:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_api(*, host: str = "127.0.0.1", port: int = 8766, debug: bool = False) -> int:
    app = create_app()
    print(f"\n  SoundCut API  →  http://{host}:{port}")
    if _FRONTEND_DIST.exists():
        print(f"  React UI      →  http://{host}:{port}/")
    else:
        print(f"  Dev server    →  cd frontend && npm run dev")
    print()
    app.run(host=host, port=port, debug=debug)
    return 0
