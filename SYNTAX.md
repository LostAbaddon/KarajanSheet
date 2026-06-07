# KarajanSheet v1.1 语法参考

KarajanSheet 是 Karajan 音频脚本引擎的领域特定语言（DSL），用于声明式地定义多音轨音频的编排与合成。

## 全局指令

以 `@` 开头，放置在 @track 之前（可在任何 @track 之前穿插声明）。

| 指令 | 说明 | 默认 | 示例 |
|------|------|------|------|
| `@sample_rate <hz>` | 输出采样率 | `24000` | `@sample_rate 44100` |
| `@base_volume <rms>` | 全局 RMS 响度基准 | 不归一化 | `@base_volume 0.2` |
| `@base_path <path>` | 相对路径基目录 | `.` | `@base_path ./sounds/` |
| `@peak_limit <dB>` | 总线峰值上限 (dBFS) | `0` | `@peak_limit -1.0` |

## 音轨（Track）

以 `@track <name>` 开头。一个 `.audio` 脚本至少定义一条音轨。多条音轨默认从 0 秒同时开始播放，最终叠加混音输出。

```karajansheet
@track main
    volume: <gain>            # 整轨音量增益倍数（默认 1.0，叠在 segment vol 之上）
    pan: <-1..+1>            # 整轨左右声道（默认 0 = 居中）
    delay: <time>             # 整轨延迟（默认 0s）
```

## 片段定义（Segment）

`@segment <name>` 定义音轨下的一个音频片段。

### 音频来源（二选一）

| 字段 | 说明 | 示例 |
|------|------|------|
| `file:` | 音频文件路径 | `file: bgm.mp3` |
| `tts:` | TTS 合成文本 | `tts: "你好世界"` |

`tts:` 需配合 `voice:` 和 `ref_text:` 显式声明。**缺省时交由 OmniVoice 使用其自身默认值，不会被静默复用前一段的配置。**

### TTS 配置

| 字段 | 说明 | 示例 |
|------|------|------|
| `voice:` | 参考音频路径（可选；不写则用 OmniVoice 默认） | `voice: sample.wav` |
| `ref_text:` | 参考文本（可选；不写则用 OmniVoice 默认） | `ref_text: "参考语音文本"` |

### 音频处理

| 字段 | 说明 | 示例 |
|------|------|------|
| `trim:` | 截取时间区间 | `trim: 0s 10s` |
| `vol:` | 音量控制（可多条，叠加在整轨 vol 之下） | `vol: 0s-2s A0.8` |
| `delay:` | 段前延迟（正=静音，负=与前段重叠） | `delay: -0.5s` / `delay: 1s` |

> `gap:` 已在 v1.1 废弃，请改用 `delay:`。

### 时间格式

- `Ns` — 从开头计 N 秒
- `N%` — 从开头计 N% 位置
- `-Ns` — 从末尾倒数 N 秒
- `-N%` — 从末尾倒数 N% 位置

### 音量规格

- `L0.8` — 左声道增益 0.8 倍
- `R1.2` — 右声道增益 1.2 倍
- `A1.3` — 双声道增益 1.3 倍
- 可组合：`L0.5 R0.8`

## 相对时间控制（@on）

`@on <other_track>` 声明本音轨相对于另一个音轨的时间约束。一个音轨可以写**多条 @on**。

| 子字段 | 说明 | 默认 |
|--------|------|------|
| `after_start:` | 本音轨开始点 = 目标音轨**开始**后 N 秒 | 不使用 |
| `after_end:` | 本音轨开始点 = 目标音轨**结束**后 N 秒 | `0s` |
| `end_relative:` | 本音轨结束点 = 目标音轨结束 + N 秒 | 不截断 |

- **after_start 优先级最高**：一旦设置，after_end 被忽略。
- **多条 @on 共存时**：第一个给出起始约束（after_start / after_end）的 @on 决定本音轨的开始时间；所有给出 end_relative 的 @on 中取最早的时间点作为强制截断。

```karajansheet
@track bgm
    volume: 0.3
    # 两个 @on：一个管开始，一个管结束
    @on voiceover
        after_start: 0s            # 与主播同时开始
    @on voiceover
        end_relative: -0.2s        # 早于主播结束 0.2 秒截断
```

## 循环区间（@loop）

`@loop <from_seg> <to_seg>` 声明音轨内的循环区间（闭区间）。循环一直执行，直到本音轨被 `end_relative` 强制截断或脚本结束。

**再入规则**：每次循环再入时，第一段 `from_seg` 的 `delay` 相对于上一轮循环体最后一段 `to_seg` 的结束点计算。

```karajansheet
@track looped
    @loop a b
    @segment a
        file: clip.wav
        trim: 0s 2s
        delay: 0.5s               # 段前 0.5s（再入时相对上次 b 结束 +0.5s）
    @segment b
        file: clip.wav
        trim: 2s 4s
        delay: 0s
```

## 完整示例

```karajansheet
@sample_rate 24000
@base_volume 0.2
@base_path .
@peak_limit -1.0

@track voiceover
    volume: 1.0
    pan: 0

    @segment intro
        tts: "欢迎收听今天的节目"
        voice: sample.wav
        ref_text: "参考语音文本"

    @segment narration
        tts: "我是节目主持人塔塔，大家好！"
        delay: -0.3s

@track bgm
    volume: 0.3
    pan: -0.4

    @on voiceover
        after_start: 0s
    @on voiceover
        end_relative: -0.2s

    @loop bgm_a bgm_b

    @segment bgm_a
        file: bgm.wav
        trim: 0s 4s

    @segment bgm_b
        file: bgm.wav
        trim: 4s 8s

### 音量渐变

`vol:` 支持 `->` 线性渐变语法（v1.1）：

- `R1.0->0.0` — 右声道从 1.0 线性降到 0.0
- `L0.0->1.0 R1.0->0.0` — 声道平移（声道转移）
- `A0.0->1.0` — 整体音量线性渐大

多个 `vol:` 可叠加，每个 `vol:` 独立定义自己的时间窗。渐变值指 `gain` 倍数（非分贝），0.0=静音，1.0=原始音量。

示例：
```chopinsheet
vol: 0s-3s R1.0->0.0 L0.0->1.0   # 0~3 秒从右耳滑到左耳
vol: 3s-4s R0.0->1.0 L1.0->0.0   # 3~4 秒从左耳滑回右耳
```
