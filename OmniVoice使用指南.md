# OmniVoice 使用指南

> 基于 OmniVoice 官方文档编写，涵盖模型全部对外功能。
> 官方仓库：[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
> 模型卡：[k2-fsa/OmniVoice@HuggingFace](https://huggingface.co/k2-fsa/OmniVoice)
> 论文：[arXiv:2604.00688](https://arxiv.org/abs/2604.00688)

---

## 一、模型概述

OmniVoice 是一个大规模多语种 zero-shot TTS 模型，支持 646 种语言，基于扩散语言模型架构。核心能力：

- **音色克隆（Voice Cloning）**：通过 3-10 秒参考音频，克隆任意说话人的音色；
- **声音设计（Voice Design）**：无需参考音频，通过属性标签组合描述目标声音；
- **自动声音（Auto Voice）**：不提供任何声纹参考，由模型随机生成音色；
- **非语言符号**：内联标签插入笑声、叹息、疑问语气等；
- **发音控制**：拼音/音标覆盖特定字词的默认发音；
- **节奏与速度控制**：通过 `speed` / `duration` 调整语速或固定时长；
- **快速推理**：RTF 最低 0.025（40 倍于实时）。

### 1.1 支持的语种

OmniVoice 官方声明支持 **646 种语言**，涵盖东亚、东南亚、南亚、中东、欧洲、非洲、美洲等主要语系。以下是常用语种的中英文示例（**任意语种的文本都可以直接传 `text` 参数，OmniVoice 会自动识别**）：

| 语种 | 英文名 | 示例文本 |
|------|--------|----------|
| 中文（普通话） | Mandarin Chinese | `text="大家好，欢迎收听今天的节目。"` |
| 英语 | English | `text="Welcome to today's show."` |
| 日语 | Japanese | `text="私が名探偵、工藤タタだ！"` |
| 韩语 | Korean | `text="안녕하세요, 환영합니다."` |
| 法语 | French | `text="Bonjour, bienvenue à l'émission."` |
| 德语 | German | `text="Guten Tag, willkommen zur Show."` |
| 西班牙语 | Spanish | `text="Hola, bienvenidos al programa de hoy."` |
| 葡萄牙语 | Portuguese | `text="Olá, bem-vindos ao programa de hoje."` |
| 俄语 | Russian | `text="Здравствуйте, добро пожаловать."` |
| 阿拉伯语 | Arabic | `text="مرحبا بكم في برنامج اليوم."` |
| 印地语 | Hindi | `text="आज के कार्यक्रम में आपका स्वागत है।"` |
| 意大利语 | Italian | `text="Benvenuti allo show di oggi."` |

> 完整 646 语种列表见 OmniVoice 模型卡：[k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)。

### 1.2 设置信息总览

OmniVoice 的所有可设置参数（`model.generate(**kwargs)`）按功能分组如下：

| 分组 | 参数 | 类型 | 默认 | 是否必填 |
|------|------|------|------|----------|
| 文本 | `text` | str | — | **必填** |
| 克隆 | `ref_audio` | str | None | 可选 |
| 克隆 | `ref_text` | str | None | 可选（与 ref_audio 配对） |
| 设计 | `instruct` | str | None | 可选 |
| 语速 | `speed` | float | 1.0 | 可选 |
| 时长 | `duration` | float | None | 可选（与 speed 互斥，duration 优先） |
| 解码 | `num_step` | int | 32 | 可选 |
| 解码 | `denoise` | bool | True | 可选 |
| 解码 | `guidance_scale` | float | 2.0 | 可选 |
| 解码 | `t_shift` | float | 0.1 | 可选 |
| 采样 | `position_temperature` | float | 5.0 | 可选 |
| 采样 | `class_temperature` | float | 0.0 | 可选 |
| 采样 | `layer_penalty_factor` | float | 5.0 | 可选 |
| 前后处理 | `preprocess_prompt` | bool | True | 可选 |
| 前后处理 | `postprocess_output` | bool | True | 可选 |
| 分块 | `audio_chunk_duration` | float | 15.0 | 可选 |
| 分块 | `audio_chunk_threshold` | float | 30.0 | 可选 |

> **唯一必填项是 `text`**。其他参数**全部可选**——任何组合下、不填任何参数也能正常调用（OmniVoice 有完整默认配置）。例如：
> ```python
> audio = model.generate(text="Hello")  # 零配置，OmniVoice 自动选音色/语速/解码策略
> ```

---

## 二、三种生成模式

### 2.1 声音克隆（Voice Cloning）

提供 `ref_audio`（参考音频）和 `ref_text`（参考音频对应文本），模型克隆该音色朗读目标文本。

```python
from omnivoice import OmniVoice
import soundfile as sf

model = OmniVoice.from_pretrained("k2-fsa/OmniVoice")

# 中文克隆
audio = model.generate(
    text="欢迎使用 OmniVoice 语音合成。",
    ref_audio="sample.wav",
    ref_text="参考音频的完整转录文本。",
)
sf.write("output.wav", audio[0], 24000)

# 英文克隆
audio = model.generate(
    text="Welcome to OmniVoice.",
    ref_audio="english_voice.wav",
    ref_text="This is the reference transcript.",
)

# 日文克隆
audio = model.generate(
    text="OmniVoice へようこそ。",
    ref_audio="japanese_voice.wav",
    ref_text="これはリファレンス書き起こしです。",
)
```

**要点**：

- 参考音频 3-10 秒最佳；过长会拖慢推理，且可能降低克隆质量；
- `ref_text` 可省略，省略时模型自动调用 Whisper 做 ASR 转写；
- 同语言克隆（参考音频和合成文本同一语言）质量最高；跨语言克隆会带有参考音频的口音；
- 阿拉伯数字建议先用文本归一化工具转为单词（如 "123" → "one hundred twenty-three"）。

### 2.2 声音设计（Voice Design）

不提供参考音频，用 `instruct` 参数描述目标声音的属性。

```python
# 中文设计
audio = model.generate(
    text="这是一段用属性标签合成的声音。",
    instruct="女，青年，高音调，四川话",
)

# 英文设计
audio = model.generate(
    text="This is synthesized with voice design.",
    instruct="female, young adult, high pitch, american accent",
)

# 日文设计
audio = model.generate(
    text="これはボイスデザインによる合成です。",
    instruct="male, middle-aged, moderate pitch",
)

# 韩文设计
audio = model.generate(
    text="이것은 음성 설계를 통한 합성입니다.",
    instruct="female, teenager, high pitch",
)
```

详情见**第三节：声音设计属性全览**。

### 2.3 自动声音

不提供任何声纹参考，模型自动选一个音色。

```python
audio = model.generate(text="这是一段未指定音色的合成。")
```

---

## 三、声音设计属性全览（`instruct` 参数）

`instruct` 为逗号分隔的属性字符串，英文用半角逗号 `,`，中文用全角逗号 `，`（模型会自动纠正混用）。每个类别最多选一个属性，不同类别可自由组合。

### 3.1 性别

| English | 中文 |
|---------|------|
| `male` | `男` |
| `female` | `女` |

### 3.2 年龄

| English | 中文 |
|---------|------|
| `child` | `儿童` |
| `teenager` | `少年` |
| `young adult` | `青年` |
| `middle-aged` | `中年` |
| `elderly` | `老年` |

### 3.3 音调

| English | 中文 |
|---------|------|
| `very low pitch` | `极低音调` |
| `low pitch` | `低音调` |
| `moderate pitch` | `中音调` |
| `high pitch` | `高音调` |
| `very high pitch` | `极高音调` |

### 3.4 风格

| English | 中文 |
|---------|------|
| `whisper` | `耳语` |

### 3.5 英语口音（仅对英语合成生效）

`american accent` / `british accent` / `australian accent` / `canadian accent` / `indian accent` / `chinese accent` / `korean accent` / `japanese accent` / `portuguese accent` / `russian accent`

### 3.6 中文方言（仅对中文合成生效）

`河南话` / `陕西话` / `四川话` / `贵州话` / `云南话` / `桂林话` / `济南话` / `石家庄话` / `甘肃话` / `宁夏话` / `青岛话` / `东北话`

**使用示例**：

```
# 纯英文
"male, elderly, low pitch, whisper, american accent"

# 纯中文
"女，中年，中音调，陕西话"

# 中英混写
"female, young adult, 四川话"
```

**注意**：

- `instruct` 属性可任意省略，模型自动填充缺失项（只写 `"female"` 也行）；
- 大小写不敏感；
- 部分属性组合可能效果不佳，如果不满意可简化 `instruct` 字符串；
- 同时提供 `ref_audio` 和 `instruct` 时：如果两者冲突，模型倾向于参考音频的风格；如果两者一致，`instruct` 可提升克隆稳定性（典型场景：四川话方言克隆，提供 `ref_audio="sichuan.wav"` + `instruct="四川话"`）。

---

## 四、非语言符号（情绪/语气标签）

在内联文本中直接插入标签，模型生成对应的非语言声音。这些标签在合成时会被识别并转换为对应的语气、笑声、叹息等声音。

| 标签 | 含义 |
|------|------|
| `[laughter]` | 笑声 |
| `[sigh]` | 叹息 |
| `[confirmation-en]` | 确认语气（嗯哼） |
| `[question-en]` | 疑问语气 |
| `[question-ah]` | 疑问语气（啊？） |
| `[question-oh]` | 疑问语气（哦？） |
| `[question-ei]` | 疑问语气（诶？） |
| `[question-yi]` | 疑问语气（咦？） |
| `[surprise-ah]` | 惊讶语气（啊！） |
| `[surprise-oh]` | 惊讶语气（哦！） |
| `[surprise-wa]` | 惊讶语气（哇！） |
| `[surprise-yo]` | 惊讶语气（哟！） |
| `[dissatisfaction-hnn]` | 不满语气（哼） |

**使用示例**：

```python
audio = model.generate(
    text="[laughter] 你真逗，我没想到会这样。"
)
audio = model.generate(
    text="[sigh] 这件事真的很难办啊..."
)
audio = model.generate(
    text="[surprise-wa] 这也太棒了吧！[laughter]"
)
```

> 标签可出现在文本的任意位置，支持多个标签混合使用。

---

## 五、发音控制

### 5.1 中文拼音（数字声调）

用大写拼音 + 数字声调覆盖多音字或生僻字的发音。

```python
# "打折(ZHE2)" / "折(SHE2)本" / "折(ZHE1)腾"
text = "这批货物打ZHE2出售后他严重SHE2本了，再也经不起ZHE1腾了。"
```

声调数字：1（阴平）、2（阳平）、3（上声）、4（去声）。

### 5.2 英语音标（CMU 发音词典）

用方括号包裹 CMU 音标覆盖默认发音。

```python
# bass 的两种读音
text = "He plays the [B EY1 S] guitar while catching a [B AE1 S] fish."
```

CMU 音标参考：[CMU Pronouncing Dictionary](https://svn.code.sf.net/p/cmusphinx/code/trunk/cmudict/cmudict.0.7a)

---

## 六、节奏与速度控制

### 6.1 `speed` — 语速因子

- `speed=1.0`：默认语速；
- `speed>1.0`：加速（数值越大越快，输出时长越短）；
- `speed<1.0`：减速（数值越小越慢，输出时长越长）。

```python
# 中文加速
audio = model.generate(text="大家好，欢迎收听。", speed=1.4)

# 英文减速
audio = model.generate(text="Welcome to today's show.", speed=0.8)

# 日文默认语速
audio = model.generate(text="私が名探偵だ！", speed=1.0)
```

### 6.2 `duration` — 固定输出时长

直接指定输出音频的总秒数。**当 `duration` 和 `speed` 同时设置时，`duration` 优先。**

```python
# 中文固定 10 秒
audio = model.generate(text="一段较长的中文文本...", duration=10.0)

# 英文固定 5 秒
audio = model.generate(text="Some English text here...", duration=5.0)

# 日文固定 8 秒
audio = model.generate(text="日本語のテキスト...", duration=8.0)
```

> 默认开启 `postprocess_output=True` 会去除末尾静音，实际输出可能略短于指定 `duration`。如需精确匹配，设置 `postprocess_output=False`。

---

## 七、生成参数详解

以下参数通过 `model.generate(**kwargs)` 传入。

### 7.1 解码参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `num_step` | int | 32 | 扩散去掩码步数。32 质量最高，16 推理更快 |
| `denoise` | bool | True | 是否启用降噪 token，提升语音清晰度 |
| `guidance_scale` | float | 2.0 | CFG 引导强度 |
| `t_shift` | float | 0.1 | 噪声调度的时间步位移，越小越侧重早期步 |

### 7.2 采样参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `position_temperature` | float | 5.0 | 掩码位置选择温度。0 贪心，越大越随机 |
| `class_temperature` | float | 0.0 | Token 采样温度。0 贪心，越大越随机 |
| `layer_penalty_factor` | float | 5.0 | 深层码本惩罚，鼓励底层先解码 |

### 7.3 前后处理

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `preprocess_prompt` | bool | True | 对克隆参考音频预处理（去长静音、补标点） |
| `postprocess_output` | bool | True | 对生成音频后处理（去长静音） |

### 7.4 长文本分块

当合成文本预计超过 `audio_chunk_threshold` 秒时，模型自动切分为 `audio_chunk_duration` 秒左右的块逐段合成，保证显存稳定。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `audio_chunk_duration` | float | 15.0 | 每个分块的目标时长（秒） |
| `audio_chunk_threshold` | float | 30.0 | 触发分块的预计时长阈值（秒） |

---

## 八、在 Karajan 脚本中使用 OmniVoice

Karajan（本项目的音频脚本引擎）通过 `tts:` 字段调用 OmniVoice。在 `.audio` 脚本中：

```karajansheet
@voice host
    audio: sample.wav
    text: "大家好，我是主持人塔塔"

@track voiceover
    @segment intro
        tts: "[laughter] 欢迎收听今天的节目！"
        ref_voice: host
```

`tts:` 字段中的文本直接传给 OmniVoice，因此所有非语言符号、拼音控制均可在脚本中直接使用。

---

## 九、实用技巧

1. **参考音频**：3-10 秒、同语言、清晰无背景噪音，效果最佳；
2. **声音设计不稳定时**：尝试减少 `instruct` 属性数量，或改回声音克隆模式；
3. **短音频（1-2 秒）**：模型在没有参考音频时可能无法可靠生成——此时请提供 `ref_audio`；
4. **加速推理**：将 `num_step` 设为 16，牺牲少量质量换 2 倍速度；
5. **精确时长**：用 `duration` + `postprocess_output=False`；
6. **闽南语**：只能使用 Tai-lo 罗马拼音输入，不支持汉字输入；
7. **方言克隆**：`ref_audio` + 匹配的 `instruct` 方言标签同时使用，可提升方言合成稳定性。

---

## 参考

- [OmniVoice GitHub](https://github.com/k2-fsa/OmniVoice)
- [HuggingFace 模型卡](https://huggingface.co/k2-fsa/OmniVoice)
- [HuggingFace 在线体验](https://huggingface.co/spaces/k2-fsa/OmniVoice)
- [论文 arXiv:2604.00688](https://arxiv.org/abs/2604.00688)
- [声音设计属性参考](https://github.com/k2-fsa/OmniVoice/blob/master/docs/voice-design.md)
- [生成参数参考](https://github.com/k2-fsa/OmniVoice/blob/master/docs/generation-parameters.md)
- [CMU 发音词典](https://svn.code.sf.net/p/cmusphinx/code/trunk/cmudict/cmudict.0.7a)

---

## 附录 A：完整参数速查表

> **重要**：除 `text` 外所有参数**完全可选**。OmniVoice 有完整的默认配置，下面所有参数都可不设置。

### A.1 必填项

| 参数 | 类型 | 含义 |
|------|------|------|
| `text` | str | **必填**。要合成的文本。中英日韩等 646 种语言都直接传字符串。 |

### A.2 声音来源（可选，三选一或都不选）

| 参数 | 类型 | 中文说明 | English | 典型示例 |
|------|------|----------|---------|----------|
| `ref_audio` | str (路径) | 声音克隆参考音频路径 | Voice cloning reference audio path | `ref_audio="sample.wav"` |
| `ref_text` | str | 参考音频对应文本（与 `ref_audio` 配对） | Reference transcript | `ref_text="大家好，这里是胡聊瞎侃嘚啵嘚播客"` |
| `instruct` | str | 声音设计属性标签 | Voice design attribute string | `instruct="male, young adult, 四川话"` |

**三种模式**：
- **克隆模式**：`ref_audio` + `ref_text` 同时给出
- **设计模式**：仅给出 `instruct`
- **自动模式**：三者都不给 → OmniVoice 自己选默认音色

### A.3 节奏与速度（可选）

| 参数 | 类型 | 默认 | 中文说明 | English | 典型示例 |
|------|------|------|----------|---------|----------|
| `speed` | float | 1.0 | 语速因子（>1 加速，<1 减速） | Speech rate factor | `speed=1.4` |
| `duration` | float | None | 固定输出时长（秒，与 `speed` 互斥，duration 优先） | Fixed output duration in seconds | `duration=10.0` |

### A.4 解码参数（可选，进阶）

| 参数 | 类型 | 默认 | 中文说明 | English |
|------|------|------|----------|---------|
| `num_step` | int | 32 | 扩散去掩码步数（32 质量最高，16 更快） | Diffusion unmasking steps |
| `denoise` | bool | True | 是否启用降噪 token | Enable denoise tokens |
| `guidance_scale` | float | 2.0 | CFG 引导强度 | CFG guidance strength |
| `t_shift` | float | 0.1 | 噪声调度时间步位移 | Noise schedule time shift |

### A.5 采样参数（可选，进阶）

| 参数 | 类型 | 默认 | 中文说明 | English |
|------|------|------|----------|---------|
| `position_temperature` | float | 5.0 | 掩码位置选择温度（0 贪心） | Position sampling temperature |
| `class_temperature` | float | 0.0 | Token 采样温度（0 贪心） | Class sampling temperature |
| `layer_penalty_factor` | float | 5.0 | 深层码本惩罚 | Deep codebook penalty |

### A.6 前后处理（可选）

| 参数 | 类型 | 默认 | 中文说明 | English |
|------|------|------|----------|---------|
| `preprocess_prompt` | bool | True | 对克隆参考音频预处理（去长静音、补标点） | Preprocess reference audio |
| `postprocess_output` | bool | True | 对生成音频后处理（去长静音） | Postprocess generated audio |

### A.7 长文本分块（可选）

| 参数 | 类型 | 默认 | 中文说明 | English |
|------|------|------|----------|---------|
| `audio_chunk_duration` | float | 15.0 | 每个分块目标时长（秒） | Target chunk duration in seconds |
| `audio_chunk_threshold` | float | 30.0 | 触发分块的预计时长阈值（秒） | Chunking threshold |

### A.8 声音设计属性（`instruct` 子参数，中英对照）

| 类别 | 英文属性 | 中文属性 |
|------|----------|----------|
| 性别 Gender | `male` | `男` |
| 性别 Gender | `female` | `女` |
| 年龄 Age | `child` | `儿童` |
| 年龄 Age | `teenager` | `少年` |
| 年龄 Age | `young adult` | `青年` |
| 年龄 Age | `middle-aged` | `中年` |
| 年龄 Age | `elderly` | `老年` |
| 音调 Pitch | `very low pitch` | `极低音调` |
| 音调 Pitch | `low pitch` | `低音调` |
| 音调 Pitch | `moderate pitch` | `中音调` |
| 音调 Pitch | `high pitch` | `高音调` |
| 音调 Pitch | `very high pitch` | `极高音调` |
| 风格 Style | `whisper` | `耳语` |
| 英语口音 English Accent | `american accent` | — |
| 英语口音 English Accent | `british accent` | — |
| 英语口音 English Accent | `australian accent` | — |
| 英语口音 English Accent | `canadian accent` | — |
| 英语口音 English Accent | `indian accent` | — |
| 英语口音 English Accent | `chinese accent` | — |
| 英语口音 English Accent | `korean accent` | — |
| 英语口音 English Accent | `japanese accent` | — |
| 英语口音 English Accent | `portuguese accent` | — |
| 英语口音 English Accent | `russian accent` | — |
| 中文方言 Chinese Dialect | — | `河南话` / `陕西话` / `四川话` / `贵州话` / `云南话` / `桂林话` / `济南话` / `石家庄话` / `甘肃话` / `宁夏话` / `青岛话` / `东北话` |

### A.9 非语言符号（情绪/语气标签）

| 标签 | 含义 |
|------|------|
| `[laughter]` | 笑声 laughter |
| `[sigh]` | 叹息 sigh |
| `[confirmation-en]` | 确认语气（嗯哼）confirmation |
| `[question-en]` | 疑问语气 question |
| `[question-ah]` / `[question-oh]` / `[question-ei]` / `[question-yi]` | 疑问语气变体 |
| `[surprise-ah]` / `[surprise-oh]` / `[surprise-wa]` / `[surprise-yo]` | 惊讶语气变体 |
| `[dissatisfaction-hnn]` | 不满语气（哼）dissatisfaction |

### A.10 多语言综合示例

**例 1：英文文本 + 英文克隆音色**
```python
audio = model.generate(
    text="Welcome to the show.",
    ref_audio="english_voice.wav",
    ref_text="This is the reference transcript.",
)
```

**例 2：中文文本 + 中文设计音色**
```python
audio = model.generate(
    text="欢迎收听今天的节目",
    instruct="女，青年，中音调，普通话",
    speed=1.0,
)
```

**例 3：日文文本 + 自动音色**
```python
audio = model.generate(
    text="私が名探偵、工藤タタだ！",
)
```

**例 4：韩文文本 + 设计音色 + 加速**
```python
audio = model.generate(
    text="안녕하세요, 환영합니다.",
    instruct="female, young adult, moderate pitch",
    speed=1.3,
)
```

**例 5：法文文本 + 克隆音色**
```python
audio = model.generate(
    text="Bonjour, bienvenue à l'émission.",
    ref_audio="french_voice.wav",
    ref_text="Voici la transcription de référence.",
)
```

**例 6：零配置（OmniVoice 用全部默认）**
```python
audio = model.generate(text="Hello world")
```

**例 7：长文本自动分块**
```python
audio = model.generate(
    text="非常长非常长非常长..." * 100,  # 极长文本
    speed=1.0,
    audio_chunk_duration=15.0,
    audio_chunk_threshold=30.0,
)
```
