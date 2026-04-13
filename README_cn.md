# sound-cut 声剪

`sound-cut` 是一个 Python 音视频处理工具，支持自动去除停顿、响度均衡、AI 语音增强和字幕生成，提供 **Web UI** 和 **命令行** 两种使用方式。

## Web UI（推荐）

### 本地开发

```bash
# 1. 启动 API 服务
DASHSCOPE_API_KEY=<你的密钥> python start.py

# 2. 另开终端启动前端开发服务器
cd frontend && npm install && npm run dev
```

浏览器访问 [http://localhost:5173](http://localhost:5173)。

### 部署到 Zeabur（免费，国内可直接访问）

1. 将代码推送到 GitHub
2. 在 [zeabur.com](https://zeabur.com) 创建项目，地区选择**香港**或**新加坡**
3. 添加服务 → Git → 选择本仓库，分支 `feature/web-ui`
4. 设置环境变量：`DASHSCOPE_API_KEY=<你的密钥>`
5. 生成域名，部署完成

Dockerfile 已包含所有依赖：Node 前端构建 + Python + ffmpeg，一键部署。

### Docker 部署

```bash
docker build -t sound-cut .
docker run -p 8080:8080 -e DASHSCOPE_API_KEY=<你的密钥> sound-cut
```

浏览器访问 [http://localhost:8080](http://localhost:8080)。

---

## 命令行（CLI）

### 快速入门

```bash
sound-cut input.mp3 --cut
sound-cut input.mp4 --cut --auto-volume --enhance-speech
sound-cut input.mp3 --subtitle
```

默认输出路径：
- `input.mp3` → `input.cut.mp3`
- `input.mp4` → `input.cut.mp4`

指定输出路径：

```bash
sound-cut input.mp3 -o output.mp3 --cut
```

### 安装

```bash
pip install -e ".[dev]"
```

依赖：Python 3.11+、`ffmpeg`、`ffprobe`

---

## 功能一览

| 功能 | 参数 | 说明 |
|------|------|------|
| 静音裁切 | `--cut` | 自动检测并移除长时间停顿 |
| 音量均衡 | `--auto-volume` | 响度归一化，默认目标 −16 LUFS |
| 语音增强 | `--enhance-speech` | DeepFilterNet3 AI 降噪，提升人声清晰度 |
| 字幕生成 | `--subtitle` | FunASR + DashScope API 语音转文字 |

四项功能完全独立，可自由组合。

### 处理流程

```
probe_source_media()
  → enhance_audio()              # --enhance-speech
  → normalize_audio_for_analysis()
  → WebRtcSpeechAnalyzer.analyze()
  → refine_speech_ranges()
  → build_edit_decision_list()   # --cut
  → render_audio_from_edl()
  → normalize_loudness()         # --auto-volume
  → generate_subtitles()         # --subtitle
  → export_delivery_audio()
→ RenderSummary
```

---

## CLI 参数说明

### 静音裁切
- `--cut` — 启用静音裁切
- `--aggressiveness {natural,balanced,dense}` — 裁切力度，默认 `balanced`
- `--min-silence-ms N` — 可被移除的最短静音时长（毫秒）
- `--padding-ms N` — 语音边界两侧保留的缓冲时长（毫秒）
- `--crossfade-ms N` — 剪切边界处的交叉淡化时长（毫秒）

### 音量均衡
- `--auto-volume` — 启用响度归一化
- `--target-lufs N` — 目标响度，默认 `-16.0`

### 语音增强
- `--enhance-speech` — 启用语音增强
- `--enhancer-backend {deepfilternet3,resemble-enhance}` — 增强后端，默认 `deepfilternet3`
- `--enhancer-profile {natural,strong}` — 增强强度，默认 `natural`
- `--model-path PATH` — 指定本地模型目录

### 字幕生成
- `--subtitle` — 启用字幕生成（需要 `DASHSCOPE_API_KEY`）
- `--subtitle-language LANG` — 语言提示（如 `zh`、`en`、`ja`），默认自动识别
- `--subtitle-format {srt,vtt}` — 输出格式，默认 `srt`
- `--subtitle-sidecar` — 只输出字幕文件，不嵌入视频
- `--subtitle-mkv` — 嵌入为 MKV 软字幕轨道
- `--subtitle-burn` — 将字幕硬烧录入视频画面
- `--subtitle-max-chars N` — 每条字幕最大字符数，默认 `25`

### 其他
- `--keep-temp` — 保留中间文件（调试用）
- `-o / --output PATH` — 显式指定输出路径

---

## 示例

激进裁切并添加交叉淡化：

```bash
sound-cut podcast.mp3 -o podcast.cut.mp3 \
  --cut --aggressiveness dense \
  --min-silence-ms 140 --crossfade-ms 5
```

语音增强 + 裁切 + 响度均衡一键完成：

```bash
sound-cut lecture.wav \
  --enhance-speech --cut --auto-volume --target-lufs -14
```

生成独立字幕文件：

```bash
DASHSCOPE_API_KEY=<密钥> sound-cut interview.mp3 \
  --subtitle --subtitle-language zh --subtitle-sidecar
```

完整流水线 — 增强 + 裁切 + 均衡 + 硬烧字幕：

```bash
DASHSCOPE_API_KEY=<密钥> sound-cut talk.mp4 \
  --enhance-speech --cut --auto-volume \
  --subtitle --subtitle-burn
```

---

## 模型管理

```bash
sound-cut models list
sound-cut models install deepfilternet3
sound-cut models import deepfilternet3 /path/to/model-dir
sound-cut models verify deepfilternet3
```

DeepFilterNet3 还需要额外安装运行时依赖：`pip install deepfilternet`

---

## 命令行输出示例

```text
input_duration_s=49.002
output_duration_s=38.402
removed_duration_s=10.600
kept_segment_count=11
```

---

## 运行测试

```bash
pytest
```

集成测试（需要先启动 API 服务）：

```bash
python tests/integration/test_api_e2e.py
```
