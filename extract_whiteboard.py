#!/usr/bin/env python3
"""
视频板书提取器 - extract_whiteboard.py
从教学视频中抽关键板书帧 → OCR 识别 → 汇总板书全文

用法:
    python extract_whiteboard.py <video_path> [--output OUTPUT_DIR]
    python extract_whiteboard.py "D:/videos/lesson01.mp4"
    python extract_whiteboard.py "D:/videos/lesson01.mp4" --output ./result_lesson01
"""

import os

# 必须在导入 paddle 之前禁用 oneDNN（Windows CPU 兼容性修复）
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("KMP_AFFINITY", "disabled")
os.environ.setdefault("OMP_NUM_THREADS", "4")

import argparse
import json
import subprocess
import sys
import shutil
import time
import hashlib
from pathlib import Path
from datetime import timedelta


def get_ffmpeg_path():
    """获取 ffmpeg 路径：优先 imageio-ffmpeg 自带二进制，其次系统 PATH"""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.isfile(exe):
            return exe
    except ImportError:
        pass
    return "ffmpeg"


def get_video_duration(video_path):
    """用 ffmpeg 解析视频时长（不需要 ffprobe）"""
    import re
    try:
        ffmpeg = get_ffmpeg_path()
        r = subprocess.run(
            [ffmpeg, "-i", video_path],
            capture_output=True, text=True
        )
        stderr = r.stderr or r.stdout
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
    except Exception:
        pass
    return 0


def check_deps():
    """检查必要依赖"""
    missing = []
    try:
        subprocess.run([get_ffmpeg_path(), "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        missing.append("imageio-ffmpeg (pip install imageio-ffmpeg)")

    for mod, pkg in [("PIL", "Pillow"), ("cv2", "opencv-python-headless"), ("rapidocr_onnxruntime", "rapidocr-onnxruntime")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"缺少依赖: {', '.join(missing)}")
        print(f"安装命令: pip install {' '.join(m for m in missing if 'ffmpeg' not in m.lower())} imageio-ffmpeg")
        return False
    return True


def parse_timestamp(frame_name, fps):
    """从帧文件名推算时间戳。帧名如 frame_00042.png, 每秒 fps 帧"""
    base = os.path.splitext(frame_name)[0]
    parts = base.replace("frame_", "").split("_")
    try:
        frame_idx = int(parts[0])
    except (ValueError, IndexError):
        return 0
    return frame_idx / fps


def format_ts(seconds):
    """秒 → HH:MM:SS 或 MM:SS"""
    td = timedelta(seconds=int(seconds))
    total = int(td.total_seconds())
    h, m = divmod(total, 3600)
    m, s = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def str_similarity(a, b):
    """两个字符串的 Jaccard 相似度（字符级）"""
    if not a or not b:
        return 0.0
    set_a = set(a.replace(" ", ""))
    set_b = set(b.replace(" ", ""))
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


# 案例帧检测关键词：只要关键帧 OCR 中出现这些词，就认为当前在讲八字案例
EXAMPLE_KEYWORDS = [
    "坤造", "乾造", "出生时间", "出生于", "专业版", "阳历", "农历",
    "年柱", "月柱", "日柱", "时柱", "长生", "空亡", "十神", "七杀", "正官",
    "偏财", "正财", "食神", "伤官", "比肩", "劫财", "正印", "偏印"
]


def detect_example(lines_text):
    """判断 OCR 文本是否包含八字案例特征。返回命中的关键词列表"""
    full = " ".join(lines_text)
    hits = [kw for kw in EXAMPLE_KEYWORDS if kw in full]
    return hits


# ======================================================================
# 阶段 1：ffmpeg 抽帧
# ======================================================================
def extract_frames(video_path, output_dir, fps=1):
    """
    用 ffmpeg 按固定 fps 抽帧，输出为 frame_00001.png 等
    返回 (帧总数, 视频时长秒数)
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/4] 抽帧中 (fps={fps})...")

    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", f"fps={fps},scale=960:-1",
        "-q:v", "3",
        "-threads", str(os.cpu_count() or 4),
        os.path.join(output_dir, "frame_%05d.png")
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ffmpeg 错误:\n{result.stderr}")
        sys.exit(1)

    frames = sorted([f for f in os.listdir(output_dir) if f.endswith(".png")])
    total = len(frames)
    print(f"  共抽出 {total} 帧")

    # 获取视频时长
    duration = get_video_duration(video_path)
    if duration == 0:
        duration = total / fps

    return total, duration, frames


# ======================================================================
# 阶段 2：帧差异检测，只保留板书变化的帧
# ======================================================================
def compute_phash(img_path, hash_size=16):
    """计算感知哈希 (pHash)，用于检测图像内容变化"""
    import numpy as np
    from PIL import Image
    img = Image.open(img_path).convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = np.array(img).flatten().tolist()
    rows = [pixels[i * (hash_size + 1):(i + 1) * (hash_size + 1)] for i in range(hash_size)]
    diff = []
    for row in rows:
        for col in range(hash_size):
            diff.append(row[col] > row[col + 1])
    return sum(2 ** i for i, v in enumerate(diff) if v)


def hamming_distance(h1, h2):
    return bin(h1 ^ h2).count("1")


def detect_keyframes(frames_dir, frames, fps, min_gap_sec=10, diff_threshold=12):
    """
    检测板书变化的关键帧。
    - min_gap_sec: 两次变化之间至少间隔 N 秒（避免同一页 PPT 的过渡动画被多次捕捉）
    - diff_threshold: 哈希汉明距离阈值，低于此值视为相同页面
    返回: [(帧文件名, 时间戳秒)]
    """
    print(f"[2/4] 检测板书变化帧...")

    # 先抽掉中间大部分帧，只每隔 min_gap_sec * fps 帧比较一次
    # 这样大幅减少计算量，而且板书变化不会太频繁
    compare_step = max(1, int(min_gap_sec * fps))
    keyframes = []
    prev_hash = None

    for i in range(0, len(frames), compare_step):
        fname = frames[i]
        fpath = os.path.join(frames_dir, fname)
        ts = parse_timestamp(fname, fps)

        try:
            cur_hash = compute_phash(fpath)
        except Exception as e:
            print(f"  跳过 {fname}: {e}")
            continue

        if prev_hash is not None:
            dist = hamming_distance(prev_hash, cur_hash)
            if dist >= diff_threshold:
                keyframes.append((fname, ts))
                print(f"  板书变化 @ {format_ts(ts)} (hash dist={dist})")
        else:
            # 第一帧一定保留
            keyframes.append((fname, ts))

        prev_hash = cur_hash

    print(f"  保留 {len(keyframes)} 个关键帧（共 {len(frames)} 帧）")
    return keyframes


# ======================================================================
# 阶段 3：RapidOCR 识别
# ======================================================================
def ocr_keyframes(frames_dir, keyframes, verbose=True):
    """
    对关键帧做 OCR（使用 RapidOCR，基于 ONNX Runtime，模型从国内 CDN 下载）。
    返回: [(帧文件名, 时间戳, [{text, confidence, box}...], 案例命中词列表)]
    """
    print("[3/4] OCR 识别关键帧（RapidOCR）...")

    from ocr_v6 import RapidOCR
    engine = RapidOCR()
    print(f"  RapidOCR 引擎就绪")

    results = []
    example_count = 0
    total = len(keyframes)
    for idx, (fname, ts) in enumerate(keyframes):
        fpath = os.path.join(frames_dir, fname)
        try:
            raw_result, _ = engine(fpath)
        except Exception as e:
            print(f"  [{idx+1}/{total}] OCR 失败 {fname}: {e}")
            results.append((fname, ts, [], []))
            continue

        # RapidOCR 返回 [[box, text, score], ...] 或 None
        lines = []
        if raw_result:
            for item in raw_result:
                text = item[1].strip() if item[1] else ""
                score = float(item[2]) if len(item) > 2 else 0.0
                if len(text) >= 2 and score > 0.5:
                    lines.append({"text": text, "confidence": round(score, 3)})

        # 案例帧检测
        example_hits = detect_example([l["text"] for l in lines])
        is_example = len(example_hits) >= 1
        if is_example:
            example_count += 1

        if verbose:
            if lines:
                preview = " | ".join(l["text"][:30] for l in lines[:3])
                tag = " [案例]" if is_example else ""
            else:
                preview, tag = "(无文字)", ""
            print(f"  [{idx+1}/{total}] {fname} @ {format_ts(ts)}:{tag} {preview} ({len(lines)} 行)")

        results.append((fname, ts, lines, example_hits))

    print(f"  共识别 {len(results)} 个关键帧，其中 {example_count} 个疑似案例帧")
    return results


# ======================================================================
# 阶段 4：去重 + 汇总输出
# ======================================================================
def deduplicate_and_summarize(ocr_results, fps, text_sim_threshold=0.85):
    """
    把 OCR 结果去重：相邻的关键帧如果文本高度重复（相似度 > threshold），合并为一段。
    返回结构化列表。
    """
    print("[4/4] 去重 & 汇总...")

    if not ocr_results:
        return []

    merged = []
    current = {
        "start_ts": ocr_results[0][1],
        "end_ts": ocr_results[0][1],
        "frame": ocr_results[0][0],
        "text_lines": [],
        "example_hits": set()
    }

    for i, (fname, ts, lines, example_hits) in enumerate(ocr_results):
        lines_text = [l["text"] for l in lines]
        all_text = "\n".join(lines_text)

        if not current["text_lines"]:
            current["text_lines"] = lines
            current["start_ts"] = ts
            current["end_ts"] = ts
            current["frame"] = fname
            current["example_hits"] = set(example_hits)
            continue

        prev_text = " ".join(l["text"] for l in current["text_lines"])
        curr_text = " ".join(lines_text)

        similarity = str_similarity(prev_text, curr_text)

        if similarity < text_sim_threshold:
            # 板书变了，保存前一段，开新段
            current["example_hits"] = list(current["example_hits"])
            merged.append(current)
            current = {
                "start_ts": ts,
                "end_ts": ts,
                "frame": fname,
                "text_lines": lines,
                "example_hits": set(example_hits)
            }
        else:
            # 同一页板书，延伸时间
            current["end_ts"] = ts
            if len(lines) > len(current["text_lines"]):
                current["text_lines"] = lines  # 保留行数更多的版本
            current["example_hits"] |= set(example_hits)
            current["frame"] = fname

    current["example_hits"] = list(current["example_hits"])
    merged.append(current)
    print(f"  合并后共 {len(merged)} 段板书")
    return merged


def save_output(merged, video_name, output_dir, frames_dir):
    """输出 Markdown 汇总 + JSON 结构化数据 + 案例截图"""
    os.makedirs(output_dir, exist_ok=True)
    examples_dir = os.path.join(output_dir, "examples")
    os.makedirs(examples_dir, exist_ok=True)

    example_total = sum(1 for seg in merged if seg.get("example_hits"))

    # --- Markdown ---
    md_path = os.path.join(output_dir, "whiteboard_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {video_name} - 板书汇总\n\n")
        f.write(f"提取时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"共 {len(merged)} 段板书，其中 {example_total} 段含八字案例\n\n---\n\n")

        for idx, seg in enumerate(merged, 1):
            start = format_ts(seg["start_ts"])
            end = format_ts(seg["end_ts"])
            duration = seg["end_ts"] - seg["start_ts"]
            example_hits = seg.get("example_hits", [])
            example_tag = " [含八字案例]" if example_hits else ""

            f.write(f"## 第 {idx} 段板书  ({start} - {end}, 约 {int(duration)}s){example_tag}\n\n")
            for line in seg["text_lines"]:
                f.write(f"- {line['text']}\n")
            if example_hits:
                f.write(f"\n**案例特征词:** {', '.join(example_hits)}\n")
                example_file = f"example_{idx:03d}_{start.replace(':', '')}.png"
                f.write(f"**案例截图:** `{example_file}`\n")
            f.write("\n---\n\n")

    print(f"\n  Markdown 已保存: {md_path}")

    # --- JSON ---
    json_path = os.path.join(output_dir, "whiteboard_data.json")
    json_out = []
    for idx, seg in enumerate(merged, 1):
        start = format_ts(seg["start_ts"])
        example_file = None
        if seg.get("example_hits"):
            example_file = f"example_{idx:03d}_{start.replace(':', '')}.png"
            src = os.path.join(frames_dir, seg["frame"])
            dst = os.path.join(examples_dir, example_file)
            try:
                shutil.copy2(src, dst)
            except Exception as e:
                print(f"  复制案例截图失败 {src}: {e}")

        json_out.append({
            "section": seg.get("section", ""),
            "start": start,
            "end": format_ts(seg["end_ts"]),
            "start_seconds": round(seg["start_ts"], 1),
            "end_seconds": round(seg["end_ts"], 1),
            "frame": seg["frame"],
            "is_example": bool(seg.get("example_hits")),
            "example_hits": seg.get("example_hits", []),
            "example_image": example_file,
            "lines": [{"text": l["text"], "confidence": l["confidence"]} for l in seg["text_lines"]]
        })

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_out, f, ensure_ascii=False, indent=2)

    print(f"  JSON 已保存: {json_path}")
    print(f"  案例截图目录: {examples_dir} ({example_total} 张)")
    return md_path, json_path, examples_dir


# ======================================================================
# 主入口
# ======================================================================
def main():
    parser = argparse.ArgumentParser(description="视频板书提取器")
    parser.add_argument("video", help="视频文件路径")
    parser.add_argument("--output", "-o", default=None, help="输出目录（默认自动生成）")
    parser.add_argument("--fps", type=int, default=1, help="抽帧 fps (默认 1)")
    parser.add_argument("--min-gap", type=int, default=10, help="板书变化最小间隔秒数 (默认 10)")
    parser.add_argument("--diff-threshold", type=int, default=8, help="哈希差异阈值 (默认 8, 越小越敏感)")
    parser.add_argument("--sim-threshold", type=float, default=0.85, help="文本合并相似度阈值 (默认 0.85)")
    parser.add_argument("--keep-frames", action="store_true", help="保留全部中间帧（默认只留关键帧）")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        print(f"视频文件不存在: {args.video}")
        sys.exit(1)

    # 输出目录
    video_name = os.path.splitext(os.path.basename(args.video))[0]
    base_dir = args.output or os.path.join("D:/video-skill-output", video_name)
    frames_dir = os.path.join(base_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  视频板书提取器")
    print(f"  输入: {args.video}")
    print(f"  输出: {base_dir}")
    print(f"{'='*60}\n")

    # 1. 抽帧（如果已缓存则跳过）
    existing = sorted([f for f in os.listdir(frames_dir) if f.endswith(".png")]) if os.path.isdir(frames_dir) else []
    if existing and len(existing) > 10:
        print(f"[1/4] 检测到 {len(existing)} 帧已缓存，跳过抽帧")
        frames = existing
        total = len(existing)
        duration = get_video_duration(args.video) or (total / args.fps)
    else:
        total, duration, frames = extract_frames(args.video, frames_dir, fps=args.fps)
    print(f"  视频时长: {format_ts(duration)} ({int(duration)}s), 总帧数: {total}\n")

    # 2. 检测板书变化
    keyframes = detect_keyframes(
        frames_dir, frames, args.fps,
        min_gap_sec=args.min_gap,
        diff_threshold=args.diff_threshold
    )

    if not keyframes:
        print("未检测到任何板书变化")
        sys.exit(1)

    # 3. OCR
    ocr_results = ocr_keyframes(frames_dir, keyframes)

    # 4. 去重 & 汇总
    merged = deduplicate_and_summarize(ocr_results, args.fps, args.sim_threshold)

    # 5. 输出
    md_path, json_path, examples_dir = save_output(merged, video_name, base_dir, frames_dir)

    print(f"\n{'='*60}")
    print(f"  完成！")
    print(f"  板书 Markdown: {md_path}")
    print(f"  结构化 JSON:  {json_path}")
    print(f"  案例截图目录: {examples_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if not check_deps():
        sys.exit(1)
    main()
