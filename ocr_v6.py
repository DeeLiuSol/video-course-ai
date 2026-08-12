# -*- coding: utf-8 -*-
"""
PP-OCRv6 OCR 兼容包装（高质量版）

对外提供与旧版 rapidocr_onnxruntime 相同的 API：
    ocr = RapidOCR()
    result, _ = ocr(img_path_or_ndarray)
    result = [[box, text, score], ...]  或 None

内部使用新版 rapidocr 包。档位通过环境变量 OCR_V6_TIER 选择：
    small  (默认)  PP-OCRv6_small，精度 81.3%，快
    medium         PP-OCRv6_medium（服务端档），精度 83.2%，CPU 仍流畅
medium 模型放在 D:/workbuddy-data/models/rapidocr/。
"""
import os
import numpy as np

MODEL_DIR = r"D:/workbuddy-data/models/rapidocr"
TIERS = {
    "small": {},  # 使用 rapidocr 包内置 small 模型
    "medium": {
        "Det.model_path": os.path.join(MODEL_DIR, "PP-OCRv6_det_medium.onnx"),
        "Rec.model_path": os.path.join(MODEL_DIR, "PP-OCRv6_rec_medium.onnx"),
    },
}


class RapidOCR:
    def __init__(self, *args, **kwargs):
        import rapidocr
        tier = os.environ.get("OCR_V6_TIER", "small").lower()
        params = TIERS.get(tier, {})
        self._engine = rapidocr.RapidOCR(params=params if params else None)

    def __call__(self, img_content, *args, **kwargs):
        """兼容旧 API：返回 ([[box, text, score], ...] or None, None)"""
        out = self._engine(img_content)
        if out is None:
            return None, None
        boxes = getattr(out, "boxes", None)
        txts = getattr(out, "txts", None)
        scores = getattr(out, "scores", None)
        if txts is None:
            return None, None
        result = []
        n = len(txts)
        for i in range(n):
            # 转成原生 Python 类型，保证 JSON 可序列化（兼容旧API）
            box = None
            if boxes is not None and i < len(boxes):
                try:
                    box = [[float(p[0]), float(p[1])] for p in boxes[i]]
                except Exception:
                    box = None
            score = float(scores[i]) if scores is not None and i < len(scores) else 0.0
            result.append([box, str(txts[i]), score])
        return result, None
