#!/usr/bin/env python3
"""
重命名视频目录、案例截图，并更新板书文档中的引用。
按照赚钱方式分类，每张截图标注关键特征。
"""

import os
import shutil
import re
import json

BASE_DIR = "D:/video-skill-output"

# === 1. 新的视频目录名 ===
OLD_DIRNAME = "lesson_3_1"
NEW_DIRNAME = "课程目录名（按需设置）（3-1）"
OLD_DIR = os.path.join(BASE_DIR, OLD_DIRNAME)
NEW_DIR = os.path.join(BASE_DIR, NEW_DIRNAME)

# === 2. 截图重命名映射 ===
# 格式: "旧文件名" -> "新文件名"
# 命名规则: {赚钱方式}_{关键特征描述}_{三位序号}.png
RENAME_MAP = {
    # ======== 第七种·贸易赚钱 (01:41 - 02:21) ========
    "example_005_0141.png": "贸易赚钱_八字见合合代表贸易_001.png",
    "example_006_0151.png": "贸易赚钱_驿马流通之象_002.png",
    "example_007_0201.png": "贸易赚钱_伏吟倒买倒卖_003.png",
    "example_008_0211.png": "贸易赚钱_甲寅卖甲具进货转手营卖_004.png",

    # ======== 第六种·开店赚钱 (03:11) ========
    "example_011_0311.png": "开店赚钱_贸易伏吟倒买倒卖1982年生_001.png",

    # ======== 第十四种·偷窃抢劫 (03:41 - 04:11) ========
    "example_013_0341.png": "偷窃抢劫_八字见穿刑暗合财星_001.png",
    "example_014_0351.png": "偷窃抢劫_依赖父母因偷东西进去过1986年生_002.png",
    "example_015_0401.png": "偷窃抢劫_阴湿丑土亥子水克坏火过度阴坏阳_003.png",

    # ======== 第五种·肉体赚钱 (05:01 - 06:51) ========
    "example_020_0501.png": "肉体赚钱_禄半桃花小姐1996年生_001.png",
    "example_021_0511.png": "肉体赚钱_食伤穿制财官用肉体搞男人女人_002.png",
    "example_023_0531.png": "肉体赚钱_食伤乱合多个异性鸭子2000年生_003.png",
    "example_024_0551.png": "肉体赚钱_KTV酒吧食伤乱合与多个异性1998年生_004.png",
    "example_026_0621.png": "肉体赚钱_红寅墨骗刑辛代部960万1991年生_005.png",
    "example_027_0631.png": "肉体赚钱_侵吞公款930万打赏女主播_006.png",
    "example_028_0641.png": "肉体赚钱_禄桃花食伤乱合1991年生_007.png",
    "example_029_0651.png": "肉体赚钱_食伤穿制财官偷窃抢劫并行_008.png",

    # ======== 第十五种·偏门赚钱 (07:11 - 13:01) ========
    "example_031_0711.png": "偏门赚钱_小姐改行美甲还找大哥1993年生_001.png",
    "example_032_0801.png": "偏门赚钱_食伤旺导比肩刀极男壬1990年生_002.png",
    "example_043_1041.png": "偏门赚钱_命中带劫财劫财为喜用者_003.png",
    "example_044_1051.png": "偏门赚钱_穿绝财星财星为忌神赚到钱_004.png",
    "example_045_1101.png": "偏门赚钱_做资金盘骗6000万跑路新加坡_005.png",
    "example_046_1111.png": "偏门赚钱_官穿比劫穿别人才挣钱_006.png",
    "example_047_1141.png": "偏门赚钱_日时禄刃与偏财同柱捞偏门_007.png",

    # ======== 偏门玄学 (12:41 - 13:51) ========
    "example_049_1241.png": "偏门玄学_地支辰戌丑未食伤库至少有一个_008.png",
    "example_051_1301.png": "偏门玄学_八字天干透六丁六甲_009.png",
    "example_052_1311.png": "偏门玄学_白龙王命例1937年生_010.png",
    "example_053_1321.png": "偏门玄学_陈朗八字用印制食伤_011.png",
    "example_054_1331.png": "偏门玄学_诸葛亮刘伯温命例_012.png",
    "example_055_1341.png": "偏门玄学_陈朗八字劫财正印1937年生_013.png",
    "example_056_1351.png": "偏门玄学_弦曲大师辛复印_014.png",

    # ======== 第九种·黑社会赚钱 (14:01 - 15:31) ========
    "example_057_1401.png": "黑社会赚钱_辰戌丑未多食伤库比劫库_001.png",
    "example_058_1421.png": "黑社会赚钱_阳刃穿绝十神带小弟干坏事_002.png",
    "example_059_1431.png": "黑社会赚钱_重庆黑社会大哥劫财带伤官_003.png",
    "example_060_1441.png": "黑社会赚钱_阳刃穿子重庆黑社会_004.png",
    "example_061_1451.png": "黑社会赚钱_黑社会老大取三个老婆负债半个亿_005.png",
    "example_062_1501.png": "黑社会赚钱_财星与阳刃同柱做事很绝_006.png",
    "example_063_1511.png": "黑社会赚钱_重庆正宗黑社会老大1972年生_007.png",
    "example_064_1521.png": "黑社会赚钱_带劫财辰戌丑未阴暗不可告人_008.png",
    "example_065_1531.png": "黑社会赚钱_劫财伤官遇财官不主牢狱惹官司_009.png",
    "example_066_1541.png": "黑社会赚钱_高利贷收保护费_010.png",
    "example_067_1551.png": "黑社会赚钱_劫财三官欲财官惹官非_011.png",
    "example_068_1601.png": "黑社会赚钱_劫财伤官遇财官大运有油黏合_012.png",
    "example_069_1611.png": "黑社会赚钱_十五种取财方式全讲完总结_013.png",

    # ======== 第二种·体力赚钱 (08:31 - 10:01) ========
    "example_035_0831.png": "体力赚钱_比劫多财星弱辛苦严重负债1988年生_001.png",
    "example_036_0841.png": "体力赚钱_八字不见食伤不爱动脑_002.png",
    "example_038_0901.png": "体力赚钱_无食伤没脑子司机开老板车泡妞1956年生_003.png",
    "example_039_0921.png": "体力赚钱_财多压身身弱财重富屋贫人_004.png",
    "example_041_0951.png": "体力赚钱_财重禄弱身弱财重农村祖父1979年生_005.png",
}

def rename_screenshots(examples_dir=None, rename_map=None):
    """重命名所有案例截图"""
    if rename_map is None:
        rename_map = RENAME_MAP
    if examples_dir is None:
        examples_dir = os.path.join(NEW_DIR, "whiteboard", "examples")
    if not os.path.exists(examples_dir):
        print(f"ERROR: examples dir not found: {examples_dir}")
        return

    renamed_count = 0
    for old_name, new_name in sorted(rename_map.items()):
        old_path = os.path.join(examples_dir, old_name)
        new_path = os.path.join(examples_dir, new_name)
        if os.path.exists(old_path):
            os.rename(old_path, new_path)
            renamed_count += 1
            print(f"  OK: {old_name} -> {new_name}")
        else:
            print(f"  MISS: {old_name} not found")

    print(f"\nRenamed {renamed_count}/{len(RENAME_MAP)} screenshots.\n")
    return RENAME_MAP

def update_markdown_file(filepath, rename_map):
    """更新MD文件中的截图引用"""
    if not os.path.exists(filepath):
        print(f"  SKIP: {filepath} not found")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    replacements = 0
    for old_name, new_name in rename_map.items():
        if old_name in content:
            content = content.replace(old_name, new_name)
            replacements += 1

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  Updated {filepath}: {replacements} replacements")

def update_handover_doc(new_dirname):
    """更新项目交接文档中的引用"""
    handover_path = os.path.join(BASE_DIR, "项目开发交接文档.md")
    if not os.path.exists(handover_path):
        print(f"  SKIP: {handover_path} not found")
        return

    with open(handover_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 替换所有 lesson_3_1 引用
    replacements = 0
    old_refs = [
        "lesson_3_1",
        "lesson_3_1/whiteboard",
        "lesson_3_1/asr_output",
    ]
    for old_ref in old_refs:
        new_ref = old_ref.replace("lesson_3_1", new_dirname)
        count = content.count(old_ref)
        if count > 0:
            content = content.replace(old_ref, new_ref)
            replacements += count

    with open(handover_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  Updated {handover_path}: {replacements} replacements")

def update_knowledge_points(rename_map):
    """增强板书知识点解析：用新截图名和更详细的描述"""
    kp_path = os.path.join(NEW_DIR, "whiteboard", "板书知识点解析.md")
    if not os.path.exists(kp_path):
        print(f"  SKIP: {kp_path} not found")
        return

    # 截图引用已在 update_markdown_file 中替换，这里补充描述
    with open(kp_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 为每个案例补充更详细的描述
    descriptions = {
        "贸易赚钱_八字见合合代表贸易_001.png": "八字见合，合代表贸易——做贸易要上面接供应商、下面接抢购商",
        "贸易赚钱_驿马流通之象_002.png": "八字要有驿马（甲丙庚壬寅申巳亥），驿马为流通之象",
        "贸易赚钱_伏吟倒买倒卖_003.png": "八字中伏吟之象代表倒买倒卖",
        "贸易赚钱_甲寅卖甲具进货转手营卖_004.png": "甲寅卖甲具：用印得到根基的食伤，顾客的欲望来生甲木（甲具）",

        "开店赚钱_贸易伏吟倒买倒卖1982年生_001.png": "1982年生开店案例：正官正财伏吟倒买倒卖，同时带有黑社会、依赖父母特征",

        "偷窃抢劫_八字见穿刑暗合财星_001.png": "偷窃抢劫第一特征：八字中易见穿、刑",
        "偷窃抢劫_依赖父母因偷东西进去过1986年生_002.png": "1986年生案例：依赖父母+做业务+被人骗钱+偷窃抢劫，申经冲丙寅偷别人钱财",
        "偷窃抢劫_阴湿丑土亥子水克坏火过度阴坏阳_003.png": "八字中见阴湿的丑土、亥子水去克坏火，阴坏阳过度，坑蒙拐骗",

        "肉体赚钱_禄半桃花小姐1996年生_001.png": "禄半桃花：自身禄合了子午卯酉，1996年生女命做小姐",
        "肉体赚钱_食伤穿制财官用肉体搞男人女人_002.png": "食伤穿制财官：不分别用肉体去搞男人或搞女人",
        "肉体赚钱_食伤乱合多个异性鸭子2000年生_003.png": "2000年生男命做鸭子：食伤乱合，肉体与多个异性在一起",
        "肉体赚钱_KTV酒吧食伤乱合与多个异性1998年生_004.png": "1998年生KTV酒吧女：食伤乱合、丙伤官壬正印，与多个异性",
        "肉体赚钱_红寅墨骗刑辛代部960万1991年生_005.png": "红寅墨案例：1991年生女命骗刑辛代部960万，子穿卫食伤穿财官",
        "肉体赚钱_侵吞公款930万打赏女主播_006.png": "会计侵吞公款930万打赏女主播，每周飞上海睡一觉回来",
        "肉体赚钱_禄桃花食伤乱合1991年生_007.png": "1991年生案例：禄桃花+食伤乱合，偏印正印食神配置",
        "肉体赚钱_食伤穿制财官偷窃抢劫并行_008.png": "同时带有偷窃抢劫+肉体赚钱双重特征，食伤穿制财官",

        "偏门赚钱_小姐改行美甲还找大哥1993年生_001.png": "1993年生女：做过小姐改行做美甲，一边做美甲一边摸客人大腿，还找大哥",
        "偏门赚钱_食伤旺导比肩刀极男壬1990年生_002.png": "1990年生女做鸡：食伤旺导比肩，官价格很高",
        "偏门赚钱_命中带劫财劫财为喜用者_003.png": "偏门赚钱第一特征：命中带劫财且劫财为喜用者，搞资金盘都算",
        "偏门赚钱_穿绝财星财星为忌神赚到钱_004.png": "一般穿绝财星，财星为忌神主赚到钱，若财星为喜神反主破财",
        "偏门赚钱_做资金盘骗6000万跑路新加坡_005.png": "做资金盘赚6000万跑新加坡案例：用官穿比劫，穿到别人就能挣钱",
        "偏门赚钱_官穿比劫穿别人才挣钱_006.png": "官穿比劫用来当财看，穿别人的才挣到钱",
        "偏门赚钱_日时禄刃与偏财同柱捞偏门_007.png": "日时禄刃与偏财同柱，一般是赚偏门——要么自己坐偏财，要么食伤的禄占偏财",

        "偏门玄学_地支辰戌丑未食伤库至少有一个_008.png": "吃玄学饭第一特征：地支中辰戌丑未至少有一个，要食伤库",
        "偏门玄学_八字天干透六丁六甲_009.png": "八字天干透六丁六甲——刘伯文、诸葛亮、陈朗、白龙王、邵伟华的八字都有此特征",
        "偏门玄学_白龙王命例1937年生_010.png": "白龙王1937年生命例：近代除陈朗外名气最大的玄学大师，给周星驰、梁朝伟等人看过",
        "偏门玄学_陈朗八字用印制食伤_011.png": "陈朗八字：用印制食伤的配置",
        "偏门玄学_诸葛亮刘伯温命例_012.png": "诸葛亮、刘伯温命例：六丁六甲玄学配置",
        "偏门玄学_陈朗八字劫财正印1937年生_013.png": "陈朗八字详细盘：劫财正印配置，1937年生",
        "偏门玄学_弦曲大师辛复印_014.png": "弦曲大师命例：辛复印偏印透干配置",

        "黑社会赚钱_辰戌丑未多食伤库比劫库_001.png": "八字辰戌丑未多，且在命局中扮演食伤库或比劫库——阴暗不可告人，尤其是丑和辰",
        "黑社会赚钱_阳刃穿绝十神带小弟干坏事_002.png": "用阳刃去穿绝其它十神，代表带领小弟去干坏事",
        "黑社会赚钱_重庆黑社会大哥劫财带伤官_003.png": "重庆黑社会大哥案例：劫财带伤官，被采取到局子里",
        "黑社会赚钱_阳刃穿子重庆黑社会_004.png": "用胃去穿子（阳刃穿），这种八字都有灾的",
        "黑社会赚钱_黑社会老大取三个老婆负债半个亿_005.png": "重庆正宗黑社会老大：取了三个老婆离了两次，负债半个亿，以前常把人腿挡护着",
        "黑社会赚钱_财星与阳刃同柱做事很绝_006.png": "财星与阳刃同柱，做事很绝，这种人惹到就很麻烦",
        "黑社会赚钱_重庆正宗黑社会老大1972年生_007.png": "1972年生重庆黑社会老大案例：取三个老婆，带劫财伤官",
        "黑社会赚钱_带劫财辰戌丑未阴暗不可告人_008.png": "带劫财+辰戌丑未：阴暗不可告人的东西",
        "黑社会赚钱_劫财伤官遇财官不主牢狱惹官司_009.png": "夏仲奇真传口诀：劫财伤官遇财官，不主牢狱惹官司",
        "黑社会赚钱_高利贷收保护费_010.png": "黑社会赚钱范围：诈骗、收保护费、借钱不还、放高利贷",
        "黑社会赚钱_劫财三官欲财官惹官非_011.png": "劫财三官遇财官，大运有油黏合要出事",
        "黑社会赚钱_劫财伤官遇财官大运有油黏合_012.png": "劫财伤官二人只要遇到大运有油黏合，真的要出事",
        "黑社会赚钱_十五种取财方式全讲完总结_013.png": "十五种取财方式全部讲完，视频收尾",

        "体力赚钱_比劫多财星弱辛苦严重负债1988年生_001.png": "比劫多而财星弱：赚钱不多且辛苦，严重负债——都是打工的",
        "体力赚钱_八字不见食伤不爱动脑_002.png": "八字不见食伤：食伤代表脑子灵感智慧，不带食伤之人一般不太喜欢动脑",
        "体力赚钱_无食伤没脑子司机开老板车泡妞1956年生_003.png": "1956年生案例：无食伤没脑子，趁老板下班把车子开出去泡妞",
        "体力赚钱_财多压身身弱财重富屋贫人_004.png": "财多压身为身弱财重富屋贫人——整天晚要赚钱什么都想挣但挣不了大钱",
        "体力赚钱_财重禄弱身弱财重农村祖父1979年生_005.png": "1979年生农村祖父命例：财重禄弱，种地都不动脑子赚钱",
    }

    # 在每张截图后添加描述（如果还没有描述的话）
    for new_name, desc in descriptions.items():
        # 查找引用并添加描述
        marker = f"![案例截图](examples/{new_name})"
        if marker in content:
            # 检查紧接着是否已有描述行
            enhanced = f"{marker}\n> {desc}"
            if enhanced not in content:
                content = content.replace(marker, enhanced)

    with open(kp_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Enhanced {kp_path} with detailed descriptions")

def main():
    # === 独立模式：新视频截图重命名（--examples-dir + --map-json）===
    import argparse
    ap = argparse.ArgumentParser(description="重命名案例截图")
    ap.add_argument("--examples-dir", help="目标 examples 目录（新视频用）")
    ap.add_argument("--map-json", help="RENAME_MAP 的 JSON 文件路径")
    args = ap.parse_args()

    if args.examples_dir and args.map_json:
        with open(args.map_json, "r", encoding="utf-8") as f:
            rename_map = json.load(f)
        print(f"[独立模式] 重命名截图: {args.examples_dir}")
        print(f"  映射条数: {len(rename_map)}")
        renamed = rename_screenshots(args.examples_dir, rename_map)
        print("=" * 60)
        print("DONE (独立模式)")
        print(f"Screenshots renamed: {len(renamed) if renamed else 0}/{len(rename_map)}")
        print("=" * 60)
        return

    print("=" * 60)
    print("视频资产管理：重命名目录、截图，更新文档")
    print("=" * 60)

    # Step 1: Verify directory (already copied via PowerShell)
    print(f"\n[Step 1] Verify directory")
    print(f"  From: {OLD_DIR}")
    print(f"  To:   {NEW_DIR}")
    if os.path.exists(NEW_DIR):
        print("  OK: Target directory exists")
    else:
        print("  ERROR: Target directory not found")
        return

    # Step 2: Rename screenshots
    print(f"\n[Step 2] Rename screenshots")
    rename_map = rename_screenshots()

    # Build reverse map for file list
    new_names_list = sorted(rename_map.values())

    # Step 3: Update 板书知识点解析.md
    print(f"\n[Step 3] Update 板书知识点解析.md")
    board_kp = os.path.join(NEW_DIR, "whiteboard", "板书知识点解析.md")
    update_markdown_file(board_kp, rename_map)
    update_knowledge_points(rename_map)

    # Step 4: Update 板书原文字汇总.md
    print(f"\n[Step 4] Update 板书原文字汇总.md")
    board_summary = os.path.join(NEW_DIR, "whiteboard", "板书原文字汇总.md")
    update_markdown_file(board_summary, rename_map)

    # Step 5: Update 项目开发交接文档.md
    print(f"\n[Step 5] Update 项目开发交接文档.md")
    update_handover_doc(NEW_DIRNAME)

    # Step 6: Generate asset manifest
    print(f"\n[Step 6] Generate asset manifest")
    manifest_path = os.path.join(NEW_DIR, "资产清单.md")
    manifest_lines = [
        f"# {NEW_DIRNAME} — 资产清单",
        "",
        f"生成时间: 2026-08-08",
        "视频时长: 16:11",
        "视频主题: 课程主题示例（命理取财方式）",
        "",
        "## 视频简介",
        "",
        "示例：本讲为某命理课程，系统讲解取财方式判断口诀与命例。",
        "涵盖技术、体力、老板、骗子、肉体、开店、贸易、权力、黑社会、依赖父母、做业务、",
        "被人骗钱、投资脑袋发昏赔钱、偷窃抢劫、偏门（股票投机赌博）共十五种赚钱方式。",
        "每种方式配有至少一个真实八字案例，部分案例配有多个时间点的板书截图。",
        "",
        "## 文件结构",
        "",
        "```",
        f"{NEW_DIRNAME}/",
        "├── audio.wav                          # 视频提取的音频 (16分钟)",
        "├── 资产清单.md                        # 本文件",
        "├── asr_output/                       # ASR语音转写结果",
        "│   ├── transcript_plain.txt           # 纯文本无时间戳",
        "│   ├── transcript_corrected.txt       # 术语校正版（带时间戳）",
        "│   ├── transcript_raw.txt             # 原始转写（带时间戳）",
        "│   ├── transcript.srt                 # SRT字幕",
        "│   └── transcript_segments.json       # 结构化JSON+校正日志",
        "└── whiteboard/                        # 板书提取结果",
        "    ├── 板书原文字汇总.md              # 61段板书纯文字",
        "    ├── 板书知识点解析.md              # 结构化知识点+案例截图+详细描述",
        "    ├── whiteboard_data.json           # 原始OCR数据",
        "    ├── whiteboard_data_improved.json  # 优化后OCR数据（去水印+行合并）",
        "    ├── frames/                        # 979张关键帧原图",
        "    └── examples/                      # 48张案例截图（已按内容命名）",
        "```",
        "",
        "## 案例截图索引",
        "",
        "| 序号 | 文件名 | 所属知识点 |",
        "|------|--------|-----------|",
    ]

    # Group by category
    categories_order = [
        "贸易赚钱", "开店赚钱", "偷窃抢劫", "肉体赚钱",
        "偏门赚钱", "偏门玄学", "黑社会赚钱", "体力赚钱"
    ]
    current_cat = None
    for name in new_names_list:
        cat = name.split("_")[0]
        if cat in ["偏门赚钱", "偏门玄学"]:
            cat_display = "第十五种·偏门赚钱/偏门玄学"
        elif cat in ["黑社会赚钱"]:
            cat_display = "第九种·黑社会赚钱"
        elif cat in ["体力赚钱"]:
            cat_display = "第二种·体力赚钱"
        elif cat in ["肉体赚钱"]:
            cat_display = "第五种·肉体赚钱"
        elif cat in ["开店赚钱"]:
            cat_display = "第六种·开店赚钱"
        elif cat in ["贸易赚钱"]:
            cat_display = "第七种·贸易赚钱"
        elif cat in ["偷窃抢劫"]:
            cat_display = "第十四种·偷窃抢劫"
        else:
            cat_display = cat

        if cat_display != current_cat:
            current_cat = cat_display
            manifest_lines.append(f"| | **{cat_display}** | |")

        # Extract number
        num_match = re.search(r'_(\d+)\.png$', name)
        num = num_match.group(1) if num_match else "?"
        # Extract description
        desc_match = re.search(r'_{(.+?)}_', name)
        if not desc_match:
            # manual extraction
            parts = name.replace(".png", "").split("_")
            desc = "_".join(parts[1:]) if len(parts) > 1 else name
        else:
            desc = desc_match.group(1)
        # Better: just strip the category prefix and number suffix
        desc = name.replace(cat + "_", "").replace(f"_{num}.png", "").replace(".png", "")

        manifest_lines.append(f"| {num} | {name} | {desc} |")

    manifest_lines += [
        "",
        "---",
        f"*共 {len(new_names_list)} 张案例截图，按赚钱方式分类命名*",
    ]

    with open(manifest_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(manifest_lines))
    print(f"  Created {manifest_path}")

    print("\n" + "=" * 60)
    print("ALL DONE!")
    print(f"New directory: {NEW_DIR}")
    print(f"Screenshots renamed: {len(rename_map)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
