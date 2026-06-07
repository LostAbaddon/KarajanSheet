#!/usr/bin/env python3
"""
Audio Script Engine - 自定义音频脚本语言解析与执行器 v1.1

脚本语法概览:
    @sample_rate 24000          # 输出采样率（可选，默认 24000）
    @base_volume 0.15           # 全局响度基准线（RMS 目标值，可选）
    @base_path ./sounds/        # 相对路径的基路径（可选）
    @peak_limit -1.0            # 总线峰值上限（dBFS，默认 0，可选）
    @track <name>               # 定义一个音轨
        volume: <gain>          # 整轨音量增益倍数（可选，默认 1.0）
        pan: <-1..+1>          # 整轨左右声道（可选，默认 0）
        delay: <time>           # 整轨延迟秒数（可选，默认 0s）

        @on <other_track>       # 相对目标音轨的时间控制（可写多块）
            after_start: <time> # 目标音轨开始后多少秒本音轨启动（设了就用它）
            after_end: <time>   # 目标音轨结束后多少秒本音轨才启动
            end_relative: <time># 本音轨结束点相对目标音轨结束的位移
            fade_in: <time>       # 本音轨首 N 秒做线性渐入（可选）
            fade_out: <time>      # 本音轨尾 N 秒做线性渐出（可选）
        # 多个 @on 可同时存在：首个给出起始约束的 @on 决定开始时间，
        # 所有给出 end_relative 的 @on 中取最早的时间点作为截断。

        @loop <start> <end>     # 循环区间（段名，闭区间，可选）

        @segment <name>         # 定义一个音频片段
            file: <path>        # 音频文件（支持 mp3/wav/m4a/flac 等）
            tts: "<text>"       # TTS 合成文本（与 file 二选一）
            voice: <path>       # TTS 音色参考音频（配合 tts 使用）
            ref_text: "<text>"  # TTS 参考文本（配合 tts 使用）
            trim: <start> <end> # 截取时间区间
            vol: <range> <spec> # 音量控制（可多条）
            delay: <time>       # 段前延迟（正=静音，负=与上一段重叠）

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
    """一条音量控制指令。支持 -> 渐变。"""
    start: TimeValue
    end: Optional[TimeValue] = None
    left_gain: Optional[float] = None
    right_gain: Optional[float] = None
    all_gain: Optional[float] = None
    to_left_gain: Optional[float] = None
    to_right_gain: Optional[float] = None
    to_all_gain: Optional[float] = None


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
    delay: Optional[float] = None          # 段前延迟（正=静音，负=与前段重叠）


@dataclass
class RelativeWindow:
    """音轨间相对时间控制。

    三个字段独立设置：
      - after_start:  本音轨开始点相对目标音轨开始点的位移
      - after_end:    本音轨开始点相对目标音轨结束点的位移
      - end_relative: 本音轨结束点相对目标音轨结束点的位移

    优先级：after_start 设置了就用 after_start（after_end 被忽略）。

    多个 @on 块可以共存：每个块都声明它锁定的 target_track。
    执行时：第一个给出起始约束（after_start/after_end）的 @on 决定开始时间；
           所有给出 end_relative 的 @on 中取最早时间点作为强制截断。

    fade_in_sec / fade_out_sec：在音轨播放的首/尾 N 秒做线性渐入/渐出。
    """
    target_track: str
    after_start: Optional[float] = None
    after_end: float = 0.0
    end_relative: Optional[float] = None
    fade_in_sec: float = 0.0          # 首 N 秒做渐入（0 = 不渐入）
    fade_out_sec: float = 0.0         # 尾 N 秒做渐出（0 = 不渐出）

@dataclass
class Track:
    """一条音轨。"""
    name: str
    volume: float = 1.0                     # 整轨音量增益倍数
    pan: float = 0.0                        # -1=全左, 0=居中, 1=全右
    delay: float = 0.0                      # 整轨延迟秒数
    relative_windows: list = field(default_factory=list)  # list[RelativeWindow]
    loop_start: Optional[str] = None        # 循环起始 segment 名
    loop_end: Optional[str] = None          # 循环结束 segment 名
    segments: list = field(default_factory=list)  # list[Segment]

@dataclass
class Script:
    """完整脚本 AST。"""
    sample_rate: int = 24000
    base_volume: Optional[float] = None   # RMS 目标值
    base_path: str = "."
    peak_limit_db: float = 0.0              # @peak_limit（默认 0 dBFS）
    tracks: list = field(default_factory=list)   # list[Track]


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
    解析音量规格。
      静态:  'L0.5', 'R1.2', 'A0.8', 'L0.5 R0.8'
      渐变:  'L0.0->1.0', 'R1.0->0.0 L0.0->1.0'
    返回 (left_gain, right_gain, all_gain, to_left, to_right, to_all)
    """
    parts = spec.strip().split()
    left_gain = right_gain = all_gain = None
    to_left = to_right = to_all = None
    for p in parts:
        m = re.match(r"^([LRA])([\d.]+)(?:->([\d.]+))?$", p, re.IGNORECASE)
        if not m:
            raise ValueError(f"无法解析音量规格: '{p}'")
        ch, v1 = m.group(1).upper(), float(m.group(2))
        v2 = float(m.group(3)) if m.group(3) else None
        if ch == "L":
            left_gain, to_left = v1, v2
        elif ch == "R":
            right_gain, to_right = v1, v2
        elif ch == "A":
            all_gain, to_all = v1, v2
    return left_gain, right_gain, all_gain, to_left, to_right, to_all


def parse_script(filepath: str) -> Script:
    """解析脚本文件，返回 Script AST。"""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"脚本文件不存在: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    script = Script()
    current_track: Optional[Track] = None
    current_segment: Optional[Segment] = None
    current_relative: Optional[RelativeWindow] = None  # 正在解析的 @on

    # 追踪缩进上下文：track 下的字段/@on 比 segment 缩进多一级；segment 内字段再缩进一级
    # 简化策略：用"当前所在的缩进级"区分 track-level / segment-level
    # track-level: @track 后的行无 @ 前缀且匹配 volume/pan/delay: 
    # segment-level: @segment 后的行匹配 file/tts/voice/ref_text/trim/vol/delay:

    def _flush_segment():
        nonlocal current_segment, current_track
        if current_track is not None and current_segment is not None:
            current_track.segments.append(current_segment)
            current_segment = None

    def _parse_track_field(line: str, lineno: int):
        nonlocal current_track, current_relative
        # track-level 字段
        vol_match = re.match(r"^volume:\s*([\d.]+)$", line, re.IGNORECASE)
        if vol_match:
            current_track.volume = float(vol_match.group(1))
            return True
        pan_match = re.match(r"^pan:\s*([-]?[\d.]+)$", line, re.IGNORECASE)
        if pan_match:
            current_track.pan = float(pan_match.group(1))
            return True
        tk_delay = re.match(r"^delay:\s*(-?[\d.]+)(s|ms)?$", line, re.IGNORECASE)
        if tk_delay:
            v = float(tk_delay.group(1))
            u = (tk_delay.group(2) or "s").lower()
            current_track.delay = v if u == "s" else v / 1000.0
            return True
        return False

    def _parse_on_field(line: str, lineno: int):
        nonlocal current_relative
        if current_relative is None:
            return False
        as_match = re.match(r"^after_start:\s*(-?[\d.]+)(s|ms)?$", line, re.IGNORECASE)
        if as_match:
            v = float(as_match.group(1))
            u = (as_match.group(2) or "s").lower()
            current_relative.after_start = v if u == "s" else v / 1000.0
            return True
        ae_match = re.match(r"^after_end:\s*(-?[\d.]+)(s|ms)?$", line, re.IGNORECASE)
        if ae_match:
            v = float(ae_match.group(1))
            u = (ae_match.group(2) or "s").lower()
            current_relative.after_end = v if u == "s" else v / 1000.0
            return True
        er_match = re.match(r"^end_relative:\s*(-?[\d.]+)(s|ms)?$", line, re.IGNORECASE)
        if er_match:
            v = float(er_match.group(1))
            u = (er_match.group(2) or "s").lower()
            current_relative.end_relative = v if u == "s" else v / 1000.0
            return True
        fi_match = re.match(r"^fade_in\s*:\s*(-?[\d.]+)(s|ms)?$", line, re.IGNORECASE)
        if fi_match:
            v = float(fi_match.group(1))
            u = (fi_match.group(2) or "s").lower()
            current_relative.fade_in_sec = v if u == "s" else v / 1000.0
            return True
        fo_match = re.match(r"^fade_out\s*:\s*(-?[\d.]+)(s|ms)?$", line, re.IGNORECASE)
        if fo_match:
            v = float(fo_match.group(1))
            u = (fo_match.group(2) or "s").lower()
            current_relative.fade_out_sec = v if u == "s" else v / 1000.0
            return True
        return False

    def _parse_segment_field(line: str, lineno: int):
        nonlocal current_segment
        # file: (reuse existing regex)
        file_match = re.match(r"^file:\s+(.+)$", line, re.IGNORECASE)
        if file_match:
            current_segment.file_path = file_match.group(1).strip()
            return True
        # tts:
        tts_match = re.match(r'^tts:\s+"(.+)"$', line, re.IGNORECASE)
        if tts_match:
            current_segment.tts_text = tts_match.group(1)
            return True
        # voice:
        voice_match = re.match(r"^voice:\s+(.+)$", line, re.IGNORECASE)
        if voice_match:
            current_segment.tts_voice = voice_match.group(1).strip()
            return True
        # ref_text:
        rt_match = re.match(r'^ref_text:\s+"(.+)"$', line, re.IGNORECASE)
        if rt_match:
            current_segment.tts_ref_text = rt_match.group(1)
            return True
        # trim:
        trim_match = re.match(r"^trim:\s+(.+?)\s+(.+)$", line, re.IGNORECASE)
        if trim_match:
            current_segment.trim_start = parse_time(trim_match.group(1))
            current_segment.trim_end = parse_time(trim_match.group(2))
            return True
        # vol:
        vol_match = re.match(
            r"^vol:\s+(-?[\d.]+[s%]?)\s*-\s*(-?[\d.]+[s%]?)?\s+(.+)$",
            line, re.IGNORECASE
        )
        if vol_match:
            start_str = vol_match.group(1)
            end_str = vol_match.group(2)
            spec_str = vol_match.group(3).strip()
            start = parse_time(start_str)
            end = parse_time(end_str) if end_str else None
            left_gain, right_gain, all_gain, to_left, to_right, to_all = parse_vol_spec(spec_str)
            current_segment.vol_commands.append(
                VolCommand(start=start, end=end,
                           left_gain=left_gain, right_gain=right_gain,
                           all_gain=all_gain,
                           to_left_gain=to_left, to_right_gain=to_right,
                           to_all_gain=to_all)
            )
            return True
        # delay: (segment-level)
        delay_match = re.match(r"^delay:\s*(-?[\d.]+)(s|ms)?$", line, re.IGNORECASE)
        if delay_match:
            v = float(delay_match.group(1))
            u = (delay_match.group(2) or "s").lower()
            current_segment.delay = v if u == "s" else v / 1000.0
            return True
        # gap: 废弃
        if re.match(r"^gap\s*:", line, re.IGNORECASE):
            raise SyntaxError(
                f"第 {lineno} 行: 'gap' 字段已废弃，请改用 'delay'"
                "(语义：相对上一段结束点的位移量，正=延后，负=提前/重叠)"
            )
        return False

    for lineno, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        # 跳过空行和注释
        if not line or line.startswith("#"):
            continue

        # 全局指令（以 @ 开头）
        if line.startswith("@"):
            # @segment 指令
            seg_match = re.match(r"^@segment\s+(.+)$", line, re.IGNORECASE)
            if seg_match:
                _flush_segment()
                if current_track is None:
                    raise SyntaxError(f"第 {lineno} 行: @segment 必须出现在 @track 内")
                current_segment = Segment(name=seg_match.group(1).strip())
                current_relative = None  # @on 不是 segment 的一部分
                continue

            # @track 指令
            track_match = re.match(r"^@track\s+(.+)$", line, re.IGNORECASE)
            if track_match:
                _flush_segment()
                current_relative = None
                current_track = Track(name=track_match.group(1).strip())
                script.tracks.append(current_track)
                continue

            # @on 指令（必须在 track 内）
            on_match = re.match(r"^@on\s+(.+)$", line, re.IGNORECASE)
            if on_match:
                if current_track is None:
                    raise SyntaxError(f"第 {lineno} 行: @on 必须出现在 @track 内")
                _flush_segment()
                rw = RelativeWindow(target_track=on_match.group(1).strip())
                current_track.relative_windows.append(rw)
                current_relative = rw
                continue

            # @loop 指令（必须在 track 内）
            loop_match = re.match(r"^@loop\s+(\S+)\s+(\S+)$", line, re.IGNORECASE)
            if loop_match:
                if current_track is None:
                    raise SyntaxError(f"第 {lineno} 行: @loop 必须出现在 @track 内")
                _flush_segment()
                current_track.loop_start = loop_match.group(1).strip()
                current_track.loop_end = loop_match.group(2).strip()
                current_relative = None
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

            # @peak_limit
            pl_match = re.match(r"^@peak_limit\s+(-?[\d.]+)$", line, re.IGNORECASE)
            if pl_match:
                script.peak_limit_db = float(pl_match.group(1))
                continue

            raise SyntaxError(f"第 {lineno} 行: 无法识别的全局指令 '{line}'")

        # 非 @ 开头的行 —— track-level 字段、@on 子字段、或 segment 内字段
        if current_track is None:
            raise SyntaxError(f"第 {lineno} 行: 内容出现在 @track 之前: '{line}'")

        # 优先级：如果在 @on 上下文中，先尝试 @on 子字段
        if current_relative is not None and _parse_on_field(line, lineno):
            continue

        # 尝试 track-level 字段（仅当没有活跃 segment 时）
        if current_segment is None:
            if _parse_track_field(line, lineno):
                continue

        # segment 内字段
        if current_segment is not None:
            if _parse_segment_field(line, lineno):
                continue
            raise SyntaxError(f"第 {lineno} 行: 无法识别的字段 '{line}'")
        else:
            raise SyntaxError(f"第 {lineno} 行: 需要 @segment 或合法的 track 字段，而不是 '{line}'")

    _flush_segment()

    if not script.tracks:
        raise ValueError("脚本中没有定义任何 @track")
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

    # 边界：区间无效时返回 1 帧占位（避免上游崩溃）
    if end_sec <= start_sec:
        end_sec = start_sec + 1.0 / sr

    start_frame = int(start_sec * sr)
    end_frame = int(end_sec * sr)
    end_frame = min(end_frame, len(data))
    if start_frame >= end_frame:
        start_frame = end_frame - 1
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

        n_seg = end_frame - start_frame
        ramp = np.linspace(0.0, 1.0, n_seg, dtype=np.float32)

        def _lerp(a, b, r):
            if b is None:
                return np.full_like(r, a)
            return a + (b - a) * r

        seg_all = _lerp(cmd.all_gain, cmd.to_all_gain, ramp)
        seg_left = _lerp(cmd.left_gain, cmd.to_left_gain, ramp)
        seg_right = _lerp(cmd.right_gain, cmd.to_right_gain, ramp)

        if n_channels == 1:
            if cmd.all_gain is not None:
                gain[start_frame:end_frame] = seg_all
            if cmd.left_gain is not None:
                gain[start_frame:end_frame] = seg_left
            elif cmd.right_gain is not None:
                gain[start_frame:end_frame] = seg_right
        else:
            if cmd.all_gain is not None:
                gain[start_frame:end_frame, :] = seg_all[:, None]
            if cmd.left_gain is not None:
                gain[start_frame:end_frame, 0] = seg_left
            if cmd.right_gain is not None and n_channels >= 2:
                gain[start_frame:end_frame, 1] = seg_right

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

def generate_tts(text: str, voice_path: Optional[str], ref_text: Optional[str],
                 target_sr: int, base_path: str) -> np.ndarray:
    """
    调用 OmniVoice 模型进行语音合成。
    返回 float32 numpy 数组（单声道）。
    voice_path 或 ref_text 缺省时，交给 OmniVoice 自己处理默认值。
    """
    kwargs = {"text": text}
    if ref_text is not None:
        kwargs["ref_text"] = ref_text

    if voice_path is None:
        # 不指定 voice，让 OmniVoice 用其默认音色
        print(f'  [TTS] 合成（OmniVoice 默认音色）: "{text[:40]}{"..." if len(text) > 40 else ""}"')
    else:
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
        kwargs["ref_audio"] = input_file
        print(f'  [TTS] 合成: "{text[:40]}{"..." if len(text) > 40 else ""}"')

    audio = _get_tts_model().generate(**kwargs)

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


def _process_segment_data(seg: Segment, sr: int, base_path: str,
                         base_volume: Optional[float]) -> np.ndarray:
    """处理单个 segment，返回音频数据 numpy 数组。"""
    # 加载音频
    if seg.file_path:
        data, _ = load_audio(seg.file_path, sr, base_path)
    elif seg.tts_text:
        # 显式声明则用之；缺省则交给 OmniVoice 自己处理默认值
        voice = seg.tts_voice
        ref = seg.tts_ref_text
        data = generate_tts(seg.tts_text, voice, ref, sr, base_path)
    else:
        raise ValueError(f"片段 '{seg.name}' 缺少 file 或 tts 定义")

    # 截取
    if seg.trim_start is not None and seg.trim_end is not None:
        data = apply_trim(data, sr, seg.trim_start, seg.trim_end)

    # 响度归一化
    if base_volume is not None:
        data = normalize_loudness(data, base_volume)

    # 音量控制
    if seg.vol_commands:
        data = apply_volume_commands(data, sr, seg.vol_commands)

    return data


def _render_track(track: Track, sr: int, base_path: str,
                  base_volume: Optional[float],
                  force_stop: Optional[float] = None) -> np.ndarray:
    """
    渲染一条音轨，返回其整轨音频 numpy 数组。
    如果 force_stop 非 None，到达该秒数后停止（用于 @on end_relative）。
    """
    if not track.segments:
        return np.array([], dtype=np.float32)

    # 检查是否有循环区间
    has_loop = track.loop_start is not None and track.loop_end is not None
    loop_start_idx = loop_end_idx = -1
    if has_loop:
        for i, seg in enumerate(track.segments):
            if seg.name == track.loop_start:
                loop_start_idx = i
            if seg.name == track.loop_end:
                loop_end_idx = i
        if loop_start_idx < 0 or loop_end_idx < 0:
            raise ValueError(f"Track '{track.name}': @loop 中的段名 '{track.loop_start}' 或 '{track.loop_end}' 未找到")

    # 第一遍：计算每个 segment 的音频数据和时长
    seg_datas = []
    seg_durations = []
    for seg in track.segments:
        data = _process_segment_data(seg, sr, base_path, base_volume)
        seg_datas.append(data)
        seg_durations.append(len(data) / sr)

    # 展开时间线（处理循环）
    timeline = []  # list of (seg_idx, data) 按播放顺序

    if has_loop:
        # 非循环前缀（loop_start_idx 之前）
        for i in range(0, loop_start_idx):
            timeline.append((i, seg_datas[i]))
        # 循环体
        loop_body = list(range(loop_start_idx, loop_end_idx + 1))
        # 防御上限
        SAFETY_MAX = 100000 if force_stop is not None else 100
        # elapsed_sec = 循环体内部的累计时长（不包含前缀）
        # 截断判定：循环体累计时长达到 force_stop 时立即停止
        loop_elapsed = 0.0
        loop_count = 0
        while loop_count < SAFETY_MAX:
            loop_done = False
            for seg_idx in loop_body:
                seg_dur = seg_durations[seg_idx]
                # 如果这一段会跨越 force_stop，则只取到 force_stop 之前
                if force_stop is not None and loop_elapsed + seg_dur > force_stop:
                    # 这一段会被 force_stop 截断，但 timeline 仍要包含整段，
                    # 后续 intervals 组装 + force_stop 切片会处理
                    timeline.append((seg_idx, seg_datas[seg_idx]))
                    loop_done = True
                    break
                timeline.append((seg_idx, seg_datas[seg_idx]))
                loop_elapsed += seg_dur
                if force_stop is not None and loop_elapsed >= force_stop:
                    loop_done = True
                    break
            if loop_done:
                break
            loop_count += 1
    else:
        for i in range(len(track.segments)):
            timeline.append((i, seg_datas[i]))

    # 第二遍：在关键时间轴上组装（带 delay）
    # timeline 内：第一个 segment 的 delay 相对 0；后续 segment 的 delay 相对前一个 segment 的起始
    intervals = []  # (data, start_frames)
    current_frame = 0

    for t_idx, (seg_idx, data) in enumerate(timeline):
        seg = track.segments[seg_idx]
        seg_delay = seg.delay or 0.0

        # 再入规则：如果循环再入（t_idx > 0 且前一个是 loop_end），delay 相对上一个 segment 的结束
        # 但这里 timeline 已展开，直接用上一次的 end 加 delay
        if t_idx > 0:
            prev_end_frame = intervals[-1][1] + len(intervals[-1][0])
            current_frame = prev_end_frame + int(seg_delay * sr)
        else:
            # 第一个 segment：delay 相对 0
            current_frame = int(seg_delay * sr)

        if current_frame < 0:
            current_frame = 0
        intervals.append((data, current_frame))

    # 构建单轨输出
    total_frames = 0
    for data, start in intervals:
        total_frames = max(total_frames, start + len(data))

    is_stereo = any(d.ndim > 1 and d.shape[1] >= 2 for d in seg_datas)
    n_channels = 2 if is_stereo else 1

    if n_channels == 1:
        track_out = np.zeros(total_frames, dtype=np.float32)
    else:
        track_out = np.zeros((total_frames, n_channels), dtype=np.float32)

    for data, start in intervals:
        end = start + len(data)
        if data.ndim == 1 and n_channels > 1:
            data = np.column_stack([data, data])
        track_out[start:end] += data

    # 应用 track 级别的 volume / pan
    if track.volume != 1.0:
        track_out *= track.volume
    if track.pan != 0.0 and n_channels >= 2:
        pan_val = float(track.pan)
        left_gain = min(1.0, 1.0 - pan_val)
        right_gain = min(1.0, 1.0 + pan_val)
        track_out[:, 0] *= left_gain
        track_out[:, 1] *= right_gain

    # fade_in / fade_out 语义：
    # - fade_in: 本音轨开头 fade_in_sec 秒内从 0 线性增到原音量
    # - fade_out: 截断点（包括自然结束和 force_stop）之前 fade_out_sec 秒内
    #   从原音量线性降到 0；如果 force_stop 已设，按 force_stop 算窗口
    fade_in_s = max((rw.fade_in_sec for rw in track.relative_windows), default=0.0)
    fade_out_s = max((rw.fade_out_sec for rw in track.relative_windows), default=0.0)

    # 决定本音轨实际"右边界"用于 fade_out
    # 注意此时 force_stop 还未生效，需要参考传入的 force_stop
    # 在调用 _render_track 时 force_stop 是参数

    if fade_in_s > 0 and len(track_out) > 0:
        ramp_len = min(int(fade_in_s * sr), len(track_out))
        ramp = np.linspace(0, 1, ramp_len, dtype=np.float32)
        if n_channels >= 2:
            track_out[:ramp_len, 0] *= ramp
            track_out[:ramp_len, 1] *= ramp
        else:
            track_out[:ramp_len] *= ramp

    if fade_out_s > 0 and len(track_out) > 0:
        # fade_out 窗口的右边界：
        #   - 如果 force_stop 已给且 < 自然长度，窗口 = [force_stop - fade_out_s, force_stop]
        #   - 否则 = 自然尾部 fade_out_s 秒
        natural_end = len(track_out) / sr
        if force_stop is not None and force_stop < natural_end:
            fade_out_end_sec = force_stop
        else:
            fade_out_end_sec = natural_end
        fade_out_end_frame = int(fade_out_end_sec * sr)
        fade_out_start_frame = max(0, fade_out_end_frame - int(fade_out_s * sr))
        n = fade_out_end_frame - fade_out_start_frame
        if n > 0:
            ramp = np.linspace(1, 0, n, dtype=np.float32)
            if n_channels >= 2:
                track_out[fade_out_start_frame:fade_out_end_frame, 0] *= ramp
                track_out[fade_out_start_frame:fade_out_end_frame, 1] *= ramp
            else:
                track_out[fade_out_start_frame:fade_out_end_frame] *= ramp

    # 截断
    if force_stop is not None:
        stop_frame = int(force_stop * sr)
        if stop_frame < len(track_out):
            track_out = track_out[:stop_frame]

    return track_out


def execute_script(script: Script, output_path: str,
                   cli_base_path: Optional[str] = None) -> None:
    """执行脚本，生成最终音频文件。"""
    sr = script.sample_rate

    base_path = cli_base_path if cli_base_path else script.base_path
    base_path = os.path.abspath(base_path)

    print(f"采样率: {sr} Hz")
    print(f"基路径: {base_path}")
    if script.base_volume is not None:
        print(f"响度基准线: {script.base_volume} (RMS)")
    if script.peak_limit_db != 0.0:
        print(f"总线峰值上限: {script.peak_limit_db} dBFS")
    print(f"音轨数: {len(script.tracks)}")
    print()

    # ---- 拓扑排序：处理 @on 依赖 ----
    track_map = {t.name: t for t in script.tracks}
    in_degree = {t.name: 0 for t in script.tracks}
    for t in script.tracks:
        for rw in t.relative_windows:
            if rw.target_track in in_degree:
                in_degree[t.name] += 1

    queue = [n for n, deg in in_degree.items() if deg == 0]
    sorted_order = []
    while queue:
        cur = queue.pop(0)
        sorted_order.append(cur)
        for t in script.tracks:
            for rw in t.relative_windows:
                if rw.target_track == cur:
                    in_degree[t.name] -= 1
                    if in_degree[t.name] == 0:
                        queue.append(t.name)

    if len(sorted_order) != len(script.tracks):
        raise ValueError("音轨间存在循环依赖，无法继续")

    # ============================================================
    # 阶段 1：纯计算阶段
    # 不实际加载音频，只计算：
    #   - 每个 segment 的预估时长（trim 区间大小 / tts 一律估 5s 占位 / file 用 ffprobe 读时长）
    #   - 每个 track 的自然时长（loop 展开后）
    #   - 每个 track 在 master 上的起点
    #   - 每个 track 的 force_stop（end_relative → 本音轨时间线）
    # ============================================================
    print("=== 阶段 1：时间规划 ===")
    track_starts = {}      # name -> seconds (master 上起点)
    track_durations = {}   # name -> seconds (本音轨自然时长)
    track_end_times = {}   # name -> seconds (master 上结束点)
    track_force_stops = {} # name -> seconds or None

    # 工具：从文件头读时长（不加载整个文件）
    def _probe_file_seconds(path: str) -> float:
        if not os.path.isabs(path):
            path = os.path.join(base_path, path)
        try:
            info = sf.info(path)
            return float(info.frames) / float(info.samplerate)
        except Exception:
            try:
                # fallback: ffmpeg/ffprobe
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path],
                    capture_output=True, text=True
                )
                return float(r.stdout.strip())
            except Exception:
                return 5.0  # 兜底

    def _seg_estimate_seconds(seg) -> float:
        """估算单个 segment 的时长（不加载实际音频数据）"""
        # tts 暂时用固定预估（5 秒占位）；后续会按比例缩放
        if seg.tts_text is not None and seg.file_path is None:
            base = 5.0  # 占位
        else:
            if seg.file_path is None:
                base = 1.0
            else:
                base = _probe_file_seconds(seg.file_path)
        # trim 影响
        if seg.trim_start is not None and seg.trim_end is not None:
            total = base
            s = seg.trim_start.to_seconds(total)
            e = seg.trim_end.to_seconds(total)
            base = max(0.001, e - s)
        return base

    # 第一遍：算每个 track 的自然时长（loop 展开后，截断到 force_stop）
    for tname in sorted_order:
        t = track_map[tname]
        # 在没有 force_stop 的前提下，先按"无限循环"算一个保守上限；
        # force_stop 信息等会按 @on 依赖关系迭代收敛
        # 第一次：假设没有 force_stop
        if t.loop_start is not None and t.loop_end is not None:
            body_idx = [i for i, sg in enumerate(t.segments)
                        if t.loop_start <= sg.name and sg.name <= t.loop_end]
            # 简化：直接用 loop_start/loop_end 名称找索引
            ls = le = -1
            for i, sg in enumerate(t.segments):
                if sg.name == t.loop_start: ls = i
                if sg.name == t.loop_end: le = i
            loop_body = list(range(ls, le + 1)) if ls >= 0 and le >= 0 else []
            prefix = list(range(0, ls)) if ls >= 0 else []
            body_dur = sum(_seg_estimate_seconds(t.segments[i]) for i in loop_body)
            prefix_dur = sum(_seg_estimate_seconds(t.segments[i]) for i in prefix)
            # 没有 force_stop 时自然长度 = 前缀 + N*body, N = SAFETY(100)
            SAFETY = 100
            nat_dur = prefix_dur + body_dur * SAFETY
        else:
            nat_dur = sum(_seg_estimate_seconds(sg) for sg in t.segments)
        track_durations[tname] = nat_dur
        print(f"  [预] {tname} 自然时长 ≈ {nat_dur:.2f}s")

    # 迭代收敛 force_stop（最多 5 轮，足够处理链式依赖）
    for _round in range(5):
        # 算每个 track 的 master 起点（依赖其他 track 的 master 起点 + 时长）
        for tname in sorted_order:
            t = track_map[tname]
            base = t.delay or 0.0
            for rw in t.relative_windows:
                if rw.target_track not in track_end_times:
                    continue
                if rw.after_start is not None:
                    base += rw.after_start
                break
            track_starts[tname] = base
            track_end_times[tname] = base + track_durations[tname]

        # 算每个 track 的 force_stop
        changed = False
        for tname in sorted_order:
            t = track_map[tname]
            start = track_starts[tname]
            fs = None
            for rw in t.relative_windows:
                if rw.end_relative is not None and rw.target_track in track_end_times:
                    abs_cut = track_end_times[rw.target_track] + rw.end_relative
                    local = max(0.0, abs_cut - start)
                    if fs is None or local < fs:
                        fs = local
            old_dur = track_durations[tname]
            if fs is not None and fs < old_dur:
                track_durations[tname] = fs
                changed = True
        if not changed:
            break

    # 重新算 master 终点
    for tname in sorted_order:
        track_end_times[tname] = track_starts[tname] + track_durations[tname]
        track_force_stops[tname] = track_durations[tname]
        if tname in track_force_stops and track_durations[tname] > 0:
            print(f"  [终] {tname}: 起点 {track_starts[tname]:.2f}s, 结束 {track_end_times[tname]:.2f}s")

    print("=== 阶段 2：实际渲染 ===")
    rendered = {}

    for tname in sorted_order:
        t = track_map[tname]
        print(f"[Track] {tname} ({len(t.segments)} segments)")
        force_stop = track_force_stops[tname]
        if force_stop is not None:
            print(f"  force_stop: {force_stop:.2f}s")
        track_data = _render_track(
            t, sr, base_path,
            script.base_volume, force_stop
        )
        rendered[tname] = track_data
        print(f"  实际时长: {len(track_data) / sr:.2f} 秒")

    # ---- 计算各 track 在 master 上的绝对位置（阶段 1 已算） ----
    track_positions = {n: int(v * sr) for n, v in track_starts.items()}
    max_end_frame = max(int(v * sr) for v in track_end_times.values())
    for tname in sorted_order:
        print(f"  master 位置: {track_starts[tname]:.2f}s → {track_end_times[tname]:.2f}s")

    # ---- 混合到 master ----
    max_channels = 1
    for data in rendered.values():
        if data.ndim > 1:
            max_channels = max(max_channels, data.shape[1])

    if max_channels > 1:
        master = np.zeros((max_end_frame, max_channels), dtype=np.float32)
    else:
        master = np.zeros(max_end_frame, dtype=np.float32)

    for tname in sorted_order:
        data = rendered[tname]
        start = track_positions[tname]
        end = start + len(data)

        if data.ndim == 1 and max_channels > 1:
            data = np.column_stack([data, data])

        master[start:end] += data

    # ---- 总线峰值限制 ----
    peak = float(np.max(np.abs(master)))
    peak_db = 20 * np.log10(max(peak, 1e-10))
    limit_linear = 10 ** (script.peak_limit_db / 20.0)
    print(f"  混合后峰值: {peak_db:.1f} dBFS (限制阈值: {script.peak_limit_db} dBFS)")
    if peak > limit_linear:
        factor = limit_linear / peak
        master *= factor
        print(f"  已限制: 缩放系数 {factor:.3f}")
    elif peak > 1.0:
        master /= peak  # 硬裁剪到 0 dBFS
        print(f"  已裁剪到 0 dBFS")

    if max_channels == 1:
        master = master.flatten()

    total_duration = len(master) / sr
    print(f"总时长: {total_duration:.2f} 秒")

    sf.write(output_path, master, sr)
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
