#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_board_pages.py — 板书原文字汇总（分页版，v4.8.2）

复现人工提取方法：人肉在视频里"板书有变化就截图、避开八字案例、重复内容按上下文合并"。
本脚本从已有分段（whiteboard_data_improved.json）里挑出"稳定页面"：
  1. 每段算板书完整度分数（干净长行总长度）
  2. 局部最高点（板面最满的瞬间）= 候选页面
  3. 噪声过滤：段内大部分行是"一次性噪声"（字幕/新闻/案例残留，只在 1 段出现）→ 排除
  4. 内容去重：候选页与已选页内容 ≥50% 重叠 → 跳过（滚动中间态）
  5. 页内跨帧补全：候选页的截断行，用全片该主题的完整版补全
  6. 合并相邻近重复页（≥50% 重叠取更全者）

用法:
  python generate_board_pages.py 3-1 [--out <path>]
  默认写 D:\\video-skill-output\\课程目录名（按需设置）（<course>）\\板书原文字汇总.md
"""
import argparse
import importlib.util
import io
import os
import re
import sys
from collections import OrderedDict

spec = importlib.util.spec_from_file_location("bfc", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "board_fluency_check.py"))
bfc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bfc)

MIN_SCORE = 60          # 候选页最低完整度分数
MIN_LEN = 8             # 参与打分的行最短长度
OVERLAP_SKIP = 0.5      # 与已选页内容重叠 ≥50% 视为重复，跳过
MERGE_OVERLAP = 0.5     # 相邻两页重叠 ≥50% 时合并（保留更全者）
NOISE_PERSIST = 2       # 行出现在 ≥2 段才算"持久板书行"


def is_title(t):
    return bool(re.match(r"^(第[一二三四五六七八九十\d]+种|内容[一二三四五六七八九十]+)[、:：]", bfc._norm(t)))


def build_point_consensus(data):
    """
    跨帧共识投票：同一"要点槽位"（同编号 + 与相同其它要点同现）取出现次数最多的版本。
    解决单帧 OCR 整行认错（"2、身浊灼吐…" vs 正确 "2、身强财旺…"）——字符串相似度匹配不上，
    但正确版出现 14 次、垃圾版 1 次，投票可压回正确版。
    返回 dict: slot_id -> (raw 最完整版本, 出现次数)。
    """
    entries = []  # (coset_frozenset, num, clean_text, raw_text)
    for seg in data:
        block = []  # 当前主题块：标题到下一标题之间的连续要点

        def flush():
            for num, bt in block:
                coset = frozenset(bfc._norm(o[1]) for o in block if o[1] != bt)
                entries.append((coset, num, bfc._norm(bt), bt))

        for ln in seg.get("lines", []):
            bt = board_part(ln["text"].strip())
            if not bt:
                continue
            if is_title(bt):
                flush()
                block = []
                continue
            nm = re.match(r"^(\d+)[、.．]", bfc._norm(bt))
            if nm:
                block.append((nm.group(1), bt))
        flush()
    # 并查集：coset 相交即同槽
    parent = list(range(len(entries)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    n = len(entries)
    for i in range(n):
        for j in range(i + 1, n):
            # 同编号 + 同现要点相交 → 同槽（防同主题 1/2/3 点互相并掉）
            if entries[i][1] == entries[j][1] and entries[i][0] and entries[i][0] & entries[j][0]:
                union(i, j)
    slot_versions = {}
    clean_to_slot = {}
    for i, (_, num, clean, raw) in enumerate(entries):
        slot_versions.setdefault(find(i), []).append((clean, raw))
        clean_to_slot[clean] = find(i)
    consensus = {}
    for slot, vers in slot_versions.items():
        from collections import Counter
        cnt = Counter(c for c, _ in vers)
        best_clean, best_cnt = max(cnt.items(), key=lambda kv: (kv[1], len(kv[0])))
        if best_cnt >= 3:
            best_raw = max((r for c, r in vers if c == best_clean), key=len)
            consensus[slot] = (best_raw, best_cnt)
    # clean 文本 -> (共识 raw, 次数)：单帧 OCR 全错（身浊灼吐）也会映射到其槽位共识
    clean_to_consensus = {}
    for clean, slot in clean_to_slot.items():
        if slot in consensus:
            clean_to_consensus[clean] = consensus[slot]
    return clean_to_consensus


def board_part(text):
    """从行文本剥离排盘残留，返回板书部分（混合行拆开后保留板书侧）。"""
    sp = bfc.split_chart_mixed(text)
    if sp is not None:
        bp, cp, reason = sp
        return bp  # 纯排盘行（bp 为空）也返回空，由调用方跳过
    bt, hc = bfc._board_only(text)
    if hc:
        return ""
    return bt


def board_lines(seg):
    """段内干净板书行（去排盘残留、≥MIN_LEN）。返回 norm 列表。"""
    ts = []
    for ln in seg.get("lines", []):
        t = ln["text"].strip()
        if not t:
            continue
        bp = board_part(t)
        if not bp:
            continue
        nt = bfc._norm(bp)
        if len(nt) >= MIN_LEN:
            ts.append(nt)
    return ts


def seg_score(seg):
    return sum(len(t) for t in board_lines(seg))


def clean_tail(x):
    """去尾数字/噪声，用于比较行完整度（"…之象3" 与 "…之" 视为可对齐）。"""
    return re.sub(r"[。！？\s\d]+$", "", bfc._norm(re.sub(r"\s+", "", x)))


def build_page_candidates(data):
    """返回候选页列表 [(sec, seg, lines_set)]。"""
    segs = sorted(data, key=lambda s: s["start_seconds"])
    scored = [(s, seg_score(s), len(board_lines(s))) for s in segs]

    # 每行出现段数（持久度）
    line_counts = {}
    for s in segs:
        for t in set(board_lines(s)):
            line_counts[t] = line_counts.get(t, 0) + 1

    cands = []
    for i, (s, sc, nc) in enumerate(scored):
        prev = scored[i - 1][1] if i > 0 else -1
        nxt = scored[i + 1][1] if i + 1 < len(scored) else -1
        if sc < MIN_SCORE or sc < prev or sc < nxt:
            continue
        ls = set(board_lines(s))
        if not ls:
            continue
        # 噪声过滤：仅对案例帧生效——案例帧里若大部分行是"一次性内容"
        # （字幕/新闻/案例残留，只在该段出现）则该帧主体不是稳定板书页。
        # 非案例帧（目录页等）内容只出现一次但确是真板书 → 不按此过滤。
        if s.get("is_example"):
            persist = sum(1 for t in ls if line_counts.get(t, 0) >= NOISE_PERSIST)
            if persist / len(ls) < 0.5:
                continue
        # 内容去重：与已选页重叠 ≥50% → 跳过（滚动中间态/近重复）
        dup = False
        for (psec, pseg, pls) in cands:
            if not ls:
                continue
            if len(ls & pls) / len(ls) >= OVERLAP_SKIP:
                dup = True
                break
        if not dup:
            cands.append((int(s["start_seconds"]), s, ls))
    return cands


def _pool_lines(data):
    """全片干净长行池 (norm)。"""
    pool = []
    for seg in data:
        for t in board_lines(seg):
            pool.append(t)
    return pool


def _fullest(nt, pool):
    """在池里找 nt 的更长完整版（同锚相似/子序列）。找不到返回 None。"""
    key = bfc._line_key(nt)
    best = None
    best_len = len(clean_tail(nt))
    for cand in pool:
        if cand == nt:
            continue
        cn = bfc._norm(cand)
        ck = bfc._line_key(cn)
        if key and ck and ck != key:
            continue
        ok = bfc._similar(nt, cn)
        if not ok and key and ck and ck == key:
            body = re.sub(r"^\d+[、.．]\s*", "", nt)
            if len(body) >= 4:
                ok = bfc._is_subsequence(clean_tail(nt), clean_tail(cn))
        if ok:
            cl = len(clean_tail(cn))
            if cl > best_len:
                best, best_len = cand, cl
    return best


def page_complement(seg, pool):
    """页内补全：把段内每行替换为全片该主题更完整版本。就地修改 lines。"""
    changed = 0
    for l in seg.get("lines", []):
        t = l["text"].strip()
        if not t:
            continue
        bt = board_part(t)
        if not bt or len(bfc._norm(bt)) < 4:
            continue
        full = _fullest(bfc._norm(bt), pool)
        if full and len(clean_tail(full)) > len(clean_tail(bt)):
            l["text"] = full
            changed += 1
    return changed


def merge_pages(cands):
    """合并相邻近重复页：两页内容重叠 ≥50% 时保留更长者。"""
    if not cands:
        return []
    merged = [cands[0]]
    for cur in cands[1:]:
        prev = merged[-1]
        cur_ls, prev_ls = cur[2], prev[2]
        if cur_ls and prev_ls:
            inter = len(cur_ls & prev_ls)
            ov = max(inter / len(cur_ls), inter / len(prev_ls))
            if ov >= MERGE_OVERLAP:
                # 保留行更多者；行数相同保留后出现的
                if len(cur_ls) > len(prev_ls):
                    merged[-1] = cur
                continue
        merged.append(cur)
    return merged


def render_pages(cands, data):
    """渲染为 markdown。返回 (md 文本, 页面数)。"""
    pool = _pool_lines(data)
    clean_to_consensus = build_point_consensus(data)  # 跨帧共识投票
    out = []
    out.append("# 板书原文字汇总（分页版）")
    out.append("")
    out.append(f"共 {len(cands)} 个稳定板面（从视频板书变化中挑选，重复内容已按上下文合并）")
    out.append("")
    out.append("---")
    for idx, (sec, seg, ls) in enumerate(cands, 1):
        page_complement(seg, pool)
        out.append("")
        out.append(f"## 第 {idx} 页  ({sec // 60:02d}:{sec % 60:02d})")
        # 按原板面行序输出（标题在上，要点在下），去重
        seen = set()
        rendered = []
        for ln in seg.get("lines", []):
            t = ln["text"].strip()
            if not t:
                continue
            bt = board_part(t)
            if not bt:
                continue
            cons = clean_to_consensus.get(bfc._norm(bt))
            if cons and cons[0] != bt:
                bt = cons[0]  # 跨帧共识版（防单帧 OCR 整行认错）
            nt = bfc._norm(bt)
            if len(nt) < 4 or nt in seen:
                continue
            seen.add(nt)
            rendered.append(bt)
        # 换行断词拼接：短残片（无锚、≤8 字）且上一行未以句末标点收尾 → 拼回上一行
        joined = []
        for bt in rendered:
            nnt = bfc._norm(bt)
            is_frag = bfc._line_key(nnt) is None and len(nnt) <= 8
            if (joined and is_frag
                    and not re.search(r"[。！？；]$", bfc._norm(joined[-1]))):
                joined[-1] = joined[-1].rstrip("，,、 ") + bt
            else:
                joined.append(bt)
        for bt in joined:
            out.append(bt)
        out.append("")
    return "\n".join(out), len(cands)


def main():
    ap = argparse.ArgumentParser(description="板书原文字汇总（分页版）")
    ap.add_argument("course", help="课程号，如 3-1")
    ap.add_argument("--out", help="输出 md 路径（默认覆盖板书原文字汇总.md）")
    args = ap.parse_args()

    data, wb, _ = bfc.load_course(args.course)
    print(f"加载 {len(data)} 段板书: {wb}")

    cands = build_page_candidates(data)
    print(f"候选稳定页面（去重后）: {len(cands)} 个")
    for sec, s, ls in cands:
        print(f"  sec {sec:4d}  {len(ls)} 行")

    cands = merge_pages(cands)
    print(f"合并相邻重复后: {len(cands)} 个")

    md, n = render_pages(cands, data)
    out = args.out or os.path.join(
        bfc.course_dir(args.course), "板书原文字汇总.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"已写入 {out}（{n} 页）")


if __name__ == "__main__":
    main()
