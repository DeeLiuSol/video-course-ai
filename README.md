# 讲解视频内容提取框架（VideoCourseAI）

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](requirements.txt)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/DeeLiuSol/video-course-ai/pulls)

面向**讲解/教学/直播视频**的一站式内容提取框架：从视频中自动提取**板书文字（OCR）**、**语音听译（ASR）**、**字幕/文稿解析**，并用**领域术语词典**做校正，产出结构化报告。

已实际用于命理课程（八字取财方式讲解），同一框架可扩展到中医、法律、金融等任何领域的讲解/直播视频。

---

## 能力矩阵（支持 4 种视频形态）

| 视频形态 | 处理方式 | 关键产出 |
|---------|---------|---------|
| **无字幕 + 有板书** | 板书 OCR + 语音 ASR 听译 | 板书原文 + 听译文本 + 术语校正 |
| **无字幕 + 无板书** | 纯语音 ASR 听译 | 听译文本 + 术语校正 |
| **有字幕** | 直接解析已有字幕（跳过 ASR） | 字幕文本 + 术语校正 |
| **有原始听译文稿** | 文稿直接作为文本源 / 词典参考 | 结构化文本 + 术语词典反哺 |

> 核心优势：**领域术语词典三层校正**——whisper 等通用 ASR 对专业术语（命理/中医/法律）天生识别弱，本框架用词典驱动纠错大幅提升准确率。

## 架构总览

```
┌──────────────┐   ┌──────────────────┐   ┌─────────────────────┐
│  输入视频      │   │  内容提取层        │   │  词典校正层           │
│  无字幕有板书   │──▶│  ├ 抽帧+OCR(板书)  │──▶│  V1 精确映射          │
│  无字幕无板书   │   │  ├ ASR 听译(语音)  │   │  V2 上下文规则        │
│  有字幕/文稿   │   │  └ 字幕/文稿解析   │   │  V3 组合术语          │
└──────────────┘   └──────────────────┘   └─────────────────────┘
                                              │
                              ┌───────────────┴──────────────┐
                              ▼                              ▼
                    ┌──────────────────┐            ┌──────────────────┐
                    │  关键帧分析       │            │  报告生成         │
                    │  稳定板面挑选      │            │  知识点+案例       │
                    │  跨帧共识投票      │            │  +主讲人口述      │
                    └──────────────────┘            └──────────────────┘
```

## 功能模块

| 模块 | 脚本 | 说明 |
|------|------|------|
| 视频抽帧 + OCR 板书 | `extract_whiteboard.py` + `ocr_v6.py` | pHash 去重 + PP-OCRv6 识别板书文字 |
| 板书后处理 | `improve_board.py` | OCR 字符纠错 + 水印过滤 + 板书/非板书分离 + 断行修复 |
| **语音听译（ASR）** | `transcribe_whispercpp.py` | whisper.cpp large-v3-turbo 贪心解码（不依赖 torch，AMD CPU 可用） |
| **字幕/文稿解析** | `parse_subtitles.py` | 解析已有字幕/文稿（.srt/.vtt/.ass/.txt）→ 标准分段 JSON，无需 ASR 即接入词典校正与下游分析 |
| **术语词典校正** | `reapply_asr_correction.py` | 三层校正：V1精确映射 + V2上下文规则 + V3组合术语（词典格式见 `glossary.schema.json`） |
| 关键帧/板面分析 | `board_fluency_check.py` + `generate_board_pages.py` | 稳定板面挑选 + 跨帧共识投票修正单帧 OCR 认错 + 合并重复 |
| 报告生成 | `generate_case_analysis.py` | 知识点详解 + 案例 + 主讲人口述分析（示例领域：命理） |
| 截图重命名 | `rename_assets.py` | 案例截图按内容命名 |
| 识图（可选） | `vision_qwen.py` | Qwen-VL 视觉大模型，处理板面/图表 |

## 核心特性（解决的实际问题）

1. **稳定板面挑选**：视频板面滚动/擦写的中间态（60 段）→ 用"板书完整度分数局部最高点"挑出稳定板面（6-8 页），复现人工"挑好时机截图"
2. **跨帧共识投票**：单帧 OCR 整行认错（如 `身浊灼吐` vs 正确 `身强财旺`）字符串补全救不回，用"同槽位取多数帧版本"投票纠正
3. **术语词典三层校正**：whisper 对专业术语弱，词典驱动三层校正大幅提升准确率（词典格式见 `glossary.schema.json`，领域词典自行填充）
4. **板书/非板书分离**：OCR 混入的图表/排盘数据分离，不污染正文
5. **多形态适配**：无字幕有板书（OCR+ASR）/ 无字幕无板书（纯 ASR）/ 有字幕（直接解析）/ 有文稿（作词典参考）

## 交叉对比（Cross-Reference）⭐

讲解视频里各信息源**互相关联**——主讲人口述紧扣板书、案例紧扣当前讲解主题、字幕/文稿是可靠文本源。本框架利用这种关联做交叉验证：

| 交叉对比 | 做法 | 价值 |
|---------|------|------|
| **案例 ↔ 板书主题** | 用干净板书原文构建"第X种→要点"参照表；案例按"时间窗内板行 + 主讲人口述"与参照表交叉比对，命中要点最多的主题即归属 | 案例自动归类到正确主题（替代硬编码关键词猜） |
| **板书原文 ↔ ASR 听译** | 主讲人念的多是板书原句；用板书参照做 ASR 误听纠正（如 `乱合→乱和`、`肉体→陆体`） | 大幅减少听译人工后处理 |
| **字幕/文稿 ↔ 词典** | 有字幕/文稿的视频，其文本直接作为校正源并可反哺领域词典 | 词典越用越准 |

> 核心思路：**板面文字是讲解的"可靠锚点"**，用它校准其它弱信号（ASR 误听、单帧 OCR 认错、案例归属），而不是各自孤立处理。

## 快速开始

```bash
# 依赖：video-skill venv（OCR/报告）+ whisper312 venv（ASR），见 requirements.txt
V=示例课程号
OUT="D:/video-skill-output/<课程>/"

# 1. 抽帧 + OCR 板书（无字幕有板书的视频）
cd "<视频目录>"
OCR_V6_TIER=small python extract_whiteboard.py "./<视频>.mp4" --output "$OUT/whiteboard" --min-gap 10 --diff-threshold 8 --keep-frames

# 2. 板书后处理
python improve_board.py "$OUT/whiteboard/whiteboard_data.json" --output "$OUT/whiteboard/whiteboard_data_improved.json" --frames "$OUT/whiteboard/frames"

# 3. 文本源：有字幕/文稿 → 解析（跳过 ASR）；无字幕 → ASR 听译，然后统一词典校正
# 3a. 有字幕/文稿（如 video.srt）
python parse_subtitles.py --subtitle video.srt --output "$OUT/asr_output" --glossary glossary.json
# 3b. 无字幕 → ASR 听译
python transcribe_whispercpp.py "$OUT/audio.wav" --glossary glossary.json --model large-v3-turbo --output "$OUT/asr_output" --threads 8
python reapply_asr_correction.py "$OUT/asr_output" --glossary glossary.json

# 4. 关键帧分析（稳定板面 + 共识投票）
python board_fluency_check.py "$V" --fix
python generate_board_pages.py "$V"

# 5. 报告生成
python generate_case_analysis.py --wb-dir "$OUT/whiteboard" --asr-dir "$OUT/asr_output"
```

## 目录/路径说明

- 脚本内 `OUTPUT_ROOT` / `OUTPUT_DIR` / `WB_DIR` 等硬编码了本机输出路径（`D:\video-skill-output\...`），**发布后需按你的环境调整**
- 词典 `glossary.json` 为领域专属（命理/中医/法律各有各的术语），本项目不附完整词典，格式见 `glossary.schema.json`
- 提取出的课程内容（板书/口述）属原课程版权，**请勿随代码发布**

## License

[MIT](LICENSE)
