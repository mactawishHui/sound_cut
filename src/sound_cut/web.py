from __future__ import annotations

import argparse
from dataclasses import replace
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any

from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for
from werkzeug.utils import secure_filename

from sound_cut.cli import (
    _finite_float,
    _non_negative_int,
    resolve_output_path,
)
from sound_cut.core import EnhancementConfig, SoundCutError, build_profile
from sound_cut.core.models import DEFAULT_TARGET_LUFS, LoudnessNormalizationConfig, SubtitleConfig
from sound_cut.editing.pipeline import process_audio

_APP_TITLE = "声剪 · SoundCut Studio"

_PAGE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500&family=Noto+Serif+SC:wght@700;900&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:           #F4EFE5;
      --surface:      #FDFAF4;
      --surface-hov:  #EDE7DB;
      --ink:          #1C1814;
      --muted:        rgba(28,24,20,0.48);
      --dim:          rgba(28,24,20,0.25);
      --red:          #C24326;
      --red-dim:      rgba(194,67,38,0.08);
      --red-border:   rgba(194,67,38,0.24);
      --blue:         #2C4B6E;
      --blue-dim:     rgba(44,75,110,0.07);
      --blue-border:  rgba(44,75,110,0.22);
      --border:       rgba(28,24,20,0.09);
      --border-s:     rgba(28,24,20,0.18);
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }

    body {
      font-family: "Crimson Pro", "Noto Serif SC", Georgia, serif;
      color: var(--ink);
      background: var(--bg);
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }

    /* Subtle paper grain */
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.68' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' opacity='0.028'/%3E%3C/svg%3E");
      pointer-events: none;
      z-index: 0;
    }

    .shell {
      position: relative;
      z-index: 1;
      max-width: 960px;
      margin: 0 auto;
      padding: 44px 28px 100px;
    }

    /* ── MASTHEAD ── */
    .masthead {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      border-bottom: 2px solid var(--ink);
      padding-bottom: 14px;
      margin-bottom: 60px;
      animation: fadeIn 0.5s ease both;
    }

    .brand {
      display: flex;
      align-items: baseline;
      gap: 14px;
    }

    .brand-kanji {
      font-family: "Noto Serif SC", serif;
      font-size: 1.5rem;
      font-weight: 900;
      letter-spacing: -0.04em;
    }

    .brand-latin {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.68rem;
      font-weight: 500;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .masthead-tag {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.67rem;
      letter-spacing: 0.07em;
      color: var(--muted);
    }

    /* ── HERO ── */
    .hero {
      margin-bottom: 68px;
      animation: slideUp 0.55s 0.04s ease both;
    }

    .hero-bg-num {
      font-family: "Crimson Pro", serif;
      font-size: clamp(6rem, 15vw, 14rem);
      font-weight: 300;
      line-height: 0.88;
      letter-spacing: -0.07em;
      color: rgba(28,24,20,0.06);
      user-select: none;
      margin-bottom: -0.06em;
    }

    .hero-title {
      font-family: "Noto Serif SC", serif;
      font-size: clamp(2.8rem, 6.5vw, 6rem);
      font-weight: 900;
      line-height: 1.0;
      letter-spacing: -0.04em;
      margin-bottom: 20px;
    }

    .hero-title .hi { color: var(--red); }

    .hero-desc {
      max-width: 52ch;
      font-size: 1.12rem;
      line-height: 1.88;
      color: var(--muted);
      font-family: "Noto Sans SC", sans-serif;
    }

    /* ── SECTION ── */
    .section {
      margin-bottom: 52px;
    }

    .section:nth-child(1) { animation: slideUp 0.45s 0.10s ease both; }
    .section:nth-child(2) { animation: slideUp 0.45s 0.17s ease both; }
    .section:nth-child(3) { animation: slideUp 0.45s 0.24s ease both; }

    .section-rule {
      border: none;
      border-top: 1px solid var(--border-s);
      margin-bottom: 22px;
    }

    .section-header {
      display: flex;
      align-items: baseline;
      gap: 14px;
      margin-bottom: 22px;
    }

    .section-num {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.7rem;
      font-weight: 500;
      letter-spacing: 0.1em;
      color: var(--red);
    }

    .section-title {
      font-family: "Crimson Pro", "Noto Serif SC", serif;
      font-size: 1.55rem;
      font-weight: 600;
      letter-spacing: -0.02em;
    }

    /* ── FILE UPLOAD ── */
    .upload-zone {
      display: block;
      position: relative;
      border: 1.5px dashed var(--border-s);
      border-radius: 3px;
      padding: 38px 28px;
      text-align: center;
      cursor: pointer;
      background: var(--surface);
      transition: border-color 0.2s ease, background 0.2s ease;
    }

    .upload-zone:hover {
      border-color: var(--red);
      background: var(--red-dim);
    }

    .upload-zone.has-file {
      border-color: var(--blue);
      background: var(--blue-dim);
    }

    .upload-zone input[type="file"] {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
      width: 100%;
      height: 100%;
    }

    .upload-title {
      font-family: "Crimson Pro", serif;
      font-size: 1.3rem;
      font-weight: 400;
      margin-bottom: 7px;
    }

    .upload-hint {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.72rem;
      letter-spacing: 0.05em;
      color: var(--muted);
    }

    .upload-fname {
      display: none;
      margin-top: 13px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.8rem;
      color: var(--blue);
      background: rgba(44,75,110,0.09);
      border: 1px solid var(--blue-border);
      border-radius: 2px;
      padding: 5px 13px;
      display: inline-block;
    }

    /* ── TOGGLE ROWS ── */
    .toggle-list { display: flex; flex-direction: column; }

    .toggle-item {
      display: flex;
      align-items: center;
      gap: 18px;
      padding: 16px 6px;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      transition: padding-left 0.15s ease;
      user-select: none;
    }

    .toggle-item:first-child { border-top: 1px solid var(--border); }
    .toggle-item:hover { padding-left: 10px; }

    .toggle-item input[type="checkbox"] { display: none; }

    .toggle-dot {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      border: 1.5px solid rgba(28,24,20,0.28);
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: border-color 0.18s ease, background 0.18s ease;
    }

    .toggle-dot::after {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: white;
      opacity: 0;
      transition: opacity 0.15s ease;
    }

    .toggle-item[data-active="true"] .toggle-dot {
      border-color: var(--red);
      background: var(--red);
    }

    .toggle-item[data-active="true"] .toggle-dot::after { opacity: 1; }

    .toggle-body { flex: 1; }

    .toggle-name {
      font-family: "Crimson Pro", "Noto Serif SC", serif;
      font-size: 1.18rem;
      font-weight: 600;
      letter-spacing: -0.01em;
      margin-bottom: 2px;
    }

    .toggle-desc {
      font-size: 0.88rem;
      color: var(--muted);
      font-family: "Noto Sans SC", sans-serif;
      line-height: 1.5;
    }

    .toggle-cli {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.68rem;
      letter-spacing: 0.05em;
      color: var(--dim);
      flex-shrink: 0;
    }

    /* ── FIELDS ── */
    .fg { display: grid; gap: 14px; }
    .fg2 { grid-template-columns: 1fr 1fr; }
    .fg3 { grid-template-columns: 1fr 1fr 1fr; }

    .field { display: flex; flex-direction: column; gap: 6px; }

    .field label {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.68rem;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 500;
    }

    input[type="text"],
    input[type="number"],
    select {
      border: 1px solid var(--border-s);
      border-radius: 2px;
      padding: 9px 11px;
      background: var(--surface);
      color: var(--ink);
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.87rem;
      width: 100%;
      transition: border-color 0.18s, box-shadow 0.18s;
      -webkit-appearance: none;
      appearance: none;
    }

    select {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='rgba(28,24,20,0.38)' stroke-width='1.4' stroke-linecap='round' fill='none'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 11px center;
      padding-right: 28px;
    }

    input:focus, select:focus {
      outline: none;
      border-color: var(--red);
      box-shadow: 0 0 0 3px var(--red-dim);
    }

    input::placeholder { color: var(--dim); }

    /* ── ADVANCED ── */
    .advanced {
      border-top: 1px solid var(--border-s);
      margin-bottom: 52px;
      animation: slideUp 0.45s 0.31s ease both;
    }

    .advanced summary {
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 15px 0;
      cursor: pointer;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.72rem;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--muted);
      user-select: none;
      transition: color 0.15s;
    }

    .advanced summary:hover { color: var(--ink); }
    .advanced summary::-webkit-details-marker { display: none; }

    .adv-arrow { transition: transform 0.2s ease; }
    details[open] .adv-arrow { transform: rotate(180deg); }

    .adv-body {
      padding-bottom: 32px;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }

    .adv-block {
      display: none;
      flex-direction: column;
      gap: 14px;
    }

    .adv-block[data-visible="true"] {
      display: flex;
      animation: slideUp 0.2s ease;
    }

    .adv-tag {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--red);
      font-weight: 500;
    }

    .adv-sep {
      height: 1px;
      background: var(--border);
    }

    /* ── MINI TOGGLES (subtitle embed mode) ── */
    .mini-list {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }

    .mini-item {
      display: flex;
      flex-direction: column;
      gap: 5px;
      padding: 13px;
      border: 1px solid var(--border-s);
      border-radius: 2px;
      cursor: pointer;
      background: var(--surface);
      transition: border-color 0.15s, background 0.15s;
      user-select: none;
    }

    .mini-item:hover {
      border-color: var(--red-border);
      background: var(--red-dim);
    }

    .mini-item[data-active="true"] {
      border-color: var(--red-border);
      background: var(--red-dim);
    }

    .mini-item input[type="checkbox"] { display: none; }

    .mini-name {
      font-family: "Noto Sans SC", sans-serif;
      font-size: 0.84rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 7px;
    }

    .mini-name::before {
      content: "○";
      font-size: 0.7rem;
      color: var(--dim);
      transition: color 0.15s;
      flex-shrink: 0;
    }

    .mini-item[data-active="true"] .mini-name::before {
      content: "●";
      color: var(--red);
    }

    .mini-desc {
      font-family: "Noto Sans SC", sans-serif;
      font-size: 0.76rem;
      color: var(--muted);
      line-height: 1.5;
    }

    /* ── CHECK ROW ── */
    .check-row {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 13px 16px;
      border: 1px solid var(--border);
      border-radius: 2px;
      background: var(--surface);
      cursor: pointer;
      transition: border-color 0.15s;
    }

    .check-row:hover { border-color: var(--border-s); }

    .check-row input {
      accent-color: var(--red);
      width: 14px;
      height: 14px;
      flex-shrink: 0;
      margin-top: 3px;
    }

    .check-row strong {
      display: block;
      font-size: 0.9rem;
      font-weight: 700;
      font-family: "Noto Sans SC", sans-serif;
      margin-bottom: 2px;
    }

    .check-row span {
      font-size: 0.78rem;
      color: var(--muted);
      font-family: "Noto Sans SC", sans-serif;
    }

    /* ── ALERTS ── */
    .alert {
      padding: 13px 17px;
      border-radius: 2px;
      font-size: 0.92rem;
      line-height: 1.65;
      font-family: "Noto Sans SC", sans-serif;
      margin-bottom: 10px;
    }

    .alert.error {
      background: var(--red-dim);
      border: 1px solid var(--red-border);
      border-left: 3px solid var(--red);
      color: var(--red);
    }

    /* ── RESULT ── */
    .result-block {
      border: 1px solid var(--blue-border);
      background: var(--blue-dim);
      border-radius: 3px;
      padding: 24px;
      margin-bottom: 12px;
      animation: slideUp 0.3s ease;
    }

    .result-head {
      display: flex;
      align-items: baseline;
      gap: 14px;
      margin-bottom: 18px;
    }

    .result-badge {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--blue);
      background: rgba(44,75,110,0.10);
      border: 1px solid var(--blue-border);
      border-radius: 2px;
      padding: 3px 8px;
    }

    .result-title {
      font-family: "Crimson Pro", serif;
      font-size: 1.45rem;
      font-weight: 600;
      letter-spacing: -0.02em;
    }

    .metrics {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1px;
      background: rgba(44,75,110,0.10);
      border-radius: 2px;
      overflow: hidden;
      border: 1px solid rgba(44,75,110,0.12);
      margin-bottom: 16px;
    }

    .metric {
      background: var(--surface);
      padding: 13px 16px;
    }

    .metric strong {
      display: block;
      font-family: "IBM Plex Mono", monospace;
      font-size: 1.2rem;
      color: var(--blue);
      letter-spacing: -0.02em;
      margin-bottom: 4px;
    }

    .metric span {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.65rem;
      color: var(--muted);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .dl-row { display: flex; gap: 10px; flex-wrap: wrap; }

    .dl-btn {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.78rem;
      letter-spacing: 0.04em;
      padding: 8px 17px;
      border-radius: 2px;
      background: rgba(44,75,110,0.10);
      border: 1px solid var(--blue-border);
      color: var(--blue);
      text-decoration: none;
      transition: background 0.15s;
    }

    .dl-btn:hover { background: rgba(44,75,110,0.18); }

    /* ── SUBMIT — HANKO SEAL ── */
    .submit-area {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 28px;
      flex-wrap: wrap;
      border-top: 2px solid var(--ink);
      padding-top: 32px;
      animation: slideUp 0.45s 0.38s ease both;
    }

    .submit-note {
      font-family: "Noto Sans SC", sans-serif;
      font-size: 0.9rem;
      color: var(--muted);
      line-height: 1.82;
      max-width: 44ch;
    }

    /* The hanko (判子) seal button */
    .btn-seal {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      width: 88px;
      height: 88px;
      border-radius: 50%;
      border: 2.5px solid var(--red);
      background: transparent;
      color: var(--red);
      cursor: pointer;
      position: relative;
      transition: background 0.22s ease, color 0.22s ease,
                  transform 0.22s ease, box-shadow 0.22s ease;
      flex-shrink: 0;
      font-family: "Noto Serif SC", serif;
      gap: 1px;
    }

    /* Inner concentric ring */
    .btn-seal::before {
      content: "";
      position: absolute;
      inset: 6px;
      border-radius: 50%;
      border: 1px solid rgba(194,67,38,0.30);
      transition: border-color 0.22s ease;
    }

    .btn-seal:hover {
      background: var(--red);
      color: white;
      transform: rotate(-6deg) scale(1.05);
      box-shadow: 5px 5px 0 rgba(194,67,38,0.20);
    }

    .btn-seal:hover::before { border-color: rgba(255,255,255,0.30); }
    .btn-seal:active { transform: rotate(-4deg) scale(0.97); box-shadow: none; }

    .seal-cjk {
      font-size: 1.1rem;
      font-weight: 900;
      letter-spacing: 0.1em;
      line-height: 1;
      z-index: 1;
    }

    .seal-lat {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.48rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      opacity: 0.68;
      z-index: 1;
    }

    /* ── ANIMATIONS ── */
    @keyframes fadeIn {
      from { opacity: 0; }
      to   { opacity: 1; }
    }

    @keyframes slideUp {
      from { opacity: 0; transform: translateY(12px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 760px) {
      .metrics    { grid-template-columns: 1fr 1fr; }
      .fg2, .fg3  { grid-template-columns: 1fr 1fr; }
      .mini-list  { grid-template-columns: 1fr 1fr; }
      .hero-bg-num { display: none; }
      .toggle-cli { display: none; }
    }

    @media (max-width: 520px) {
      .shell { padding: 28px 18px 72px; }
      .metrics, .fg2, .fg3, .mini-list { grid-template-columns: 1fr; }
      .submit-area { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
  <div class="shell">

    <!-- MASTHEAD -->
    <header class="masthead">
      <div class="brand">
        <span class="brand-kanji">声剪</span>
        <span class="brand-latin">SoundCut Studio</span>
      </div>
      <span class="masthead-tag" id="date-tag"></span>
    </header>

    <!-- HERO -->
    <section class="hero">
      <div class="hero-bg-num">声</div>
      <h1 class="hero-title">
        让<span class="hi">声音</span>只留<span class="hi">精华</span>
      </h1>
      <p class="hero-desc">
        上传音频或视频，选择需要的处理项。<br>
        静音裁切、音量均衡、语音增强、字幕生成——四种功能可单独使用，也可全部叠加。
      </p>
    </section>

    <form method="post" enctype="multipart/form-data">

      {% if error %}
      <div class="alert error">{{ error }}</div>
      {% endif %}

      {% if result %}
      <div class="result-block">
        <div class="result-head">
          <span class="result-badge">处理完成</span>
          <span class="result-title">结果文件已就绪</span>
        </div>
        <div class="metrics">
          <div class="metric">
            <strong>{{ "%.2f"|format(result.summary.input_duration_s) }}s</strong>
            <span>Original</span>
          </div>
          <div class="metric">
            <strong>{{ "%.2f"|format(result.summary.output_duration_s) }}s</strong>
            <span>Output</span>
          </div>
          <div class="metric">
            <strong>{{ "%.2f"|format(result.summary.removed_duration_s) }}s</strong>
            <span>Removed</span>
          </div>
          <div class="metric">
            <strong>{{ result.summary.kept_segment_count }}</strong>
            <span>Segments</span>
          </div>
        </div>
        <div class="dl-row">
          <a class="dl-btn" href="{{ url_for('download', job_id=result.job_id, artifact='output') }}">→ 下载处理结果</a>
          {% if result.has_subtitle %}
          <a class="dl-btn" href="{{ url_for('download', job_id=result.job_id, artifact='subtitle') }}">→ 下载字幕文件</a>
          {% endif %}
        </div>
      </div>
      {% endif %}

      <!-- 01 · FILE -->
      <div class="section">
        <hr class="section-rule">
        <div class="section-header">
          <span class="section-num">01 ·</span>
          <span class="section-title">上传源文件</span>
        </div>
        <label class="upload-zone" id="upload-zone" for="input_file">
          <p class="upload-title">点击选择文件，或拖放到这里</p>
          <p class="upload-hint">MP3 · M4A · WAV · MP4 · MKV · MOV · WEBM · AAC</p>
          <div class="upload-fname" id="upload-fname"></div>
          <input id="input_file" type="file" name="input_file" required
            accept=".mp3,.m4a,.wav,.mp4,.mov,.mkv,.flv,.webm,.aac,.ogg">
        </label>
      </div>

      <!-- 02 · MODES -->
      <div class="section">
        <hr class="section-rule">
        <div class="section-header">
          <span class="section-num">02 ·</span>
          <span class="section-title">选择处理操作</span>
        </div>
        <div class="toggle-list">
          <label class="toggle-item" data-active="{{ 'true' if form.cut else 'false' }}">
            <input type="checkbox" name="cut" {% if form.cut %}checked{% endif %}>
            <div class="toggle-dot"></div>
            <div class="toggle-body">
              <div class="toggle-name">静音裁切</div>
              <div class="toggle-desc">自动检测并移除长时间停顿，输出更紧凑的音频</div>
            </div>
            <span class="toggle-cli">--cut</span>
          </label>
          <label class="toggle-item" data-active="{{ 'true' if form.auto_volume else 'false' }}">
            <input type="checkbox" name="auto_volume" {% if form.auto_volume %}checked{% endif %}>
            <div class="toggle-dot"></div>
            <div class="toggle-body">
              <div class="toggle-name">音量均衡</div>
              <div class="toggle-desc">响度标准化到 -16 LUFS，统一来自不同来源的音频音量</div>
            </div>
            <span class="toggle-cli">--auto-volume</span>
          </label>
          <label class="toggle-item" data-active="{{ 'true' if form.enhance_speech else 'false' }}">
            <input type="checkbox" name="enhance_speech" {% if form.enhance_speech %}checked{% endif %}>
            <div class="toggle-dot"></div>
            <div class="toggle-body">
              <div class="toggle-name">语音增强</div>
              <div class="toggle-desc">AI 降噪处理，过滤背景噪音，提升人声清晰度</div>
            </div>
            <span class="toggle-cli">--enhance-speech</span>
          </label>
          <label class="toggle-item" data-active="{{ 'true' if form.subtitle else 'false' }}">
            <input type="checkbox" name="subtitle" {% if form.subtitle %}checked{% endif %}>
            <div class="toggle-dot"></div>
            <div class="toggle-body">
              <div class="toggle-name">生成字幕</div>
              <div class="toggle-desc">FunASR 语音转文字，支持多语言自动识别，可嵌入视频</div>
            </div>
            <span class="toggle-cli">--subtitle</span>
          </label>
        </div>
      </div>

      <!-- 03 · BASIC CONFIG -->
      <div class="section">
        <hr class="section-rule">
        <div class="section-header">
          <span class="section-num">03 ·</span>
          <span class="section-title">基础配置</span>
        </div>
        <div class="fg" style="max-width: 260px;">
          <div class="field">
            <label for="aggressiveness">裁切激进度</label>
            <select id="aggressiveness" name="aggressiveness">
              {% for value in ["natural", "balanced", "dense"] %}
              <option value="{{ value }}" {% if form.aggressiveness == value %}selected{% endif %}>{{ value }}</option>
              {% endfor %}
            </select>
          </div>
        </div>
      </div>

      <!-- ADVANCED -->
      <details class="advanced">
        <summary>
          <span>高级配置 — 展开细节参数</span>
          <span class="adv-arrow">↓</span>
        </summary>
        <div class="adv-body">

          <!-- cut params -->
          <div class="adv-block" data-feature="cut" data-visible="{{ 'true' if form.cut else 'false' }}">
            <div class="adv-tag">裁切参数</div>
            <div class="fg fg3">
              <div class="field">
                <label for="min_silence_ms">最短静音 (ms)</label>
                <input id="min_silence_ms" type="number" min="0" name="min_silence_ms"
                  value="{{ form.min_silence_ms }}" placeholder="默认">
              </div>
              <div class="field">
                <label for="padding_ms">首尾留白 (ms)</label>
                <input id="padding_ms" type="number" min="0" name="padding_ms"
                  value="{{ form.padding_ms }}" placeholder="默认">
              </div>
              <div class="field">
                <label for="crossfade_ms">交叉淡化 (ms)</label>
                <input id="crossfade_ms" type="number" min="0" name="crossfade_ms"
                  value="{{ form.crossfade_ms }}" placeholder="默认">
              </div>
            </div>
          </div>

          <!-- volume params -->
          <div class="adv-block" data-feature="auto_volume" data-visible="{{ 'true' if form.auto_volume else 'false' }}">
            <div class="adv-tag">响度目标</div>
            <div class="fg" style="max-width: 200px;">
              <div class="field">
                <label for="target_lufs">Target LUFS</label>
                <input id="target_lufs" type="number" step="0.1" name="target_lufs"
                  value="{{ form.target_lufs }}" placeholder="-16.0">
              </div>
            </div>
          </div>

          <!-- enhance params -->
          <div class="adv-block" data-feature="enhance_speech" data-visible="{{ 'true' if form.enhance_speech else 'false' }}">
            <div class="adv-tag">增强参数</div>
            <div class="fg fg2">
              <div class="field">
                <label for="enhancer_backend">增强后端</label>
                <select id="enhancer_backend" name="enhancer_backend">
                  {% for value in ["deepfilternet3", "metricgan-plus", "demucs-vocals", "resemble-enhance"] %}
                  <option value="{{ value }}" {% if form.enhancer_backend == value %}selected{% endif %}>{{ value }}</option>
                  {% endfor %}
                </select>
              </div>
              <div class="field">
                <label for="enhancer_profile">增强强度</label>
                <select id="enhancer_profile" name="enhancer_profile">
                  {% for value in ["natural", "strong"] %}
                  <option value="{{ value }}" {% if form.enhancer_profile == value %}selected{% endif %}>{{ value }}</option>
                  {% endfor %}
                </select>
              </div>
              <div class="field">
                <label for="enhancer_fallback">失败回退</label>
                <select id="enhancer_fallback" name="enhancer_fallback">
                  {% for value in ["fail", "original", "deepfilternet3", "metricgan-plus"] %}
                  <option value="{{ value }}" {% if form.enhancer_fallback == value %}selected{% endif %}>{{ value }}</option>
                  {% endfor %}
                </select>
              </div>
              <div class="field">
                <label for="model_path">模型目录</label>
                <input id="model_path" type="text" name="model_path"
                  value="{{ form.model_path }}" placeholder="留空使用默认缓存目录">
              </div>
            </div>
          </div>

          <!-- subtitle params -->
          <div class="adv-block" data-feature="subtitle" data-visible="{{ 'true' if form.subtitle else 'false' }}">
            <div class="adv-tag">字幕参数</div>
            <div class="fg fg2">
              <div class="field">
                <label for="subtitle_format">字幕格式</label>
                <select id="subtitle_format" name="subtitle_format">
                  {% for value in ["srt", "vtt"] %}
                  <option value="{{ value }}" {% if form.subtitle_format == value %}selected{% endif %}>{{ value }}</option>
                  {% endfor %}
                </select>
              </div>
              <div class="field">
                <label for="subtitle_language">字幕语言</label>
                <input id="subtitle_language" type="text" name="subtitle_language"
                  value="{{ form.subtitle_language }}" placeholder="留空自动识别">
              </div>
              <div class="field">
                <label for="subtitle_api_key">DashScope API Key</label>
                <input id="subtitle_api_key" type="text" name="subtitle_api_key"
                  value="{{ form.subtitle_api_key }}" placeholder="sk-...">
              </div>
              <div class="field">
                <label for="subtitle_max_chars">单条最大字符数</label>
                <input id="subtitle_max_chars" type="number" min="0" name="subtitle_max_chars"
                  value="{{ form.subtitle_max_chars }}">
              </div>
            </div>
            <div class="mini-list">
              <label class="mini-item" data-active="{{ 'true' if form.subtitle_sidecar else 'false' }}">
                <input type="checkbox" name="subtitle_sidecar" {% if form.subtitle_sidecar %}checked{% endif %}>
                <div class="mini-name">仅输出字幕文件</div>
                <div class="mini-desc">不嵌入媒体，只生成 .srt / .vtt sidecar</div>
              </label>
              <label class="mini-item" data-active="{{ 'true' if form.subtitle_mkv else 'false' }}">
                <input type="checkbox" name="subtitle_mkv" {% if form.subtitle_mkv %}checked{% endif %}>
                <div class="mini-name">MKV 软字幕</div>
                <div class="mini-desc">封装进 MKV，可在播放器中切换显示</div>
              </label>
              <label class="mini-item" data-active="{{ 'true' if form.subtitle_burn else 'false' }}">
                <input type="checkbox" name="subtitle_burn" {% if form.subtitle_burn %}checked{% endif %}>
                <div class="mini-name">硬烧录字幕</div>
                <div class="mini-desc">字幕烧入画面，任何播放器均可见</div>
              </label>
            </div>
          </div>

          <div class="adv-sep"></div>

          <label class="check-row">
            <input type="checkbox" name="keep_temp" {% if form.keep_temp %}checked{% endif %}>
            <div>
              <strong>保留临时文件</strong>
              <span>调试时使用，会占用额外磁盘空间</span>
            </div>
          </label>

        </div>
      </details>

      <!-- SUBMIT -->
      <div class="submit-area">
        <p class="submit-note">
          处理过程同步执行，完成后页面自动显示结果。<br>
          大文件或启用语音增强时可能需要数分钟，请耐心等待。
        </p>
        <button class="btn-seal" type="submit" title="开始处理">
          <span class="seal-cjk">处理</span>
          <span class="seal-lat">process</span>
        </button>
      </div>

    </form>
  </div>

  <script>
    // Masthead date
    const d = new Date();
    const tag = document.getElementById('date-tag');
    if (tag) tag.textContent =
      d.getFullYear() + ' · ' +
      String(d.getMonth()+1).padStart(2,'0') + ' · ' +
      String(d.getDate()).padStart(2,'0');

    // File input
    const fi = document.getElementById('input_file');
    const fn = document.getElementById('upload-fname');
    const uz = document.getElementById('upload-zone');
    if (fi) {
      fi.addEventListener('change', () => {
        const f = fi.files[0];
        if (f) {
          fn.textContent = f.name;
          fn.style.display = 'inline-block';
          uz.classList.add('has-file');
        } else {
          fn.style.display = 'none';
          uz.classList.remove('has-file');
        }
      });
    }

    // Toggle rows + advanced blocks + mini-items
    function sync(name) {
      const cb = document.querySelector(`input[name="${name}"]`);
      if (!cb) return;
      const row = cb.closest('.toggle-item');
      if (row) row.dataset.active = cb.checked ? 'true' : 'false';
      const mini = cb.closest('.mini-item');
      if (mini) mini.dataset.active = cb.checked ? 'true' : 'false';
      const block = document.querySelector(`.adv-block[data-feature="${name}"]`);
      if (block) block.dataset.visible = cb.checked ? 'true' : 'false';
    }

    ['cut','auto_volume','enhance_speech','subtitle',
     'subtitle_sidecar','subtitle_mkv','subtitle_burn'].forEach(n => {
      const cb = document.querySelector(`input[name="${n}"]`);
      if (!cb) return;
      cb.addEventListener('change', () => sync(n));
      sync(n);
    });
  </script>
</body>
</html>
"""


def build_ui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut ui")
    parser.set_defaults(command="ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    return parser


def create_app() -> Flask:
    app = Flask(__name__)
    workspace = Path(tempfile.gettempdir()) / "sound-cut-web"
    workspace.mkdir(parents=True, exist_ok=True)
    app.config["WORKSPACE"] = workspace
    app.config["JOBS"] = {}

    @app.get("/")
    def index():
        return render_template_string(
            _PAGE_TEMPLATE,
            title=_APP_TITLE,
            form=_default_form_state(),
            result=None,
            error=None,
        )

    @app.post("/")
    def process_upload():
        file = request.files.get("input_file")
        if file is None or not file.filename:
            return _render_form(error="Choose an input file before starting processing.")

        form = _read_form_state(request.form)
        if not any((form["cut"], form["auto_volume"], form["enhance_speech"], form["subtitle"])):
            return _render_form(form=form, error="Enable at least one processing mode before processing.")

        job_id = secrets.token_hex(8)
        job_dir = app.config["WORKSPACE"] / job_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        input_name = secure_filename(file.filename) or "input.bin"
        input_path = input_dir / input_name
        file.save(input_path)

        try:
            summary, effective_output = _run_web_job(
                input_path=input_path,
                output_dir=output_dir,
                form=form,
            )
        except SoundCutError as exc:
            return _render_form(form=form, error=str(exc))
        except ValueError as exc:
            return _render_form(form=form, error=str(exc))

        subtitle_path = summary.subtitle_path
        app.config["JOBS"][job_id] = {
            "output_path": effective_output,
            "subtitle_path": subtitle_path,
        }
        result = {
            "job_id": job_id,
            "summary": summary,
            "has_subtitle": subtitle_path is not None and subtitle_path.exists(),
        }
        return render_template_string(
            _PAGE_TEMPLATE,
            title=_APP_TITLE,
            form=form,
            result=result,
            error=None,
        )

    @app.get("/downloads/<job_id>/<artifact>")
    def download(job_id: str, artifact: str):
        job = app.config["JOBS"].get(job_id)
        if job is None:
            abort(404)
        if artifact == "output":
            path = job["output_path"]
        elif artifact == "subtitle":
            path = job["subtitle_path"]
        else:
            abort(404)
        if path is None or not Path(path).exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=Path(path).name)

    return app


def _render_form(*, form: dict[str, Any] | None = None, error: str | None = None):
    return render_template_string(
        _PAGE_TEMPLATE,
        title=_APP_TITLE,
        form=form or _default_form_state(),
        result=None,
        error=error,
    )


def _default_form_state() -> dict[str, Any]:
    return {
        "cut": False,
        "auto_volume": False,
        "enhance_speech": True,
        "subtitle": False,
        "keep_temp": False,
        "aggressiveness": "balanced",
        "target_lufs": "",
        "min_silence_ms": "",
        "padding_ms": "",
        "crossfade_ms": "",
        "enhancer_backend": "deepfilternet3",
        "enhancer_profile": "natural",
        "enhancer_fallback": "fail",
        "model_path": "",
        "subtitle_format": "srt",
        "subtitle_language": "",
        "subtitle_api_key": "",
        "subtitle_sidecar": False,
        "subtitle_max_chars": "25",
        "subtitle_mkv": False,
        "subtitle_burn": False,
    }


def _read_form_state(form: Any) -> dict[str, Any]:
    state = _default_form_state()
    state.update(
        {
            "cut": form.get("cut") == "on",
            "auto_volume": form.get("auto_volume") == "on",
            "enhance_speech": form.get("enhance_speech") == "on",
            "subtitle": form.get("subtitle") == "on",
            "keep_temp": form.get("keep_temp") == "on",
            "aggressiveness": form.get("aggressiveness", "balanced"),
            "target_lufs": form.get("target_lufs", "").strip(),
            "min_silence_ms": form.get("min_silence_ms", "").strip(),
            "padding_ms": form.get("padding_ms", "").strip(),
            "crossfade_ms": form.get("crossfade_ms", "").strip(),
            "enhancer_backend": form.get("enhancer_backend", "deepfilternet3"),
            "enhancer_profile": form.get("enhancer_profile", "natural"),
            "enhancer_fallback": form.get("enhancer_fallback", "fail"),
            "model_path": form.get("model_path", "").strip(),
            "subtitle_format": form.get("subtitle_format", "srt"),
            "subtitle_language": form.get("subtitle_language", "").strip(),
            "subtitle_api_key": form.get("subtitle_api_key", "").strip(),
            "subtitle_sidecar": form.get("subtitle_sidecar") == "on",
            "subtitle_max_chars": form.get("subtitle_max_chars", "25").strip(),
            "subtitle_mkv": form.get("subtitle_mkv") == "on",
            "subtitle_burn": form.get("subtitle_burn") == "on",
        }
    )
    return state


def _run_web_job(*, input_path: Path, output_dir: Path, form: dict[str, Any]):
    profile = build_profile(form["aggressiveness"])
    overrides = {
        "min_silence_ms": _optional_int(form["min_silence_ms"]),
        "padding_ms": _optional_int(form["padding_ms"]),
        "crossfade_ms": _optional_int(form["crossfade_ms"]),
    }
    profile = replace(profile, **{key: value for key, value in overrides.items() if value is not None})

    loudness = LoudnessNormalizationConfig(
        enabled=form["auto_volume"],
        target_lufs=DEFAULT_TARGET_LUFS if not form["target_lufs"] else _finite_float(form["target_lufs"]),
    )
    enhancement = EnhancementConfig(
        enabled=form["enhance_speech"],
        backend=form["enhancer_backend"],
        profile=form["enhancer_profile"],
        model_path=Path(form["model_path"]) if form["model_path"] else None,
        fallback=form["enhancer_fallback"],
    )
    subtitle = SubtitleConfig(
        enabled=form["subtitle"],
        language=form["subtitle_language"] or None,
        format=form["subtitle_format"],
        api_key=form["subtitle_api_key"] or os.environ.get("DASHSCOPE_API_KEY"),
        sidecar_only=form["subtitle_sidecar"],
        max_chars_per_subtitle=_non_negative_int(form["subtitle_max_chars"] or "25"),
        embed_mode="burn" if form["subtitle_burn"] else "mkv" if form["subtitle_mkv"] else "mp4",
    )

    output_path = resolve_output_path(input_path, None)
    output_path = output_dir / output_path.name
    summary = process_audio(
        input_path,
        output_path,
        profile,
        keep_temp=form["keep_temp"],
        loudness=loudness,
        enable_cut=form["cut"],
        enhancement=enhancement,
        subtitle=subtitle,
    )
    effective_output = summary.output_path or output_path
    return summary, effective_output


def _optional_int(value: str) -> int | None:
    if not value:
        return None
    return _non_negative_int(value)


def run_ui(*, host: str, port: int, debug: bool = False) -> int:
    app = create_app()
    app.run(host=host, port=port, debug=debug)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_ui_parser()
    args = parser.parse_args(argv)
    return run_ui(host=args.host, port=args.port, debug=args.debug)
