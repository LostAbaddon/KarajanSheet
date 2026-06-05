# Chopin v1.0.0

**Chopin** 是一个基于自定义脚本语言的音频编排引擎。使用 **ChopinSheet** 脚本语法声明式地定义多段音频的拼接、TTS 合成、音量控制与响度归一化,一键生成最终音频。

## 特性

- **ChopinSheet 脚本语言** — 声明式 DSL,简洁描述音频片段编排
- **TTS 集成** — 内置 OmniVoice 语音合成,支持音色克隆
- **多格式支持** — 自动处理 mp3/wav/m4a/flac 等常见音频格式
- **精确控制** — 支持时间截取、声道音量控制、片段间隔/重叠、响度归一化
- **批量合成** — 提供长文本分批 TTS 合成与自动拼接工具

## 安装

```bash
pip install omnivoice numpy soundfile torch
```

此外需要系统安装 `ffmpeg` 用于音频格式转换。

## 快速开始

### 1. 编写 ChopinSheet 脚本

创建一个 `.audio` 文件:

```chopinsheet
@sample_rate 24000
@base_volume 0.2
@base_path .

@segment intro
    tts: "欢迎收听今天的节目,这是一个关于音频脚本引擎的演示"
    voice: sample.wav
    ref_text: "大家好,这里是胡聊瞎侃嘚啵嘚播客,我是主持人塔塔"
    gap: -0.5s

@segment narration
    tts: "我是节目主持人,我叫塔塔,大家好!"
```

### 2. 执行脚本

```bash
python audio_script.py -s example.audio -o output.wav
```

### 3. 批量 TTS 合成

```bash
python batch_tts.py \
  --sampleAudio sample.wav \
  --sampleText sample.txt \
  --target script.md \
  --output output.wav \
  --interval 0.3
```

## ChopinSheet 语法

完整语法参考请见 [SYNTAX.md](SYNTAX.md)。

## TTS 引擎

本项目使用 **[OmniVoice](https://github.com/k2-fsa/OmniVoice)** 作为语音合成引擎。OmniVoice 是一个基于语音离散化标记的 zero-shot 大规模 TTS 模型,能够通过参考音频实现高保真的音色克隆。

- 官网/GitHub: [https://github.com/k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
- HuggingFace 模型: [k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)

## 命令行参数

### audio_script.py

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--script` | `-s` | 脚本文件路径 | 必填 |
| `--output` | `-o` | 输出音频文件路径 | `output.wav` |
| `--base-path` | `-b` | 覆盖脚本中的 `@base_path` | 脚本中设置的值 |

### batch_tts.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--sampleAudio` | 音色克隆参考音频路径 | `sample.wav` |
| `--sampleText` | 参考文本内容文件路径 | 与 `--sampleAudio` 配合使用 |
| `--target` | 待合成文本文件路径 | 必填 |
| `--output` | 输出音频路径 | `batch_output.wav` |
| `--interval` | 段落间静音间隔(秒) | `0.3` |
| `--max-chars` | 每段最大字符数 | `500` |

## 开源协议

本项目采用 [Apache License 2.0](LICENSE) 开源协议。
