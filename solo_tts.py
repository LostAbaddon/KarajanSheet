from omnivoice import OmniVoice
import soundfile as sf
import numpy as np
import torch
import time
import os
import shutil
import subprocess
import argparse

def resolve_path(path):
    if path is None:
        return None
    return os.path.abspath(path)

def split_text(text, max_chars=500):
    """
    将文本按段落拆分，每块尽可能接近但不超过 max_chars 字。
    先按 \\n\\n 划分自然段，然后贪心合并：逐个往当前块里装，
    装不下（总字数 > max_chars）就封口开新块。单段超 max_chars 的
    则按句子/字符降级拆分。
    """
    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # 先把超长段落拆开，使每个原子段都不超过 max_chars
    atoms = []
    for para in raw_paragraphs:
        if len(para) <= max_chars:
            atoms.append(para)
        else:
            sentences = _split_by_sentence(para)
            for sent in sentences:
                if len(sent) <= max_chars:
                    atoms.append(sent)
                else:
                    for i in range(0, len(sent), max_chars):
                        atoms.append(sent[i:i + max_chars])

    # 合并原子段：往 buf 里装，装不下时把当前 atom 作为最后一段加入再封口
    chunks = []
    buf = ""
    for atom in atoms:
        sep = "\n\n" if buf else ""
        if not buf or len(buf) + len(sep) + len(atom) <= max_chars:
            buf += sep + atom
        else:
            chunks.append(buf + sep + atom)
            buf = ""
    if buf:
        chunks.append(buf)

    return chunks

def _split_by_sentence(text):
    """按中文标点拆分句子，保留标点在句尾。"""
    delimiters = {"。", "！", "？", "；", ".", "!", "?", ";"}
    sentences = []
    start = 0
    for i, ch in enumerate(text):
        if ch in delimiters:
            sentences.append(text[start:i + 1].strip())
            start = i + 1
    if start < len(text):
        remainder = text[start:].strip()
        if remainder:
            sentences.append(remainder)
    return sentences if sentences else [text]

def merge_audio(file_paths, output_path, sample_rate=24000, interval=0.3):
    """将多个 wav 按顺序拼接，中间插入指定秒数的静音，输出到 output_path。"""
    silence = np.zeros(int(sample_rate * interval), dtype=np.float32)
    segments = []

    for path in file_paths:
        data, sr = sf.read(path)
        if data.ndim > 1:
            data = data.mean(axis=1)  # 立体声转单声道
        if sr != sample_rate:
            raise ValueError(f"采样率不一致: {path} ({sr} vs {sample_rate})")
        segments.append(data.astype(np.float32))
        segments.append(silence.copy())

    # 去掉最后一段静音
    if segments:
        segments.pop()

    merged = np.concatenate(segments) if segments else np.array([], dtype=np.float32)
    sf.write(output_path, merged, sample_rate)

# ========== 命令行参数解析 ==========
parser = argparse.ArgumentParser(description="OmniVoice 长文本批量语音合成工具")
parser.add_argument("--sampleAudio", type=str, default=None,
                    help="音色克隆参考音频文件路径")
parser.add_argument("--sampleText", type=str, default=None,
                    help="克隆声音的参考文本内容文件路径（必须与 --sampleAudio 配合使用）")
parser.add_argument("--target", type=str, default=None,
                    help="待合成为语音的文本内容文件路径")
parser.add_argument("--output", type=str, default=None,
                    help="输出音频文件路径")
parser.add_argument("--interval", type=float, default=0.3,
                    help="段落间静音间隔（秒），默认 0.3")
parser.add_argument("--max-chars", type=int, default=500,
                    help="每段最大字符数，默认 500")
args = parser.parse_args()

# ========== 参数校验 ==========
if args.sampleAudio is not None and args.sampleText is None:
    parser.error("--sampleAudio 必须与 --sampleText 配合使用，请同时指定 --sampleText <file_path>")
if args.sampleText is not None and args.sampleAudio is None:
    parser.error("--sampleText 必须与 --sampleAudio 配合使用，请同时指定 --sampleAudio <file_path>")
if args.target is None:
    parser.error("--target 必须指定待合成文本文件路径")

# ========== 解析路径 ==========
sample_audio_path = resolve_path(args.sampleAudio) if args.sampleAudio else resolve_path("sample.wav")
sample_text_path = resolve_path(args.sampleText)
target_text_path = resolve_path(args.target)
output_path = resolve_path(args.output) if args.output else resolve_path("batch_output.wav")

# ========== 读取文本内容 ==========
if not os.path.exists(target_text_path):
    raise FileNotFoundError(f"目标文本文件不存在: {target_text_path}")
with open(target_text_path, "r", encoding="utf-8") as f:
    target_text = f.read().strip()

ref_text = "大家好，这里是胡聊瞎侃嘚啵嘚播客，我是主持人塔塔"
if sample_text_path is not None:
    if not os.path.exists(sample_text_path):
        raise FileNotFoundError(f"参考文本文件不存在: {sample_text_path}")
    with open(sample_text_path, "r", encoding="utf-8") as f:
        ref_text = f.read().strip()

# ========== 参考音频处理 ==========
input_file = sample_audio_path
assert input_file is not None, "参考音频路径不能为空"

if input_file.endswith(".mp3"):
    wav_file = input_file.replace(".mp3", ".wav")
    if not os.path.exists(wav_file):
        subprocess.run([
            "ffmpeg", "-y", "-i", input_file,
            "-ar", "24000", "-ac", "1", wav_file,
        ], capture_output=True)
    input_file = wav_file

if not os.path.exists(input_file):
    raise FileNotFoundError(f"参考音频不存在: {input_file}")

# ========== 文本分段 ==========
chunks = split_text(target_text, max_chars=args.max_chars)
print(f"参考音频: {input_file}")
print(f"参考文本: {ref_text[:50]}{'...' if len(ref_text) > 50 else ''}")
print(f"目标文本: 共 {len(target_text)} 字符，拆分为 {len(chunks)} 段")
print(f"输出路径: {output_path}")
print(f"合并间隔: {args.interval} 秒")
print()

# ========== 创建临时目录 ==========
temp_dir = resolve_path("temp")
os.makedirs(temp_dir, exist_ok=True)

# ========== 加载模型 ==========
print("加载模型...")
model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="mps",
    dtype=torch.float16
)
print("模型加载完成\n")

# ========== 逐段生成音频 ==========
temp_files = []
total_start = time.time()

for idx, chunk in enumerate(chunks):
    chunk_file = os.path.join(temp_dir, f"chunk_{idx:04d}.wav")
    temp_files.append(chunk_file)

    print(f"[{idx + 1}/{len(chunks)}] 生成中 ({len(chunk)} 字): {chunk[:40]}{'...' if len(chunk) > 40 else ''}")

    start_time = time.time()
    audio = model.generate(
        text=chunk,
        ref_audio=input_file,
        ref_text=ref_text,
    )
    elapsed = time.time() - start_time

    sf.write(chunk_file, audio[0], 24000)
    print(f"  ✅ 完成，耗时 {elapsed:.2f} 秒 -> {chunk_file}")

total_elapsed = time.time() - total_start
print(f"\n全部 {len(chunks)} 段生成完毕，总耗时 {total_elapsed:.2f} 秒\n")

# ========== 合并音频 ==========
print("合并音频...")
merge_audio(temp_files, output_path, sample_rate=24000, interval=args.interval)
print(f"✅ 最终音频已导出到: {output_path}")

# ========== 清理中间文件 ==========
print("清理临时文件...")
if os.path.exists(temp_dir):
    shutil.rmtree(temp_dir)
print("完成。")
