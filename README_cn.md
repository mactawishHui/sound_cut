# sound-cut

`sound-cut` 是一个 Python 命令行工具，用于缩短语音音频，通过移除低频停顿来保持语音内容完整。

## 快速入门

对音频文件运行该工具：

```bash
python3.11 -m sound_cut input.mp3 --cut
```

这将在输入文件旁边生成一个缩短后的输出文件。默认路径：
- `input.mp3` -> `input.cut.mp3`
- `input.m4a` -> `input.cut.m4a`
- `input.wav` -> `input.cut.wav`
- `input.mp4` -> `input.cut.mp4`

如果您需要指定输出路径：

```bash
python3.11 -m sound_cut input.mp3 -o output.mp3 --cut
```

## 系统要求

- Python `3.11+`
- `ffmpeg`
- `ffprobe`

## 安装
以可编辑模式安装：
```bash
python3.11 -m pip install -e .[dev]
```

## 工作原理

命令行界面 (CLI)：
1. 探测输入媒体
2. 在设置 `--enhance-speech` 时先执行语音增强
3. 检测语音区域
4. 构建保留/丢弃时间线
5. 在设置 `--cut` 时剪切源时间线
6. 在设置 `--auto-volume` 时对最终输出做响度归一化
7. 导出所请求的音频文件

对于诸如 `mp3` 和 `m4a` 之类的压缩输出，输出比特率会在 `64k` 到 `128k` 的范围内自适应选择，以保持输出文件大小合理。

## 处理模式

`--enhance-speech`、`--cut` 和 `--auto-volume` 是相互独立的功能。它们可以单独使用，也可以在同一条命令里一起使用。

有效的命令形式：

```bash
sound-cut input.mp3 --enhance-speech
sound-cut input.mp3 --cut
sound-cut input.mp3 --auto-volume
sound-cut input.mp3 --enhance-speech --cut
sound-cut input.mp3 --enhance-speech --auto-volume
sound-cut input.mp3 --cut --aggressiveness dense --auto-volume
sound-cut input.mp3 --auto-volume --target-lufs -14
```

`--enhance-speech` 会在可选剪切前先进行本地语音增强。`--cut` 会根据检测到的语音时间线执行剪切。`--auto-volume` 会对最终输出启用响度归一化。三种模式默认都不启用。

## 输出规则

- 如果省略 `-o/--output`，则输出格式会跟随输入后缀（如果支持）。
- 支持的输出格式为 `.mp3`、`.m4a`、`.wav` 和 `.mp4`。
- 对于 `.mp4` 输出，会先处理音轨，再把处理后的音轨回封装到视频中。
- 对于 `.mp4` 且启用 `--cut` 的场景，会对音频和视频应用同一条保留/丢弃时间线，保证音视频同步。
- 不支持的输入后缀在自动推断输出格式时会回退到 `.m4a`。
- 输入路径和输出路径必须不同。

## 常用选项

- `--aggressiveness {natural,balanced,dense}`：控制去除停顿的力度。默认值为 `balanced`。
- `--min-silence-ms N`：覆盖可去除的最小静音长度。
- `--padding-ms N`：保留检测到的语音边界周围的额外音频。
- `--crossfade-ms N`：在剪辑边界处应用短淡入淡出效果。
- `--enhance-speech`：启用本地离线语音增强（在可选剪切前执行）。
- `--enhancer-backend {deepfilternet3,resemble-enhance}`：选择增强后端，默认 `deepfilternet3`。`resemble-enhance` 目前仍是占位后端，暂不可直接运行。
- `--enhancer-profile {natural,strong}`：选择增强强度，默认 `natural`。
- `--model-path PATH`：显式指定本地模型目录。对于 `deepfilternet3`，该路径可直接指向原始模型文件目录（不强制需要 manifest）。
- `--auto-volume`：为最终输出启用响度归一化。该功能默认关闭，必须显式开启。
- `--target-lufs N`：在启用 `--auto-volume` 时设置目标响度。默认值为 `-16.0`。
- `--cut`：启用输入音频的剪切。该功能默认关闭，必须显式开启。
- `--keep-temp`：保留中间分析音频以进行调试。

## 示例

更激进的剪辑，并明确输出：

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
  --cut \
  --aggressiveness dense \
  --min-silence-ms 140 \
  --padding-ms 40 \
  --crossfade-ms 5
```

在同一条命令里同时剪切并做响度归一化：

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
  --cut \
  --aggressiveness dense \
  --min-silence-ms 140 \
  --padding-ms 40 \
  --crossfade-ms 5 \
  --auto-volume \
  --target-lufs -14.0
```

如果省略 `--target-lufs`，`--auto-volume` 会使用默认目标 `-16.0`：

```bash
python3.11 -m sound_cut interview.wav \
  --auto-volume
```

在同一条命令里同时执行语音增强、剪切和响度归一化：

```bash
python3.11 -m sound_cut lecture.wav \
  --enhance-speech \
  --cut \
  --auto-volume
```

## 模型命令

安装并检查本地增强模型：

```bash
python3.11 -m sound_cut models list
python3.11 -m sound_cut models install deepfilternet3
```

导入本地已下载模型目录：

```bash
python3.11 -m sound_cut models import deepfilternet3 /path/to/model-dir
python3.11 -m sound_cut models verify deepfilternet3
```

`models install` 会先创建本地模型目录与 manifest 脚手架。
`models import` 负责拷贝实际模型文件，随后可用 `models verify` 校验是否就绪。
`models list` 会将仅有脚手架的目录显示为 `prepared` 状态。

`DeepFilterNet3` 增强能力还需要本地运行时依赖（例如 `pip install deepfilternet`）。

## 命令行输出

该命令会打印一个简短的摘要：
- `input_duration_s`：原始时长
- `output_duration_s`：最终时长
- `removed_duration_s`：已移除的时长
- `kept_segment_count`：保留的语音片段数量

示例：

```text
input_duration_s=49.002
output_duration_s=38.402
removed_duration_s=10.600
kept_segment_count=11
```

## 运行测试

```bash
python3.11 -m pytest -q
```
