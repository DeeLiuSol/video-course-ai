# CHANGELOG

## v1.0.0 (2026-08-11)
### 新增
- 讲解视频内容提取框架：视频抽帧+OCR 板书 → ASR 听译 → 术语词典三层校正 → 关键帧分析（稳定板面+跨帧共识投票）→ 报告生成
- 核心脚本：extract_whiteboard / improve_board / transcribe_whispercpp / reapply_asr_correction / board_fluency_check / generate_board_pages / generate_case_analysis / rename_assets
- 词典 schema 样例（glossary.schema.json，不含领域内容）
- MIT License
