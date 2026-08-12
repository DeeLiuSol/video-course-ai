#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_subtitles.py — 解析已有字幕/文稿，接入听译校正与下游分析。

适用场景：视频**没有板书但有字幕**（或原始听译文稿）时，无需跑 ASR，
直接把已有字幕解析成标准 transcript_segments.json，再复用
reapply_asr_correction.py 做领域术语词典校正，下游报告/分析流程不变。

支持格式：.srt / .vtt / .ass / .txt（[mm:ss] 或纯文本行）

用法:
  python parse_subtitles.py --subtitle video.srt --output D:/video-skill-output/<课程>/asr_output
  # 可选：解析后直接跑词典校正
  python parse_subtitles.py --subtitle video.srt --output ... --glossary glossary.json
"""
import argparse
import json
import os
import re
import sys

TS_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})")  # [HH:]MM:SS,mmm
SIMPLE_TS_RE = re.compile(r"\[(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\]")


def _to_seconds(m):
    """把时间戳匹配结果转秒。m 来自 TS_RE 或 SIMPLE_TS_RE。"""
    g = m.groups()
    if len(g) == 4:  # HH:MM:SS,mmm
        h, mm, ss, ms = g
    else:  # [mm:ss] 或 [mm:ss:hh] 三组
        if g[2] is None:
            mm, ss, h, ms = g[0], g[1], 0, 0
        else:
            mm, ss, h, ms = g[1], g[2], g[0], 0
    return int(h or 0) * 3600 + int(mm) * 60 + int(ss) + int(ms or 0) / 1000.0


def parse_srt(path):
    """解析 .srt：序号 + HH:MM:SS,mmm --> HH:MM:SS,mmm + 多行文本"""
    segs = []
    cur = None
    for line in open(path, encoding="utf-8-sig"):
        line = line.rstrip("\n")
        if line.isdigit():
            continue
        m = TS_RE.search(line)
        if m and "-->" in line:
            if cur:
                segs.append(cur)
            start = _to_seconds(m)
            m2 = TS_RE.search(line, m.end())
            end = _to_seconds(m2) if m2 else start
            cur = {"start": start, "end": end, "text": ""}
        elif cur and line.strip():
            cur["text"] += ("" if not cur["text"] else " ") + line.strip()
    if cur:
        segs.append(cur)
    return [s for s in segs if s["text"].strip()]


def parse_vtt(path):
    """解析 .vtt：WEBVTT 头 + 时间轴 + 文本"""
    segs = []
    cur = None
    for line in open(path, encoding="utf-8-sig"):
        line = line.rstrip("\n")
        if line.startswith("WEBVTT") or line.startswith("NOTE") or line.strip() == "":
            continue
        m = TS_RE.search(line)
        if m and "-->" in line:
            if cur:
                segs.append(cur)
            start = _to_seconds(m)
            m2 = TS_RE.search(line, m.end())
            end = _to_seconds(m2) if m2 else start
            cur = {"start": start, "end": end, "text": ""}
        elif cur and line.strip():
            cur["text"] += ("" if not cur["text"] else " ") + line.strip()
    if cur:
        segs.append(cur)
    return [s for s in segs if s["text"].strip()]


def parse_ass(path):
    """解析 .ass/.ssa：Dialogue: layer,start,end,style,...text"""
    segs = []
    for line in open(path, encoding="utf-8-sig"):
        line = line.rstrip("\n")
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        start, end = parts[1], parts[2]
        text = parts[9].replace("\\N", " ").strip()
        if not text:
            continue
        m = TS_RE.search(start)
        m2 = TS_RE.search(end)
        if m and m2:
            segs.append({"start": _to_seconds(m), "end": _to_seconds(m2), "text": text})
    return segs


def parse_txt(path):
    """解析纯文本：优先 [mm:ss] 前缀，否则每行一段"""
    segs = []
    for line in open(path, encoding="utf-8-sig"):
        line = line.rstrip()
        if not line.strip():
            continue
        m = SIMPLE_TS_RE.match(line)
        if m:
            ts = _to_seconds(m)
            text = line[m.end():].strip()
            segs.append({"start": ts, "end": ts + 2, "text": text})
        else:
            segs.append({"start": 0.0, "end": 0.0, "text": line.strip()})
    return [s for s in segs if s["text"].strip()]


PARSERS = {
    ".srt": parse_srt,
    ".vtt": parse_vtt,
    ".ass": parse_ass,
    ".ssa": parse_ass,
    ".txt": parse_txt,
}


def main():
    ap = argparse.ArgumentParser(description="解析已有字幕/文稿 → transcript_segments.json")
    ap.add_argument("--subtitle", required=True, help="字幕/文稿文件（.srt/.vtt/.ass/.txt）")
    ap.add_argument("--output", required=True, help="输出目录（生成 transcript_segments.json）")
    ap.add_argument("--glossary", help="领域词典 JSON 路径；提供则解析后自动跑词典校正")
    args = ap.parse_args()

    ext = os.path.splitext(args.subtitle)[1].lower()
    if ext not in PARSERS:
        print(f"[错误] 不支持的格式 {ext}，支持: {list(PARSERS)}")
        sys.exit(1)

    segs = PARSERS[ext](args.subtitle)
    print(f"[解析] {os.path.basename(args.subtitle)} → {len(segs)} 段")

    os.makedirs(args.output, exist_ok=True)
    data = {
        "audio": os.path.basename(args.subtitle),
        "model": "subtitle-source",
        "language": "zh",
        "corrections_v1_count": 0, "corrections_v2_count": 0, "corrections_v3_count": 0,
        "corrections_v1": [], "corrections_v2": [], "corrections_v3": [],
        "segments": [{"start": f"{s['start']:.1f}", "end": f"{s['end']:.1f}",
                      "text": s["text"], "text_v1": s["text"],
                      "text_v2": s["text"], "text_v3": s["text"]} for s in segs],
    }
    out = os.path.join(args.output, "transcript_segments.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"[输出] {out}")

    if args.glossary:
        import reapply_asr_correction as rac
        rac.reapply(args.output, args.glossary)


if __name__ == "__main__":
    main()
