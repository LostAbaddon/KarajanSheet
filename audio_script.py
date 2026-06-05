#!/usr/bin/env python3
"""
Audio Script Engine - 自定义音频脚本语言解析与执行器

脚本语法概览:
    @sample_rate 24000          # 输出采样率（可选，默认 24000）
    @base_volume 0.15           # 全局响度基准线（RMS 目标值，可选）
    @base_path ./sounds/        # 相对路径的基路径（可选）

    @segment <name>             # 定义一个音频片段
        file: <path>            # 音频文件（支持 mp3/wav/m4a/flac 等）
        tts: "<text>"           # TTS 合成文本（与 file 二选一）
        voice: <path>           # TTS 音色参考音频（配合 tts 使用）
        ref_text: "<text>"      # TTS 参考文本（配合 tts 使用）
        trim: <start> <end>     # 截取时间区间
        vol: <range> <spec>     # 音量控制（可多条）
        gap: <time>             # 与下一段的间隔（正=静音，负=重叠）

时间格式: Ns(秒) | N%(百分比) | -Ns(倒数秒) | -N%(倒数百分比)
vol spec:  R0.8(右声道80%) | L1.2(左声道120%) | A1.3(全部130%)
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice


# ============================================================
# 0. TTS 模型全局缓存（避免重复加载造成 MPS 假死）
# ============================================================

_tts_model = None


def _get_tts_model():
    global _tts_model
    if _tts_model is None:
        print("加载 TTS 模型...")
        _tts_model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map="mps",
            dtype=torch.float16
        )
    return _tts_model


# ============================================================
# 1. 数据模型 (AST)
# ============================================================

@dataclass
class TimeValue:
    """时间值解析结果。正文=从头计数，负值=从尾倒数。"""
    value: float        # 绝对值
    is_negative: bool   # 是否从末尾倒数
    is_percent: bool    # 是否百分比（否则为秒）

    def to_seconds(self, total_seconds: float) -> float:
        """将时间值转换为相对于给定总时长的秒数。"""
        if self.is_percent:
            seconds = total_seconds * self.value / 100.0
        else:
            seconds = self.value
        if self.is_negative:
            seconds = total_seconds + seconds  # seconds 本身为负
        return max(0.0, min(seconds, total_seconds))


@dataclass
class VolCommand:
    """一条音量控制指令。"""
    start: TimeValue
    end: Optional[TimeValue] = None  # None 表示到结尾
    left_gain: Optional[float] = None   # L 声道增益倍数
    right_gain: Optional[float] = None  # R 声道增益倍数
    all_gain: Optional[float] = None    # A 双声道增益倍数


@dataclass
class Segment:
    """一个音频片段定义。"""
    name: str
    file_path: Optional[str] = None       # 音频文件路径
    tts_text: Optional[str] = None        # TTS 合成文本
    tts_voice: Optional[str] = None       # TTS 参考音频
    tts_ref_text: Optional[str] = None    # TTS 参考文本
    trim_start: Optional[TimeValue] = None
    trim_end: Optional[TimeValue] = None
    vol_commands: list = field(default_factory=list)  # list[VolCommand]
    gap: Optional[float] = None           # 与下一段的间隔秒数（可为负）


@dataclass
class Script:
    """完整脚本 AST。"""
    sample_rate: int = 24000
    base_volume: Optional[float] = None   # RMS 目标值
    base_path: str = "."
    segments: list = field(default_factory=list)  # list[Segment]


# ============================================================
# 2. 语法解析器
# ============================================================

def parse_time(s: str) -> TimeValue:
    """解析时间字符串，如 '5s', '-3s', '50%', '-10%'"""
    s = s.strip()
    is_negative = s.startswith("-")
    if is_negative:
        s = s[1:]
    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1]
    else:
        # 去掉末尾的 's'（可选）
        s = re.sub(r"s$", "", s, flags=re.IGNORECASE)
    try:
        value = float(s)
    except ValueError:
        raise ValueError(f"无法解析时间值: '{s}'（原始: '{s}')")
    return TimeValue(value=value, is_negative=is_negative, is_percent=is_percent)


def parse_vol_spec(spec: str) -> tuple:
    """
    解析音量规格，如 'L0.5', 'R1.2', 'A0.8', 'L0.5 R0.8'
    返回 (left_gain, right_gain, all_gain)
    """
    parts = spec.strip().split()
    left_gain = None
    right_gain = None
    all_gain = None
    for p in parts:
        m = re.match(r"^([LRA])([\d.]+)$", p, re.IGNORECASE)
        if not m:
            raise ValueError(f"无法解析音量规格: '{p}'")
        channel, val = m.group(1).upper(), float(m.group(2))
        if channel == "L":
            left_gain = val
        elif channel == "R":
            right_gain = val
        elif channel == "A":
            all_gain = val
    return left_gain, right_gain, all_gain


def parse_script(filepath: str) -> Script:
    """解析脚本文件，返回 Script AST。"""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"脚本文件不存在: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    script = Script()
    current_segment: Optional[Segment] = None

    for lineno, raw_line in enumerate(lines, 1):
        line = raw_line.strip()

        # 跳过空行和注释
        if not line or line.startswith("#"):
            continue

        # 全局指令
        if line.startswith("@"):
            # @segment 指令 —— 结束上一个 segment，开始新的
            seg_match = re.match(r"^@segment\s+(.+)$", line, re.IGNORECASE)
            if seg_match:
                if current_segment is not None:
                    script.segments.append(current_segment)
                current_segment = Segment(name=seg_match.group(1).strip())
                continue

            # @sample_rate
            sr_match = re.match(r"^@sample_rate\s+(\d+)$", line, re.IGNORECASE)
            if sr_match:
                script.sample_rate = int(sr_match.group(1))
                continue

            # @base_volume
            bv_match = re.match(r"^@base_volume\s+([\d.]+)$", line, re.IGNORECASE)
            if bv_match:
                script.base_volume = float(bv_match.group(1))
                continue

            # @base_path
            bp_match = re.match(r"^@base_path\s+(.+)$", line, re.IGNORECASE)
            if bp_match:
                script.base_path = bp_match.group(1).strip()
                continue

            raise SyntaxError(f"第 {lineno} 行: 无法识别的全局指令 '{line}'")

        # segment 内部字段
        if current_segment is None:
            raise SyntaxError(f"第 {lineno} 行: 内容出现在 @segment 之前: '{line}'")

        # file:
        file_match = re.match(r"^file:\s+(.+)$", line, re.IGNORECASE)
        if file_match:
            current_segment.file_path = file_match.group(1).strip()
            continue

        # tts:
        tts_match = re.match(r'^tts:\s+"(.+)"$', line, re.IGNORECASE)
        if tts_match:
            current_segment.tts_text = tts_match.group(1)
            continue

        # voice:
        voice_match = re.match(r"^voice:\s+(.+)$", line, re.IGNORECASE)
        if voice_match:
            current_segment.tts_voice = voice_match.group(1).strip()
            continue

        # ref_text:
        rt_match = re.match(r'^ref_text:\s+"(.+)"$', line, re.IGNORECASE)
        if rt_match:
            current_segment.tts_ref_text = rt_match.group(1)
            continue

        # trim:
        trim_match = re.match(r"^trim:\s+(.+?)\s+(.+)$", line, re.IGNORECASE)
        if trim_match:
            current_segment.trim_start = parse_time(trim_match.group(1))
            current_segment.trim_end = parse_time(trim_match.group(2))
            continue

        # vol: 支持格式:
        #   vol: 0s-1s L0.5 R0.8      (正时间区间)
        #   vol: -3s- R1.5            (从倒数 3 秒到结尾)
        #   vol: 5s- -2s A1.0         (含负值结束时间)
        vol_match = re.match(
            r"^vol:\s+(-?[\d.]+[s%]?)\s*-\s*(-?[\d.]+[s%]?)?\s+(.+)$",
            line, re.IGNORECASE
        )
        if vol_match:
            start_str = vol_match.group(1)
            end_str = vol_match.group(2)  # 可能为 None（表示到结尾）
            spec_str = vol_match.group(3).strip()

            start = parse_time(start_str)
            end = parse_time(end_str) if end_str else None

            left_gain, right_gain, all_gain = parse_vol_spec(spec_str)
            current_segment.vol_commands.append(
                VolCommand(start=start, end=end,
                           left_gain=left_gain, right_gain=right_gain,
                           all_gain=all_gain)
            )
            continue

        # gap:
        gap_match = re.match(r"^gap:\s+(.+)$", line, re.IGNORECASE)
        if gap_match:
            gap_str = gap_match.group(1).strip()
            current_segment.gap = parse_time(gap_str).value
            # gap 的正负号由 TimeValue.is_negative 决定
            if parse_time(gap_str).is_negative:
                current_segment.gap = -current_segment.gap
            continue

        raise SyntaxError(f"第 {lineno} 行: 无法识别的字段 '{line}'")

    # 最后一个 segment
    if current_segment is not None:
        script.segments.append(current_segment)

    if not script.segments:
        raise ValueError("脚本中没有定义任何 @segment")

    return script


# ============================================================
# 3. 音频加载与转换
# ============================================================

def _convert_to_wav(input_path: str, target_sr: int = 24000) -> str:
    """使用 ffmpeg 将任意音频格式转为临时 WAV 文件。返回临时文件路径。"""
    suffix = ".wav"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = tmp.name
    tmp.close()

    # 先检查原始音频的通道数
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=channels",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path
    ]
    try:
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        channels = int(probe_result.stdout.strip()) if probe_result.stdout.strip() else 1
    except Exception:
        channels = 1

    # 转换：保持原声道数，统一采样率
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", str(target_sr),
        "-ac", str(channels),
        "-sample_fmt", "s16",
        tmp_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        os.unlink(tmp_path)
        raise RuntimeError(f"ffmpeg 转换失败: {input_path}\n{result.stderr}")
    return tmp_path


def _load_wav(path: str, target_sr: int) -> tuple:
    """加载 WAV 文件，重采样到 target_sr 如果需要。返回 (data, sr)。"""
    data, sr = sf.read(path)

    # soundfile 读取后自动归一化到 [-1, 1] 范围的 float64
    # 统一转为 float32 以节省内存
    if data.dtype != np.float32:
        data = data.astype(np.float32)

    # 如果采样率不一致，用线性插值重采样
    if sr != target_sr:
        if data.ndim == 1:
            old_len = len(data)
            new_len = int(old_len * target_sr / sr)
            data = np.interp(
                np.linspace(0, old_len - 1, new_len),
                np.arange(old_len),
                data
            )
        else:
            old_len = data.shape[0]
            new_len = int(old_len * target_sr / sr)
            new_data = np.zeros((new_len, data.shape[1]), dtype=np.float32)
            for ch in range(data.shape[1]):
                new_data[:, ch] = np.interp(
                    np.linspace(0, old_len - 1, new_len),
                    np.arange(old_len),
                    data[:, ch]
                )
            data = new_data
        sr = target_sr

    return data, sr


def load_audio(path: str, target_sr: int = 24000,
               base_path: str = ".") -> tuple:
    """
    加载音频文件，自动处理格式转换和重采样。
    返回 (numpy_array, sample_rate)。

    单声道: shape (N,) 或 (N, 1)
    立体声: shape (N, 2)
    统一转为 float32，范围大致在 [-1, 1]。
    """
    # 相对路径 → 基于 base_path 解析
    if not os.path.isabs(path):
        path = os.path.join(base_path, path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"音频文件不存在: {path}")

    ext = os.path.splitext(path)[1].lower()

    # WAV 直接加载，其他格式先转 WAV
    if ext == ".wav":
        return _load_wav(path, target_sr)
    else:
        tmp_path = _convert_to_wav(path, target_sr)
        try:
            data, sr = _load_wav(tmp_path, target_sr)
            return data, sr
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ============================================================
# 4. 音频处理
# ============================================================

def compute_rms(data: np.ndarray) -> float:
    """计算音频数据的 RMS（均方根）值。"""
    squared = data.astype(np.float64) ** 2
    mean_square = np.mean(squared)
    return float(np.sqrt(mean_square))


def apply_trim(data: np.ndarray, sr: int,
               trim_start: TimeValue, trim_end: TimeValue) -> np.ndarray:
    """根据 trim 时间区间截取音频。"""
    total_sec = len(data) / sr
    start_sec = trim_start.to_seconds(total_sec)
    end_sec = trim_end.to_seconds(total_sec)

    if start_sec >= end_sec:
        raise ValueError(f"trim 起始时间({start_sec:.2f}s) >= 结束时间({end_sec:.2f}s)")

    start_frame = int(start_sec * sr)
    end_frame = int(end_sec * sr)
    return data[start_frame:end_frame]


def apply_volume_commands(data: np.ndarray, sr: int,
                          vol_commands: list) -> np.ndarray:
    """
    应用音量控制指令。
    为音频创建增益数组，按 vol 指令的时间区间修改增益值。

    输入 data 可以是 (N,) 单声道或 (N, C) 多声道。
    增益形状与之相同，后面相乘。
    """
    if not vol_commands:
        return data

    total_frames = len(data)
    total_sec = total_frames / sr

    # 确定声道数
    if data.ndim == 1:
        n_channels = 1
    else:
        n_channels = data.shape[1]

    # 创建增益数组，初始为 1.0
    if n_channels == 1:
        gain = np.ones(total_frames, dtype=np.float32)
    else:
        gain = np.ones((total_frames, n_channels), dtype=np.float32)

    for cmd in vol_commands:
        start_sec = cmd.start.to_seconds(total_sec)
        end_sec = total_sec if cmd.end is None else cmd.end.to_seconds(total_sec)

        if start_sec >= end_sec:
            continue

        start_frame = int(start_sec * sr)
        end_frame = min(int(end_sec * sr), total_frames)

        if start_frame >= end_frame:
            continue

        # 应用增益：A 先设置全部，L/R 可覆盖特定声道
        if n_channels == 1:
            if cmd.all_gain is not None:
                gain[start_frame:end_frame] = cmd.all_gain
            if cmd.left_gain is not None:
                gain[start_frame:end_frame] = cmd.left_gain
            elif cmd.right_gain is not None:
                gain[start_frame:end_frame] = cmd.right_gain
        else:
            if cmd.all_gain is not None:
                gain[start_frame:end_frame, :] = cmd.all_gain
            if cmd.left_gain is not None:
                gain[start_frame:end_frame, 0] = cmd.left_gain
            if cmd.right_gain is not None and n_channels >= 2:
                gain[start_frame:end_frame, 1] = cmd.right_gain

    # 应用增益
    if data.ndim == 1:
        return data * gain
    else:
        return data * gain


def normalize_loudness(data: np.ndarray, base_volume: float) -> np.ndarray:
    """
    响度归一化：将音频 RMS 对齐到 base_volume。
    每段独立计算：gain = base_volume / max(rms, threshold)
    对极静音段设置最小 RMS 阈值，防止过度放大。
    """
    rms = compute_rms(data)
    # 最小 RMS 阈值：防止静音段被无限放大（-60dB ≈ 0.001）
    min_rms = 0.001
    effective_rms = max(rms, min_rms)
    gain = base_volume / effective_rms
    # 限制最大增益，防止极端放大（最多 10 倍 ≈ +20dB）
    gain = min(gain, 10.0)
    return data * gain


# ============================================================
# 5. TTS 集成
# ============================================================

def generate_tts(text: str, voice_path: str, ref_text: str,
                 target_sr: int, base_path: str) -> np.ndarray:
    """
    调用 OmniVoice 模型进行语音合成。
    返回 float32 numpy 数组（单声道）。
    """
    # 解析 voice 路径
    if not os.path.isabs(voice_path):
        voice_path = os.path.join(base_path, voice_path)

    # MP3 等格式先转 WAV
    input_file = voice_path
    if not input_file.endswith(".wav"):
        wav_file = input_file.rsplit(".", 1)[0] + ".wav"
        if not os.path.exists(wav_file):
            subprocess.run([
                "ffmpeg", "-y", "-i", input_file,
                "-ar", "24000", "-ac", "1", wav_file,
            ], capture_output=True)
        input_file = wav_file

    if not os.path.exists(input_file):
        raise FileNotFoundError(f"TTS 参考音频不存在: {input_file}")

    print(f'  [TTS] 合成: "{text[:40]}{"..." if len(text) > 40 else ""}"')
    audio = _get_tts_model().generate(
        text=text,
        ref_audio=input_file,
        ref_text=ref_text,
    )

    # audio[0] 是生成的音频 numpy 数组
    data = audio[0]
    if data.dtype != np.float32:
        data = data.astype(np.float32)

    # 如果目标采样率不是 24000，重采样
    if target_sr != 24000:
        old_len = len(data)
        new_len = int(old_len * target_sr / 24000)
        data = np.interp(
            np.linspace(0, old_len - 1, new_len),
            np.arange(old_len),
            data
        )

    print(f"  [TTS] 生成完成，{len(data) / target_sr:.1f} 秒")
    return data


# ============================================================
# 6. 组装输出
# ============================================================

def assemble_output(processed_segments: list, gaps: list,
                    sr: int) -> np.ndarray:
    """
    将所有处理后的音频片段按 gap 拼接为最终输出。

    processed_segments: list of (data, sr) 元组，data 为 numpy 数组
    gaps: 每个 segment 之后的间隔秒数（正=静音，负=重叠），
          最后一个 gap 为 None（不考虑）
    返回拼接后的 numpy 数组。
    """
    if not processed_segments:
        return np.array([], dtype=np.float32)

    # 确定声道数（取所有片段中的最大声道数）
    max_channels = 1
    for data, _ in processed_segments:
        if data.ndim == 1:
            ch = 1
        else:
            ch = data.shape[1]
        max_channels = max(max_channels, ch)

    # 统一所有片段到 max_channels
    unified_segments = []
    for data, _ in processed_segments:
        if data.ndim == 1 and max_channels > 1:
            # 单声道扩展为立体声
            data = np.column_stack([data, data])
        elif data.ndim > 1 and data.shape[1] < max_channels:
            # 补齐声道
            pad_ch = max_channels - data.shape[1]
            data = np.pad(data, ((0, 0), (0, pad_ch)), mode='constant')
        unified_segments.append(data)

    # 计算总长度
    # 布局: [seg0][gap0][seg1][gap1][seg2]...
    # 负 gap = 重叠，seg1 从 seg0 结束往前 |gap| 处开始
    total_frames = 0
    positions = []  # 每个 segment 的起始帧位置

    for i, data in enumerate(unified_segments):
        if i == 0:
            positions.append(0)
            total_frames = len(data)
        else:
            gap = gaps[i - 1] if i - 1 < len(gaps) else 0.0
            prev_end = positions[i - 1] + len(unified_segments[i - 1])
            if gap >= 0:
                # 正间隔：在上一段结束后加 gap 秒静音
                start_frame = prev_end + int(gap * sr)
            else:
                # 负间隔（重叠）：从前一段结束往前 |gap| 秒开始
                start_frame = prev_end + int(gap * sr)  # gap 为负
            positions.append(start_frame)
            total_frames = max(total_frames, start_frame + len(data))

    # 构建输出缓冲区
    output = np.zeros((total_frames, max_channels), dtype=np.float32)

    for i, data in enumerate(unified_segments):
        start = positions[i]
        end = start + len(data)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        # 叠加（处理重叠区域的混音）
        output[start:end] += data

    # 归一化：防止叠加区域削波
    max_val = np.max(np.abs(output))
    if max_val > 1.0:
        output /= max_val

    # 如果所有输入都是单声道，输出也保持单声道
    if max_channels == 1:
        output = output.flatten()

    return output


# ============================================================
# 7. 主流程
# ============================================================

def execute_script(script: Script, output_path: str,
                   cli_base_path: Optional[str] = None) -> None:
    """
    执行脚本，生成最终音频文件。
    """
    sr = script.sample_rate

    # base_path: CLI 参数覆盖脚本中的设置
    base_path = cli_base_path if cli_base_path else script.base_path
    base_path = os.path.abspath(base_path)

    print(f"采样率: {sr} Hz")
    print(f"基路径: {base_path}")
    if script.base_volume is not None:
        print(f"响度基准线: {script.base_volume} (RMS)")
    print(f"片段数: {len(script.segments)}")
    print()

    processed = []
    gaps = []

    for idx, seg in enumerate(script.segments):
        print(f"[{idx + 1}/{len(script.segments)}] {seg.name}")

        # --- 5.1 加载音频 ---
        if seg.file_path:
            print(f"  加载: {seg.file_path}")
            data, _ = load_audio(seg.file_path, sr, base_path)
        elif seg.tts_text:
            print(f"  TTS 合成")
            voice = seg.tts_voice or "sample.wav"
            ref = seg.tts_ref_text or "大家好，这里是胡聊瞎侃嘚啵嘚播客，我是主持人塔塔"
            data = generate_tts(seg.tts_text, voice, ref, sr, base_path)
        else:
            raise ValueError(f"片段 '{seg.name}' 缺少 file 或 tts 定义")

        print(f"  原始: {len(data) / sr:.2f} 秒, shape={data.shape}, RMS={compute_rms(data):.4f}")

        # --- 5.2 截取 ---
        if seg.trim_start is not None and seg.trim_end is not None:
            data = apply_trim(data, sr, seg.trim_start, seg.trim_end)
            print(f"  截取后: {len(data) / sr:.2f} 秒")

        # --- 5.3 响度归一化 ---
        if script.base_volume is not None:
            rms_before = compute_rms(data)
            data = normalize_loudness(data, script.base_volume)
            rms_after = compute_rms(data)
            gain_db = 20 * np.log10(max(rms_after, 1e-10) / max(rms_before, 1e-10))
            print(f"  响度归一化: RMS {rms_before:.4f} → {rms_after:.4f} ({gain_db:+.1f} dB)")

        # --- 5.4 音量控制 ---
        if seg.vol_commands:
            data = apply_volume_commands(data, sr, seg.vol_commands)
            print(f"  音量控制: {len(seg.vol_commands)} 条指令")

        # --- 5.5 记录 gap ---
        if seg.gap is not None and idx < len(script.segments) - 1:
            gaps.append(seg.gap)
            print(f"  间隔: {seg.gap:+.2f}s")
        elif idx < len(script.segments) - 1:
            gaps.append(0.0)  # 默认无间隔

        processed.append((data, sr))
        print(f"  最终: {len(data) / sr:.2f} 秒\n")

    # --- 6. 组装 ---
    print("组装输出...")
    output = assemble_output(processed, gaps, sr)
    total_duration = len(output) / sr if output.ndim == 1 else output.shape[0] / sr
    print(f"总时长: {total_duration:.2f} 秒")

    # --- 7. 写入 ---
    sf.write(output_path, output, sr)
    print(f"\n✅ 输出完成: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Audio Script Engine - 自定义音频脚本语言执行器"
    )
    parser.add_argument(
        "--script", "-s", type=str, required=True,
        help="脚本文件路径"
    )
    parser.add_argument(
        "--output", "-o", type=str, default="output.wav",
        help="输出音频文件路径（默认: output.wav）"
    )
    parser.add_argument(
        "--base-path", "-b", type=str, default=None,
        help="覆盖脚本中的 @base_path 设置"
    )
    args = parser.parse_args()

    # 解析脚本
    script = parse_script(args.script)

    # 执行
    execute_script(script, args.output, args.base_path)


if __name__ == "__main__":
    main()
