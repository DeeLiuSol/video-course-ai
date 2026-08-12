#!/usr/bin/env python3
"""
视频课程 ASR 转写 + 子平法术语校对 (whisper.cpp 引擎)
===================================================
使用 pywhispercpp (whisper.cpp 的 Python 绑定)，无需 PyTorch。
与 transcribe_and_correct.py 使用相同的校正逻辑。

用法:
  python transcribe_whispercpp.py <audio.wav> --glossary ziping_glossary.json --model small
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# ============================================================
# 1. 加载术语词典
# ============================================================
def load_glossary(glossary_path):
    """加载子平法术语词典，构建同音词 → 正确术语的映射表
    
    重要：不使用 categories.aliases 做全局替换！
    aliases 中的条目（如 "人"→"壬"）只在 BaZi 上下文成立，
    全局执行会导致口语中的"人"被错误替换为"壬"。
    只使用 asr_correction_map（精心策划的映射）和 context_rules（上下文规则）。
    """
    with open(glossary_path, "r", encoding="utf-8") as f:
        glossary = json.load(f)

    correction_map = dict(glossary.get("asr_correction_map", {}))

    # 注意：不再从 categories.aliases 自动构建！
    # aliases 中的映射是双向的且上下文敏感的，不能全局应用。

    # 按长度降序排列，长词优先匹配
    sorted_map = sorted(correction_map.items(), key=lambda x: -len(x[0]))
    return sorted_map, glossary


# ============================================================
# 2. 第一遍校正：术语词典正则替换
# ============================================================
def apply_glossary_correction(text, correction_map, glossary):
    corrections_applied = []
    corrected = text
    for wrong, right in correction_map:
        if wrong in corrected:
            pattern = re.escape(wrong)
            if re.search(pattern, corrected):
                count = len(re.findall(pattern, corrected))
                corrected = re.sub(pattern, right, corrected)
                corrections_applied.append({
                    "original": wrong,
                    "corrected": right,
                    "count": count
                })
    return corrected, corrections_applied


# ============================================================
# 3. 第二遍校正：LLM 语义上下文校对
# ============================================================
def apply_llm_correction(raw_text, glossary, api_key=None):
    context_rules = [
        (r"食伤\s*(生|\s*生)\s*财", "食伤生财", "食伤生财组合"),
        (r"伤官\s*(见|\s*见)\s*官", "伤官见官", "伤官见官组合"),
        (r"枭神\s*(夺|\s*夺)\s*食", "枭神夺食", "枭神夺食组合"),
        (r"食神\s*(制|\s*制)\s*杀", "食神制杀", "食神制杀组合"),
        (r"杀\s*(印|\s*印)\s*相生", "杀印相生", "杀印相生组合"),
        (r"财\s*(旺|\s*旺)\s*身弱", "财旺身弱", "财旺身弱"),
        (r"身旺\s*(无|\s*无)\s*财", "身旺无财", "身旺无财"),
        (r"身弱\s*(不|\s*不)\s*胜财", "身弱不胜财", "身弱不胜财"),
        (r"官杀\s*(混杂|\s*混\s*杂)", "官杀混杂", "官杀混杂"),
        (r"比劫\s*(夺|\s*夺)\s*财", "比劫夺财", "比劫夺财"),
        (r"贪财\s*(坏|\s*坏)\s*印", "贪财坏印", "贪财坏印"),
    ]

    corrected = raw_text
    context_corrections = []
    for pattern, replacement, desc in context_rules:
        if re.search(pattern, corrected):
            corrected = re.sub(pattern, replacement, corrected)
            context_corrections.append({"pattern": desc, "replacement": replacement})

    return corrected, context_corrections


# ============================================================
# 4. SRT 格式生成
# ============================================================
def format_srt_timestamp(seconds):
    """格式化为 SRT 时间戳: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(segments, output_path):
    """生成 SRT 字幕文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = format_srt_timestamp(seg["start"])
            end = format_srt_timestamp(seg["end"])
            text = seg.get("text_v2", seg.get("text_v1", seg["text"]))
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def format_timestamp(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ============================================================
# 5. 主流程 (pywhispercpp 引擎)
# ============================================================
def transcribe(audio_path, output_dir, model_size="small", glossary_path=None,
               language="zh", n_threads=4, print_progress=True):
    """
    主流程：pywhispercpp ASR → 术语词典校正 → LLM 上下文校正 → 输出
    """
    os.makedirs(output_dir, exist_ok=True)

    # --- 加载词典 ---
    if glossary_path and os.path.exists(glossary_path):
        correction_map, glossary_data = load_glossary(glossary_path)
        print(f"[词典] 加载 {len(correction_map)} 条术语映射")
    else:
        correction_map, glossary_data = [], {}
        print("[词典] 未找到术语词典，跳过术语校正")

    # --- ASR: pywhispercpp (whisper.cpp C++ 引擎) ---
    from pywhispercpp.model import Model

    # 模型名映射（pywhispercpp 使用 ggml 模型名）
    model_map = {
        "tiny": "tiny",
        "base": "base",
        "small": "small",
        "medium": "medium",
        "large": "large-v3",
        "large-v3": "large-v3",
        "large-v3-turbo": "large-v3-turbo",
    }
    ggml_model = model_map.get(model_size, model_size)

    print(f"[ASR] 加载模型 whisper.cpp {ggml_model}...")
    model = Model(
        ggml_model,
        n_threads=n_threads,
        print_progress=print_progress,
        print_realtime=False,
        print_timestamps=False,
    )

    print(f"[ASR] 开始转写: {audio_path}")
    segments_raw = []
    full_raw = ""

    # pywhispercpp transcribe 返回 segment 生成器
    result_segments = model.transcribe(
        str(audio_path),
        language=language,
        # whisper.cpp 参数
    )

    for seg in result_segments:
        seg_text = seg.text.strip() if hasattr(seg, 'text') else str(seg).strip()
        if not seg_text:
            continue

        # 去除 whisper 默认的前导/后导空格和特殊标记
        seg_text = seg_text.lstrip()

        # 获取时间戳
        t0 = seg.t0 / 100.0 if hasattr(seg, 't0') else 0  # pywhispercpp 返回 10ms 单位
        t1 = seg.t1 / 100.0 if hasattr(seg, 't1') else 0

        segments_raw.append({
            "start": round(t0, 2),
            "end": round(t1, 2),
            "text": seg_text
        })
        full_raw += seg_text + " "

    print(f"[ASR] 完成，共 {len(segments_raw)} 段")

    # --- 保存原始转写 ---
    raw_txt_path = os.path.join(output_dir, "transcript_raw.txt")
    with open(raw_txt_path, "w", encoding="utf-8") as f:
        for seg in segments_raw:
            ts = format_timestamp(seg["start"])
            f.write(f"[{ts}] {seg['text']}\n")
    print(f"[输出] 原始转写: {raw_txt_path}")

    # --- 第一遍校正：术语词典 ---
    print("[校正] 第一遍: 术语词典正则替换...")
    full_corrected_v1, corrections_v1 = apply_glossary_correction(
        full_raw, correction_map, glossary_data
    )

    for seg in segments_raw:
        seg["text_v1"] = apply_glossary_correction(seg["text"], correction_map, glossary_data)[0]

    # --- 第二遍校正：LLM 上下文 ---
    print("[校正] 第二遍: LLM 上下文规则校对...")
    full_corrected_v2, corrections_v2 = apply_llm_correction(
        full_corrected_v1, glossary_data
    )

    for seg in segments_raw:
        seg["text_v2"] = apply_llm_correction(seg.get("text_v1", seg["text"]), glossary_data)[0]

    # --- 保存校正后转写 TXT ---
    corrected_path = os.path.join(output_dir, "transcript_corrected.txt")
    with open(corrected_path, "w", encoding="utf-8") as f:
        for seg in segments_raw:
            ts = format_timestamp(seg["start"])
            final_text = seg.get("text_v2", seg.get("text_v1", seg["text"]))
            f.write(f"[{ts}] {final_text}\n")
    print(f"[输出] 校正转写: {corrected_path}")

    # --- 生成 SRT ---
    srt_path = os.path.join(output_dir, "transcript.srt")
    generate_srt(segments_raw, srt_path)
    print(f"[输出] SRT 字幕: {srt_path}")

    # --- 保存纯文本（无时间戳） ---
    plain_path = os.path.join(output_dir, "transcript_plain.txt")
    with open(plain_path, "w", encoding="utf-8") as f:
        f.write(full_corrected_v2.strip())
    print(f"[输出] 纯文本: {plain_path}")

    # --- 保存结构化 JSON ---
    json_path = os.path.join(output_dir, "transcript_segments.json")
    json_out = {
        "audio": os.path.basename(audio_path),
        "model": f"whisper.cpp-{ggml_model}",
        "language": language,
        "corrections_v1_count": sum(c["count"] for c in corrections_v1),
        "corrections_v2_count": len(corrections_v2),
        "corrections_v1": corrections_v1,
        "corrections_v2": corrections_v2,
        "segments": segments_raw
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_out, f, ensure_ascii=False, indent=2)
    print(f"[输出] 结构化数据: {json_path}")

    return full_corrected_v2, segments_raw


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="视频课程 ASR 转写 (whisper.cpp 引擎)")
    parser.add_argument("audio", help="音频文件路径 (.wav)")
    parser.add_argument("--output", "-o", default=None, help="输出目录")
    parser.add_argument("--model", "-m", default="small",
                        choices=["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
                        help="Whisper 模型大小 (default: small)")
    parser.add_argument("--glossary", "-g", default=None, help="术语词典 JSON 路径")
    parser.add_argument("--language", "-l", default="zh", help="音频语言代码")
    parser.add_argument("--threads", "-t", type=int, default=4, help="CPU 线程数")
    args = parser.parse_args()

    if args.output is None:
        args.output = os.path.join(os.path.dirname(args.audio) or ".", "asr_output")

    print("=" * 60)
    print(f"  视频课程 ASR 转写 + 子平法术语校对")
    print(f"  引擎: whisper.cpp (pywhispercpp)")
    print(f"  音频: {args.audio}")
    print(f"  模型: {args.model}")
    print(f"  词典: {args.glossary or '无'}")
    print(f"  输出: {args.output}")
    print("=" * 60)

    start = time.time()
    text, segments = transcribe(
        args.audio, args.output, args.model, args.glossary,
        args.language, args.threads
    )
    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"  完成! 耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  段数: {len(segments)}")
    print(f"  原始转写: {os.path.join(args.output, 'transcript_raw.txt')}")
    print(f"  校正转写: {os.path.join(args.output, 'transcript_corrected.txt')}")
    print(f"  SRT 字幕: {os.path.join(args.output, 'transcript.srt')}")
    print(f"  分段 JSON: {os.path.join(args.output, 'transcript_segments.json')}")
    print(f"{'='*60}")
