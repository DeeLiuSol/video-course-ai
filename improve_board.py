#!/usr/bin/env python3
"""
板书后处理优化器 - improve_board.py (v2)
针对已有 OCR 结果做四项优化：
  1. 坐标感知的行合并 — 同一 Y 层的文字合并为一行
  2. 增强噪声过滤 — 水印、频道名、装饰文字（合并前+合并后双重过滤）
  3. 字符级纠错 — 修复 RapidOCR 对八字命理字符的系统性误识别
  4. 智能去重 — 基于结构相似度而非字符相似度

用法:
  python improve_board.py <whiteboard_data.json> [--output OUTPUT_JSON]

说明: 需要在 video-skill venv 中运行（依赖 rapidocr_onnxruntime）
"""

import json, os, sys, re
from collections import defaultdict

import numpy as np
import cv2


# ============================================================
# 增强噪声词库
# ============================================================
NOISE_EXACT = {
    # 水印/频道标识
    "宝藏博主", "+关注", "易懂小课堂", "易懂小课学一期", "易懂小课堂期",
    "易懂小课堂朋", "易懂小课学朋", "易懂小课堂一朋", "易懂小课堂一明",
    "懂小课堂期我", "易懂小课学一期，", "易懂小课堂一朋，", "易懂小课学朋，",
    "易懂小课堂一朋！", "懂小课堂期我", "易懂小课堂朋", "易懂小课堂期我",
    "青武老师养", "精心制作", "白龙王",
    # 水印变体（OCR识别错误）
    "易懂小课堂一期", "易懂小课堂一期，", "易懂小课堂一期！",
    "易懂小课堂明", "易懂小课堂期#", "易懂小课堂期让", "易懂小课堂期班",
    "易懂小课堂期！", "易懂小课堂一", "易懂小课堂，" , "易懂小课堂明，",
    "易懂小课堂朋，", "易懂小课堂朋！",
    # 乱码
    "123第12花3", "12345第1未", "12345第1未2", "翼仆2345剃亻2",
    "CCTV13", "在一起", "冯提", "陪酒", "陈朗",
    "暖暖贴", "暖贴", "暖暖",
    # 额外噪声
    "9:37收0#8", "9:37体0口日", "吉祥万年历", "吉样万年历", "【专业版】", "专业版",
    "B站易懂小课堂", "B站易懂小小课堂", "B站", "易懂小课堂朋，", "易懂小课堂朋！",
    # 新增水印变体
    "易懂小课堂一明！", "易懂小课堂明！", "易懂小课堂期#",
    "VIP加急", "VIP", "加急", "重庆面来", "重庆",
    "精简版", "精简", "【精简版】", "【精简】",
    "【分析】", "分析",
    "小课堂", "课堂",
}

# 更强力的模式匹配
NOISE_PATTERNS = [
    re.compile(r'^[第\d]+[第\d]+[花未剃亻][\d二]+$'),  # 乱码数字行
    re.compile(r'^[12]{3,}[第\d花未剃亻一二三]*$'),
    re.compile(r'^第\d+[花未]'),  # "第12花3" 之类
    re.compile(r'^[一-龥]小[课学][堂学][期朋一二三四五六七八九十]\W*$'),  # "X小课堂X" + optional punctuation
    re.compile(r'^[一-龥]{1,2}[小课]学[一二三]?[期朋明让班]{0,2}[，。、！!？]?$'),  # 各种"易懂小课堂"变体
    re.compile(r'^[一-龥][武老师][老养][师]?$'),  # "X武老师养"
    re.compile(r'^\d+[，。,.]?\d*$'),  # 纯数字
    re.compile(r'^\d+:\d+[收体口]\d*[口日#]?\d*$'),  # 时间戳噪声 "9:37收0#8"
    re.compile(r'^[BＢ]站'),  # B站开头
    re.compile(r'^VIP', re.IGNORECASE),  # VIP开头
    re.compile(r'吉祥万年历|吉样万年历'),  # 万年历水印
    re.compile(r'易懂小[课学][堂学]'),  # 任何包含"易懂小课堂"的
    re.compile(r'小[课学][堂学]'),  # 任何包含"小课堂"的（碎片水印）
    re.compile(r'重庆'),  # 重庆水印
    re.compile(r'专业版|精简版|【.*版】|【.*】'),  # 版本标记
]


def is_noise(text):
    """判断是否是噪声文字"""
    t = text.strip()
    if not t or len(t) < 2:
        return True
    if t in NOISE_EXACT:
        return True
    for pat in NOISE_PATTERNS:
        if pat.search(t):
            return True
    # 过度碎的片段（大部分是水印残留）
    if len(t) <= 3 and not any(c in t for c in "八字命财富官杀印食伤比劫干支"):
        if not re.search(r'[a-zA-Z\d]', t):
            return True
    # v4.8: 无中文字符 → 纯拉丁/数字串（英文横幅、水印、乱码如 un/EE）
    if not re.search(r'[一-鿿]', t):
        # 板书编号残片（如 "1、" "1、-"）保留待补全层，其余判噪声
        if not re.match(r'^\d+[、.．]?-?$', t):
            return True
    return False


# ============================================================
# 字符级 OCR 纠错（上下文感知）
# ============================================================
# 八字命理十神后缀，用于判断天干上下文
TEN_GOD_SUFFIXES = (
    "正财", "偏财", "七杀", "正官", "偏官", "正印", "偏印",
    "食神", "伤官", "比肩", "劫财", "食伤",
    "财", "官", "印", "杀", "比", "劫", "食", "伤",
)

# 天干集合
HEAVENLY_STEMS = set("甲乙丙丁戊己庚辛壬癸")
# 地支集合
EARTHLY_BRANCHES = set("子丑寅卯辰巳午未申酉戌亥")

# 字符纠错规则列表：(编译后的正则, 替换字符串, 描述)
OCR_CHAR_FIXES = []

def _add_fix(pattern, replacement, desc=""):
    """添加一条字符纠错规则"""
    OCR_CHAR_FIXES.append((re.compile(pattern), replacement, desc))

# --- 天干混淆纠错 ---

# 王 → 壬（王 后面接十神 = 天干壬）
_add_fix(r'王(?=正财|偏财|七杀|正官|偏官|正印|偏印|食神|伤官|比肩|劫财|食伤)', '壬', '王→壬(天干+十神)')
# 王 → 壬（后面接五行 = 天干壬，如壬水/壬木）
_add_fix(r'王(?=水|木|火|土|金)', '壬', '王→壬(天干+五行: 壬水等)')
# 王 在天干列表中（甲、丙、庚、王、寅...）
_add_fix(r'(甲、丙、庚、)王(、寅)', r'\1壬\2', '王→壬(天干列表)')
_add_fix(r'(庚、)王(、寅)', r'\1壬\2', '王→壬(天干列表)')

# 关 → 癸（关 后面接十神 = 天干癸）
_add_fix(r'关(?=正财|偏财|七杀|正官|偏官|正印|偏印|食神|伤官|比肩|劫财|食伤)', '癸', '关→癸(天干+十神)')

# 葵 → 癸（葵 后面接十神或地支 = 天干癸）
_add_fix(r'葵(?=比肩|七杀|正财|偏财|正印|偏印|食神|伤官|劫财|比|七|正|偏|食|伤|未|酉|末|卯)', '癸', '葵→癸(天干)')
_add_fix(r'葵(?=癸)', '癸', '葵→癸(叠字)')
# 葵末 → 癸未
_add_fix(r'葵末', '癸未', '葵末→癸未(地支)')
# 葵未 → 癸未 (直接替换)
_add_fix(r'(?<!癸)葵(?!比|七|正|偏|食|伤|未|酉|末|卯|癸)', '癸', '葵→癸(独立)')

# 笑 → 癸（笑 后面接十神或地支 = 天干癸）
_add_fix(r'笑(?=比肩|七杀|正财|偏财|正印|偏印|食神|伤官|劫财|酉|未|比|七|正|偏|食|伤)', '癸', '笑→癸(天干)')
_add_fix(r'笑酉', '癸酉', '笑酉→癸酉(地支)')

# 窦 → 癸
_add_fix(r'窦(?=正财|正印|偏财|偏印|七杀|正官|比肩|劫财|食神|伤官)', '癸', '窦→癸(天干)')
# 浅 → 癸（在比肩前）
_add_fix(r'浅(?=比肩)', '癸', '浅→癸(天干)')
# 英 → 癸（在正印/正财前）
_add_fix(r'英(?=正印|正财|偏印|偏财)', '癸', '英→癸(天干)')
# 突 → 癸
_add_fix(r'突(?=正财|正印|偏财|偏印)', '癸', '突→癸(天干)')
# 爱 → 癸
_add_fix(r'爱(?=正财|正印|偏财|偏印)', '癸', '爱→癸(天干)')
# 奏 → 癸
_add_fix(r'奏(?=正财|正印|偏财|偏印)', '癸', '奏→癸(天干)')

# 成 → 戊（成 后面接十神 = 天干戊）
_add_fix(r'成(?=伤官|偏印|比肩|食神|正官|正印|偏财|正财|七杀|劫财|土)', '戊', '成→戊(天干)')
# 成在辰戌丑未中应为戌（更详细规则见下方地支纠错区）

# 康 → 庚（康 后面接十神或地支 = 天干庚）
_add_fix(r'康(?=正官|正印|偏印|食神|偏财|正财|七杀|比肩|劫财|辰|金)', '庚', '康→庚(天干)')
_add_fix(r'康辰', '庚辰', '康辰→庚辰(干支)')
_add_fix(r'康正官', '庚正官', '康正官→庚正官')

# --- 十神混淆纠错 ---

# 动 → 劫（动财 = 劫财）
_add_fix(r'动财', '劫财', '动财→劫财(十神)')
_add_fix(r'己动财', '己劫财', '己动财→己劫财')
_add_fix(r'已动财', '己劫财', '已动财→己劫财')
_add_fix(r'戊动财', '戊劫财', '戊动财→戊劫财')
_add_fix(r'癸动财', '癸劫财', '癸动财→癸劫财')

# 停 → 偏（停财=偏财, 停印=偏印）
_add_fix(r'停财', '偏财', '停财→偏财(十神)')
_add_fix(r'停印', '偏印', '停印→偏印(十神)')

# 馆 → 偏/官
_add_fix(r'馆(?=印)', '偏', '馆→偏(十神: 馆印→偏印)')
_add_fix(r'(?<=正)馆', '官', '正馆→正官')
# 辛馆印 → 辛偏印
_add_fix(r'馆印', '偏印', '馆印→偏印(十神)')

# 编印 → 偏印
_add_fix(r'编印', '偏印', '编印→偏印(十神)')
# 复印 → 偏印 (在辛后)
_add_fix(r'辛复印', '辛偏印', '辛复印→辛偏印')
# 隐印 → 偏印
_add_fix(r'隐印', '偏印', '隐印→偏印(十神)')
# 候印 → 偏印
_add_fix(r'候印', '偏印', '候印→偏印(十神)')

# 食祥 → 食神
_add_fix(r'食祥', '食神', '食祥→食神(十神)')

# 比屏/比鼻 → 比肩
_add_fix(r'比屏', '比肩', '比屏→比肩(十神)')
_add_fix(r'比鼻', '比肩', '比鼻→比肩(十神)')
_add_fix(r'比屑', '比肩', '比屑→比肩(十神)')

# --- 108例经典案例 OCR 误读修复（2026-08-09）---

# 编财 → 偏财
_add_fix(r'编财', '偏财', '编财→偏财(十神)')

# 仿言/伤言 → 伤官
_add_fix(r'仿言', '伤官', '仿言→伤官(十神)')
_add_fix(r'伤言', '伤官', '伤言→伤官(十神)')

# 正富/正宫/正营 → 正官
_add_fix(r'正富', '正官', '正富→正官(十神)')
_add_fix(r'正宫', '正官', '正宫→正官(十神)')
_add_fix(r'正营', '正官', '正营→正官(十神)')

# 七茶 → 七杀
_add_fix(r'七茶', '七杀', '七茶→七杀(十神)')

# 比扇/比房 → 比肩
_add_fix(r'比扇', '比肩', '比扇→比肩(十神)')
_add_fix(r'比房', '比肩', '比房→比肩(十神)')

# 食种 → 食神
_add_fix(r'食种', '食神', '食种→食神(十神)')

# 吴 → 戊（后接十神 = 天干戊）
_add_fix(r'吴(?=[正偏食伤比劫][官杀印财神肩])', '戊', '吴→戊(天干+十神)')

# 柔/奖/灸 → 癸（后接十神 = 天干癸）
_add_fix(r'[柔奖灸](?=比肩|七杀|正财|偏财|正印|偏印|食神|伤官|劫财)', '癸', '柔/奖/灸→癸(天干+十神)')

# 幸 → 辛（后接十神 = 天干辛）
_add_fix(r'幸(?=比肩|七杀|正财|偏财|正印|偏印|食神|伤官|劫财)', '辛', '幸→辛(天干+十神)')

# 纳音
_add_fix(r'石幅木', '石榴木', '石幅木→石榴木(纳音)')
_add_fix(r'整上土', '壁上土', '整上土→壁上土(纳音)')

# 写财 → 偏财（在特定上下文）
_add_fix(r'(?<=[辛庚癸壬甲乙丙丁戊己])写财', r'\g<0>偏财', '写财→偏财')  # This won't work well, skip

# 烫正印 → 戊正印
_add_fix(r'烫正印', '戊正印', '烫正印→戊正印')

# 买正印 → 癸正印 (猜测)
# Skip - too uncertain

# --- 地支混淆纠错 ---

# 卵 → 卯
_add_fix(r'卵(?=酉|月)', '卯', '卵→卯(地支)')
_add_fix(r'(子午)卵(酉)', r'\1卯\2', '子午卵酉→子午卯酉')

# 已 → 巳（已时 = 巳时, 地支）
_add_fix(r'已(?=时)', '巳', '已→巳(地支: 巳时)')
_add_fix(r'寅申已亥', '寅申巳亥', '寅申已亥→寅申巳亥(地支)')
_add_fix(r'申已', '申巳', '申已→申巳(地支)')
_add_fix(r'已(?=、亥)', '巳', '已→巳(地支: 已、亥→巳、亥)')
_add_fix(r'已(?=、)', '巳', '已→巳(地支: 已、→巳、)')
# 已 → 己（已 后面接十神 = 天干己）
_add_fix(r'已(?=食神|偏财|正印|七杀|正财|偏印|伤官|比肩|劫财|土|动财|劫财|正官)', '己', '已→己(天干)')

# 成 → 戌（成时 = 戌时, 成土 = 戌土, 地支）
_add_fix(r'成(?=时)', '戌', '成→戌(地支: 戌时)')
_add_fix(r'成(?=土)', '戌', '成→戌(地支: 戌土)')
_add_fix(r'辰成(?=丑)', '辰戌', '辰成→辰戌(地支)')
_add_fix(r'辰成丑未', '辰戌丑未', '辰成丑未→辰戌丑未(地支)')
_add_fix(r'(?<=丑)成(?=未)', '戌', '成→戌(地支: 丑成未→丑戌未)')

# --- 节气/历法纠错 ---

_add_fix(r'小器', '小暑', '小器→小暑(节气)')
_add_fix(r'小暴', '小暑', '小暴→小暑(节气)')
_add_fix(r'小晏', '小暑', '小晏→小暑(节气)')
_add_fix(r'白辆', '白露', '白辆→白露(节气)')
_add_fix(r'惊垫', '惊蛰', '惊垫→惊蛰(节气)')
_add_fix(r'农压', '农历', '农压→农历')
_add_fix(r'小送', '小运', '小送→小运(命理)')

# --- 命理术语纠错 ---

_add_fix(r'暗台', '暗合', '暗台→暗合(命理)')
_add_fix(r'伏寅', '伏吟', '伏寅→伏吟(命理)')
_add_fix(r'侄买侄卖', '倒买倒卖', '侄买侄卖→倒买倒卖')
_add_fix(r'导卖导卖', '倒买倒卖', '导卖导卖→倒买倒卖')
_add_fix(r'代表侄', '代表倒买倒卖', '代表侄→代表倒买倒卖')
_add_fix(r'临富', '临官', '临富→临官(十二长生)')
_add_fix(r'乙印(?=\s|$)', '乙卯', '乙印→乙卯(干支)')
_add_fix(r'成宝', '戊寅', '成宝→戊寅(干支)')
_add_fix(r'禄纤桃花', '禄桃花', '禄纤桃花→禄桃花(命理)')
_add_fix(r'换像', '换象', '换像→换象(命理)')

# --- 杂项 OCR 纠错 ---
_add_fix(r'羊古', '辛苦', '羊古→辛苦(OCR误识)')
_add_fix(r'产重负债', '严重负债', '产重→严重(OCR误识)')
_add_fix(r'第士种', '第十种', '第士种→第十种(士→十)')
_add_fix(r'第士个', '第十个', '第士个→第十个(士→十)')
_add_fix(r'儿种', '第九种', '儿种→第九种(儿→九,缺第)')
_add_fix(r'复印', '伏吟', '复印→伏吟(命理)')
_add_fix(r'复印之象', '伏吟之象', '复印之象→伏吟之象(命理)')
_add_fix(r'动多', '劫多', '动多→劫多(十神)')
_add_fix(r'比动多', '比劫多', '比动多→比劫多(十神)')
_add_fix(r'穿绝财', '穿绝财', '穿绝财→穿绝财(命理)')
_add_fix(r'一牙绝星', '一穿绝星', '一牙绝星→一穿绝星(命理)')
_add_fix(r'石灯', '财星', '石灯→财星(命理)')
_add_fix(r'为喜伸', '为喜神', '为喜伸→为喜神(十神)')
_add_fix(r'总伸', '忌神', '总伸→忌神(十神)')
_add_fix(r'吸灯', '忌神', '吸灯→忌神(十神)')
_add_fix(r'懒到钱', '赚到钱', '懒→赚(OCR误识)')
_add_fix(r'收购', '破财', '收购→破财(命理上下文)')
_add_fix(r'抗膏', '抗高', '抗膏→抗高(OCR误识)')
_add_fix(r'捷正印', '戊正印', '捷→戊(天干)')
_add_fix(r'滨印', '偏印', '滨→偏(十神)')
_add_fix(r'妥偏印', '戊偏印', '妥→戊(天干)')
_add_fix(r'成信财', '戊正财', '成信财→戊正财(天干)')
_add_fix(r'唐辰', '庚辰', '唐→庚(天干)')
_add_fix(r'笑五子', '癸巳子', '笑五子→癸巳子(干支)')
_add_fix(r'庚成', '庚戌', '庚成→庚戌(地支)')
_add_fix(r'丁已', '丁巳', '丁已→丁巳(地支)')
_add_fix(r'己印', '己巳', '己印→己巳(地支)')
_add_fix(r'壬寅辛丑', '壬寅辛丑', '壬寅辛丑→壬寅辛丑(干支)')
_add_fix(r'手劫材', '辛劫财', '手劫材→辛劫财(天干)')
_add_fix(r'千劫材', '辛劫财', '千劫材→辛劫财(天干)')
_add_fix(r'窗印', '辛印', '窗→辛(天干)')
_add_fix(r'惠，正印', '癸正印', '惠，正印→癸正印(天干)')
_add_fix(r'审下印', '辛偏印', '审下印→辛偏印(天干)')
_add_fix(r'信财', '偏财', '信→偏(十神)')
_add_fix(r'贝(?=出生|一九)', '见', '贝→见(上下文)')
_add_fix(r'男(?=八字|穿|刑)', '见', '男→见(上下文)')
_add_fix(r'白(?=第五种|丑|亥)', '', '白→(冗余)')
_add_fix(r'购星', '财星', '购→财(命理)')
_add_fix(r'问的', '忌的', '问→忌(十神)')

# --- v4.8 黄底排盘残留修复（2026-08-11）---
# 十神 OCR 误识归一（配合 is_chart_token 变体词，把排盘残留分离出板书）
_add_fix(r'比眉', '比肩', '比眉→比肩(十神)')
_add_fix(r'侧财', '偏财', '侧财→偏财(十神)')
_add_fix(r'被人骤', '被人骗', '被人骤→被人骗(OCR误识)')
_add_fix(r'被人驱', '被人骗', '被人驱→被人骗(OCR误识)')


# 固定搭配保护（#28）：命中完整词条时跳过字符级改写，避免拆坏合法搭配
GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ziping_glossary.json")
_FIXED_PHRASES_RE = None


def _load_fixed_phrases_re():
    """惰性加载 ziping_glossary.json 的 fixed_phrases，构建最长优先匹配正则。

    最长优先：避免"午戌三合"抢先吞掉"寅午戌三合"；只保护规范写法，
    OCR 变体（如 戌→成）不命中，仍由下方字级规则归一。
    """
    global _FIXED_PHRASES_RE
    if _FIXED_PHRASES_RE is not None:
        return _FIXED_PHRASES_RE
    try:
        with open(GLOSSARY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        phrases = [p for p in (data.get("fixed_phrases") or [])
                   if isinstance(p, str) and p]
        phrases = sorted(set(phrases), key=len, reverse=True)
        _FIXED_PHRASES_RE = re.compile("|".join(map(re.escape, phrases))) if phrases else None
    except Exception:
        _FIXED_PHRASES_RE = None
    return _FIXED_PHRASES_RE


def fix_ocr_chars(text):
    """
    对 OCR 文本应用上下文感知的字符纠错。
    按规则列表顺序应用，每条规则只修改匹配的部分。

    固定搭配保护（#28）：完整命中 fixed_phrases 的合法搭配先掩码为
    PUA 占位符，纠错全部应用后再还原——字级规则不会拆散完整词条。
    """
    phrases = _load_fixed_phrases_re()
    if phrases is not None:
        placeholder = {}          # PUA 占位符 -> 原固定搭配
        counter = [0xE000]

        def _mask(m):
            ch = chr(counter[0])
            counter[0] += 1
            placeholder[ch] = m.group(0)
            return ch

        text = phrases.sub(_mask, text)
        for pattern, replacement, desc in OCR_CHAR_FIXES:
            text = pattern.sub(replacement, text)
        for ch, ph in placeholder.items():
            text = text.replace(ch, ph)
        return text
    for pattern, replacement, desc in OCR_CHAR_FIXES:
        text = pattern.sub(replacement, text)
    return text


# ============================================================
# 坐标感知的行合并
# ============================================================
def create_ocr_engine():
    """创建并返回全局 OCR 引擎（复用避免重复加载模型）"""
    from ocr_v6 import RapidOCR
    return RapidOCR()


# ============================================================
# 案例八字图表区域检测（按背景色分离板书与案例）
# ============================================================

def detect_case_chart_mask(image_path):
    """
    检测画面中黄底/米底投影的案例八字图表区域。
    讲师在讲解案例时会在白板上投影出带有黄色/米色背景的八字排盘，
    该区域与板书（白底黑字/红字）在颜色上可区分。
    返回二值 mask：255 表示案例图表区域，0 表示其他区域。
    """
    try:
        img_data = np.fromfile(image_path, dtype=np.uint8)
        img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
        if img is None:
            return None

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # 黄底/米底案例图表的 HSV 范围
        lower = np.array([15, 20, 80])
        upper = np.array([45, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)

        # 合并相近像素，形成连通区域
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        # 只保留面积适中的连通区域（案例图表，而非水印小图标）
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = img.shape[:2]
        img_area = h * w
        min_area = img_area * 0.01   # 至少占画面 1%
        max_area = img_area * 0.80   # 最多占画面 80%

        case_mask = np.zeros((h, w), dtype=np.uint8)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if min_area < area < max_area:
                cv2.drawContours(case_mask, [cnt], -1, 255, -1)

        return case_mask
    except Exception:
        return None


def box_mask_overlap(box, mask):
    """
    计算 OCR 文本框与 mask 的重叠比例。
    box: RapidOCR 返回的 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    返回值：0.0 ~ 1.0，表示文本框面积中有多少比例落在 mask 区域内。
    """
    if mask is None:
        return 0.0

    h, w = mask.shape[:2]
    pts = np.array(box, dtype=np.int32)

    # 构建文本框 mask
    box_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(box_mask, [pts], 255)

    # 交集面积
    inter = cv2.bitwise_and(box_mask, mask)
    inter_area = np.sum(inter > 0)
    box_area = np.sum(box_mask > 0)

    return inter_area / box_area if box_area > 0 else 0.0


def merge_items_into_lines(items):
    """将 OCR 子项按 Y 坐标分组、X 坐标排序，合并为文本行。"""
    if not items:
        return []

    items.sort(key=lambda i: i["y"])
    rows = []
    current_row = [items[0]]
    row_y = items[0]["y"]

    for item in items[1:]:
        if abs(item["y"] - row_y) < 25:
            current_row.append(item)
        else:
            rows.append(current_row)
            current_row = [item]
            row_y = item["y"]
    rows.append(current_row)

    merged_lines = []
    for row in rows:
        row.sort(key=lambda i: i["x"])
        merged_text = " ".join(item["text"] for item in row)
        avg_conf = sum(item["confidence"] for item in row) / len(row)
        merged_lines.append({
            "text": merged_text,
            "confidence": round(avg_conf, 3),
            "y": row[0]["y"],
        })

    return merged_lines


def fix_line_breaks(lines):
    """
    修复 OCR 行合并时被错误拆断的文本行。
    
    RapidOCR 有时会把一行末尾的字识别为独立一行（如"长"和"命"被分成两行）。
    本函数基于文本语义和 Y 坐标把断行重新接回，同时避免把真正不同行的内容合并。
    
    合并条件（需同时满足）：
      1. 两行 Y 坐标接近（< 20px），说明很可能是同一物理行
      2. 下一行不是新的编号/主题开头
      3. 上一行明显不完整：长度<=2、有未闭合括号、或以"、"结尾且较短
    """
    if not lines:
        return lines

    # 新编号/主题行的开头模式
    new_line_patterns = [
        r'^第[一二三四五六七八九十百千]+[种个类章]',  # 第一种、第十四种
        r'^内容[一二三四五六七八九十百千]+、',         # 内容一、
        r'^\d+[、.．]',                                # 1、2.
        r'^[（(]',                                     # （小姐、鸭子...）
    ]

    fixed = [lines[0]]
    for line in lines[1:]:
        prev = fixed[-1]
        prev_text = prev["text"].strip()
        curr_text = line["text"].strip()

        # 当前行是否是新编号/主题开头？
        is_new_line = any(re.match(p, curr_text) for p in new_line_patterns)

        # 两行 Y 坐标是否接近？同一物理行内不同字的基线差异通常 < 35px
        y_close = abs(line["y"] - prev["y"]) < 35

        # 上一行是否明显不完整？
        is_fragment = False
        # 1. 极短且不是编号/主题
        if len(prev_text) <= 2 and not any(re.match(p, prev_text) for p in new_line_patterns):
            is_fragment = True
        # 2. 有未闭合的左括号
        if prev_text.count('（') > prev_text.count('）') or \
           prev_text.count('(') > prev_text.count(')'):
            is_fragment = True
        # 3. 以顿号结尾且较短（列举项被截断）
        if prev_text.endswith('、') and len(prev_text) < 12:
            is_fragment = True

        if y_close and not is_new_line and is_fragment:
            # 合并到前一行
            merged_text = prev_text + curr_text
            fixed[-1] = {
                "text": merged_text,
                "confidence": round((prev["confidence"] + line["confidence"]) / 2, 3),
                "y": prev["y"],
            }
        else:
            fixed.append(line)

    return fixed

# 颜色检测是第一层防线（HSV 黄底区域），但存在局限：
#   - 投影可能非纯黄色（灯光偏色）
#   - OCR 文本框可能跨越板书和案例两个区域
# 文本级检测是第二层防线：通过识别八字排盘的文本模式
#   [天干/地支][十神] 连续组合（如"乙正官 丁正印 乙正官 吴正财"）
#   将混入板书内容的案例八字数据分离出来。

# 天干（含 OCR 常见误识别变体）
STEM_CHARS_EXT = set("甲乙丙丁戊己庚辛壬癸奏假夹柄成吴康王关葵笑已一")
# 地支（含 OCR 常见误识别变体）
BRANCH_CHARS_EXT = set("子丑寅卯辰巳午未申酉戌亥卵已")
# 五行（排盘中可能出现，如"甲木正官"）
ELEMENT_CHARS = set("木火土金水")
# 所有可用于八字排盘前缀的字符
ALL_CHART_PREFIX_CHARS = STEM_CHARS_EXT | BRANCH_CHARS_EXT | ELEMENT_CHARS

# 十神完整列表（含 OCR 常见误识别变体）
TEN_GODS_ALL = [
    "正财", "偏财", "七杀", "正官", "偏官", "正印", "偏印",
    "食神", "伤官", "比肩", "劫财", "食伤",
    # OCR 变体
    "动财", "停财", "馆财", "正馆", "偏馆", "馆印", "停印",
    "伤国", "伤馆", "食商",
    # v4.8 黄底排盘残留变体（比眉=比肩、侧财=偏财、度实印/实印=正印、功财=劫财、信印=正印 等）
    "比眉", "顶比眉", "庚比眉", "顶比肩", "侧财", "丙侧财", "度实印", "实印",
    "信印", "乙信印", "正印门", "功财", "国财",
]
# 按长度降序排列，优先匹配长词（避免"正财"截断"正财"之类的问题）
TEN_GODS_SORTED = sorted(set(TEN_GODS_ALL), key=len, reverse=True)
# 十神集合（用于独立十神词的快速查找）
TEN_GODS_SET = set(TEN_GODS_ALL)

# 排盘表头/标记词（独立出现在排盘区域，板书内容中不会以独立词形式出现）
CHART_HEADER_WORDS = {"日干", "日支", "大运", "小运", "流年", "命宫", "身宫", "胎元"}

# 规范十神（白板正文也常见，如"食伤""比肩"，不能仅凭此判排盘）
CORE_TEN_GODS = {"正财", "偏财", "七杀", "正官", "偏官", "正印", "偏印",
                 "食神", "伤官", "比肩", "劫财", "食伤"}
# 仅 OCR 变体/排盘专属十神词（v4.8：白板不会单独出现"比眉/侧财/功财"等）
TENTATIVE_CHART_WORDS = set(TEN_GODS_ALL) - CORE_TEN_GODS


def is_ganzhi_run(word):
    """
    判断一个"词"是否是连续干支配对串（v4.8 新增）。
    要求按两位一组严格 [天干][地支] 交替（含 OCR 变体字）：
      庚辰 己卯 → True；己亥戊戌 → True
      甲乙丙丁 / 甲庚壬丙寅申巳亥（天干地支列表）→ False（乙庚丙申…不满足配对）
    """
    if len(word) < 2 or len(word) % 2 != 0:
        return False
    for i in range(0, len(word), 2):
        if word[i] not in STEM_CHARS_EXT or word[i + 1] not in BRANCH_CHARS_EXT:
            return False
    return True


def is_chart_attached_word(word):
    """排盘附属词（v4.8 新增）：出生时间/出生于/实岁/农历年份/小运大运后干支串。"""
    if word.startswith("出生时间") or word.startswith("出生于"):
        return True
    if re.match(r'^实岁[:：]?\d', word):
        return True
    if re.match(r'^农历[:：]\s*\d', word):
        return True
    if re.match(r'^(小运|大运|流年|命宫|身宫|胎元)[:：]?', word):
        return True
    return False


def is_chart_token(word):
    """
    判断一个"词"是否是八字排盘中的 token：
      - [干支][十神] 组合（如 乙正官、吴正财）
      - 独立十神名（如 七杀、正官）
      - 排盘表头词（如 日干、大运）
      - 连续干支配对串（庚辰 己卯，v4.8）
      - 排盘附属词（出生时间/实岁/农历年份/小运，v4.8）
    """
    if is_bazi_chart_word(word):
        return True
    if word in TEN_GODS_SET:
        return True
    if word in CHART_HEADER_WORDS:
        return True
    if is_ganzhi_run(word):
        return True
    if is_chart_attached_word(word):
        return True
    return False


def strong_chart_signal(text):
    """v4.8：内容级强排盘信号——用于行合并前把排盘框分流到 case_lines。

    只认"白板正文不会单独出现"的强信号：干支组合/干支串/排盘附属/OCR 变体十神词。
    独立规范十神名（食伤/比肩/正财…白板正文常见）不参与，避免把板书字框误移走。
    """
    w = text.strip()
    if not w:
        return False
    if is_bazi_chart_word(w):
        return True
    if is_ganzhi_run(w):
        return True
    if is_chart_attached_word(w):
        return True
    if w in TENTATIVE_CHART_WORDS:
        return True
    return False


def is_bazi_chart_word(word):
    """
    判断一个"词"是否是八字排盘的 [干支][十神] 组合。
    例如：乙正官、丁正印、吴正财（吴=戊的OCR误识）、奏正财（奏=甲的OCR误识）
    """
    if len(word) < 3:
        return False
    for god in TEN_GODS_SORTED:
        if word.endswith(god):
            prefix = word[:-len(god)]
            if 1 <= len(prefix) <= 3 and all(c in ALL_CHART_PREFIX_CHARS for c in prefix):
                return True
    return False


def separate_bazi_chart_from_line(line_text):
    """
    从一行文本中分离出八字排盘数据和板书内容。
    返回 (board_part, case_part)。
    
    示例：
      "第二种、体力赚 乙正官 丁正印 乙正官 吴正财"
      → ("第二种、体力赚", "乙正官 丁正印 乙正官 吴正财")
      
      "奏正财 乙正官 吴正财 辛伤国"
      → ("", "奏正财 乙正官 吴正财 辛伤国")
      
      "1、比劫多而财 奏正财 乙正官 吴正财 辛伤国"
      → ("1、比劫多而财", "奏正财 乙正官 吴正财 辛伤国")
      
      "3、食伤穿制财官 七杀 七杀 劫财"
      → ("3、食伤穿制财官", "七杀 七杀 劫财")
    """
    # v4.8 整行排盘附属（出生/实岁/农历年份）：直接整行移走。
    # 注意 "3、用 出生于…" 这类混合行不以这些开头，走下方逐词拆分。
    if re.match(r'^(出生时间|出生于|实岁[:：]|农历[:：]\s*\d)', line_text):
        return "", line_text
    words = line_text.split()
    chart_words = []
    board_words = []
    
    for word in words:
        if is_chart_token(word):
            chart_words.append(word)
        else:
            board_words.append(word)
    
    # 规则1: 2+ 排盘词 → 全部分离
    if len(chart_words) >= 2:
        board_part = " ".join(board_words) if board_words else ""
        case_part = " ".join(chart_words) if chart_words else ""
        return board_part, case_part
    
    # 规则2: 整行只有一个排盘词且无板书内容 → 移到案例
    # 例如 "辛食神"、"七杀"、"日干" 独占一行
    if len(chart_words) == 1 and len(board_words) == 0:
        return "", line_text
    
    # 规则3: 行尾有1个排盘词，前面是完整板书内容（带编号前缀）→ 分离
    # 例如 "第四种、骗子 癸偏财" → "第四种、骗子" + "癸偏财"
    if len(chart_words) == 1 and len(board_words) >= 1:
        # 排盘词必须在行尾
        if words[-1] == chart_words[0]:
            board_part = " ".join(board_words)
            # 板书部分必须有编号前缀（确保是完整知识点，而非半句）
            if re.match(r'^第[一二三四五六七八九十\d]+[种类步]', board_part) or \
               re.match(r'^\d+、', board_part) or \
               re.match(r'^内容[一二三四五六七八九十\d]', board_part):
                return board_part, chart_words[0]

    # 规则4（v4.8）: 单个排盘附属词混在行中（出生时间/出生于/实岁/农历年份/小运），
    # 即使板书部分无编号前缀也分离——排盘附属信息绝不属于板书正文。
    # 例："富，一般为带团队 出生时间：阳历1901年6月2日23时0分" → 挖出附属词归 case
    if len(chart_words) == 1 and is_chart_attached_word(chart_words[0]):
        idx = words.index(chart_words[0])
        board_part = " ".join(words[:idx] + words[idx + 1:])
        return board_part, chart_words[0]

    # 不满足以上规则，视为板书内容
    return line_text, ""


def post_separate_board_case(segments):
    """
    后处理：对所有段落的 lines 做文本级八字排盘检测，
    将混入板书内容的案例八字数据分离到 case_lines。
    
    这是颜色检测的补充层：即使 HSV 颜色检测未能分离（投影非黄色、
    或 OCR 框跨越两个区域），文本模式检测仍能识别并纠正。
    """
    moved_count = 0
    split_count = 0
    
    for seg in segments:
        board_lines = seg.get("lines", [])
        case_lines = seg.get("case_lines", [])
        new_board = []
        
        for line in board_lines:
            text = line["text"]
            board_part, case_part = separate_bazi_chart_from_line(text)
            
            if case_part and not board_part:
                # 整行都是八字排盘 → 移到 case_lines
                case_lines.append({"text": case_part, "confidence": line.get("confidence", 0)})
                moved_count += 1
            elif case_part and board_part:
                # 混合行 → 分离：板书部分保留，八字部分移走
                new_board.append({"text": board_part, "confidence": line.get("confidence", 0)})
                case_lines.append({"text": case_part, "confidence": line.get("confidence", 0)})
                split_count += 1
            else:
                # 纯板书内容，原样保留
                new_board.append(line)
        
        seg["lines"] = new_board
        seg["case_lines"] = case_lines
    
    return moved_count, split_count


# ============================================================
# 坐标感知的行合并（板书内容 + 案例八字内容 分离）
# ============================================================

def re_ocr_with_boxes(keyframe_path, engine):
    """
    对单个关键帧重新 OCR，保留 box 坐标，并按背景色分离：
      - 板书内容（白底黑字/红字）
      - 案例八字内容（黄底/米底投影图表）
    返回 (board_lines, case_lines)
    """
    raw_result, _ = engine(keyframe_path)
    case_mask = detect_case_chart_mask(keyframe_path)

    if not raw_result:
        return [], []

    board_items = []
    case_items = []

    for box, text, score in raw_result:
        text = text.strip() if text else ""
        score = float(score) if score else 0.0

        # 合并前先过滤噪声（关键改进：防止水印混入内容行）
        if len(text) < 1 or score <= 0.4:
            continue
        if is_noise(text):
            continue

        # 先做字符纠错
        text = fix_ocr_chars(text)

        # 纠错后再次检查是否变成了噪声
        if is_noise(text):
            continue

        # box: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        y_center = (box[0][1] + box[2][1]) / 2
        x_center = (box[0][0] + box[2][0]) / 2
        item = {
            "text": text,
            "confidence": round(score, 3),
            "x": x_center,
            "y": y_center,
            "box": [[int(p[0]), int(p[1])] for p in box]
        }

        # 按与案例图表 mask 的重叠度分类（v4.8：再叠加内容级强排盘预判——
        # 白底/浅底排盘 HSV 漏检时也在行合并前分流，避免与白板行拼接）
        overlap = box_mask_overlap(box, case_mask)
        if overlap > 0.5 or strong_chart_signal(text):
            case_items.append(item)
        else:
            board_items.append(item)

    board_lines = merge_items_into_lines(board_items)
    case_lines = merge_items_into_lines(case_items)

    # 修复被错误拆断的行（RapidOCR 有时会把一行末尾的字识别为独立一行）
    board_lines = fix_line_breaks(board_lines)
    case_lines = fix_line_breaks(case_lines)

    return board_lines, case_lines


# ============================================================
# 段内去重
# ============================================================
def segment_structural_hash(lines):
    """计算段落的结构哈希：只看行数和每行长度分布"""
    if not lines:
        return ""
    lengths = [len(l["text"]) for l in lines]
    return f"{len(lines)}:{min(lengths)}:{max(lengths)}"


def deduplicate_segments(segments):
    """
    基于结构相似度的段落去重：
    如果两个段落的行数相同且每行长度分布相似（>70%），视为重复
    """
    if len(segments) <= 1:
        return segments

    deduped = [segments[0]]
    for seg in segments[1:]:
        is_dup = False
        cur_hash = segment_structural_hash(seg["lines"])
        cur_texts = set(l["text"] for l in seg["lines"])

        for prev in deduped[-3:]:  # 只和最近3段比较
            prev_texts = set(l["text"] for l in prev["lines"])
            if not cur_texts or not prev_texts:
                continue
            overlap = len(cur_texts & prev_texts) / max(len(cur_texts | prev_texts), 1)
            if overlap > 0.6:
                is_dup = True
                break

        if not is_dup:
            deduped.append(seg)
        else:
            # 保留时间跨度更长的版本
            prev = deduped[-1]
            prev["end_seconds"] = max(prev.get("end_seconds", 0), seg.get("end_seconds", 0))
            prev["end"] = max(prev.get("end", ""), seg.get("end", ""))
            # 保留文本行更多的版本
            if len(seg.get("lines", [])) > len(prev.get("lines", [])):
                prev["lines"] = seg["lines"]

    return deduped


# ============================================================
# 主流程
# ============================================================
def improve(input_json, output_json=None, frames_dir=None):
    """
    读取 whiteboard_data.json，对每个关键帧重新 OCR（带坐标），
    然后合并同行文字、去噪、去重、字符纠错，输出优化后的 JSON。
    """
    with open(input_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    if output_json is None:
        output_json = input_json.replace(".json", "_improved.json")

    # 推断 frames 目录
    if frames_dir is None:
        base_dir = os.path.dirname(input_json)
        frames_dir = os.path.join(base_dir, "frames")

    print(f"读取 {len(data)} 段板书数据")
    print(f"帧目录: {frames_dir}")
    print(f"初始化 OCR 引擎...")
    engine = create_ocr_engine()

    # 统计字符纠错次数
    fix_count = 0

    print(f"重新OCR并合并同行文字...")
    new_data = []
    total = len(data)
    for idx, seg in enumerate(data):
        frame_name = seg.get("frame", "")
        frame_path = os.path.join(frames_dir, frame_name)

        if not os.path.exists(frame_path):
            print(f"  [{idx+1}/{total}] 跳过 (帧不存在): {frame_name}")
            # 保留原始数据，但做字符纠错
            seg_copy = dict(seg)
            fixed_lines = []
            for l in seg["lines"]:
                if is_noise(l["text"]):
                    continue
                fixed = fix_ocr_chars(l["text"])
                if fixed != l["text"]:
                    fix_count += 1
                fixed_lines.append({"text": fixed, "confidence": l.get("confidence", 0), "y": l.get("y", 0)})
            seg_copy["lines"] = fixed_lines
            seg_copy.setdefault("case_lines", [])
            new_data.append(seg_copy)
            continue

        # 重新OCR带坐标（已在内部做了去噪+字符纠错+板书/案例分离）
        try:
            board_lines, case_lines = re_ocr_with_boxes(frame_path, engine)
        except Exception as e:
            print(f"  [{idx+1}/{total}] OCR失败 {frame_name}: {e}")
            seg_copy = dict(seg)
            fixed_lines = []
            for l in seg["lines"]:
                if is_noise(l["text"]):
                    continue
                fixed = fix_ocr_chars(l["text"])
                if fixed != l["text"]:
                    fix_count += 1
                fixed_lines.append({"text": fixed, "confidence": l.get("confidence", 0), "y": l.get("y", 0)})
            seg_copy["lines"] = fixed_lines
            seg_copy.setdefault("case_lines", [])
            new_data.append(seg_copy)
            continue

        if not board_lines and not case_lines:
            print(f"  [{idx+1}/{total}] 无有效文字: {frame_name}")
            new_data.append(dict(seg, lines=[], case_lines=[]))
            continue

        # 合并后再次去噪 + 字符纠错（板书内容）
        clean_lines = []
        for l in board_lines:
            text = l["text"]
            # 字符纠错（合并后可能有新的上下文）
            fixed = fix_ocr_chars(text)
            if fixed != text:
                fix_count += 1
            # 去噪
            if is_noise(fixed):
                continue
            clean_lines.append({"text": fixed, "confidence": l["confidence"], "y": l.get("y", 0)})

        # 案例八字内容也做字符纠错，但不过度去噪（保留专业术语）
        clean_case_lines = []
        for l in case_lines:
            text = l["text"]
            fixed = fix_ocr_chars(text)
            if fixed != text:
                fix_count += 1
            # 案例图表里的水印已在前面过滤，这里只过滤明显噪声
            if is_noise(fixed):
                continue
            clean_case_lines.append({"text": fixed, "confidence": l["confidence"], "y": l.get("y", 0)})

        if clean_lines or clean_case_lines:
            preview = " | ".join(l["text"][:40] for l in clean_lines[:3])
            tag = " [案例]" if seg.get("is_example") else ""
            print(f"  [{idx+1}/{total}] {frame_name} @ {seg['start']}:{tag} {preview} ({len(clean_lines)} 板书行, {len(clean_case_lines)} 案例行)")
        else:
            print(f"  [{idx+1}/{total}] {frame_name} @ {seg['start']}: (无有效文字)")

        new_seg = dict(seg)
        new_seg["lines"] = clean_lines
        new_seg["case_lines"] = clean_case_lines
        new_data.append(new_seg)

    # 段级去重
    print(f"\n段级去重...")
    new_data = deduplicate_segments(new_data)
    print(f"  去重后: {len(new_data)} 段")
    print(f"  字符纠错: {fix_count} 处")

    # 文本级案例八字分离（补充颜色检测的不足）
    print(f"\n文本级案例八字分离...")
    moved, split_ = post_separate_board_case(new_data)
    print(f"  移动 {moved} 行到案例, 拆分 {split_} 行混合内容")

    # is_example 定案：case_lines（HSV黄底+干支十神分离）非空，或 extract 强信号命中。
    # extract 阶段的关键词命中（含十神词）会把教学板书帧误判为案例，这里覆盖重判。
    # 经 3-3 验证：真案例 case_lines>0 或 强信号（坤造/空亡/长生等）；教学板书帧两者皆无。
    for s in new_data:
        s["is_example"] = is_true_example(s)

    # 输出
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
    print(f"\n优化后 JSON: {output_json}")
    print(f"共 {len(new_data)} 段，案例 {sum(1 for s in new_data if s['is_example'])} 段")

    return output_json


# ============================================================
# 案例重判工具（修正已生成的数据，无需重跑 OCR）
# ============================================================
# ============================================================
# 案例定案：extract 强信号 + case_lines 双重判据
# ============================================================
# extract 阶段的关键词命中过于宽松（含十神词），会把教学板书帧误判为案例。
# 这里只保留"排盘专属、教学板书不出现"的强信号词，与 case_lines（黄底+干支十神分离）互补。
# 注意：年柱/月柱/日柱/时柱、十神词必须排除 —— 教学板书会出现"印星在时柱""食神制官"等。
STRONG_EXAMPLE_KEYWORDS = {
    "乾造", "坤造", "出生时间", "出生于", "空亡", "长生",
    "大运", "小运", "流年", "命宫", "身宫", "胎元", "排盘",
}


def is_true_example(seg):
    """真案例判定：case_lines（HSV黄底+干支十神分离）非空，或 extract 强信号命中。
    3-3 验证：真案例命中其一（13/13）；教学板书帧两者皆无（9/9）。"""
    if seg.get("case_lines"):
        return True
    strong = [h for h in seg.get("example_hits", []) if h in STRONG_EXAMPLE_KEYWORDS]
    return bool(strong)


def rejudge_examples(improved_json, examples_dir=None, rename_map_path=None, write_json=True):
    """
    以"case_lines（HSV黄底+干支十神分离）非空 或 extract 强信号命中"为真案例判据，
    重判各段的 is_example，并按 rename_map 全量对账清理截图：
      - 真案例集合 = 各段 is_true_example 且带 example_image
      - rename_map 中不在集合内的 key → 删除对应截图 + 移除条目
      - 覆盖 improve 去重后 example_image 丢失、extract 误抽教学帧等遗留问题

    解决 extract 阶段关键词命中（含十神词）把教学板书帧误判为案例的问题。
    参数:
      improved_json    : whiteboard_data_improved.json 路径（读写）
      examples_dir     : 案例截图目录（可空；非空则删除被误判段的截图）
      rename_map_path  : rename_map JSON 路径（可空；非空则删除误判条目并写回）
      write_json       : 是否把重判后的 is_example 写回 improved_json
    """
    with open(improved_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. 计算真案例集合（is_true_example 且带 example_image）
    true_images = set()
    for s in data:
        if is_true_example(s) and s.get("example_image"):
            true_images.add(s["example_image"])

    # 2. 加载 rename_map（example_XXX_MMSS.png -> 中文名.png）
    rename_map = {}
    if rename_map_path and os.path.exists(rename_map_path):
        with open(rename_map_path, "r", encoding="utf-8") as f:
            rename_map = json.load(f)

    # 3. 全量对账：移除不在真案例集合的条目 + 删除对应截图
    removed_keys = [img for img in rename_map if img not in true_images]
    if examples_dir:
        for img in removed_keys:
            target = os.path.join(examples_dir, rename_map[img])
            if os.path.exists(target):
                os.remove(target)
                print(f"  [删除] {img} -> {rename_map[img]}")
            else:
                print(f"  [跳过] 不存在: {target}")

    # 4. 更新 rename_map
    if rename_map_path and rename_map:
        for img in removed_keys:
            rename_map.pop(img, None)
        with open(rename_map_path, "w", encoding="utf-8") as f:
            json.dump(rename_map, f, ensure_ascii=False, indent=2)
        print(f"  rename_map 更新: {rename_map_path} ({len(removed_keys)} 条移除, 剩 {len(rename_map)} 条)")

    # 5. 重判 is_example 写回
    if write_json:
        for s in data:
            s["is_example"] = is_true_example(s)
        with open(improved_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  JSON 更新: {improved_json}")

    total = len(data)
    ex = len(true_images)
    print(f"  重判完成: 共 {total} 段, 真案例 {ex} 段, 剔除 {len(removed_keys)} 条")
    return removed_keys


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="板书OCR后处理优化 (v2: 含字符纠错)")
    parser.add_argument("input_json", help="原始 whiteboard_data.json")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 路径")
    parser.add_argument("--frames", "-f", default=None, help="帧图片目录")
    parser.add_argument("--rejudge", action="store_true",
                        help="案例重判模式：以 case_lines 为准重判 is_example，清理误判截图与 rename_map（输入为 improved JSON）")
    parser.add_argument("--examples", default=None, help="rejudge 模式：案例截图目录")
    parser.add_argument("--rename-map", default=None, help="rejudge 模式：rename_map JSON 路径")
    args = parser.parse_args()

    if args.rejudge:
        rejudge_examples(args.input_json, args.examples, getattr(args, "rename_map", None))
    else:
        improve(args.input_json, args.output, args.frames)
