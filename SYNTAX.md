# ChopinSheet 语法参考

ChopinSheet 是 Chopin 音频脚本引擎的领域特定语言(DSL),用于声明式地定义多段音频的编排与合成。

## 全局指令

指令以 `@` 开头,放置在脚本顶部(第一个 `@segment` 之前)。

| 指令 | 说明 | 示例 |
|------|------|------|
| `@sample_rate <hz>` | 输出采样率(默认 24000) | `@sample_rate 44100` |
| `@base_volume <rms>` | 全局响度基准线(RMS 目标值) | `@base_volume 0.2` |
| `@base_path <path>` | 相对路径的基路径 | `@base_path ./sounds/` |

## 片段定义

每个 `@segment <name>` 定义一个音频片段,内部字段缩进书写。

### 音频来源(二选一)

| 字段 | 说明 | 示例 |
|------|------|------|
| `file:` | 音频文件路径(mp3/wav/m4a/flac 等) | `file: bgm.mp3` |
| `tts:` | TTS 合成文本(配合 voice + ref_text) | `tts: "你好世界"` |

### TTS 配置

| 字段 | 说明 | 示例 |
|------|------|------|
| `voice:` | TTS 音色参考音频路径 | `voice: sample.wav` |
| `ref_text:` | TTS 参考文本内容 | `ref_text: "参考语音文本"` |

### 音频处理

| 字段 | 说明 | 示例 |
|------|------|------|
| `trim:` | 截取时间区间 | `trim: 0s 10s` / `trim: 10% -5%` |
| `vol:` | 音量控制(可多条) | `vol: 0s-2s A0.8` / `vol: -3s- R1.5` |
| `gap:` | 与下一段的间隔(正=静音,负=重叠) | `gap: 0.5s` / `gap: -0.3s` |

### 时间格式

- `Ns` — 从开头计 N 秒
- `N%` — 从开头计 N% 位置
- `-Ns` — 从末尾倒数 N 秒
- `-N%` — 从末尾倒数 N% 位置

### 音量规格(vol)

- `L0.8` — 左声道增益 0.8 倍
- `R1.2` — 右声道增益 1.2 倍
- `A1.3` — 双声道增益 1.3 倍
- 可组合: `L0.5 R0.8`

## 完整示例

```chopinsheet
@sample_rate 24000
@base_volume 0.2
@base_path .

@segment intro
    tts: "欢迎收听今天的节目"
    voice: sample.wav
    ref_text: "参考语音文本"
    gap: -0.5s

@segment narration
    tts: "我是节目主持人塔塔，大家好！"

@segment bgm
    file: bgm.mp3
    trim: 0s 30s
    vol: 0s-5s A0.3
    vol: 5s- A1.0
    gap: 1s
```
