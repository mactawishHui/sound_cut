# ── Stage 1: build React frontend ──────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ─────────────────────────────────────────────────
FROM python:3.11-slim

# System deps: ffmpeg + build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python package
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e "."

# Copy built frontend into the location Flask expects
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8766

CMD python -c "\
import os; \
from sound_cut.api import run_api; \
run_api(host='0.0.0.0', port=int(os.environ.get('PORT', 8766)))"
