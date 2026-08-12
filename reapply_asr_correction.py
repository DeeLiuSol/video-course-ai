#!/usr/bin/env python3
"""
ASR 重校正脚本 - reapply_asr_correction.py
==========================================
读取已有的 transcript_raw.txt / transcript_segments.json，
用扩展后的 ziping_glossary.json 重新校正，无需重跑 ASR。

用法:
  python reapply_asr_correction.py <asr_output_dir> --glossary ziping_glossary.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ============================================================
# 时间戳格式化
# ============================================================
def format_timestamp(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_srt_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ============================================================
# 加载词典
# ============================================================
def load_glossary(glossary_path):
    """加载术语词典，构建 纠错映射表 + 上下文规则
    
    重要：不使用 categories.aliases 做全局替换！
    aliases 中的条目（如 "人"→"壬"）只在 BaZi 上下文成立，
    全局执行会导致口语中的"人"被错误替换为"壬"。
    只使用 asr_correction_map（精心策划的映射）和 context_rules（上下文规则）。
    """
    with open(glossary_path, "r", encoding="utf-8") as f:
        glossary = json.load(f)

    # 1. 精确匹配映射（asr_correction_map）—— 唯一的精确匹配来源
    correction_map = dict(glossary.get("asr_correction_map", {}))

    # 注意：不再从 categories.aliases 自动构建！
    # aliases 中的映射是双向的且上下文敏感的，不能全局应用。
    # 例如 "壬".aliases 包含 "人"，但 "人" → "壬" 只在 BaZi 上下文成立。
    # 口语中的 "人" 应该保持 "人"。

    # 过滤掉 noop 和 identity 映射
    clean_map = {k: v for k, v in correction_map.items()
                 if v != "noop" and k != v}

    # 按长度降序排列（长词优先）
    sorted_map = sorted(clean_map.items(), key=lambda x: -len(x[0]))

    # 3. 上下文规则
    context_rules_raw = glossary.get("context_rules", {}).get("rules", [])
    context_rules = []
    for rule in context_rules_raw:
        if len(rule) >= 2 and rule[1] != "noop":
            pattern = rule[0]
            replacement = rule[1]
            desc = rule[2] if len(rule) > 2 else ""
            # 跳过 identity 规则
            if pattern != replacement:
                try:
                    compiled = re.compile(pattern)
                    context_rules.append((compiled, replacement, desc))
                except re.error as e:
                    print(f"  [警告] 跳过无效规则 '{pattern}': {e}")

    return sorted_map, context_rules, glossary


# ============================================================
# 第一遍校正：精确匹配替换
# ============================================================
def apply_exact_correction(text, correction_map):
    """用精确匹配替换纠错"""
    corrections = []
    corrected = text
    for wrong, right in correction_map:
        if wrong in corrected:
            count = corrected.count(wrong)
            corrected = corrected.replace(wrong, right)
            corrections.append({
                "original": wrong,
                "corrected": right,
                "count": count
            })
    return corrected, corrections


# ============================================================
# 第二遍校正：上下文规则替换
# ============================================================
def apply_context_correction(text, context_rules):
    """用上下文感知规则纠错"""
    corrections = []
    corrected = text
    for pattern, replacement, desc in context_rules:
        matches = list(pattern.finditer(corrected))
        if matches:
            count = len(matches)
            # 处理反向引用 (\g<0>, \1 等)
            try:
                corrected = pattern.sub(replacement, corrected)
                corrections.append({
                    "pattern": desc or pattern.pattern,
                    "replacement": replacement,
                    "count": count
                })
            except re.error as e:
                print(f"  [警告] 替换失败 '{desc}': {e}")
    return corrected, corrections


# ============================================================
# 第三遍校正：LLM 语义上下文校对（组合术语）
# ============================================================
def apply_composite_correction(text):
    """修复组合术语中的残留错误"""
    rules = [
        (r'食伤\s*(?:生\s*)?财', '食伤生财', '食伤生财组合'),
        (r'伤官\s*见\s*官', '伤官见官', '伤官见官组合'),
        (r'枭神\s*夺\s*食', '枭神夺食', '枭神夺食组合'),
        (r'食神\s*制\s*杀', '食神制杀', '食神制杀组合'),
        (r'杀\s*印\s*相\s*生', '杀印相生', '杀印相生组合'),
        (r'财\s*旺\s*身\s*弱', '财旺身弱', '财旺身弱'),
        (r'身\s*旺\s*无\s*财', '身旺无财', '身旺无财'),
        (r'身\s*弱\s*不\s*胜\s*财', '身弱不胜财', '身弱不胜财'),
        (r'官\s*杀\s*混\s*杂', '官杀混杂', '官杀混杂'),
        (r'比\s*劫\s*夺\s*财', '比劫夺财', '比劫夺财'),
        (r'贪\s*财\s*坏\s*印', '贪财坏印', '贪财坏印'),
        (r'比\s*劫\s*多\s*而\s*财\s*星\s*弱', '比劫多而财星弱', '比劫多而财星弱'),
        (r'子\s*午\s*卯\s*酉', '子午卯酉', '子午卯酉'),
        (r'辰\s*戌\s*丑\s*未', '辰戌丑未', '辰戌丑未'),
        (r'甲\s*庚\s*壬\s*丙\s*寅\s*申\s*巳\s*亥', '甲庚壬丙寅申巳亥', '天干地支列表'),
        (r'半\s*合', '半合', '半合归一'),
        (r'三\s*会', '三会', '三会归一'),
    ]
    corrected = text
    corrections = []
    for pattern, replacement, desc in rules:
        if re.search(pattern, corrected):
            corrected = re.sub(pattern, replacement, corrected)
            corrections.append({"pattern": desc, "replacement": replacement})
    return corrected, corrections


# ============================================================
# 主流程
# ============================================================
def reapply(asr_dir, glossary_path):
    """读取已有ASR输出，重新校正"""
    # 加载词典
    print(f"[词典] 加载: {glossary_path}")
    exact_map, context_rules, glossary = load_glossary(glossary_path)
    print(f"[词典] 精确匹配: {len(exact_map)} 条")
    print(f"[词典] 上下文规则: {len(context_rules)} 条")

    # 读取 segments.json
    json_path = os.path.join(asr_dir, "transcript_segments.json")
    if not os.path.exists(json_path):
        print(f"[错误] 找不到: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data["segments"]
    print(f"[ASR] 读取 {len(segments)} 段转写")

    # 对每段应用三遍校正
    all_v1_corrections = []
    all_v2_corrections = []
    all_v3_corrections = []

    for seg in segments:
        raw_text = seg["text"]

        # V1: 精确匹配
        v1_text, v1_corrections = apply_exact_correction(raw_text, exact_map)
        seg["text_v1"] = v1_text
        for c in v1_corrections:
            all_v1_corrections.append(c)

        # V2: 上下文规则
        v2_text, v2_corrections = apply_context_correction(v1_text, context_rules)
        seg["text_v2"] = v2_text
        for c in v2_corrections:
            all_v2_corrections.append(c)

        # V3: 组合术语
        v3_text, v3_corrections = apply_composite_correction(v2_text)
        seg["text_v3"] = v3_text
        for c in v3_corrections:
            all_v3_corrections.append(c)

    # 合并 V2+V3 校正统计
    # 去重统计
    v1_count = sum(c["count"] for c in all_v1_corrections)
    v2_count = len(all_v2_corrections)
    v3_count = len(all_v3_corrections)

    print(f"[校正] V1 精确匹配: {v1_count} 处替换")
    print(f"[校正] V2 上下文规则: {v2_count} 处替换")
    print(f"[校正] V3 组合术语: {v3_count} 处替换")

    # 打印 V1 top corrections
    from collections import Counter
    v1_counter = Counter()
    for c in all_v1_corrections:
        v1_counter[f"{c['original']}→{c['corrected']}"] += c["count"]
    print("\n[V1] Top 20 替换:")
    for item, count in v1_counter.most_common(20):
        print(f"  {item}: {count}x")

    # 打印 V2 top corrections
    v2_counter = Counter()
    for c in all_v2_corrections:
        v2_counter[c.get("pattern", c.get("original", "?"))] += 1
    print("\n[V2] Top 20 上下文替换:")
    for item, count in v2_counter.most_common(20):
        print(f"  {item}: {count}x")

    # --- 保存校正后 TXT ---
    corrected_path = os.path.join(asr_dir, "transcript_corrected.txt")
    with open(corrected_path, "w", encoding="utf-8") as f:
        for seg in segments:
            ts = format_timestamp(seg["start"])
            final_text = seg.get("text_v3", seg.get("text_v2", seg.get("text_v1", seg["text"])))
            f.write(f"[{ts}] {final_text}\n")
    print(f"\n[输出] 校正转写: {corrected_path}")

    # --- 保存纯文本 ---
    full_text = " ".join(
        seg.get("text_v3", seg.get("text_v2", seg.get("text_v1", seg["text"])))
        for seg in segments
    )
    plain_path = os.path.join(asr_dir, "transcript_plain.txt")
    with open(plain_path, "w", encoding="utf-8") as f:
        f.write(full_text.strip())
    print(f"[输出] 纯文本: {plain_path}")

    # --- 生成 SRT ---
    srt_path = os.path.join(asr_dir, "transcript.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = format_srt_timestamp(seg["start"])
            end = format_srt_timestamp(seg["end"])
            text = seg.get("text_v3", seg.get("text_v2", seg.get("text_v1", seg["text"])))
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
    print(f"[输出] SRT 字幕: {srt_path}")

    # --- 保存 JSON ---
    data["corrections_v1_count"] = v1_count
    data["corrections_v2_count"] = v2_count
    data["corrections_v3_count"] = v3_count
    data["corrections_v1"] = all_v1_corrections
    data["corrections_v2"] = all_v2_corrections
    data["corrections_v3"] = all_v3_corrections

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[输出] 结构化数据: {json_path}")

    return corrected_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASR 重校正（无需重跑ASR）")
    parser.add_argument("asr_dir", help="ASR 输出目录 (包含 transcript_segments.json)")
    parser.add_argument("--glossary", "-g", required=True, help="术语词典 JSON 路径")
    args = parser.parse_args()

    print("=" * 60)
    print("  ASR 重校正 (扩展词典)")
    print(f"  目录: {args.asr_dir}")
    print(f"  词典: {args.glossary}")
    print("=" * 60)

    reapply(args.asr_dir, args.glossary)

    print(f"\n{'='*60}")
    print("  完成!")
    print(f"{'='*60}")
