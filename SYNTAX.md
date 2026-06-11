# KarajanSheet v1.3 语法参考

KarajanSheet 是 Karajan 音频脚本引擎的领域特定语言（DSL），用于声明式地定义多音轨音频的编排与合成。

## 全局指令

以 `@` 开头，放置在 @track 之前（可在任何 @track 之前穿插声明）。

| 指令 | 说明 | 默认 | 示例 |
|------|------|------|------|
| `@sample_rate <hz>` | 输出采样率 | `24000` | `@sample_rate 44100` |
| `@base_volume <rms>` | 全局 RMS 响度基准 | 不归一化 | `@base_volume 0.2` |
| `@base_path <path>` | 相对路径基目录 | `.` | `@base_path ./sounds/` |
| `@peak_limit <dB>` | 总线峰值上限 (dBFS) | `0` | `@peak_limit -1.0` |
| `@voice <name>` | 声音预设（含 `audio` / `text` / `instruct` / `speed`） | — | `@voice host` |

## 声音预设（@voice）

`@voice <name>` 在脚本全局定义一个可复用的声音预设。块内**所有子字段都是可选的**——可以只写 `audio+text`（克隆模式）、只写 `instruct:`（声音设计模式）、三者都写、甚至全空。Karajan **不做任何硬性规定**，因为 OmniVoice 本身有完整默认配置。TTS 段通过 `ref_voice: <name>` 引用预设。

```karajansheet
@voice host
    audio: sample.wav
    text: "大家好，这里是胡聊瞎侃嘚啵嘚播客，我是主持人塔塔"

@voice dr_z
    instruct: "male, middle-aged, very high pitch"

@track main
    @segment intro
        tts: "欢迎收听今天的节目"
        ref_voice: host

    @segment outro
        tts: "感谢收听"
        ref_voice: host        # 同一预设
```

**字段优先级**：当一个 TTS 段同时写了 `ref_voice:` 和 `ref_audio:` / `ref_text:` 时，段内显式声明的字段**覆盖**预设的同名字段。

```karajansheet
@segment special
    tts: "这是一段临时换声音的台词"
    ref_voice: host
    ref_audio: other.wav         # 覆盖预设的 audio
    # ref_text 缺省 → 沿用预设的 text
```

**重要**：TTS 段**未声明任何 voice 配置**（既无 `ref_voice`，也未声明 `ref_audio`/`ref_text`/`instruct`/`speed`）**完全合法**——OmniVoice 会用其自身默认音色/语速来合成。零配置 TTS 是一等公民。

```karajansheet
@track main
    @segment default_voice
        tts: "我不指定任何 voice 配置，OmniVoice 用默认"
        # 无 ref_voice / ref_audio / ref_text / instruct / speed → 合法
```

**`@voice` 块的 `speed:` 字段**：可选，>1 加速、<1 减速、默认 1.0。**生效条件**：`@voice` 块里 `speed:` 仅在 `audio:` 或 `instruct:` 至少有一个被设置时才生效——它必须依附于某个声音来源才有意义。如果只写 `speed:` 而没有任何声音来源，该字段会被**静默忽略并打印警告**。

```karajansheet
@voice slow_narrator
    audio: sample.wav
    text: "..."
    speed: 0.85          # 有效

@voice invalid         # 警告：speed 单独设置无效
    speed: 1.2          # 被忽略
```

## 音轨（Track）

以 `@track <name>` 开头。一个 `.audio` 脚本至少定义一条音轨。多条音轨默认从 0 秒同时开始播放，最终叠加混音输出。

```karajansheet
@track main
    volume: <gain>            # 整轨音量增益倍数（默认 1.0，叠在 segment vol 之上）
    pan: <-1..+1>            # 整轨左右声道（默认 0 = 居中）
    delay: <time>             # 整轨延迟（默认 0s）
    speed: <float>            # 整轨 TTS 语速因子（默认 1.0；优先级低于段内 speed:）
```

## 片段定义（Segment）

`@segment <name>` 定义音轨下的一个音频片段。

### 音频来源（二选一）

| 字段 | 说明 | 示例 |
|------|------|------|
| `file:` | 音频文件路径；如指向 `.txt`/`.md`/`.markdown`/`.rst`/`.text` 等纯文本，会被**自动读取为 TTS 文本** | `file: bgm.mp3` / `file: script.md` |
| `tts:` | TTS 合成文本 | `tts: "你好世界"` |

### TTS 配置

> **全部可选**：以下字段**一个都不写**也是合法配置（OmniVoice 用默认）。`tts:` 或文本文件是**唯一必填**的 TTS 来源。

| 字段 | 说明 | 示例 |
|------|------|------|
| `ref_audio:` | 参考音频路径（声音克隆） | `ref_audio: sample.wav` |
| `ref_text:` | 参考文本（声音克隆，与 `ref_audio` 配对） | `ref_text: "参考语音文本"` |
| `instruct:` | 声音设计属性（无需参考音频） | `instruct: "female, young adult"` |
| `ref_voice:` | 引用全局 @voice 预设 | `ref_voice: host` |
| `speed:` | 语速因子（>1 加速，<1 减速，默认 1.0）<br>**优先级：段 > 轨 > voice > 1.0** | `speed: 1.4` / `speed: 0.8` |

完整 OmniVoice 参数速查表见 [OmniVoice 使用指南.md](OmniVoice使用指南.md)。

### 音频处理

| 字段 | 说明 | 示例 |
|------|------|------|
| `trim:` | 截取时间区间 | `trim: 0s 10s` |
| `vol:` | 音量控制（可多条，叠加在整轨 vol 之下） | `vol: 0s-2s A0.8` |
| `delay:` | 段前延迟（正=静音，负=与前段重叠） | `delay: -0.5s` / `delay: 1s` |

> `gap:` 已在 v1.1 废弃，请改用 `delay:`。
> `video:` 已在 v1.2 重命名为 `ref_audio:`。

### `file:` 指向纯文本文件

`file:` 支持**纯文本文件**作为 TTS 源，免去把长文嵌进脚本的麻烦。

白名单扩展名：`.txt` / `.md` / `.markdown` / `.rst` / `.text`

```karajansheet
@track main
    @segment intro
        file: notes.md             # 自动读取 notes.md 的内容作为 TTS 文本
        ref_voice: host

    @segment script
        file: script.txt           # 同上
        ref_voice: host
        speed: 0.9                 # 慢速
```

**注意**：
- 文本文件路径同样以 `@base_path` 为基目录解析
- 文本文件不存在 → 解析期抛 `FileNotFoundError`
- 同时写 `file: 文本` 和 `tts: "..."` → **文件优先**（`tts:` 字段被忽略）

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

`@on <target>` 声明本音轨相对于目标的时间约束。目标可以是**音轨名**或**段名**（v1.2 起支持段目标；同名时音轨优先）。一个音轨可以写**多条 @on**。

| 子字段 | 说明 | 默认 |
|--------|------|------|
| `after_start:` | 本音轨开始点 = 目标**开始**后 N 秒 | 不使用 |
| `after_end:` | 本音轨开始点 = 目标**结束**后 N 秒 | `0s` |
| `end_relative:` | 本音轨结束点 = 目标结束 + N 秒 | 不截断 |

- **after_start 优先级最高**：一旦设置，after_end 被忽略。
- **多条 @on 共存时**：第一个给出起始约束（after_start / after_end）的 @on 决定本音轨的开始时间；所有给出 end_relative 的 @on 中取最早的时间点作为强制截断。

### 目标解析

- `@on <track_name>` — 解析为音轨
- `@on <seg_name>` — 解析为段（跨音轨查找，任意音轨下的同名段）
- **音轨名与段名同名时，音轨优先**（v1.2 规则）

```karajansheet
@track bgm
    volume: 0.3
    # 两个 @on：一个管开始，一个管结束
    @on voiceover
        after_start: 0s            # 与主播同时开始
    @on voiceover
        end_relative: -0.2s        # 早于主播结束 0.2 秒截断
```

```karajansheet
@track sfx
    @on voiceover/intro             # 显式指向 voiceover 音轨的 intro 段
        after_start: 0.5s           # 0.5 秒后开始
    @on outro                       # outro 是一个段名
        end_relative: 1s            # outro 结束后 1 秒截断
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

## 预处理流程

`audio_script.py` 在执行时按以下**五步**完成所有时间规划（v1.2 引入的明确化设计）：

1. **步骤 A：探测固定时长** — 对 `file:` 段调 ffprobe / soundfile 读真实时长；对 TTS 段用字符数估算
2. **步骤 B：计算固定时间点** — 按拓扑顺序处理 `@on` 的 `after_start` / `after_end` 决定每条 track 的 master 起点
3. **步骤 C：计算非固定时间点与时长** — 迭代收敛 `end_relative` 决定的 track force_stop（最强约束生效）
4. **步骤 D：计算各时间段** — 解析 `@loop` 展开 + 每段 `delay:` 偏移，输出每条 track 上每段的精确区间
5. **步骤 E：声音合成与装配** — 此时所有时间数字都已锁定，依次加载/合成音频、混音、输出

每一步在控制台都有明确标题，方便排查。

## 完整示例

```karajansheet
@sample_rate 24000
@base_volume 0.2
@base_path .
@peak_limit -1.0

@voice host
    audio: sample.wav
    text: "大家好，这里是胡聊瞎侃嘚啵嘚播客，我是主持人塔塔"

@track voiceover
    volume: 1.0
    pan: 0

    @segment intro
        tts: "欢迎收听今天的节目"
        ref_voice: host

    @segment narration
        tts: "我是节目主持人塔塔，大家好！"
        ref_voice: host
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
```

### 音量渐变

`vol:` 支持 `->` 线性渐变语法（v1.1）：

- `R1.0->0.0` — 右声道从 1.0 线性降到 0.0
- `L0.0->1.0 R1.0->0.0` — 声道平移（声道转移）
- `A0.0->1.0` — 整体音量线性渐大

多个 `vol:` 可叠加，每个 `vol:` 独立定义自己的时间窗。渐变值指 `gain` 倍数（非分贝），0.0=静音，1.0=原始音量。

示例：
```karajansheet
vol: 0s-3s R1.0->0.0 L0.0->1.0   # 0~3 秒从右耳滑到左耳
vol: 3s-4s R0.0->1.0 L1.0->0.0   # 3~4 秒从左耳滑回右耳
```

## TTS 时间戳输出（.txt）

执行 `karajan_sheet.py` 生成音频时，引擎会**自动**在输出音频同路径、同 basename、`.txt` 扩展名的文件中记录所有 TTS 段的开始/结束时间与原文。

- **仅记录 TTS 段**——`file:` 段（非 TTS 音频）不参与
- **脚本中没有任何 TTS 段时，不生成此文件**

文件格式（段间空行分隔）：

```
[00:00:01.234] - [00:00:05.678]
欢迎收听今天的节目

[00:00:06.000] - [00:00:10.500]
我是节目主持人塔塔
```

- 第一行：`[hh:mm:ss.SSS] - [hh:mm:ss.SSS]`
  - 开始时间 → 结束时间（master 时间轴上的**绝对位置**，毫秒精度）
  - 时间计算包含 `delay:` 偏移和 `@on` 的 `end_relative`（force_stop）截断
- 第二行：TTS 原文
- 段间空行分隔

### 时间戳计算逻辑

1. 每条 track 上的段按 `delay:` 规则推算在 track 内的 local start，加上 `track_starts` 得到 master 绝对时间
2. 被 `force_stop`（`@on` 的 `end_relative`）**截断**的 TTS 段尾部 → 结束时间取截断点
3. 起点已超过 `force_stop` 的段 → 不在输出音频中 → **不写入 .txt**

如果某段 TTS 被多次播放（`@loop` 循环），只记录**首次出现**的时间位置。
