"""
生成板书知识点解析报告（含主讲人口述案例分析）v2

改进：
1. 更好的案例去重（按阳历/农历日期合并）
2. 非重叠 ASR 窗口
3. 知识点过滤（只保留完整、有意义的行）
4. 板书文本后处理修复
"""
import json, os, re
from datetime import datetime
from collections import defaultdict

# ============================================================
# 路径配置（可用 --wb-dir / --asr-dir 覆盖，默认 3-1）
# ============================================================
def _parse_args():
    import argparse
    p = argparse.ArgumentParser(description="生成板书知识点解析报告（含ASR交叉引用）")
    p.add_argument("--wb-dir", default="D:/video-skill-output/课程目录名（按需设置）（3-1）/whiteboard")
    p.add_argument("--asr-dir", default="D:/video-skill-output/课程目录名（按需设置）（3-1）/asr_output")
    p.add_argument("--rename-map", help="RENAME_MAP JSON 路径，自动推导 SCREENSHOT_MAP")
    return p.parse_args()

_args = _parse_args()
WB_DIR = _args.wb_dir
ASR_DIR = _args.asr_dir
WB_IMPROVED = os.path.join(WB_DIR, "whiteboard_data_improved.json")
ASR_JSON = os.path.join(ASR_DIR, "transcript_segments.json")
OUTPUT_REPORT = os.path.join(WB_DIR, "板书知识点解析.md")
EXAMPLES_DIR = os.path.join(WB_DIR, "examples")


def _derive_screenshot_map(rename_map):
    """从 RENAME_MAP（example_XXX_MMSS.png -> 新名）自动推导 SCREENSHOT_MAP（时间 -> 新名）"""
    shot_map = {}
    for old_name, new_name in rename_map.items():
        m = re.search(r'_(\d{4})\.png$', old_name)
        if m:
            ts = f"{m.group(1)[:2]}:{m.group(1)[2:]}"
            shot_map[ts] = new_name
    return shot_map

# ============================================================
# 截图时间戳 -> 描述性名称映射（来自 rename_assets.py）
# ============================================================
SCREENSHOT_MAP = {
    "01:41": "贸易赚钱_八字见合合代表贸易_001.png",
    "01:51": "贸易赚钱_驿马流通之象_002.png",
    "02:01": "贸易赚钱_伏吟倒买倒卖_003.png",
    "02:11": "贸易赚钱_甲寅卖甲具进货转手营卖_004.png",
    "03:11": "开店赚钱_贸易伏吟倒买倒卖1982年生_001.png",
    "03:41": "偷窃抢劫_八字见穿刑暗合财星_001.png",
    "03:51": "偷窃抢劫_依赖父母因偷东西进去过1986年生_002.png",
    "04:01": "偷窃抢劫_阴湿丑土亥子水克坏火过度阴坏阳_003.png",
    "05:01": "肉体赚钱_禄半桃花小姐1996年生_001.png",
    "05:11": "肉体赚钱_食伤穿制财官用肉体搞男人女人_002.png",
    "05:31": "肉体赚钱_食伤乱合多个异性鸭子2000年生_003.png",
    "05:51": "肉体赚钱_KTV酒吧食伤乱合与多个异性1998年生_004.png",
    "06:21": "肉体赚钱_红寅墨骗刑辛代部960万1991年生_005.png",
    "06:31": "肉体赚钱_侵吞公款930万打赏女主播_006.png",
    "06:41": "肉体赚钱_禄桃花食伤乱合1991年生_007.png",
    "06:51": "肉体赚钱_食伤穿制财官偷窃抢劫并行_008.png",
    "07:11": "偏门赚钱_小姐改行美甲还找大哥1993年生_001.png",
    "08:01": "偏门赚钱_食伤旺导比肩刀极男壬1990年生_002.png",
    "08:31": "体力赚钱_比劫多财星弱辛苦严重负债1988年生_001.png",
    "08:41": "体力赚钱_八字不见食伤不爱动脑_002.png",
    "09:01": "体力赚钱_无食伤没脑子司机开老板车泡妞1956年生_003.png",
    "09:21": "体力赚钱_财多压身身弱财重富屋贫人_004.png",
    "09:51": "体力赚钱_财重禄弱身弱财重农村祖父1979年生_005.png",
    "10:41": "偏门赚钱_命中带劫财劫财为喜用者_003.png",
    "10:51": "偏门赚钱_穿绝财星财星为忌神赚到钱_004.png",
    "11:01": "偏门赚钱_做资金盘骗6000万跑路新加坡_005.png",
    "11:11": "偏门赚钱_官穿比劫穿别人才挣钱_006.png",
    "11:41": "偏门赚钱_日时禄刃与偏财同柱捞偏门_007.png",
    "12:41": "偏门玄学_地支辰戌丑未食伤库至少有一个_008.png",
    "13:01": "偏门玄学_八字天干透六丁六甲_009.png",
    "13:11": "偏门玄学_白龙王命例1937年生_010.png",
    "13:21": "偏门玄学_陈朗八字用印制食伤_011.png",
    "13:31": "偏门玄学_诸葛亮刘伯温命例_012.png",
    "13:41": "偏门玄学_陈朗八字劫财正印1937年生_013.png",
    "13:51": "偏门玄学_弦曲大师辛复印_014.png",
    "14:01": "黑社会赚钱_辰戌丑未多食伤库比劫库_001.png",
    "14:21": "黑社会赚钱_阳刃穿绝十神带小弟干坏事_002.png",
    "14:31": "黑社会赚钱_重庆黑社会大哥劫财带伤官_003.png",
    "14:41": "黑社会赚钱_阳刃穿子重庆黑社会_004.png",
    "14:51": "黑社会赚钱_黑社会老大取三个老婆负债半个亿_005.png",
    "15:01": "黑社会赚钱_财星与阳刃同柱做事很绝_006.png",
    "15:11": "黑社会赚钱_重庆正宗黑社会老大1972年生_007.png",
    "15:21": "黑社会赚钱_带劫财辰戌丑未阴暗不可告人_008.png",
    "15:31": "黑社会赚钱_劫财伤官遇财官不主牢狱惹官司_009.png",
    "15:41": "黑社会赚钱_高利贷收保护费_010.png",
    "15:51": "黑社会赚钱_劫财三官欲财官惹官非_011.png",
    "16:01": "黑社会赚钱_劫财伤官遇财官大运有油黏合_012.png",
    "16:11": "黑社会赚钱_十五种取财方式全讲完总结_013.png",
}

def get_screenshots_for_case(start_sec, end_sec, max_shots=3):
    """获取案例时间范围内的截图文件名（去重连续同内容 + 限量，避免冗余）"""
    result = []
    for ts_str, filename in sorted(SCREENSHOT_MAP.items()):
        ts_sec = time_to_sec(ts_str)
        if ts_sec >= start_sec - 5 and ts_sec < end_sec:
            desc = screenshot_desc(filename)
            # 跳过描述相同的连续截图（同一张图的不同时刻）
            if result and desc == result[-1].get("desc"):
                continue
            result.append({"timestamp": ts_str, "filename": filename, "desc": desc})
    return result[:max_shots]

def screenshot_desc(filename):
    """从截图文件名提取描述部分"""
    parts = filename.replace(".png", "").split("_")
    if len(parts) >= 3:
        return "_".join(parts[1:-1])
    return filename.replace(".png", "")

def screenshot_category(filename):
    """从截图文件名提取类别（如'体力赚钱'）"""
    parts = filename.replace(".png", "").split("_")
    return parts[0] if parts else ""

def get_screenshots_for_topic(topic, knowledge_lines=None):
    """根据知识点主题获取相关案例截图"""
    # 从主题中提取类别关键词
    categories = []
    
    if "体力赚钱" in topic:
        categories.append("体力赚钱")
    if "肉体赚钱" in topic:
        categories.append("肉体赚钱")
    if "贸易赚钱" in topic:
        categories.extend(["贸易赚钱", "开店赚钱"])
    if "偷窃抢劫" in topic:
        categories.append("偷窃抢劫")
    if "偏门赚钱" in topic:
        categories.append("偏门赚钱")
    if "黑社会赚钱" in topic:
        categories.append("黑社会赚钱")
    if "老板赚钱" in topic:
        categories.append("老板赚钱")
    if "骗子赚钱" in topic:
        categories.append("骗子赚钱")
    if "开店赚钱" in topic:
        categories.append("开店赚钱")
    if "权力赚钱" in topic:
        categories.append("权力赚钱")
    if "投资" in topic or "脑袋发昏" in topic:
        categories.append("投资脑袋发昏")

    # 对于没有明确类别的主题（如"第十五种"），根据知识点内容推断
    if not categories and knowledge_lines:
        combined = " ".join(knowledge_lines)
        if any(kw in combined for kw in ["辰戌丑未", "羊刃穿绝", "财星与羊刃", "阴暗", "不可告人", "高利贷", "保护费", "劫财伤官", "官非", "牢狱", "带小弟", "黑社会"]):
            categories.append("黑社会赚钱")
        if any(kw in combined for kw in ["六丁六甲", "白龙王", "陈朗", "诸葛亮", "刘伯温", "玄学", "文昌", "太极"]):
            categories.append("偏门玄学")
        if any(kw in combined for kw in ["食伤生重财", "年月库墓", "财星生杀", "头脑发热", "破财", "财神煞", "投资失败"]):
            categories.append("投资脑袋发昏")
        if any(kw in combined for kw in ["身强食伤旺", "财星归", "三合六合", "库在日时", "库在年月", "当老板", "王健林"]):
            categories.append("老板赚钱")
        if any(kw in combined for kw in ["食伤穿刑绝财星", "比劫穿制财星", "暗合财星", "诈骗", "偷偷摸摸", "骗钱", "羊刃"]):
            categories.append("骗子赚钱")
        if any(kw in combined for kw in ["印星为用", "固定资产", "店面", "财印同柱", "开店"]):
            categories.append("开店赚钱")
        if any(kw in combined for kw in ["财生官", "财官和贵", "当官", "权力"]):
            categories.append("权力赚钱")

    # 如果主题有编号但无类别，按编号匹配
    if not categories:
        m = re.match(r'^第([一二三四五六七八九十]+)种', topic)
        if m:
            num = m.group(1)
            num_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
                       '十一':11,'十二':12,'十三':13,'十四':14,'十五':15}
            topic_num = num_map.get(num, 0)
            if topic_num == 14:
                categories.append("偷窃抢劫")
            elif topic_num == 15:
                categories.extend(["黑社会赚钱", "偏门玄学"])
            elif topic_num == 3:
                categories.append("老板赚钱")
            elif topic_num == 4:
                categories.append("骗子赚钱")
            elif topic_num == 6:
                categories.append("开店赚钱")
            elif topic_num == 8:
                categories.append("权力赚钱")
            elif topic_num == 13:
                categories.append("投资脑袋发昏")
    
    # 从 SCREENSHOT_MAP 中找到匹配的截图（限量3张，减少重复）
    result = []
    seen_filenames = set()
    for ts_str, filename in sorted(SCREENSHOT_MAP.items()):
        cat = screenshot_category(filename)
        if cat in categories and filename not in seen_filenames:
            result.append({"timestamp": ts_str, "filename": filename})
            seen_filenames.add(filename)
        if len(result) >= 3:
            break

    return result

# ============================================================
# 时间工具
# ============================================================
def time_to_sec(t):
    m = re.match(r'(\d+):(\d+)', str(t))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0

def sec_to_time(sec):
    return f"{int(sec)//60:02d}:{int(sec)%60:02d}"

def format_time(start, end):
    if end and end != start:
        return f"{start} - {end}"
    return str(start)

# ============================================================
# 文本清洗
# ============================================================
def clean_text(t):
    if not t:
        return ""
    return re.sub(r'\s+', ' ', t.strip())

# ============================================================
# 板书文本后处理修复
# ============================================================
BOARD_TEXT_FIXES = [
    (r'比动多', '比劫多'),
    (r'动财', '劫财'),
    (r'编财', '偏财'),
    (r'编印', '偏印'),
    (r'仿言', '伤官'),
    (r'伤言', '伤官'),
    (r'正富', '正官'),
    (r'正宫', '正官'),
    (r'正营', '正官'),
    (r'七茶', '七杀'),
    (r'比扇', '比肩'),
    (r'比房', '比肩'),
    (r'食种', '食神'),
    (r'王(?=水|木|火|土|金)', '壬'),
    (r'吴(?=[正偏食伤比劫][官杀印财神肩])', '戊'),
    (r'[柔奖灸](?=比肩|七杀|正财|偏财|正印|偏印|食神|伤官|劫财)', '癸'),
    (r'幸(?=比肩|七杀|正财|偏财|正印|偏印|食神|伤官|劫财)', '辛'),
    (r'石幅木', '石榴木'),
    (r'整上土', '壁上土'),
    (r'羊古', '辛苦'),
    (r'产重', '严重'),
    (r'第士种', '第十种'),
    (r'第士个', '第十个'),
    (r'儿种', '第九种'),
    (r'复印', '伏吟'),
    (r'捷正印', '戊正印'),
    (r'滨印', '偏印'),
    (r'妥偏印', '戊偏印'),
    (r'抗膏', '抗高'),
    (r'石灯', '财星'),
    (r'为喜伸', '为喜神'),
    (r'总伸', '忌神'),
    (r'吸灯', '忌神'),
    (r'懒到钱', '赚到钱'),
    (r'购星', '财星'),
    (r'问的', '忌的'),
    (r'手劫材', '辛劫财'),
    (r'千劫材', '辛劫财'),
    (r'窗印', '辛印'),
    (r'惠，正印', '癸正印'),
    (r'审下印', '辛偏印'),
    (r'成信财', '戊正财'),
    (r'唐辰', '庚辰'),
    (r'笑五子', '癸巳子'),
    (r'庚成', '庚戌'),
    (r'丁已', '丁巳'),
    (r'信财', '偏财'),
    (r'贝(?=出生|一九|阴|穿|刑)', '见'),
    (r'男(?=八字|穿|刑)', '见'),
    (r'阴湿白', '阴湿的丑土'),
    (r'穿制购', '穿制财'),
    (r'体力则', '体力赚钱'),
    (r'肉赚$', '肉赚钱'),
    (r'贝白', '见阴'),
    (r'贝阴', '见阴'),
    (r'男阴', '见阴'),
    (r'禄半桃存', '禄半桃花'),
    (r'桃存', '桃花'),
    (r'指白', '指的是'),
    (r'一一般', '一般'),
    (r'赚钱不多羊古', '赚钱不多且辛苦'),
    (r'天千透', '天干透'),
    (r'黑社会赚钧', '黑社会赚钱'),
    (r'黑社会钱', '黑社会赚钱'),
    (r'赚钧', '赚钱'),
    (r'龙女人', '或女人'),
    (r'脑袋发盾', '脑袋发昏'),
    (r'脑袋发督', '脑袋发昏'),
    (r'吴正财', '戊正财'),
    (r'吴正官', '戊正官'),
    (r'吴偏财', '戊偏财'),
    (r'辛伤国', '辛伤官'),
    (r'伤国', '伤官'),
    (r'癸末王午', '癸未壬午'),
    (r'癸末', '癸未'),
    (r'王午', '壬午'),
    (r'辛已(?!经)', '辛巳'),
    (r'戈缤财', '戊偏财'),
    (r'神王赚', '忌神主赚'),
    (r'石财里', '财星'),
    (r'牙绝生', '穿绝星'),
    (r'牙绝星', '穿绝星'),
    (r'一股牙', '一般穿'),
    (r'毛辰川', '卯辰穿'),
    (r'路去穿', '刃去穿'),
    (r'路认', '禄刃'),
    (r'偏裁', '偏财'),
    (r'扬认', '羊刃'),
    (r'阳认', '羊刃'),
    (r'小绿', '小弟'),
    (r'挡护', '打断'),
    (r'杰财', '劫财'),
    (r'欲财观', '与财关'),
    (r'不主劳欲', '不主牢狱'),
    (r'惹观死', '惹官非'),
    (r'油黏', '流年'),
    (r'口光废', '口诀'),
    (r'窗材', '传销'),
    (r'红银墨', '红颜祸'),
    (r'肿油', '肿瘤'),
    (r'鸡', '妓'),  # 在特定上下文
    (r'导得', '倒贴'),
    (r'诛车', '骗车'),
    (r'整容片', '整容骗'),
    (r'激励', '体力'),
    (r'警卫物成', '身弱物成'),
    (r'肆平人', '富屋贫人'),
    (r'商务', '压身'),
    (r'牙牙牙子', '养养鸭子'),
    (r'成的质', '成的智'),
    (r'承续丑', '辰戌丑'),
    (r'承续土', '辰戌土'),
    (r'弦曲', '玄学'),
    (r'全学', '玄学'),
    (r'去全学', '搞玄学'),
    (r'吃全学', '吃玄学'),
    (r'程序丑味', '辰戌丑未'),
    (r'6D6加', '食伤库'),
    (r'要事库', '食伤库'),
    (r'主意嘛', '主要嘛'),
]

def fix_board_text(text):
    for pattern, replacement in BOARD_TEXT_FIXES:
        text = re.sub(pattern, replacement, text)
    return text

# ============================================================
# 知识点过滤：判断一行是否是有效的板书知识点
# ============================================================
def is_valid_knowledge_line(text):
    """判断一行是否是有效的板书知识点（排除碎片、噪声、案例数据）"""
    t = text.strip()
    if not t or len(t) < 4:
        return False
    
    # 排除出生时间、阳历、农历
    if t.startswith("出生时间") or t.startswith("出生于"):
        return False
    if "出生时间" in t or "出生于" in t:
        return False
    if "阳历" in t and re.search(r'\d{4}年', t):
        return False
    if "农历" in t and re.search(r'年.{1,3}月', t):
        return False
    # 排除姓名
    if t.startswith("姓名"):
        return False
    # 排除纯数字
    if re.match(r'^\d+$', t):
        return False
    # 排除太短的碎片
    if len(t) < 5 and not re.match(r'^第[一二三四五六七八九十]+', t):
        return False
    # 排除包含大量英文/特殊字符的行
    eng_count = len(re.findall(r'[a-zA-Z]', t))
    if eng_count > 3:
        return False
    
    # === 排除排盘数据 ===
    ten_gods = ['正财', '偏财', '七杀', '正官', '偏官', '正印', '偏印', 
                '食神', '伤官', '比肩', '劫财', '食伤']
    ten_god_count = sum(1 for tg in ten_gods if tg in t)
    # 含2+十神的行 → 排盘数据
    if ten_god_count >= 2 and not re.match(r'^\d+[、.．]', t) and not re.match(r'^第[一二三四五六七八九十]+', t):
        return False
    # 含天干+十神的组合（如"乙正官"、"戊正财"）→ 排盘数据
    if re.search(r'[甲乙丙丁戊己庚辛壬癸](正财|偏财|七杀|正官|偏官|正印|偏印|食神|伤官|比肩|劫财)', t):
        return False
    # 含"日干"、"临官"、"小运"、"大运"等排盘关键词
    if re.match(r'^(小运|大运|胎元|命宫|长生|冠带|临官|帝旺|实岁|约|即约)', t):
        return False
    if any(kw in t for kw in ['临官', '小运', '大运', '胎元', '命宫', '实岁']):
        return False
    # 排除纯干支行（如"癸末王午 辛已 庚辰"）
    gan_zhi_chars = set('甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥')
    if len(t) > 5:
        gan_zhi_ratio = sum(1 for c in t if c in gan_zhi_chars) / len(t)
        if gan_zhi_ratio > 0.4:
            return False
    
    # 排除节气信息
    if re.match(r'^出生于', t):
        return False
    # 排除农历年份
    if re.match(r'^农历[：:]\d{4}$', t):
        return False
    # 排除 "X月X日" 格式
    if re.match(r'^\d+月\d+日', t) and len(t) < 20:
        return False
    # 排除 "T90" 之类的碎片
    if re.match(r'^[A-Z]\d+', t):
        return False
    # 排除纯标点
    if re.match(r'^[，。、；：！？\s]+$', t):
        return False
    # 排除含 "脚会" "女主摄" 等噪声
    if '女主摄' in t or '脚会' in t:
        return False
    # 排除含 P工 等乱码
    if 'P工' in t or 'B娱' in t:
        return False
    
    # === 排除碎片化行 ===
    # 以"的"、"与多个"、"易与"开头的碎片（OCR断行残留）
    if re.match(r'^(的|与多个|易与|身的|们\d|之人|神反|用肉体去|不多且|表脑子|没有格局|重，|股票|一般是赚|、比劫|辛写)', t):
        return False
    # 以括号开头但不完整的行
    if re.match(r'^[（(]', t) and not re.search(r'[）)]', t):
        return False
    # "喜欢动脑" 碎片（只有部分文字）
    if t.startswith("喜欢动脑") and len(t) < 20:
        return False
    # 以编号开头但内容太短的截断行（如"2、八字要有"、"3、八字中"）
    if re.match(r'^\d+[、.．]', t) and len(t) < 10:
        return False
    # 含编号且以不完整词结尾（如"八字要有"、"八字中"）
    if re.match(r'^\d+[、.．]', t) and re.search(r'(要有$|八字中$|八字见$|八字中易见$|甲、$)', t):
        return False
    # 含"※"或"X"标记的噪声行
    if t.startswith("※") or t.startswith("X") and len(t) < 30:
        return False
    # 含"营销偏门玄学"的重复噪声行
    if '营销偏门玄学' in t and len(t) < 20:
        return False
    # "偏门玄学类行"截断
    if t.endswith("类行") or t.endswith("类行") or t == "※营销偏门玄学类行":
        return False
    # "辛印" 开头的排盘碎片
    if re.match(r'^辛印\b', t) and len(t) < 15:
        return False
    # "癸" 开头但不是知识点（排盘碎片）
    if re.match(r'^癸[末未巳子]\b', t) and len(t) < 15:
        return False
    # 排除"一股牙绝生"等乱码
    if '牙绝' in t and not re.match(r'^\d+[、.．]', t):
        return False
    # 排除"※"开头的行
    if '※' in t:
        return False
    # 排除"农历" 开头的年份碎片
    if re.match(r'^农历[：:]?\d', t):
        return False
    # 排除以"、"开头的碎片
    if t.startswith('、'):
        return False
    # 排除纯十神词组（如"偏财 偏财"）
    if re.match(r'^(正财|偏财|七杀|正官|偏官|正印|偏印|食神|伤官|比肩|劫财)(\s+(正财|偏财|七杀|正官|偏官|正印|偏印|食神|伤官|比肩|劫财))+$', t):
        return False
    # 排除含"写财"的OCR乱码（"辛写财偏财偏财"、"戊写财偏财偏财"）
    if '写财' in t:
        return False
    # 排除含"财重币"的OCR乱码
    if '财重币' in t:
        return False
    # 排除"买正印"等OCR误识（应为"戊正印"）
    if re.search(r'买正印', t) and not re.match(r'^\d+[、.．]', t):
        return False
    # 排除"一股穿绝星"等碎片
    if t.startswith('一股穿'):
        return False
    # 排除以"一穿绝星"开头但不是编号行的碎片
    if t.startswith('一穿绝星') and len(t) < 30:
        return False
    # 排除"未为土为阴暗的、不"截断行
    if t.endswith('、不') or t == '未为土为阴暗的、不':
        return False
    # 排除以"偏财"结尾的单行
    if t == '偏财 偏财':
        return False
    
    return True

def deduplicate_knowledge_lines(lines):
    """对知识点行进行去重：相同编号前缀只保留最长版本"""
    if not lines:
        return []
    
    # 按编号前缀分组
    prefix_groups = defaultdict(list)
    no_prefix = []
    
    for line in lines:
        m = re.match(r'^(\d+[、.．])', line)
        if m:
            prefix_groups[m.group(1)].append(line)
        else:
            no_prefix.append(line)
    
    result = []
    # 对每个编号组，只保留最长的版本
    for prefix in sorted(prefix_groups.keys(), key=lambda x: int(re.match(r'(\d+)', x).group(1))):
        group = prefix_groups[prefix]
        # 选择最长的行
        longest = max(group, key=len)
        result.append(longest)
    
    # 无编号行去重（保留所有，但去除明显重复）
    seen = set()
    for line in no_prefix:
        # 用前20个字符作为去重key
        key = line[:20]
        if key not in seen:
            seen.add(key)
            result.append(line)
    
    # 子串去重：如果一行是另一行的子串，删除较短的那行
    final = []
    for i, line in enumerate(result):
        is_substring = False
        for j, other in enumerate(result):
            if i != j and line != other and line in other and len(line) < len(other):
                is_substring = True
                break
        if not is_substring:
            final.append(line)
    
    return final

# ============================================================
# 板书行格式化
# ============================================================
def format_board_lines(texts):
    """按板书原结构重排"""
    if not texts:
        return []
    
    topic_pattern = re.compile(r'^第[一二三四五六七八九十百千]+[种个类章]')
    content_pattern = re.compile(r'^内容[一二三四五六七八九十百千]+、')
    sub_pattern = re.compile(r'^\d+[、.．]')

    groups = []
    current_group = []

    for t in texts:
        t = t.strip()
        if not t:
            continue
        if topic_pattern.match(t) or content_pattern.match(t):
            if current_group:
                groups.append(current_group)
            current_group = [t]
        elif sub_pattern.match(t):
            current_group.append(t)
        else:
            if current_group:
                current_group.append(t)
            else:
                current_group = [t]

    if current_group:
        groups.append(current_group)

    result = []
    for group in groups:
        topic_lines = []
        sub_lines = []
        other_lines = []

        for line in group:
            if topic_pattern.match(line) or content_pattern.match(line):
                topic_lines.append(line)
            elif sub_pattern.match(line):
                sub_lines.append(line)
            else:
                other_lines.append(line)

        for tl in topic_lines:
            result.append(tl)
        # 每个子项独立一行（不合并），保持板书原结构
        for sl in sub_lines:
            result.append(sl)
        for ol in other_lines:
            result.append(ol)

    return result

# ============================================================
# 案例去重（按日期合并）
# ============================================================
def get_case_key(case_lines, board_lines=None):
    """从案例数据中提取唯一标识"""
    all_text = " ".join(l["text"] for l in case_lines)
    if board_lines:
        all_text += " " + " ".join(l["text"] for l in board_lines)
    
    # 尝试匹配阳历日期（4位年份）
    m = re.search(r'(\d{4})年(\d+)月(\d+)日', all_text)
    if m:
        return f"solar_{m.group(1)}_{m.group(2)}_{m.group(3)}"
    
    # 尝试匹配农历日期
    m = re.search(r'(一九\w+年\w+月\w+[日廿])', all_text)
    if m:
        return f"lunar_{m.group(1)}"
    
    # 尝试匹配姓名
    m = re.search(r'姓名[：:](\S+)', all_text)
    if m:
        return f"name_{m.group(1)}"
    
    # 无日期/姓名：返回 None，由 deduplicate_cases 通过时间+相似度合并
    return None

def chart_token_similarity(text1, text2):
    """计算两段排盘文本的相似度（基于十神/天干/地支 token 重叠度）"""
    # 提取所有 token
    tokens1 = set(text1.split())
    tokens2 = set(text2.split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union)

def deduplicate_cases(wb_data):
    """合并相同案例（按日期/姓名/时间+相似度），保留时间顺序"""
    result = []
    
    for i, seg in enumerate(wb_data):
        case = seg.get("case_lines", [])
        if not case:
            continue
        
        key = get_case_key(case, seg.get("lines", []))
        seg_time = time_to_sec(seg.get("start", "0:00"))
        case_text = " ".join(l["text"] for l in case)
        
        # 策略1：有明确 key（日期/姓名）→ 按 key 合并
        if key:
            merged = False
            for existing in result:
                if existing.get("key") == key:
                    existing["segments"].append(seg)
                    existing_texts = set(l["text"] for l in existing["case_lines"])
                    for l in case:
                        if l["text"] not in existing_texts:
                            existing["case_lines"].append(l)
                            existing_texts.add(l["text"])
                    for l in seg.get("lines", []):
                        existing["board_lines"].append(l)
                    merged = True
                    break
            if not merged:
                result.append({
                    "key": key,
                    "segments": [seg],
                    "case_lines": list(case),
                    "board_lines": list(seg.get("lines", [])),
                    "first_idx": i,
                    "first_time": seg_time,
                    "case_text": case_text,
                })
        else:
            # 策略2：无 key → 检查与最近案例的时间距离和相似度
            merged = False
            if result:
                last = result[-1]
                time_diff = seg_time - last.get("first_time", 0)
                # 如果在 90 秒内且排盘数据相似度 > 0.4，合并
                if time_diff < 20:
                    # 20秒内直接合并（连续帧几乎一定是同一案例）
                    last["segments"].append(seg)
                    existing_texts = set(l["text"] for l in last["case_lines"])
                    for l in case:
                        if l["text"] not in existing_texts:
                            last["case_lines"].append(l)
                            existing_texts.add(l["text"])
                    for l in seg.get("lines", []):
                        last["board_lines"].append(l)
                    last["case_text"] = last.get("case_text", "") + " " + case_text
                    merged = True
                elif time_diff < 90:
                    sim = chart_token_similarity(case_text, last.get("case_text", ""))
                    if sim > 0.3:
                        last["segments"].append(seg)
                        existing_texts = set(l["text"] for l in last["case_lines"])
                        for l in case:
                            if l["text"] not in existing_texts:
                                last["case_lines"].append(l)
                                existing_texts.add(l["text"])
                        for l in seg.get("lines", []):
                            last["board_lines"].append(l)
                        last["case_text"] = last["case_text"] + " " + case_text
                        merged = True
            
            if not merged:
                result.append({
                    "key": None,
                    "segments": [seg],
                    "case_lines": list(case),
                    "board_lines": list(seg.get("lines", [])),
                    "first_idx": i,
                    "first_time": seg_time,
                    "case_text": case_text,
                })
    
    return result

# ============================================================
# ASR 讲解提取
# ============================================================
def extract_asr_commentary(asr_segs, start_sec, end_sec):
    """提取指定时间范围内的 ASR 讲解文本"""
    texts = []
    for s in asr_segs:
        s_start = s.get("start", 0)
        if s_start >= start_sec - 3 and s_start < end_sec:
            t = s.get("text_v3", s.get("text_v2", s.get("text_v1", s.get("text", ""))))
            t = clean_text(t)
            if t:
                texts.append(t)
    return " ".join(texts)

def fix_chart_data(text):
    """修复排盘数据中的OCR错误"""
    fixes = [
        (r'吴正财', '戊正财'), (r'吴正官', '戊正官'), (r'吴偏财', '戊偏财'),
        (r'辛伤国', '辛伤官'), (r'伤国', '伤官'),
        (r'癸末', '癸未'), (r'王午', '壬午'), (r'辛已(?!经)', '辛巳'),
        (r'庚成', '庚戌'), (r'丁已(?!经)', '丁巳'), (r'乙已(?!经)', '乙巳'),
        (r'己已(?!经)', '己巳'), (r'戊成', '戊戌'),
        (r'成信财', '戊正财'), (r'戈缤财', '戊偏财'),
        (r'奏正财', '乙正财'), (r'捷正印', '戊正印'), (r'妥偏印', '戊偏印'),
        (r'唐辰', '庚辰'), (r'窗印', '辛印'),
        (r'惠，正印', '癸正印'), (r'审下印', '辛偏印'),
        (r'手劫材', '辛劫财'), (r'千劫材', '辛劫财'),
        (r'信财', '偏财'), (r'滨印', '偏印'),
        (r'动财', '劫财'), (r'比动', '比劫'),
        (r'羊古', '辛苦'), (r'产重', '严重'),
        (r'复印', '伏吟'), (r'为喜伸', '为喜神'),
        (r'总伸', '忌神'), (r'石灯', '财星'),
        (r'天千透', '天干透'),
        (r'5年儿日切力', '五年廿九日丑时'),
        (r'成 乙孩', '戊 乙亥'),
        (r'甲成乙', '甲戌乙'),
        (r'甲成', '甲戌'),
        (r'乙孩', '乙亥'),
        (r'^成$', '戊'),
        (r'漏气阵前', '漏气挣钱'),
        (r'漏气', '乱气'),
    ]
    for pattern, replacement in fixes:
        text = re.sub(pattern, replacement, text)
    return text

def clean_asr_commentary(text):
    """清理ASR讲解文本中的明显错误"""
    if not text:
        return text
    # 修复常见ASR口语化错误
    asr_fixes = [
        (r'鹿叛桃花', '禄半桃花'),
        (r'鹿叛', '禄半'),
        (r'鹿体', '肉体'),
        (r'植物毛泳', '子午卯酉'),
        (r'沉土', '辰土'),
        (r'害无暗和', '亥午暗合'),
        (r'生经', '申金'),
        (r'身经', '申金'),
        (r'突电', '偷电'),
        (r'鸡女', '妓女'),
        (r'山陪', '三陪'),
        (r'导卖', '倒卖'),
        (r'导买', '倒买'),
        (r'诚格局', '成格局'),
        (r'诚格去', '成格去'),
        (r'坑蒙管强', '坑蒙拐骗'),
        (r'阴坏阳过渡', '阴坏阳过度'),
        (r'没有食脑', '没有食伤'),
        (r'食伤玩的脑子坏', '食伤代表脑子好'),
        (r'不认啊', '不论啊'),
        (r'马斯西姆佛', '马上喜木火'),
        (r'鹿就子午卯酉', '禄就子午卯酉'),
        (r'瓶影', '丙寅'),
        (r'瓶火', '丙火'),
        (r'路认', '禄刃'),
        (r'偏裁', '偏财'),
        (r'扬认', '羊刃'),
        (r'阳认', '羊刃'),
        (r'杰财', '劫财'),
        (r'小绿', '小弟'),
        (r'窗材', '传销'),
        (r'红银墨', '红颜祸'),
        (r'肿油', '肿瘤'),
        (r'导得', '倒贴'),
        (r'诛车', '骗车'),
        (r'整容片', '整容骗'),
        (r'挡护', '打断'),
        (r'承续丑', '辰戌丑'),
        (r'承续土', '辰戌土'),
        (r'弦曲', '玄学'),
        (r'全学', '玄学'),
        (r'程序丑味', '辰戌丑未'),
        (r'6D6加', '食伤库'),
        (r'要事库', '食伤库'),
        (r'激励', '体力'),
        (r'警卫物成', '身弱物成'),
        (r'肆平人', '富屋贫人'),
        (r'商务', '压身'),
        (r'欲财观', '与财关'),
        (r'不主劳欲', '不主牢狱'),
        (r'惹观死', '惹官非'),
        (r'油黏', '流年'),
        (r'口光废', '口诀'),
        (r'毛辰川', '卯辰穿'),
        (r'路去穿', '刃去穿'),
        (r'牙牙牙子', '养养鸭子'),
        (r'牙绝生', '穿绝星'),
        (r'牙绝星', '穿绝星'),
        (r'一股牙', '一般穿'),
        (r'神王赚', '忌神主赚'),
        (r'石财里', '财星'),
        (r'成的质', '成的智'),
        (r'黑社数', '黑社会'),
        (r'摘的', '栽的'),
        (r'鹿和了', '禄合了'),
        (r'鹿就', '禄就'),
        (r'鹿要', '禄要'),
        (r'搞老头这个鸡', '搞老头这个妓'),
        (r'倒卖倒卖', '倒买倒卖'),
        # --- 命理十神/术语修正 ---
        (r'劫财三观', '劫财伤官'),
        (r'三观', '伤官'),
        (r'财关', '财官'),
        (r'观死', '官死'),
        (r'羊刃同住', '羊刃同柱'),
        (r'同住', '同柱'),
        (r'穿自裁官', '穿制财官'),
        (r'穿裁官', '穿制财官'),
        (r'穿自其他', '穿绝其他'),
        (r'穿学其他', '穿绝其他'),
        (r'穿学', '穿绝'),
        (r'穿决财星', '穿绝财星'),
        (r'穿决', '穿绝'),
        (r'穿那个胃', '穿那个未'),
        (r'子穿胃', '子穿未'),
        (r'用胃去穿', '用未去穿'),
        (r'胃穿', '未穿'),
        # --- 命理人物名修正 ---
        (r'白泳王', '白龙王'),
        (r'朱可亮', '诸葛亮'),
        (r'成蓝', '陈朗'),
        (r'成蓝的', '陈朗的'),
        (r'周新词', '周星驰'),
        (r'丑和诚', '丑和辰'),
        # --- 命理概念修正 ---
        (r'一命中贷劫财', '命中带劫财'),
        (r'命中贷劫财', '命中带劫财'),
        (r'写劫财为使用', '且劫财为喜用'),
        (r'为使用的人', '为喜用的人'),
        (r'祭神', '忌神'),
        (r'禄认', '禄刃'),
        (r'负无平仁', '富屋贫人'),
        (r'深落财重', '身弱财重'),
        (r'入落为深落', '入禄为身弱'),
        (r'成格去', '成格局'),
        (r'没成格去', '没成格局'),
        (r'官当财卡', '官当财看'),
        (r'传销观战', '传销官灾'),
        (r'单关取材', '官关取财'),
        (r'成蓝的八字', '陈朗的八字'),
        # --- 常用词修正 ---
        (r'猫有猫到', '猫有猫道'),
        (r'鼠有鼠到', '鼠有鼠道'),
        (r'银有鼠到', '各有各道'),
        (r'得现身', '得献身'),
        (r'得现役', '得献艺'),
        (r'专层的方法', '赚钱的方法'),
        (r'搞算命子的宪法', '搞算命子的心法'),
        (r'没识了', '没事了'),
        (r'高分数', '光负债'),
        (r'丁寺同等', '丁巳同柱'),
        (r'怎么造型', '怎么取财'),
        (r'追头睡熟了', '追到熟了'),
        (r'几米48', '几百万'),
        (r'江苏国许', '江苏过去'),
        # --- 更多命理术语修正 ---
        (r'漏气阵前', '肉体挣钱'),
        (r'卖漏气', '卖肉体'),
        (r'漏气的方式', '肉体的方式'),
        (r'新代部', '信贷部'),
        (r'以节多', '比劫多'),
        (r'财星落', '财星弱'),
        (r'赌播', '赌博'),
        (r'帮货的', '送货的'),
        (r'看禅', '看盘'),
        (r'画笔', '画皮'),
        (r'骗车片', '骗车骗'),
        (r'众帝', '种地'),
        (r'身弱物成', '身弱无成'),
        (r'假印物成', '假印无成'),
        (r'股帛', '股票'),
        (r'穿法主', '穿伐主'),
        (r'私民说', '市民说'),
        (r'私民决图', '市民企图'),
        (r'披到八字', '批到八字'),
        (r'一目', '乙木'),
        (r'好关掉', '好官劫'),
        (r'认照在偏偏', '刃照在偏财'),
        (r'偏偏', '偏财'),
        (r'刘伯文', '刘伯温'),
        (r'少伟华', '邵伟华'),
        (r'要什么证件玄学', '要什么赚钱玄学'),
        (r'怎么搞玄学证件', '怎么搞玄学赚钱'),
        (r'去玄学饭', '吃玄学饭'),
        (r'斗鱼一节', '都有一劫'),
        (r'新衣服', '新衣禄'),
        (r'跑面的头', '跑路的钱'),
        (r'不好有格局的不认', '不过有格局的不论'),
        (r'没成格去', '没成格局'),
        (r'成格的材质', '成格的材质'),
        (r'说法太干净', '说法太精炼'),
        (r'漏长', '落场'),
        (r'课那个根', '克那个根'),
        (r'高负债', '光负债'),
        (r'得奖老师', '大家老师'),
    ]
    for pattern, replacement in asr_fixes:
        text = re.sub(pattern, replacement, text)
    return text

# ============================================================
# 案例信息提取
# ============================================================
def extract_case_info(case_lines):
    """从案例数据行中提取结构化信息"""
    all_text = " ".join(l["text"] for l in case_lines)
    
    info = {
        "name": "",
        "solar_date": "",
        "lunar_date": "",
        "gender": "",
        "chart_data": [],
        "occupation_note": "",
    }
    
    m = re.search(r'姓名[：:]\s*(\S+)', all_text)
    if m:
        info["name"] = m.group(1).strip()
    
    m = re.search(r'阳历\s*(\d{4}年\d+月\d+日\s*\d+时\d+分)', all_text)
    if m:
        info["solar_date"] = m.group(1)
    else:
        m = re.search(r'阳历\s*(\d{4}年\d+月\d+日\d+时\d+分)', all_text)
        if m:
            info["solar_date"] = m.group(1)
    
    m = re.search(r'农历[：:]*\s*(\w+年\w+月\w+[日廿]\w*[,，]\s*\w+时)', all_text)
    if m:
        info["lunar_date"] = m.group(1)
    
    if "坤造" in all_text:
        info["gender"] = "女"
    elif "乾造" in all_text:
        info["gender"] = "男"
    
    for l in case_lines:
        t = clean_text(l["text"])
        if not t:
            continue
        if t.startswith("出生时间") or t.startswith("出生于") or t.startswith("姓名"):
            continue
        # 过滤掉碎片化的排盘信息
        if len(t) < 2:
            continue
        # 应用排盘数据OCR修复
        t = fix_chart_data(t)
        info["chart_data"].append(t)
    
    return info

# ============================================================
# 推断案例所属主题
# ============================================================
def infer_case_topic(board_lines, asr_text=""):
    """从板书上下文和ASR文本推断案例所属的赚钱方式"""
    all_text = " ".join(l["text"] for l in board_lines) + " " + asr_text
    
    topics = [
        (r'第一种[、,，]?\s*技术', "第一种·技术赚钱"),
        (r'第二种[、,，]?\s*体力', "第二种·体力赚钱"),
        (r'第三种[、,，]?\s*老板', "第三种·老板赚钱"),
        (r'第四种[、,，]?\s*骗子', "第四种·骗子赚钱"),
        (r'第五种[、,，]?\s*肉', "第五种·肉体赚钱"),
        (r'第六种[、,，]?\s*开店', "第六种·开店赚钱"),
        (r'第七种[、,，]?\s*贸易', "第七种·贸易赚钱"),
        (r'第八种[、,，]?\s*权力', "第八种·权力赚钱"),
        (r'第九种[、,，]?\s*黑社会', "第九种·黑社会赚钱"),
        (r'第十种[、,，]?\s*依赖', "第十种·依赖父母赚钱"),
        (r'第十一种[、,，]?\s*做业务', "第十一种·做业务赚钱"),
        (r'第十二种[、,，]?\s*被人骗', "第十二种·被人骗钱"),
        (r'第十三种[、,，]?\s*投资', "第十三种·投资脑袋发昏"),
        (r'第十四种[、,，]?\s*偷窃', "第十四种·偷窃抢劫"),
        (r'第十五种[、,，]?\s*偏门', "第十五种·偏门赚钱"),
    ]
    
    for pattern, label in topics:
        if re.search(pattern, all_text):
            return label

    # 兜底：按内容关键词推断（ASR口述更能反映具体案例的取财方式）
    kw_map = [
        (("食伤生重财", "年月库墓", "库墓", "财星生杀", "头脑发热", "财神煞", "投资失败"), "第十三种·投资脑袋发昏"),
        (("骗子", "诈骗", "骗钱", "骗财", "偷偷摸摸"), "第四种·骗子赚钱"),
        (("老板", "王健林", "张郎", "左辉", "当老板", "身强食伤", "食伤生财", "财星归", "库在日时", "库在年月", "库债日时"), "第三种·老板赚钱"),
        (("开店", "印星为用", "固定资产", "店面"), "第六种·开店赚钱"),
        (("权力赚钱", "财生官", "财官和贵", "当官"), "第八种·权力赚钱"),
        (("黑社会", "辰戌丑未", "羊刃穿绝", "劫财伤官", "牢狱"), "第九种·黑社会赚钱"),
    ]
    for kws, label in kw_map:
        if any(kw in all_text for kw in kws):
            return label

    return None


def build_topic_reference(wb_data):
    """
    主题参照表（来自干净板书原文）：第X种编号 -> {要点内容集合, 标题词}。
    主讲人讲的八字案例紧扣板书主题——案例归类用这份参照交叉比对，
    比硬编码关键词 + 单帧板行更可靠。
    """
    ref = {}
    for seg in wb_data:
        cur_num = None
        for l in seg.get("lines", []):
            t = clean_text(fix_board_text(l["text"])).strip()
            if not t or len(t) < 4:
                continue
            tm = re.match(r"^(第[一二三四五六七八九十\d]+种)[、,，]?\s*(\S+)", t)
            if tm:
                cur_num = tm.group(1)
                word = tm.group(2).rstrip("，,、；;")
                entry = ref.setdefault(cur_num, {"points": set(), "title": word})
                if len(word) > len(entry["title"]):
                    entry["title"] = word  # 保留最完整标题词
                continue
            if cur_num and re.match(r"^\d+[、.．]", t):
                content = re.sub(r"^\d+[、.．]\s*", "", t)
                if len(content) >= 6:
                    ref[cur_num]["points"].add(content)
    return ref


def infer_topic_by_reference(ref, combined_text):
    """
    用干净板书要点参照给案例归类：命中要点内容最多的第X种获胜。
    返回规范主题标签（如 第三种·老板赚钱）或 None。
    """
    best_num, best_score = None, 0
    for num, entry in ref.items():
        score = sum(1 for p in entry["points"] if p in combined_text)
        if score > best_score:
            best_num, best_score = num, score
    if best_score >= 1 and best_num:
        return f"{best_num}·{ref[best_num]['title']}"
    return None


# ============================================================
# 主流程
# ============================================================
def main():
    print("=== 生成板书知识点解析报告 v2 ===")

    # 0. 若提供 --rename-map，自动推导 SCREENSHOT_MAP
    global SCREENSHOT_MAP
    if _args.rename_map:
        with open(_args.rename_map, 'r', encoding='utf-8') as f:
            rename_map = json.load(f)
        derived = _derive_screenshot_map(rename_map)
        if derived:
            SCREENSHOT_MAP = derived
            print(f"   从 rename_map 推导 SCREENSHOT_MAP: {len(derived)} 条")
        else:
            print(f"   WARN: rename_map 未推导出截图映射，使用内置映射")

    # 1. 加载数据
    print("1. 加载数据...")
    with open(WB_IMPROVED, 'r', encoding='utf-8') as f:
        wb_data = json.load(f)
    with open(ASR_JSON, 'r', encoding='utf-8') as f:
        asr_data = json.load(f)
    asr_segs = asr_data["segments"]
    print(f"   板书段数: {len(wb_data)}, ASR段数: {len(asr_segs)}")
    
    # 2. 提取课程大纲
    print("2. 提取课程大纲...")
    outline_items = []
    seen_outline = set()
    for seg in wb_data:
        for l in seg.get("lines", []):
            t = fix_board_text(clean_text(l["text"]))
            if re.match(r'^内容[一二三四五六七八九十]+、', t) and len(t) > 10:
                # 去重（部分匹配）
                key = t[:15]
                if key not in seen_outline:
                    seen_outline.add(key)
                    outline_items.append(t)
    # 兜底：无"内容X、"格式时，提取"第X种、YYY赚钱"列表作为大纲
    if not outline_items:
        seen2 = set()
        for seg in wb_data:
            for l in seg.get("lines", []):
                t = fix_board_text(clean_text(l["text"]))
                if re.match(r'^第[一二三四五六七八九十]+种[、,，]?\s*\S+赚钱', t):
                    t = t.strip("。，、；：")
                    if t not in seen2:
                        seen2.add(t)
                        outline_items.append(t)
    print(f"   大纲条目: {len(outline_items)}")
    
    # 3. 提取板书知识点
    print("3. 提取板书知识点...")
    all_board_lines = []
    seen_lines = set()
    for seg in wb_data:
        for l in seg.get("lines", []):
            t = fix_board_text(clean_text(l["text"]))
            if t and is_valid_knowledge_line(t) and t not in seen_lines:
                seen_lines.add(t)
                all_board_lines.append(t)
    
    # 按主题分组（先标准化主题名）
    def normalize_topic(t):
        """标准化主题名，合并 OCR 变体"""
        # 提取"第X种"和后面的内容
        m = re.match(r'^第([一二三四五六七八九十]+)种[、,，]?\s*(.*)', t)
        if m:
            num = m.group(1)
            rest = m.group(2).strip()
            # 标准化赚钱方式名称
            topic_map = {
                '技术': '技术赚钱', '技': '技术赚钱',
                '体力': '体力赚钱', '体': '体力赚钱', '体力赌': '体力赚钱', '体力则': '体力赚钱',
                '老板': '老板赚钱',
                '骗子': '骗子赚钱',
                '肉': '肉体赚钱', '肉体': '肉体赚钱', '肉赚钱': '肉体赚钱',
                '开店': '开店赚钱',
                '贸易': '贸易赚钱',
                '业务': '业务赚钱', '做业务': '业务赚钱',
                '黑社会': '黑社会赚钱', '黑社会赚钧': '黑社会赚钱', '黑社会钱': '黑社会赚钱',
                '依赖': '依赖父母赚钱', '依赖父': '依赖父母赚钱', '依赖父母': '依赖父母赚钱',
                '被人骗': '被人骗钱',
                '投资': '投资脑袋发昏', '投资脑袋': '投资脑袋发昏',
                '偷窃': '偷窃抢劫', '偷窃抢去': '偷窃抢劫',
                '偏门': '偏门赚钱', '偏': '偏门赚钱',
                '权力': '权力赚钱',
            }
            for key, val in topic_map.items():
                if rest.startswith(key) or rest == key:
                    return f"第{num}种·{val}"
            return f"第{num}种·{rest}" if rest else f"第{num}种"
        return t
    
    topic_groups = defaultdict(list)
    current_topic = "其他"
    for t in all_board_lines:
        if re.match(r'^第[一二三四五六七八九十百千]+[种个类章]', t):
            current_topic = normalize_topic(t)
        elif re.match(r'^内容[一二三四五六七八九十百千]+、', t):
            current_topic = t
        else:
            topic_groups[current_topic].append(t)
    
    # 只保留有内容的主题
    active_topics = {k: v for k, v in topic_groups.items() if v and k != "其他"}
    other_lines = topic_groups.get("其他", [])
    
    # 对每个主题内的知识点行进行去重（相同编号只保留最长版本）
    for topic in active_topics:
        active_topics[topic] = deduplicate_knowledge_lines(active_topics[topic])
    other_lines = deduplicate_knowledge_lines(other_lines)
    print(f"   知识点主题: {len(active_topics)}, 其他: {len(other_lines)}行")
    
    # 4. 案例去重
    print("4. 案例去重...")
    case_entries = deduplicate_cases(wb_data)
    print(f"   去重后案例: {len(case_entries)}")

    # 4.5 构建主题参照表（干净板书原文 → 每个第X种的要点）
    print("4.5 构建主题参照表...")
    topic_ref = build_topic_reference(wb_data)
    print(f"   参照主题: {len(topic_ref)} 个")
    
    # 5. 为每个案例提取 ASR 讲解（非重叠窗口）
    print("5. 提取 ASR 讲解...")
    for i, ce in enumerate(case_entries):
        first_seg = ce["segments"][0]
        start_sec = time_to_sec(first_seg.get("start", "0:00"))
        
        # 非重叠：到下一个案例的开始
        if i + 1 < len(case_entries):
            next_start = time_to_sec(case_entries[i+1]["segments"][0].get("start", "0:00"))
            end_sec = next_start
        else:
            end_sec = start_sec + 120  # 最后一个案例给2分钟窗口
        
        # 如果窗口太短，适当扩展
        if end_sec - start_sec < 10:
            end_sec = start_sec + 30
        
        commentary = extract_asr_commentary(asr_segs, start_sec, end_sec)
        commentary = clean_asr_commentary(commentary)
        ce["asr_commentary"] = commentary
        ce["time_start"] = first_seg.get("start", "")
        ce["time_end"] = sec_to_time(end_sec)
        ce["case_info"] = extract_case_info(ce["case_lines"])
        # 主题：优先用干净板书原文参照（案例时间窗内的板行 + ASR 交叉比对）
        # ——主讲人讲的案例紧扣板书主题，参照比硬编码关键词可靠
        window_lines = []
        for seg in wb_data:
            ss = int(seg.get("start_seconds", 0))
            if start_sec - 3 <= ss <= end_sec + 3:
                for l in seg.get("lines", []):
                    wt = clean_text(fix_board_text(l["text"])).strip()
                    if wt and is_valid_knowledge_line(wt):
                        window_lines.append(wt)
        window_text = " ".join(window_lines)
        ref_topic = infer_topic_by_reference(topic_ref, window_text + " " + commentary)
        ce["topic"] = ref_topic or infer_case_topic(ce["board_lines"], commentary)
        # 获取案例对应的截图
        ce["screenshots"] = get_screenshots_for_case(start_sec, end_sec)

        # 案例主题：优先用截图类别（截图按内容命名，比板书/ASR推断更可靠）
        cat_topic = {
            "黑社会赚钱": "第九种·黑社会赚钱",
            "投资脑袋发昏": "第十三种·投资脑袋发昏",
            "老板赚钱": "第三种·老板赚钱",
            "骗子赚钱": "第四种·骗子赚钱",
            "开店赚钱": "第六种·开店赚钱",
            "权力赚钱": "第八种·权力赚钱",
            "体力赚钱": "第二种·体力赚钱",
            "贸易赚钱": "第七种·贸易赚钱",
            "偷窃抢劫": "第十四种·偷窃抢劫",
            "偏门赚钱": "第十五种·偏门赚钱",
        }
        if ce["screenshots"]:
            cat = screenshot_category(ce["screenshots"][0]["filename"])
            if cat in cat_topic:
                ce["topic"] = cat_topic[cat]

    # 6. 生成报告
    print("6. 生成报告...")
    lines = []
    lines.append("# 板书知识点解析")
    lines.append("")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("> 以下为视频板书中提取的知识点结构，并按主题整理了相关八字案例及主讲人口述分析。")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 课程大纲
    lines.append("## 一、课程大纲")
    lines.append("")
    for item in outline_items:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 知识点详解
    lines.append("## 二、知识点详解")
    lines.append("")
    
    # 按主题编号排序
    topic_order_map = {}
    for topic in active_topics:
        m = re.match(r'^第([一二三四五六七八九十]+)种', topic)
        if m:
            num_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
                       '十一':11,'十二':12,'十三':13,'十四':14,'十五':15}
            topic_order_map[topic] = num_map.get(m.group(1), 99)
        elif topic.startswith("内容"):
            topic_order_map[topic] = 0
        else:
            topic_order_map[topic] = 50
    
    for topic in sorted(active_topics.keys(), key=lambda x: topic_order_map.get(x, 99)):
        items = active_topics[topic]
        if not items:
            continue
        lines.append(f"### {topic}")
        lines.append("")
        formatted = format_board_lines(items)
        for f_line in formatted:
            lines.append(f"- {f_line}")
        lines.append("")
        
        # 添加相关案例截图（简短描述标注，限量3张）
        topic_shots = get_screenshots_for_topic(topic, items)
        if topic_shots:
            for ss in topic_shots:
                desc = screenshot_desc(ss["filename"])
                lines.append(f"**{desc}**")
                lines.append("")
                lines.append(f"![{desc}](examples/{ss['filename']})")
                lines.append("")
    
    # 其他知识点
    if other_lines:
        lines.append("### 其他知识点")
        lines.append("")
        formatted = format_board_lines(other_lines)
        for f_line in formatted:
            lines.append(f"- {f_line}")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # 案例分析
    lines.append("## 三、八字案例分析（含主讲人口述解析）")
    lines.append("")
    lines.append("> 以下案例按视频中出现顺序排列。每个案例包含八字排盘数据和主讲人的口述分析（从音频转写中提取并校正）。")
    lines.append("")
    
    for idx, ce in enumerate(case_entries):
        ci = ce["case_info"]
        time_str = format_time(ce["time_start"], ce["time_end"])
        topic = ce.get("topic", "")
        screenshots = ce.get("screenshots", [])
        
        # 案例标题：优先使用截图描述性名称（只取第一张 + 等N张，避免冗长）
        if screenshots:
            all_descs = [screenshot_desc(s["filename"]) for s in screenshots]
            if len(screenshots) == 1:
                title = all_descs[0]
            else:
                title = f"{all_descs[0]} 等{len(screenshots)}张截图"
            lines.append(f"### 案例 {idx+1}：{title}（{time_str}）")
        else:
            # 没有截图的案例，回退到原逻辑
            title_parts = []
            if ci["name"]:
                title_parts.append(ci["name"])
            if ci["solar_date"]:
                title_parts.append(ci["solar_date"])
            if topic:
                title_parts.append(topic)
            
            if title_parts:
                title = "·".join(title_parts)
                lines.append(f"### 案例 {idx+1}：{title}（{time_str}）")
            else:
                lines.append(f"### 案例 {idx+1}（{time_str}）")
        lines.append("")
        
        # 基本信息
        info_lines = []
        if ci["name"]:
            info_lines.append(f"**姓名**: {ci['name']}")
        if ci["solar_date"]:
            info_lines.append(f"**阳历**: {ci['solar_date']}")
        if ci["lunar_date"]:
            info_lines.append(f"**农历**: {ci['lunar_date']}")
        if ci["gender"]:
            info_lines.append(f"**性别**: {ci['gender']}（{'坤造' if ci['gender']=='女' else '乾造'}）")
        if topic:
            info_lines.append(f"**所属类型**: {topic}")
        
        if info_lines:
            for il in info_lines:
                lines.append(il)
            lines.append("")
        
        # 案例截图（简短描述标注，去掉分类前缀和序号）
        if screenshots:
            for ss in screenshots:
                ss_path = os.path.join(EXAMPLES_DIR, ss["filename"])
                if os.path.exists(ss_path):
                    desc = ss.get("desc") or screenshot_desc(ss["filename"])
                    lines.append(f"**{desc}**")
                    lines.append("")
                    lines.append(f"![{desc}](examples/{ss['filename']})")
                    lines.append("")
        
        # 排盘数据
        if ci["chart_data"]:
            lines.append("**八字排盘数据**:")
            lines.append("")
            lines.append("```")
            for cd in ci["chart_data"]:
                lines.append(cd)
            lines.append("```")
            lines.append("")
        
        # 主讲人口述分析
        commentary = ce.get("asr_commentary", "")
        if commentary and len(commentary) > 30:
            lines.append("**主讲人口述分析**:")
            lines.append("")
            lines.append(f"> {commentary}")
            lines.append("")
        else:
            lines.append("*（该案例时段的音频转写较短，无法提取有效分析）*")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    # 统计
    lines.append("## 四、统计信息")
    lines.append("")
    lines.append(f"- 板书总段数: {len(wb_data)}")
    lines.append(f"- 去重后案例数: {len(case_entries)}")
    lines.append(f"- ASR 转写段数: {len(asr_segs)}")
    total_commentary = sum(len(ce.get("asr_commentary", "")) for ce in case_entries)
    lines.append(f"- 案例讲解总字数: {total_commentary}")
    lines.append(f"- ASR 校正: V1={asr_data.get('corrections_v1_count',0)} + V2={asr_data.get('corrections_v2_count',0)} + V3={asr_data.get('corrections_v3_count',0)}")
    lines.append("")
    lines.append(f"*以上内容由 OCR + ASR 自动提取并交叉关联生成。*")
    
    # 写入
    report_text = "\n".join(lines)
    with open(OUTPUT_REPORT, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n报告已生成: {OUTPUT_REPORT}")
    print(f"  案例数: {len(case_entries)}")
    print(f"  讲解总字数: {total_commentary}")
    
    # 打印案例摘要
    print("\n=== 案例摘要 ===")
    for idx, ce in enumerate(case_entries):
        ci = ce["case_info"]
        commentary_len = len(ce.get("asr_commentary", ""))
        screenshots = ce.get("screenshots", [])
        if screenshots:
            name = screenshot_desc(screenshots[0]["filename"])
        else:
            name = ci["name"] or ci["solar_date"] or ci["lunar_date"] or "未命名"
        topic = ce.get("topic", "?")
        ss_count = len(screenshots)
        print(f"  {idx+1}. [{ce['time_start']}] {name} | {topic} | 讲解{commentary_len}字 | 截图{ss_count}张")
    
    return case_entries

if __name__ == "__main__":
    main()
