# sound-cut

`sound-cut` 是一个 Python 命令行工具，用于缩短语音音频，通过移除低频停顿来保持语音内容完整。

## 快速入门

对音频文件运行该工具：

```bash
python3.11 -m sound_cut input.mp3 --aggressiveness dense
```

这将在输入文件旁边生成一个缩短后的输出文件。默认路径：
- `input.mp3` -> `input.cut.mp3`
- `input.m4a` -> `input.cut.m4a`
- `input.wav` -> `input.cut.wav`

如果您需要指定输出路径：

```bash
python3.11 -m sound_cut input.mp3 -o output.mp3 --aggressiveness dense
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
2. 检测语音区域
3. 构建保留/丢弃时间线
4. 剪切原始音频
5. 导出缩短后的音频文件

对于诸如 `mp3` 和 `m4a` 之类的压缩输出，输出比特率会在 `64k 到 `128k` 的范围内自适应选择，以保持输出文件大小合理。

## 输出规则

- 如果省略 `-o/--output`，则输出格式会跟随输入后缀（如果支持）。
- 支持的输出格式为 `.mp3`、`.m4a` 和 `.wav`。
- 不支持的输入后缀在自动推断输出格式时会回退到 `.m4a`。
- 输入路径和输出路径必须不同。

## 常用选项

- `--aggressiveness {natural,balanced,dense}`：控制去除停顿的力度。默认值为 `balanced`。
- `--min-silence-ms N`：覆盖可去除的最小静音长度。
- `--padding-ms N`：保留检测到的语音边界周围的额外音频。
- `--crossfade-ms N`：在剪辑边界处应用短淡入淡出效果。
- `--auto-volume`：为最终输出启用响度归一化。该功能默认关闭，必须显式开启。
- `--target-lufs N`：在启用 `--auto-volume` 时设置目标响度。默认值为 `-16.0`。
- `--keep-temp`：保留中间分析音频以进行调试。

## 示例

更激进的剪辑，并明确输出：

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
  --aggressiveness dense \
  --min-silence-ms 140 \
  --padding-ms 40 \
  --crossfade-ms 5
```

在同一条命令里同时剪掉停顿并做响度归一化：

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
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
  --aggressiveness balanced \
  --min-silence-ms 180 \
  --auto-volume
```

## 命令行输出

该命令会打印一个简短的摘要：
- `input_duration_s`：原始时长
- `output_duration_s`：最终时长
- `removed_duration_s`：已移除的时长
- `kept_segment_count`：保留的语音片段数量片段

示例：

```文本
`input_duration_s=49.002`
`output_duration_s=38.402`
`removed_duration_s=10.600`
`kept_segment_count=11`
```

## 运行测试

```bash
`python3.11 -m pytest -q`
```
