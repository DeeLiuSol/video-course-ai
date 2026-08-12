# -*- coding: utf-8 -*-
"""flag_asr_mishears.py — ASR 正词表外疑似误听标记（#28 第二部分）。

原理：扫描 ASR 校正后的转写（text_v3），命中命理搭配模式
（十神组合 / 地支关系 / 三合三刑会局），但完整词条不在
ziping_glossary.json 的 fixed_phrases 正词表内 → 标记为疑似误听。

两类标记：
  - norm：原文含 OCR/ASR 变体字，规范后命中正词表（如 食伤生才→食伤生财）
    —— 说明该变体没被校正，建议补进校正映射
  - off：规范形式本身不在正词表（疑似误听或新词）——给出 difflib 最接近的正词条

用法:
  D:/workbuddy-data/envs/video-skill/Scripts/python.exe flag_asr_mishears.py 3-3

输出: D:/video-skill-output/字幕疑似误听标记_{course}.md
"""
import json
import os
import sys
import difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_fixed_phrases as efp

GLOSSARY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ziping_glossary.json")
CLOSE_CUTOFF = 0.6


def load_whitelist():
    d = json.load(open(GLOSSARY, encoding="utf-8"))
    return set(d.get("fixed_phrases", []) or [])


def _close(canon, whitelist):
    m = difflib.get_close_matches(canon, list(whitelist), n=1, cutoff=CLOSE_CUTOFF)
    return m[0] if m else ""


def _suggest(canon, rev, whitelist):
    """建议顺序：反序正词条 > difflib 最接近 > 空"""
    if rev and rev in whitelist:
        return rev
    return _close(canon, whitelist)


def scan_text(text, whitelist):
    """返回 [(raw, canon, kind, close)]"""
    out = []
    seen = set()

    def _emit(raw, canon, rev):
        if canon in seen:
            return
        seen.add(canon)
        if canon in whitelist:
            if raw != canon:
                out.append((raw, canon, "norm", ""))
            return
        sugg = _suggest(canon, rev, whitelist)
        if sugg:
            out.append((raw, canon, "off", sugg))
        # 无接近正词条 → 大概率是普通口语噪音，跳过（保精度）

    for m in efp.RE_TG.finditer(text):
        a = efp.canon(m.group(1), efp.TG_MAP)
        v = m.group(2)
        c = efp.canon(m.group(3), efp.TG_MAP)
        if efp.is_tg_word(a) and efp.is_tg_word(c):
            _emit(m.group(0), a + v + c, c + v + a)

    for m in efp.RE_BRANCH.finditer(text):
        b = efp.canon(m.group(1), efp.DIZHI_MAP)
        rev_pair = b[1] + b[0]
        _emit(m.group(0), b + m.group(2) + m.group(3), rev_pair + m.group(2) + m.group(3))

    for m in efp.RE_TRIPLE.finditer(text):
        _emit(m.group(0), efp.canon(m.group(1), efp.DIZHI_MAP) + m.group(2), "")

    return out


def main():
    course = sys.argv[1] if len(sys.argv) > 1 else "3-3"
    base = rf"D:\video-skill-output\课程目录模板：按本机课程目录设置（见 README）"
    asr_path = os.path.join(base, "asr_output", "transcript_segments.json")
    asr = json.load(open(asr_path, encoding="utf-8"))
    segs = asr["segments"] if isinstance(asr, dict) else asr

    whitelist = load_whitelist()
    flags = []   # (time, raw, canon, kind, close, segtext)
    for s in segs:
        t = s.get("text_v3") or ""
        for raw, canon, kind, close in scan_text(t, whitelist):
            flags.append((s.get("start", 0), raw, canon, kind, close, t))

    flags.sort(key=lambda x: (x[3], x[0]))
    n_norm = sum(1 for f in flags if f[3] == "norm")
    n_off = sum(1 for f in flags if f[3] == "off")

    OUT = rf"D:\video-skill-output\字幕疑似误听标记_{course}.md"
    L = [
        f"# {course} ASR 疑似误听标记（fixed_phrases 正词表外）",
        "",
        f"> 扫描 {len(segs)} 段校正后转写，对照 {len(whitelist)} 条 fixed_phrases 正词表。",
        f"> **norm（变体未归一）{n_norm} 处**：应改为正词条，建议补校正映射；**off（正词表外）{n_off} 处**：疑似误听或新词，请复核。",
        "",
        "| 时间 | 原文 | 规范后 | 类型 | 建议/最接近正词 | 上下文（段内） |",
        "|------|------|--------|------|------------------|----------------|",
    ]
    for tm, raw, canon, kind, close, segtext in flags:
        type_cn = "变体未归一" if kind == "norm" else "正词表外"
        sugg = close if close else canon
        ctx = segtext[:60].replace("|", "｜")
        L.append(f"| {tm:.1f} | {raw} | {canon} | {type_cn} | {sugg} | {ctx} |")
    L.append("")
    L.append("*复核后：确认误听 → 补进 asr_correction_map 或 OCR_CHAR_FIXES；确认新词 → 加入 fixed_phrases。*")
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print(f"{course}: norm {n_norm} / off {n_off} -> {OUT}")


if __name__ == "__main__":
    main()
