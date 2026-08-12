# 讲解视频内容提取框架（VideoCourseAI）

从"无字幕、有板书的讲解视频"自动提取：**板书文字 OCR**、**语音听译（ASR）**、**术语词典校正**、**关键帧信息分析**，产出结构化报告。

已实际用于命理课程（八字取财方式），同一流程可扩展应用到中医、法律、金融等任何领域的讲解/直播视频。

## 功能模块

| 模块 | 脚本 | 说明 |
|------|------|------|
| 视频抽帧 + OCR | `extract_whiteboard.py` + `ocr_v6.py` | pHash 去重 + PP-OCRv6 识别板书文字 |
| 板书后处理 | `improve_board.py` | OCR 字符纠错 + 水印过滤 + 板书/非板书分离 + 断行修复 |
| **语音听译** | `transcribe_whispercpp.py` | whisper.cpp large-v3-turbo 贪心解码（不依赖 torch） |
| **术语词典校正** | `reapply_asr_correction.py` | 三层校正：V1精确映射 + V2上下文规则 + V3组合术语（词典见 `glossary.schema.json`） |
| **关键帧分析** | `board_fluency_check.py` + `generate_board_pages.py` | 稳定板面挑选（完整度分数局部最高）+ 跨帧共识投票修正单帧 OCR 认错 + 合并重复 |
| 报告生成 | `generate_case_analysis.py` | 知识点详解 + 案例 + 主讲人口述分析（示例领域：命理） |
| 截图重命名 | `rename_assets.py` | 案例截图按内容命名 |
| 识图（可选） | `vision_qwen.py` | Qwen-VL 视觉大模型 |

## 核心特性（解决的实际问题）

1. **稳定板面挑选**：视频板面滚动/擦写的中间态（60 段）→ 用"板书完整度分数局部最高点"挑出稳定板面（6-8 页），复现人工"挑好时机截图"
2. **跨帧共识投票**：单帧 OCR 整行认错（如 `身浊灼吐` vs 正确 `身强财旺`）字符串补全救不回，用"同槽位取多数帧版本"投票纠正
3. **术语词典校正**：whisper 对专业术语天生弱，词典驱动三层校正大幅提升准确率（词典格式见 `glossary.schema.json`）
4. **板书/非板书分离**：OCR 混入的图表数据分离，不污染正文

## 快速开始

```bash
# 依赖：video-skill venv（OCR/报告）+ whisper312 venv（ASR），见 requirements.txt
V=示例课程号
OUT="D:/video-skill-output/<课程>/"

# 1. 抽帧 + OCR 板书
cd "<视频目录>"
OCR_V6_TIER=small python extract_whiteboard.py "./<视频>.mp4" --output "$OUT/whiteboard" --min-gap 10 --diff-threshold 8 --keep-frames

# 2. 板书后处理
python improve_board.py "$OUT/whiteboard/whiteboard_data.json" --output "$OUT/whiteboard/whiteboard_data_improved.json" --frames "$OUT/whiteboard/frames"

# 3. ASR 听译 + 词典校正
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
