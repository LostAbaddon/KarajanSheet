# KarajanSheet

> - AUTHOR: [LostAbaddon](lostabaddon@gmail.com)
> - VERSION: 1.3.0

**KarajanSheet** 是一个基于自定义脚本语言的音频编排引擎。使用 **KarajanSheet** 脚本语法声明式地定义多音轨音频的拼接、TTS 合成、音量控制、声道分配与响度归一化，一键生成最终音频。

## 特性

- **多音轨编排（Track）** — 任意条音轨并行播放，统一应用音量、声道、延迟；多条音轨按时间轴叠加输出
- **声音预设（@voice）** — 全局定义音色 + 参考文本，TTS 段用 `ref_voice` 一行引用，避免每段重复样板代码；支持 `audio` / `text` / `instruct` / `speed` 四个子字段，零配置合法
- **声音设计（`instruct:`）** — 用属性标签（`male, young adult, 四川话` 等）描述目标声音，**无需参考音频**即可合成特定音色
- **三级语速控制（`speed:`）** — 段 / 轨 / 预设 三个层级都能设置 `speed:`，优先级 `段 > 轨 > 预设 > 1.0`；`@voice.speed` 仅在 `audio` / `instruct` 已设时生效
- **长文本文件驱动 TTS** — `file: script.md` 自动读取文本内容作为 TTS 源；支持 `.txt` / `.md` / `.markdown` / `.rst` / `.text`
- **TTS 时间戳 .txt 输出** — 每次生成音频时自动在同路径生成同名 `.txt` 文件，记录每段 TTS 在 master 时间轴上的开始/结束时间（`[hh:mm:ss.SSS]`）与原文；没有 TTS 段时不生成
- **相对时间控制（@on）** — 一条音轨可以相对另一条音轨/段的开始/结束时间设定自己的开始点与结束点；同一音轨可写多条 @on；**track 优先**解析
- **循环区间（@loop）** — 音轨内任意闭区间无限循环，可被 @on 的 `end_relative` 强制截断
- **TTS 集成** — 内置 [OmniVoice](https://github.com/k2-fsa/OmniVoice) 语音合成，支持音色克隆与声音设计；支持 `ref_audio` + `ref_text` 显式声明、`instruct:` 声音设计、或通过 `ref_voice` 引用 @voice 预设
- **多格式支持** — 自动处理 mp3/wav/m4a/flac 等常见音频格式
- **总线峰值限制** — `@peak_limit` 防止多轨叠加后爆音
- **批量合成** — 提供长文本分批 TTS 合成与自动拼接工具
- **明确化预处理流程** — 五步流水线（A 探测 / B 固定点 / C 推算点 / D 时间段 / E 合成），每步控制台可读

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

# 声音预设：主持人塔塔
@voice host
    audio: sample.wav
    text: "大家好，这里是胡聊瞎侃嘚啵嘚播客，我是主持人塔塔"

@track voiceover
    volume: 1.0
    pan: 0

    @segment intro
        tts: "欢迎收听今天的节目，这是一个关于音频脚本引擎的演示"
        ref_voice: host

    @segment narration
        tts: "我是节目主持人，我叫塔塔，大家好！"
        ref_voice: host
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

1. 定义一个名为 `host` 的声音预设（指定 `sample.wav` 作为参考音频和一段参考文本）；
2. 渲染一条主播音轨，包含两段 TTS 合成（通过 `ref_voice: host` 共用同一声音）；
3. 同时叠加一条背景音乐，音量 30%、偏左 40%；
4. BGM 与主播同时开始，在主播结束前 0.2 秒被截断；
5. BGM 内部 `bgm_a`→`bgm_b` 循环播放直到截断。

### 2. 执行脚本

```bash
python karajan_sheet.py -s example.audio -o output.wav
```

### 3. 批量 TTS 合成

```bash
python solo_tts.py \
  --sampleAudio sample.wav \
  --sampleText sample.txt \
  --target script.md \
  --output output.wav \
  --interval 0.3
```

## KarajanSheet 语法

完整语法参考请见 [SYNTAX.md](SYNTAX.md)。

关键概念速览：

- **@voice** — 全局声音预设。**所有子字段都可选**——可以只写 `audio` + `text`（克隆模式）、只写 `instruct:`（声音设计模式）、三者都写、甚至全空。段内用 `ref_voice: <name>` 引用，可被段内的 `ref_audio` / `ref_text` / `instruct:` 覆盖
- **Track** — 一条音轨，包含任意条 @segment 与整轨级设置（volume / pan / delay）
- **@on** — 相对时间控制，可写多条；目标可以是音轨名或段名（**音轨优先**）；首个给出起始约束的 @on 决定开始点，所有给出 `end_relative` 的 @on 取最早时间点作为截断
- **@loop** — 音轨内循环区间，再入时第一段的 `delay` 相对上一轮最后一段的结束点
- **delay** — 段前延迟（替代旧版 `gap`），正=静音，负=与前段重叠
- **peak_limit** — 全局总线峰值上限（dBFS），防止叠加爆音
- **TTS 段字段**（**全部可选**，未设置时走 OmniVoice 默认）：`instruct:` 描述声音属性、`speed:` 控制语速（段 / 轨 / 预设 三级优先级）、`file:` 指向 `.md` / `.txt` 等纯文本时自动读为 TTS 源

## TTS 引擎

本项目使用 **[OmniVoice](https://github.com/k2-fsa/OmniVoice)** 作为语音合成引擎。OmniVoice 是一个基于语音离散化标记的 zero-shot 大规模 TTS 模型，支持 646 种语言，能够通过参考音频实现高保真的音色克隆，也能通过属性标签做"声音设计"（无需参考音频）。

- 官网/GitHub: [https://github.com/k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
- HuggingFace 模型: [k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)
- 完整参数速查表：[OmniVoice 使用指南.md](OmniVoice使用指南.md)

> **零配置 TTS 完全合法**：OmniVoice 有完整的默认配置。TTS 段**可以不写任何** `ref_audio` / `ref_text` / `instruct` / `speed` / `ref_voice`——直接 `tts: "..."` 就能让 OmniVoice 用默认音色/语速合成。KarajanSheet 不做任何强制参数要求。
>
> **v1.2 起推荐做法**：定义一个 `@voice` 预设保存音色参考音频与文本，段内用 `ref_voice: <name>` 引用。预设可以是**克隆模式**（`audio` + `text`）或**声音设计模式**（`instruct:`，无需参考音频）。如果需要临时覆盖，使用 `ref_audio:` / `ref_text:` / `instruct:` 显式声明即可。

## v1.2 新特性

相比 v1.1：

1. **`voice:` 字段已重命名为 `ref_audio:`**（与 OmniVoice 模型底层 API 对齐）
2. **新增 `@voice` 声音预设** — 全局声明可复用的音色配置
3. **`@on` 支持段目标** — 目标可以是音轨名或段名；同名时**音轨优先**
4. **预处理五步流程** — `execute_script` 显式拆分为 A 探测 / B 固定点 / C 推算点 / D 时间段 / E 合成

## 命令行参数

### karajan_sheet.py

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--script` | `-s` | 脚本文件路径 | 必填 |
| `--output` | `-o` | 输出音频文件路径 | `output.wav` |
| `--base-path` | `-b` | 覆盖脚本中的 `@base_path` | 脚本中设置的值 |

### solo_tts.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--sampleAudio` | 音色克隆参考音频路径 | `sample.wav` |
| `--sampleText` | 参考文本内容文件路径 | 与 `--sampleAudio` 配合使用 |
| `--target` | 待合成文本文件路径 | 必填 |
| `--output` | 输出音频路径 | `output.wav` |
| `--interval` | 段落间静音间隔（秒） | `0.3` |
| `--max-chars` | 每段最大字符数 | `500` |

## 开源协议

本项目采用 [Apache License 2.0](LICENSE) 开源协议。
