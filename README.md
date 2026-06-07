# Karajan v1.1

**Karajan** 是一个基于自定义脚本语言的音频编排引擎。使用 **KarajanSheet** 脚本语法声明式地定义多音轨音频的拼接、TTS 合成、音量控制、声道分配与响度归一化，一键生成最终音频。

## 特性

- **多音轨编排（Track）** — 任意条音轨并行播放，统一应用音量、声道、延迟；多条音轨按时间轴叠加输出
- **相对时间控制（@on）** — 一条音轨可以相对另一条音轨的开始/结束时间设定自己的开始点与结束点；同一音轨可写多条 @on
- **循环区间（@loop）** — 音轨内任意闭区间无限循环，可被 @on 的 `end_relative` 强制截断
- **TTS 集成** — 内置 [OmniVoice](https://github.com/k2-fsa/OmniVoice) 语音合成，支持音色克隆；未声明 voice/ref_text 时交由 OmniVoice 使用其默认值，**不会**被静默复用前一段配置
- **多格式支持** — 自动处理 mp3/wav/m4a/flac 等常见音频格式
- **总线峰值限制** — `@peak_limit` 防止多轨叠加后爆音
- **批量合成** — 提供长文本分批 TTS 合成与自动拼接工具

## 安装

```bash
pip install omnivoice numpy soundfile torch
```

此外需要系统安装 `ffmpeg` 用于音频格式转换。

## 快速开始

### 1. 编写 KarajanSheet 脚本

创建一个 `.audio` 文件：

```karajansheet
@sample_rate 24000
@base_volume 0.2
@base_path .
@peak_limit -1.0

@track voiceover
    volume: 1.0
    pan: 0

    @segment intro
        tts: "欢迎收听今天的节目，这是一个关于音频脚本引擎的演示"
        voice: sample.wav
        ref_text: "大家好，这里是胡聊瞎侃嘚啵嘚播客，我是主持人塔塔"

    @segment narration
        tts: "我是节目主持人，我叫塔塔，大家好！"
        delay: -0.5s

@track bgm
    volume: 0.3
    pan: -0.4

    @on voiceover
        after_start: 0s
    @on voiceover
        end_relative: -0.2s

    @loop bgm_a bgm_b

    @segment bgm_a
        file: sample.wav
        trim: 0s 4s

    @segment bgm_b
        file: sample.wav
        trim: 4s 8s
```

这个脚本：

1. 渲染一条主播音轨，包含两段 TTS 合成（第二段相对第一段重叠 0.5 秒）；
2. 同时叠加一条背景音乐，音量 30%、偏左 40%；
3. BGM 与主播同时开始，在主播结束前 0.2 秒被截断；
4. BGM 内部 `bgm_a`→`bgm_b` 循环播放直到截断。

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

## KarajanSheet 语法

完整语法参考请见 [SYNTAX.md](SYNTAX.md)。

关键概念速览：

- **Track** — 一条音轨，包含任意条 @segment 与整轨级设置（volume / pan / delay）
- **@on** — 相对时间控制，可写多条；首个给出起始约束的 @on 决定开始点，所有给出 `end_relative` 的 @on 取最早时间点作为截断
- **@loop** — 音轨内循环区间，再入时第一段的 `delay` 相对上一轮最后一段的结束点
- **delay** — 段前延迟（替代旧版 `gap`），正=静音，负=与前段重叠
- **peak_limit** — 全局总线峰值上限（dBFS），防止叠加爆音

## TTS 引擎

本项目使用 **[OmniVoice](https://github.com/k2-fsa/OmniVoice)** 作为语音合成引擎。OmniVoice 是一个基于语音离散化标记的 zero-shot 大规模 TTS 模型，能够通过参考音频实现高保真的音色克隆。

- 官网/GitHub: [https://github.com/k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
- HuggingFace 模型: [k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)

> 如果 `tts:` 段未显式声明 `voice:` / `ref_text:`，引擎会使用 OmniVoice 自己的默认音色/参考文本。要在脚本中显式指定某段使用其他音色，必须在那一段单独写 `voice:` 字段。

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
| `--interval` | 段落间静音间隔（秒） | `0.3` |
| `--max-chars` | 每段最大字符数 | `500` |

## 开源协议

本项目采用 [Apache License 2.0](LICENSE) 开源协议。
