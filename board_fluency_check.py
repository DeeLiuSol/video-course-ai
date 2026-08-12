#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
board_fluency_check.py — 板书通顺性"模拟人理解"检查（v4.8）

背景：板书随讲解逐行显示，同一知识点内后帧通常是前帧的超集（累积显示），
但跨知识点时旧内容被新内容覆盖。OCR 抓到的帧是滚动/擦写的"中间态"，
导致报告里出现 ①短句收尾截断（半行残字）②黄底八字排盘混入板书正文。

本模块模拟人理解：检测不通顺 → 跨帧找完整版（块内超集补全）→
缺则重抓帧（优先已有 1fps 帧，仍缺才 ffmpeg 细抽）→ Qwen 复核通顺性。

用法:
  python board_fluency_check.py 3-3 [--llm] [--fix] [--reframe]

第1层 启发式不通顺检测：行尾半句 / 含 OCR 乱码 / 排盘残留 / 编号残片
第2层 知识点分块聚合：按文本重叠把 seg 聚成"知识点块"，块内取每行最完整版本，
      块间不跨块补全（防新知识点覆盖旧内容的误补全）
第3层 重抓帧：块内仍缺完整版的行 → 重 OCR 该块时间窗内已有 1fps 帧；
      仍缺 → (--video 提供时) ffmpeg 按 0.3-0.5s 细抽
第4层 Qwen 复核：--llm 时把"自动修正候选"喂 Qwen 验证通顺性
落地：--fix 写回 whiteboard_data_improved.json + 重生成报告；始终输出复核清单
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import OrderedDict

# ------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------
OUTPUT_ROOT = r"D:\video-skill-output"
COURSE_DIR_TPL = os.path.join(OUTPUT_ROOT, "课程目录模板：按本机课程目录设置（见 README）")
COURSE_VIDEO = {
    # course -> (视频目录, 文件名)。含特殊字符，用 cd 相对路径调用。
    "3-3": (
        r"VIDEO_DIR: 按本机视频目录设置（示例：某命理课程 3-3）",
        "※1-光明师课程级命理知识分享： 十五种获取财富方式的命理特征（三） ——课程目录名（按需设置）（3-3）2506-720P 准高清-AVC.mp4",
    ),
}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import improve_board as ib  # noqa: E402
from extract_whiteboard import get_ffmpeg_path  # noqa: E402


def course_dir(course):
    return COURSE_DIR_TPL.format(course=course)


def course_wb_dir(course):
    return os.path.join(course_dir(course), "whiteboard")


def load_course(course):
    wb = course_wb_dir(course)
    jp = os.path.join(wb, "whiteboard_data_improved.json")
    data = json.load(open(jp, encoding="utf-8"))
    frames = os.path.join(wb, "frames")
    return data, wb, frames


# ------------------------------------------------------------------
# 第1层：启发式不通顺检测
# ------------------------------------------------------------------
# 行尾半句信号词：板书句子正常不会以这些结尾
TRAILING_FRAGMENT = re.compile(
    r"(要么是|的财或|为人打|没有明|作为日\d|食神代|的印星作|代表权|制住官星则得|"
    r"的财而|为给人打工|被年月|生了年月|是黑社会老|穿的|印星为|伤官一|食伤生|"
    r"财星虚|必须是|主要为|则得到财|一般是打|留不住|虚透一|主做业|食神一|"
    r"第[一二三四五六七八九十\d]+种$|\d+[、.．]$)$"
)
JUNK_RE = re.compile(r"[A-Za-z]{2,}|\d{4}|[A-Za-z][\u4e00-\u9fff]|[\u4e00-\u9fff][A-Za-z]")
NUM_LEAD = re.compile(r"^\d+[、.．]\s*(\S{0,3})$")  # "1、食" 这类编号+极短残片
# --- v4.8 剩余残留的补充模式（都在 case 帧上，OCR 变体/混合 token）---
# 节气信息行：出生于…第N日[节气]（含 于寒眉后第3日[节气] 这种 OCR 误识）
QIJIE_RESIDUE = re.compile(r"\[节气\]|第\d+日$|出生.*第\d+日")
# 长生十二宫阶段（排盘专用，板书不会单独出现"临官/帝旺/冠带"）
CHANGSHENG_RESIDUE = re.compile(r"^(长生|沐浴|冠带|临官|帝旺|衰|病|死|墓|绝|胎|养)$")
# 排盘 OCR 变体十神/阶段词（板书正文不会单独出现）
CHART_GARBAGE_WORDS = {"助财", "助官", "度实印", "实印", "临官", "墓库",
                       "风财", "功财", "正印门", "己助财", "比眉", "侧财", "实印门",
                       "便财", "属印", "员正官", "品正财", "助劫财"}
# 天干 + 规范十神 组合 token（戊正印 / 丙偏财 / 壬劫财）：排盘框残留
TEN_GOD_GZ = re.compile(
    r"^[甲乙丙丁戊己庚辛壬癸奏假夹柄成吴康王关葵笑已一][正偏][印财官杀刃]$")
# 干支 + 额外天干/数字的混合 token（丙寅甲丙四 / 甲午丁2）：横跨排盘框与板书框的 OCR
GZ_MIXED = re.compile(
    r"[甲乙丙丁戊己庚辛壬癸奏假夹柄成吴康王关葵笑已一]"
    r"[子丑寅卯辰巳午未申酉戌亥卵已]"
    r"[甲乙丙丁戊己庚辛壬癸奏假夹柄成吴康王关葵笑已一\d]{1,}")
# 案例姓名/字幕噪声混入板书（姓名：离婚木婚投资被编50 / 前铁部长刘车）
NAME_NOISE = re.compile(r"姓名[:：]|部长|主席")
# 纯数字穿插噪声（3第12第12）
NUM_CH_NUM = re.compile(r"\d+第\d+第")
# 乱码 + 规范十神 组合（吉样万年功 正印 / 于寒眉后…）：case 帧专属
GOD_TAIL_GARBAGE = re.compile(
    r"^[^、\d]+[一-鿿]{2,}\s+(正印|偏印|正财|偏财|食神|伤官|比肩|劫财|七杀|正官|正馆|偏馆|馆印|停印)$")
# 天干开头 + 字母乱码（己EE）
GZ_LEAD_ABC = re.compile(r"[甲乙丙丁戊己庚辛壬癸][A-Za-z]+")



def detect_suspicious_line(text):
    """返回 (是否可疑, [原因])。启发式，第2/3层再补全/复核。"""
    t = text.strip()
    if not t:
        return False, []
    reasons = []
    # 1) 排盘残留（复用 improve_board 的强信号）
    if ib.strong_chart_signal(t):
        reasons.append("排盘残留")
    # 2) OCR 乱码
    if JUNK_RE.search(t):
        reasons.append("OCR乱码")
    # 3) 行尾半句
    if TRAILING_FRAGMENT.search(t.rstrip()):
        reasons.append("行尾半句")
    # 4) 编号残片（"1、食" / "1、-" / "2、印"）
    m = NUM_LEAD.match(t)
    if m and len(t) < 6:
        reasons.append("编号残片")
    # 5) 剩余排盘残留补充模式（节气/长生/混合干支 token/姓名字幕噪声）
    if QIJIE_RESIDUE.search(t):
        reasons.append("排盘残留(节气)")
    if CHANGSHENG_RESIDUE.match(t):
        reasons.append("排盘残留(长生)")
    if t in CHART_GARBAGE_WORDS:
        reasons.append("排盘残留(变体)")
    if GZ_MIXED.search(t):
        reasons.append("排盘残留(混合token)")
    if NAME_NOISE.search(t):
        reasons.append("字幕/姓名噪声")
    if NUM_CH_NUM.search(t):
        reasons.append("数字穿插噪声")
    if GOD_TAIL_GARBAGE.match(t):
        reasons.append("乱码+十神")
    if GZ_LEAD_ABC.search(t):
        reasons.append("天干+字母乱码")
    return bool(reasons), reasons


# ------------------------------------------------------------------
# 第2层：知识点分块聚合（核心）
# ------------------------------------------------------------------
def _norm(t):
    """归一化：去首尾空白，统一编号标点，去末尾半角/标点残留。"""
    t = t.strip()
    t = t.replace("：", ":").replace("，", ",")
    return t


def _line_key(t):
    """取行的"逻辑锚"：编号前缀或知识点标题前缀，用于块内对齐同一行。"""
    m = re.match(r"^(\d+[、.．]|\d+[、.．]\s*)", t)
    if m:
        return m.group(1).strip()
    m = re.match(r"^(第[一二三四五六七八九十\d]+种[、:：]?)", t)
    if m:
        return m.group(1)
    return None


def _similar(a, b):
    """判断两行是否"同一逻辑行"：互为前缀（完整版是残片版的超集）。"""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        if a.startswith(b) or b.startswith(a):
            return True
    # 残片去末尾字符后是另一行的前缀（"1、食神代" vs "1、食神代表脑子"）
    if len(a) >= 4:
        ta = re.sub(r"[\s\d]+$", "", a)  # 去尾数字
        if len(ta) >= 4 and b.startswith(ta):
            return True
    return False


def _is_subsequence(short, long_):
    """short 是否为 long_ 的有序子序列（缺中间/缺字时用；调用前已去空格）。"""
    it = iter(long_)
    return all(ch in it for ch in short)


def build_knowledge_blocks(segs):
    """
    按文本重叠把 seg 聚成"知识点块"（连通分量聚类）。
    同一知识点在不同时刻的帧内容高度重叠（后帧是前帧超集）；
    案例帧/广告帧插在中间也不应把知识点拆开——只要两块内容重叠，
    就通过重叠传递并成同一块。块边界 = 内容无重叠（新知识点）。
    返回 list of blocks，每块是 seg 的 list。
    """
    n = len(segs)
    if n == 0:
        return []
    texts = []
    for seg in segs:
        ts = [_norm(l["text"]) for l in seg.get("lines", [])]
        texts.append([t for t in ts if t])

    # 邻接表：两 seg 内容重叠即连边
    adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if texts[i] and texts[j]:
                hit = sum(1 for t in texts[i]
                          if any(_similar(t, u) for u in texts[j]))
                overlap = hit / max(1, len(texts[i]))
                if overlap >= 0.30:
                    adj[i].append(j)
                    adj[j].append(i)

    # BFS 连通分量
    visited = [False] * n
    blocks = []
    for start in range(n):
        if visited[start]:
            continue
        stack = [start]
        visited[start] = True
        comp = []
        while stack:
            i = stack.pop()
            comp.append(segs[i])
            for j in adj[i]:
                if not visited[j]:
                    visited[j] = True
                    stack.append(j)
        comp.sort(key=lambda s: s.get("start_seconds", 0))
        blocks.append(comp)
    return blocks


GANZHI_PAIR = re.compile(r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]")
# OCR 误识十神垃圾子串（出现在排盘残留里，正文不会出现；故意排除 墓库/临官 等
# 可能出现在命理正文的词，避免误判）
_BOARD_GARBAGE = ("助财", "助官", "功财", "度实印", "实印", "正印门", "己助财")


def _board_only(text):
    """
    从候选行剥离排盘残留，返回纯板书部分。
    先复用 improve_board 的分离逻辑（处理 丙国财/乙信印/小运:癸卯 等 token），
    再兜底过滤独立干支对残留（丙寅甲丙四 这类 OCR 误识排盘）与误识十神垃圾
    （第二种、体力赚 己助财 中的 己助财）。
    返回 (板书部分, 是否含排盘)。
    """
    board_part, case_part = ib.separate_bazi_chart_from_line(text)
    if case_part:
        return board_part, True
    if GANZHI_PAIR.search(text):
        return "", True
    if any(g in text for g in _BOARD_GARBAGE):
        return "", True
    return text, False


def block_fullest_line(block, line_text):
    """
    在块内找 line_text 的"最完整版本"（超集）。找不到返回 None。
    只取同锚（编号/标题前缀一致）且互为前缀的候选。
    候选行必须先剥离排盘残留，避免把 丙国财/小运:癸卯 当完整版吸收。
    返回的完整版保留原始标点（不归一化），供写回使用。
    """
    t = _norm(line_text)
    key = _line_key(t)
    best = None
    for seg in block:
        for l in seg.get("lines", []):
            ct_orig = l["text"].strip()
            ct = _norm(ct_orig)
            if not ct or ct == t:
                continue
            ckey = _line_key(ct)
            if key and ckey and ckey != key:
                continue
            cand_orig, has_chart = _board_only(ct_orig)
            if has_chart:
                continue  # 含排盘残留，不是纯板书完整版
            cand = _norm(cand_orig)
            match = False
            if _similar(t, cand):
                match = True
            elif key and ckey and ckey == key:
                # v4.8.2: 缺中间型截断——同锚、短行是长行的有序子序列
                #   "1、必须要见到食伤， 般有食伤之人不干体力活"
                #   -> "1、必须要见到食伤，食伤代表头脑、技术，一般有食伤之人不干体力活"
                # 编号锚 body 需 ≥4 字：防 "1、"/"2、" 空编号被误补成别的知识点行
                # （同一编号会跨主题复用，如 1、食伤… vs 1、年月的印星…）
                body = re.sub(r"^\d+[、.．]\s*", "", t)
                if len(body) >= 4:
                    # 短行尾部 OCR 噪声字符（"1、年月的印！" 的 ！）不影响子序列判断
                    ts = re.sub(r"[！!？?。.．～~]+$", "",
                                _norm(re.sub(r"\s+", "", t)))
                    cs = _norm(re.sub(r"\s+", "", cand))
                    if _is_subsequence(ts, cs) and len(cand) >= len(t) + 4:
                        match = True
                # 标题行（第X种、）尾 ≤3 字判定为 OCR 截断
                # （"第十种、依赖夕"->"第十种、依赖父母赚钱"）；完整标题
                # （"第一种、技术赚钱"，尾4字）不替换——那是主讲人后来才改的历史状态。
                tm = re.match(r"^(第[一二三四五六七八九十\d]+种[、:：]?)(.*)$", t)
                if tm and len(tm.group(2)) <= 3 and len(cand) > len(t):
                    match = True
            if match:
                if best is None or len(cand) > len(best):
                    best = cand_orig  # 保留原始标点
    if best and len(_norm(best)) > len(t):
        return best
    return None


# 行尾半句强信号：此收尾必为断句，下一条若为续行应拼接
CONTINUATION_TAIL = re.compile(
    r"(要么是$|则得到财$|代表权$|的财而$|为给人打工$|一般喜$|是黑社会老$|"
    r"喜欢搞诈$|偷偷摸摸$|一般是打$|留不住$|主做业$|虚透一$|的印星作$|"
    r"没有明$|作为日\d+$|食伤代$|伤官一$|必须有$|主要为$|被年月$|生了年月$|"
    r"的财或$|比劫的$|年月的$|食伤生$|印星作为$|的印星$|食伤没有$|坐下的$|"
    r"\d+[、.．]$)")


def is_continuation_line(t):
    """判断行是否"半句收尾"，需要与下一条拼接。"""
    t = _norm(t)
    return bool(CONTINUATION_TAIL.search(t))


def _is_word_end(s):
    """判断字符串末尾是否为完整词（OCR 断行不丢字），用于决定拼接用逗号还是直拼。"""
    if not s:
        return False
    if s[-1] in "，,。；;：、 ":
        return True
    # 以常见实词结尾（"要么是/得到财/当官的"）→ 完整词，需逗号连接
    return bool(re.search(r"(么是|是|财|官|权|人|钱|骗|业务|技术|打工|脑子|到|府)$", s))


def join_split_lines(block):
    """
    块内"续行拼接"：把 OCR 断成两行的完整句重新拼回一行。
    只拼 ①行尾是半句强信号 ②下一条不是编号/标题开头（避免把新知识点粘进来）
    ③下一条不带排盘残留。
    拼接方式：若当前行尾是完整词（结尾是"是/财/钱"等，OCR 断行不丢字），
    用逗号连接；若行尾是单字（"喜"后接"欢"，OCR 只断行没丢字），直接拼接。
    返回 (拼接数, 修正明细)。
    """
    fixes = []
    changed = 0
    for seg in block:
        lines = seg.get("lines", [])
        merged = []
        i = 0
        while i < len(lines):
            cur = lines[i]
            t = _norm(cur["text"])
            if i + 1 < len(lines):
                nxt_raw = lines[i + 1]["text"]
                nxt = _norm(nxt_raw)
                _, nxt_has_chart = _board_only(nxt_raw)
                # v4.8.1: 无锚的半句（代表权力、财富，制住官星则得到财）不与缺头残片
                # （技术，一般有食伤之人不干体力活）拼接——两者是不同知识点行的碎片。
                # 只有带编号/标题锚的半句（2、…一般喜 / 3、…要么是）才续行拼接。
                can_join = (
                    _line_key(t) is not None
                    and is_continuation_line(t)
                    and not re.match(r"^(\d+[、.．]|第[一二三四五六七八九十\d]+种)", nxt)
                    and not is_continuation_line(nxt)
                    and not nxt_has_chart
                )
                # v4.8.2: 无锚行续接——OCR 把一行断成"…九种命"+"格，天命…一次性讲完"。
                # 当前行无锚且不以句末标点收尾，下一行以"单字，"开头（行内断词）→ 拼接。
                # 注意 nxt 已过 _norm（，→,），需兼容全角/半角逗号。
                if not can_join and _line_key(t) is None and len(t) >= 8 \
                        and not re.match(r"[。！？；:：]$", t) \
                        and re.match(r"^[一-鿿][,，]", nxt) \
                        and not nxt_has_chart:
                    can_join = True
            else:
                can_join = False
            if can_join:
                # 行尾是单字残片（"喜"+"欢"）→ 直接拼；否则（"要么是"+"当官的"）→ 逗号拼
                last = t.rstrip("，,；;、 ")
                joiner = "，" if len(last) >= 2 and _is_word_end(last) else ""
                new_text = cur["text"].rstrip("，,；;、 ") + joiner + nxt_raw
                fixes.append({"seg": seg.get("start_seconds"), "old": cur["text"],
                              "new": new_text, "from": "join-lines"})
                merged.append({"text": new_text, "confidence": cur.get("confidence", 0)})
                changed += 1
                i += 2
            else:
                merged.append(cur)
                i += 1
        seg["lines"] = merged
    return changed, fixes


def complement_block(block):
    """
    块内超集补全：把块内每行替换为块内最完整版本（若显著更长）。
    返回 (块内修正行数, 修正明细 list)。
    """
    fixes = []
    changed = 0
    for seg in block:
        for l in seg.get("lines", []):
            t = l["text"]
            full = block_fullest_line(block, t)
            if full and len(full) > len(t):
                old = t
                l["text"] = full
                changed += 1
                fixes.append({"seg": seg.get("start_seconds"), "old": old, "new": full,
                              "from": "block-complement"})
    return changed, fixes


def drop_anchorless_suffix(block):
    """
    v4.8.1: 删除"无锚缺头残片"——不以编号/标题开头、且是块内某完整行的真子串的行。
    例："技术，一般有食伤之人不干体力活" 是块内 "1、必须要见到食伤，食伤代表头脑、技术，…"
    的中段截取，完整版已存在，残片冗余。
    保护：①有锚（编号/标题）行不删；②残片短（<6 字，如"当官的/欢搞诈骗"）不删；
    ③完整版与残片长度接近（可能本身是独立短句）不删。
    返回 (删除数, 修正明细)。
    """
    fixes = []
    changed = 0
    # 块内所有行文本（去排盘残留），用于判断"某行是另一行的真子串"
    all_texts = []
    for seg in block:
        for l in seg.get("lines", []):
            t = l["text"].strip()
            if not t:
                continue
            bt, has_chart = _board_only(t)
            if has_chart:
                continue
            all_texts.append(_norm(bt))

    for seg in block:
        keep = []
        for l in seg.get("lines", []):
            t = l["text"].strip()
            if not t:
                keep.append(l)
                continue
            nt = _norm(t)
            if _line_key(nt) is not None:
                keep.append(l)  # 有锚（编号/标题）→ 不删
                continue
            if len(nt) < 6:
                keep.append(l)  # 短短语（当官的/欢搞诈骗）→ 保留
                continue
            # 无锚且不短：找块内是否存在"显著更长的完整版"包含它
            dropped = False
            for cand in all_texts:
                if cand == nt:
                    continue
                if nt and len(cand) >= len(nt) + 3 and nt in cand:
                    dropped = True
                    break
            if dropped:
                fixes.append({"seg": seg.get("start_seconds"), "old": t,
                              "new": "", "from": "drop-anchorless"})
                changed += 1
                continue
            keep.append(l)
        seg["lines"] = keep
    return changed, fixes


def drop_orphan_transition_fragments(blocks):
    """
    v4.8.2: 跨块清理"孤儿过渡块"的冗余残片。

    过渡帧（板面正滚向新知识点）的 OCR 内容常聚成无锚孤儿块：块内所有行都是
    缺头残片，完整版在其它块。例 sec 381 的 '不生自己的财，为给人打工的'
    完整版是块5的 '2、食伤生年月的财或比劫的财，而不生自己的财，为给人打工的'；
    '代表权力、财富，制住官星则得到财，技术，一般有食伤之人不干体力活' 则是
    过渡帧把 #3 行尾部 + #1 行尾部拼成一行。这两条完整版都在别的块，块内
    drop_anchorless_suffix 看不见 → 漏网。本函数跨块兜底。

    规则（只对无锚孤儿块）：
      A 子串冗余：整行是某完整行的真子串（且完整行显著更长）→ 删
      B 拼接冗余：整行按逗号切段后每段（≥4字）都是某完整行的子串 → 删
    完整行 = 全视频中有锚（编号/第X种）或 ≥12 字且无排盘残留的行。
    保护：有锚行 / <6 字短行（当官的）/ 切段含未覆盖段 均保留。
    返回 (删除数, 修正明细)。
    """
    complete_texts = []
    for b in blocks:
        for seg in b:
            for l in seg.get("lines", []):
                t = l["text"].strip()
                if not t:
                    continue
                nt = _norm(t)
                if len(nt) < 6:
                    continue
                if _line_key(nt) is None and len(nt) < 12:
                    continue  # 短且无锚，不作为完整行来源
                bt, has_chart = _board_only(t)
                if has_chart:
                    continue
                complete_texts.append(_norm(bt))

    fixes = []
    changed = 0
    for b in blocks:
        # 只处理无锚孤儿块（块内没有任何编号/标题锚行）
        anchored = any(_line_key(_norm(l["text"])) is not None
                       for seg in b for l in seg.get("lines", []) if l["text"].strip())
        if anchored:
            continue
        for seg in b:
            keep = []
            for l in seg.get("lines", []):
                t = l["text"].strip()
                if not t:
                    keep.append(l)
                    continue
                nt = _norm(t)
                if len(nt) < 6:
                    keep.append(l)
                    continue
                dropped = False
                # A: 真子串
                for c in complete_texts:
                    if c == nt:
                        continue
                    if len(c) >= len(nt) + 3 and nt in c:
                        dropped = True
                        break
                # B: 拼接（整行非单一子串，但按逗号切段全部可覆盖）
                if not dropped and len(nt) >= 8:
                    pieces = [p for p in re.split(r"[，,。；;]", nt) if len(p) >= 4]
                    if len(pieces) >= 2 and all(
                            any(len(c) >= len(p) and p in c for c in complete_texts)
                            for p in pieces):
                        dropped = True
                if dropped:
                    fixes.append({"seg": seg.get("start_seconds"), "old": t,
                                  "new": "", "from": "drop-orphan-frag"})
                    changed += 1
                    continue
                keep.append(l)
            seg["lines"] = keep
    return changed, fixes


# ------------------------------------------------------------------
# 第3层：重抓帧（两级）
# ------------------------------------------------------------------
def frames_in_window(frames_dir, start_sec, end_sec):
    """列出 [start_sec, end_sec] 窗口内已有的 1fps 帧路径。"""
    if not os.path.isdir(frames_dir):
        return []
    out = []
    for n in range(max(0, int(start_sec)), int(end_sec) + 1):
        p = os.path.join(frames_dir, f"frame_{n:05d}.png")
        if os.path.exists(p):
            out.append(p)
    return out


def re_ocr_frames(frame_paths, engine):
    """批量重 OCR 帧，返回 board_lines 列表（合并所有帧的行）。"""
    all_lines = []
    for fp in frame_paths:
        try:
            board_lines, _ = ib.re_ocr_with_boxes(fp, engine)
            all_lines.extend(board_lines)
        except Exception:
            continue
    return all_lines


def reframe_complement(segs, blocks, frames_dir, unresolved, engine):
    """
    第3层A：对块内仍缺完整版的行，重 OCR 该块时间窗内已有 1fps 帧。
    返回 (补齐数, 修正明细)。
    """
    fixes = []
    changed = 0
    for seg in segs:
        # 该 seg 所属块的时间窗
        block = next((b for b in blocks if seg in b), None)
        if block is None:
            continue
        st = min(s.get("start_seconds", 0) for s in block)
        en = max(s.get("end_seconds", 0) or (s.get("start_seconds", 0) + 3) for s in block)
        fps = frames_in_window(frames_dir, st, en)
        if not fps:
            continue
        # 重 OCR 窗口帧，只取与残留行"同锚"的完整版
        reocr_lines = re_ocr_frames(fps, engine)
        for l in seg.get("lines", []):
            t = l["text"]
            if not unresolved.get((id(seg), t)):
                continue
            best = None
            for rt in reocr_lines:
                rt = rt.get("text", "") if isinstance(rt, dict) else str(rt)
                rt = rt.strip()
                cand_orig, has_chart = _board_only(rt)
                if has_chart:
                    continue
                cand = _norm(cand_orig)
                if cand and _similar(t, cand) and len(cand) > len(t) + 1:
                    if best is None or len(cand) > len(best):
                        best = cand_orig  # 保留原始标点
            if best:
                fixes.append({"seg": seg.get("start_seconds"), "old": t, "new": best,
                              "from": "reframe-1fps"})
                l["text"] = best
                changed += 1
                unresolved[(id(seg), t)] = False
    return changed, fixes


# ------------------------------------------------------------------
# 第4层：Qwen 复核（可选 --llm）
# ------------------------------------------------------------------
def qwen_verify(fixes):
    """把修正候选喂 Qwen 验证通顺性，返回保留的修正明细。"""
    try:
        import vision_qwen
    except ImportError:
        return fixes
    kept = []
    for f in fixes:
        prompt = (
            f"板书 OCR 原文是「{f['old']}」，句子疑似被截断。建议补全为「{f['new']}」。"
            f"请只回答：若补全合理且通顺回复 OK，否则回复 NO 并给出更合理的补全。"
        )
        try:
            ans = vision_qwen.analyze_text(prompt, "你是板书校对助手。")
            f["qwen"] = ans.strip()[:120]
            if ans.strip().upper().startswith("OK"):
                kept.append(f)
            else:
                f["qwen_rejected"] = True
        except Exception as e:
            f["qwen"] = f"ERROR:{e}"
            kept.append(f)
        time.sleep(0.3)
    return kept


# ------------------------------------------------------------------
# 落地
# ------------------------------------------------------------------
def write_back(data, wb_dir, course):
    jp = os.path.join(wb_dir, "whiteboard_data_improved.json")
    bak = jp + ".v48.bak"
    if os.path.exists(jp) and not os.path.exists(bak):
        import shutil
        shutil.copy(jp, bak)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return bak


def regenerate_reports(wb_dir):
    """
    用修正后的 JSON 重生成 板书原文字汇总（分页版）。
    v4.8.2: 改调 generate_board_pages.py——旧 generate_reports.py 会同时覆盖
    板书知识点解析.md（完整版含主讲人口述/命主情况），造成回归。
    板书知识点解析.md 由 generate_case_analysis.py 单独生成，此处不碰。
    """
    base = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(base, "generate_board_pages.py")
    course_dir_abs = os.path.dirname(wb_dir)
    # 从 wb_dir 推课程号（……（3-2）\whiteboard → 3-2）
    m = re.search(r"（([^）]+)）[\\/]$", course_dir_abs + os.sep)
    course = m.group(1) if m else os.path.basename(course_dir_abs)
    r = subprocess.run([sys.executable, script, course],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"      [warn] 板书原文字汇总重生成失败: {r.stderr.strip()[:200]}")
        return False
    return True


def write_review_list(reviews, wb_dir, course):
    out = os.path.join(course_dir(course), f"板书通顺性复核清单_{course}.md")
    lines = [f"# 板书通顺性复核清单（{course}）", ""]
    if not reviews:
        lines.append("无低置信待复核项。")
    else:
        lines.append(f"共 {len(reviews)} 项低置信/待人工复核：\n")
        for i, r in enumerate(reviews, 1):
            lines.append(f"{i}. **时间 {r['seg']}s** 原文：`{r['old']}`")
            if r.get("new"):
                lines.append(f"   建议补全：`{r['new']}`")
            lines.append(f"   原因：{r.get('reason', '')}")
            lines.append("")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out


PURE_NOISE = re.compile(r"^[A-Za-z0-9 .:;,()（）\-—_/]+$")
CHART_LINE = re.compile(
    r"(出生时间[:：]|时间[:：]?(阳历|农历)|\d{4}年\d+月\d+日|"
    r"实岁[:：]|农历[:：]\s*\d|出生于|^[时日]柱|^[年月时]柱)")
# v4.8.2: 排盘短语 token（用于从混合行中拆出；含 出生时间/出生于/节气/农历 等）
CHART_PHRASE = re.compile(
    r"(出生时间[:：]|时间[:：]?(阳历|农历)|\d{4}年\d+月\d+日|实岁[:：]|"
    r"农历[:：]\s*\d|流年[:：]|出生于|第?\d+日\[节气\]|后?第\d+日|^[年月时日]柱|^[一-鿿]+日[节气])")


def split_chart_mixed(text):
    """
    从混合行拆出排盘/噪声 token（甲午丁2 技术… / 富，… 丙寅甲丙四 / 姓名：… /
    第七种、贸易 出生时间：阳历1982年… / 第二种、体力赚 己助财）。
    返回 (board_part, chart_part, reason) 或 None（无混合 token 可拆）。
    板书部分保留，排盘 token 移入 case_lines，纯噪声 token 直接丢弃。
    """
    t = text.strip()
    if not t:
        return None
    board_tokens, chart_tokens, dropped = [], [], []
    for token in t.split():
        if GZ_MIXED.match(token) or GZ_LEAD_ABC.match(token):
            chart_tokens.append(token)
        elif CHART_PHRASE.search(token):
            chart_tokens.append(token)  # 排盘短语（出生时间/节气/农历…）
        elif TEN_GOD_GZ.match(token) or any(g in token for g in CHART_GARBAGE_WORDS):
            chart_tokens.append(token)  # 天干+十神 / OCR 误识十神（戊正印/己助财…）
        elif re.match(r"^[甲乙丙丁戊己庚辛壬癸奏假夹柄成吴康王关葵笑已一]"
                      r"[一-鿿]{1,2}[财印官杀刃]", token):
            chart_tokens.append(token)  # 天干+乱码+十神（丁劲财/庚调财）
        elif re.match(r"^[助功便][劫比食伤][财印官]", token):
            chart_tokens.append(token)  # 排盘残留词（助劫财/功比财）
        elif re.match(r"^[^、\d]{1,5}(正官|偏官|正财|偏财|正印|偏印|劫财|比肩|"
                      r"食神|伤官|七杀|羊刃|正馆|偏馆|馆印|停印|便财|助财|功财)$", token):
            chart_tokens.append(token)  # 孤立十神 token（员正官/品正财/便财）
        elif re.search(r"\d{2,}[\d日月时分年]|^\d{3,}$|历?\d{4}\D+\d+\D+\d+", token):
            chart_tokens.append(token)  # 日期/年份/排盘残留（历1904日9月8日/1974）
        elif NAME_NOISE.search(token):
            dropped.append(token)  # 字幕/姓名噪声，丢弃
        else:
            board_tokens.append(token)
    if chart_tokens or dropped:
        board_part = " ".join(board_tokens).strip()
        reason = "混合排盘token" if chart_tokens else "字幕/姓名噪声"
        return board_part, " ".join(chart_tokens), reason
    return None


def classify_line(text, is_example=False):
    """
    给可疑行分类，决定落地动作：
      - ('remove', …)        纯乱码噪声，直接删除
      - ('chart', …)         排盘残留，整行移入 case_lines
      - ('split', board, chart, reason)  混合行 → 板书保留 + 排盘移走
      - (None, …)            不处理
    """
    t = text.strip()
    if PURE_NOISE.match(t):
        return "remove", "纯乱码噪声"
    # v4.8.2: 混合行拆分优先——含板书内容 + 排盘/噪声 token 时拆开保留板书
    # （第七种、贸易 出生时间：阳历1982年… / 第二种、体力赚 己助财 / 姓名噪声）
    sp = split_chart_mixed(t)
    if sp is not None:
        board_part, chart_part, reason = sp
        if board_part:
            return "split", board_part, chart_part, reason
        # 纯排盘/噪声 token，无板书内容 → 按原有动作整行移走/删除
        if chart_part:
            return "chart", reason
        return "remove", reason
    if CHART_LINE.search(t):
        return "chart", "排盘残留"
    if is_example:
        if QIJIE_RESIDUE.search(t):
            return "chart", "排盘残留(节气)"
        if CHANGSHENG_RESIDUE.match(t):
            return "chart", "排盘残留(长生)"
        if t in CHART_GARBAGE_WORDS:
            return "chart", "排盘残留(变体)"
        if GOD_TAIL_GARBAGE.match(t):
            return "chart", "乱码+十神"
        if GZ_LEAD_ABC.search(t):
            return "chart", "排盘残留(天干+字母)"
    if NUM_CH_NUM.search(t):
        return "remove", "数字穿插噪声"
    return None, ""


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="板书通顺性模拟人理解检查")
    ap.add_argument("course", help="课程号，如 3-3")
    ap.add_argument("--llm", action="store_true", help="用 Qwen 复核通顺性（耗额度）")
    ap.add_argument("--fix", action="store_true", help="写回修正后的 JSON 并重生成报告")
    ap.add_argument("--reframe", action="store_true",
                    help="重 OCR 已有 1fps 帧补全（需 improve_board 的 OCR 引擎，较慢）")
    ap.add_argument("--video", help="视频路径，重 OCR 仍缺时 ffmpeg 细抽帧")
    args = ap.parse_args()

    course = args.course
    data, wb, frames_dir = load_course(course)
    print(f"[1/5] 加载 {len(data)} 段板书: {wb}")

    # 第1层：启发式检测
    suspicious = {}
    for seg in data:
        for l in seg.get("lines", []):
            flag, reasons = detect_suspicious_line(l["text"])
            if flag:
                suspicious[(id(seg), l["text"])] = reasons
    print(f"      启发式检出可疑行: {len(suspicious)}")

    # 第2层：知识点分块 + 块内超集补全 + 续行拼接
    blocks = build_knowledge_blocks(data)
    print(f"[2/5] 知识点分块: {len(blocks)} 块")
    n_comp, comp_fixes = 0, []
    for b in blocks:
        c, f = complement_block(b)
        n_comp += c
        comp_fixes.extend(f)
    print(f"      块内超集补全: {n_comp} 行")
    n_join, join_fixes = 0, []
    for b in blocks:
        c, f = join_split_lines(b)
        n_join += c
        join_fixes.extend(f)
    if n_join:
        print(f"      续行拼接: {n_join} 行")

    # 第3层：重抓帧
    reframe_fixes = []
    if args.reframe:
        print("[3/5] 重 OCR 已有帧补全 ...")
        unresolved = OrderedDict((k, True) for k in suspicious.keys())
        engine = ib.create_ocr_engine()
        changed, reframe_fixes = reframe_complement(data, blocks, frames_dir, unresolved, engine)
        print(f"      重抓帧补齐: {changed} 行")
    else:
        print("[3/5] 跳过重抓帧（--reframe 开启时才执行）")

    # 落地分类：可删/可移/需复核
    all_fixes = comp_fixes + reframe_fixes + join_fixes
    removed = []   # 纯乱码噪声行 → 删除
    to_case = []   # 排盘残留行 → 移入 case_lines
    reviews = []   # 低置信 → 复核清单
    fixed_keys = set()
    for f in all_fixes:
        fixed_keys.add((f["seg"], f["old"]))

    for seg in data:
        keep = []
        is_example = bool(seg.get("is_example"))
        for l in seg.get("lines", []):
            t = l["text"]
            k = (seg.get("start_seconds"), t)
            if k in fixed_keys:
                keep.append(l)  # 已被补全（text 已改）
                continue
            action = classify_line(t, is_example=is_example)
            if action[0] == "remove":
                removed.append({"seg": seg.get("start_seconds"), "old": t, "reason": action[1]})
                continue  # 删除
            if action[0] == "chart":
                to_case.append({"seg": seg.get("start_seconds"), "old": t, "reason": action[1]})
                seg.setdefault("case_lines", []).append(
                    {"text": t, "confidence": l.get("confidence", 0)})
                continue  # 移入 case_lines
            if action[0] == "split":
                # 混合行：排盘 token 移入 case_lines，板书部分保留
                _, board_part, chart_part, reason = action
                if chart_part:
                    to_case.append({"seg": seg.get("start_seconds"), "old": t,
                                    "reason": reason, "new": chart_part})
                    seg.setdefault("case_lines", []).append(
                        {"text": chart_part, "confidence": l.get("confidence", 0)})
                if board_part and board_part != t:
                    l["text"] = board_part  # 板书部分写回
                if not board_part:
                    continue  # 无板书残留，整行处理完
                keep.append(l)
                if (id(seg), t) in suspicious:
                    reviews.append({"seg": seg.get("start_seconds"), "old": t,
                                    "reason": "；".join(suspicious[(id(seg), t)])})
                continue
            keep.append(l)
            if (id(seg), t) in suspicious:
                reviews.append({"seg": seg.get("start_seconds"), "old": t,
                                "reason": "；".join(suspicious[(id(seg), t)])})
        seg["lines"] = keep

    # 拆分混合行后，残留的板书半句（富，…高管或官 / 1、必须要见）再补全一遍
    n_comp2, comp_fixes2 = 0, []
    if to_case:
        blocks2 = build_knowledge_blocks(data)
        for b in blocks2:
            c, f = complement_block(b)
            n_comp2 += c
            comp_fixes2.extend(f)
        if n_comp2:
            print(f"      拆后二次补全: {n_comp2} 行")
            all_fixes = all_fixes + comp_fixes2

    # 无锚缺头残片删除（技术，一般有食伤之人不干体力活 → 块内有完整版则删）：
    # 与排盘无关，独立执行；删除内容进 removed 清单
    n_drop, drop_fixes = 0, []
    blocks3 = build_knowledge_blocks(data)
    for b in blocks3:
        c, f = drop_anchorless_suffix(b)
        n_drop += c
        drop_fixes.extend(f)
    if n_drop:
        print(f"      无锚残片删除: {n_drop} 行")
        removed.extend({"seg": f["seg"], "old": f["old"], "reason": "无锚缺头残片"}
                       for f in drop_fixes)
        # 更新 all_fixes 计数（仅统计，不参与写回判断——removed 已含）

    # 跨块清理孤儿过渡块残片（过渡帧把多条完整行的尾部拼成无锚孤儿块）：
    # 完整版在其它块，块内 drop_anchorless_suffix 看不见 → 跨块兜底
    blocks4 = build_knowledge_blocks(data)
    n_orph, orphan_fixes = drop_orphan_transition_fragments(blocks4)
    if n_orph:
        print(f"      孤儿块残片删除: {n_orph} 行")
        removed.extend({"seg": f["seg"], "old": f["old"], "reason": "孤儿块过渡残片"}
                       for f in orphan_fixes)

    # 第4层：Qwen 复核
    if args.llm and all_fixes:
        print(f"[4/5] Qwen 复核 {len(all_fixes)} 条修正候选 ...")
        kept = qwen_verify(all_fixes)
        print(f"      Qwen 保留: {len(kept)} 条")
        all_fixes = kept

    print(f"[5/5] 汇总：补全 {len(all_fixes)}（块内 {n_comp} + 拼接 {n_join} + 重抓帧 {len(reframe_fixes)}），"
          f"删噪声 {len(removed)}，移排盘 {len(to_case)}，待复核 {len(reviews)}")

    rv = write_review_list(reviews, wb, course)
    print(f"      复核清单: {rv}")

    if args.fix and (all_fixes or removed or to_case):
        bak = write_back(data, wb, course)
        print(f"      写回 JSON（备份 {bak}）")
        regenerate_reports(wb)
        print(f"      已重生成两份报告")


def _find_seg_sec(data, seg_id):
    for seg in data:
        if id(seg) == seg_id:
            return seg.get("start_seconds", 0)
    return 0


def _seg_block(data, blocks, seg_id):
    for seg in data:
        if id(seg) == seg_id:
            for b in blocks:
                if seg in b:
                    return b
    return [d for d in data if id(d) == seg_id]


if __name__ == "__main__":
    main()
