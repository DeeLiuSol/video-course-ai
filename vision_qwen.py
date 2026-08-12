# -*- coding: utf-8 -*-
"""
识图模块：调用阿里云百炼（DashScope / Model Studio）Qwen-VL 视觉大模型，让文本模型能"看图"。

- 模型: qwen-vl-max（质量最高）/ qwen-vl-plus（便宜快）
- 零第三方依赖（仅 urllib / base64 / json），任何 Python 环境可直接跑
- 配置读取顺序:
    Key  : 环境变量 DASHSCOPE_API_KEY > 配置文件 D:/workbuddy-data/dashscope_cfg.json
    端点 : 环境变量 DASHSCOPE_ENDPOINT > 配置文件(无则用官方默认)

用法:
    python vision_qwen.py <图片路径> [提示词]
    python vision_qwen.py --save-key sk-xxx --endpoint https://.../compatible-mode/v1
    import vision_qwen; vision_qwen.analyze_image("a.png", "读出排盘")
"""
import os, sys, json, base64, urllib.request, time

CFG = r"D:\workbuddy-data\dashscope_cfg.json"
DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
FREE_DAYS = 90          # 新用户免费额度有效期（天）
MODELS = ["qwen-vl-max", "qwen-vl-plus", "qwen2.5-vl-72b-instruct"]


def load_config():
    """返回 (api_key, chat_endpoint, created_at)。优先环境变量，其次 JSON 配置。"""
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    endpoint = os.environ.get("DASHSCOPE_ENDPOINT", "").strip()
    created_at = None
    if os.path.exists(CFG):
        try:
            cfg = json.load(open(CFG, encoding="utf-8"))
            api_key = api_key or str(cfg.get("api_key", "")).strip()
            endpoint = endpoint or str(cfg.get("endpoint", "")).strip()
            created_at = cfg.get("created_at")
        except Exception:
            pass
    if not endpoint:
        endpoint = DEFAULT_ENDPOINT
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint.rstrip("/") + "/chat/completions"
    return api_key, endpoint, created_at


def check_free_quota():
    """
    免费额度硬性限制：新用户 90 天免费额度过期后禁止继续调用（避免产生费用）。
    返回剩余天数；已过期/未启用则抛 RuntimeError。
    """
    _, _, created_at = load_config()
    if created_at is None:
        raise RuntimeError("未记录启用时间。请重新运行: python vision_qwen.py --save-key sk-xxx --endpoint <网关>")
    days_passed = (time.time() - created_at) / 86400.0
    remain = FREE_DAYS - days_passed
    if remain <= 0:
        raise RuntimeError(
            f"[90天免费额度已过期] 千问免费额度于启用后 {FREE_DAYS} 天到期（{int(days_passed)}天前已过期）。"
            f"为避免产生费用，已停止调用。如需继续请购买 token 包并联系项目负责人。")
    return remain


def get_api_key():
    key, _, _ = load_config()
    return key


def save_config(api_key, endpoint=None):
    """保存 Key 和端点到 D 盘配置文件（仅本机）。首次保存时记录免费额度启用时间。"""
    old_key, old_ep, old_created = load_config()
    cfg = {
        "api_key": api_key or old_key,
        "endpoint": (endpoint or old_ep or DEFAULT_ENDPOINT),
        "created_at": old_created if old_created else time.time(),
    }
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CFG, 0o600)
    except Exception:
        pass
    return CFG


def analyze_text(text, prompt="请检查下面这段文字是否通顺，如有截断请给出完整补全。",
                 model="qwen-plus", max_tokens=1024, timeout=60):
    """纯文本对话（不涉及图片），返回 Qwen 的回复。复用同一 key/额度检查。"""
    check_free_quota()
    api_key, endpoint, _ = load_config()
    if not api_key:
        raise RuntimeError("未找到 API Key。运行: python vision_qwen.py --save-key sk-xxx --endpoint <网关>")
    if not text:
        raise ValueError("text 不能为空")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data, ensure_ascii=False)


def analyze_image(image_path, prompt="请详细描述这张图片的内容，如果是八字排盘/板书，请把天干地支、十神等原文准确读出。",
                  model="qwen-vl-max", max_tokens=1024, timeout=60):
    """读取一张图片，返回 Qwen-VL 的文字分析。"""
    check_free_quota()  # 90天免费额度过期即拒绝，防扣费
    api_key, endpoint, _ = load_config()
    if not api_key:
        raise RuntimeError("未找到 API Key。运行: python vision_qwen.py --save-key sk-xxx --endpoint <网关>")

    if not os.path.exists(image_path):
        raise FileNotFoundError(image_path)
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(image_path)[1].lstrip(".").lower() or "png"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ("webp" if ext == "webp" else "png")

    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python vision_qwen.py --save-key sk-xxx [--endpoint https://.../compatible-mode/v1]")
        print("  python vision_qwen.py --status")
        print("  python vision_qwen.py <图片路径> [提示词]")
        sys.exit(1)
    if sys.argv[1] == "--save-key":
        key = sys.argv[2]
        ep = None
        if "--endpoint" in sys.argv:
            ep = sys.argv[sys.argv.index("--endpoint") + 1]
        path = save_config(key, ep)
        print(f"[OK] 配置已保存到 {path}")
        sys.exit(0)
    if sys.argv[1] == "--status":
        try:
            remain = check_free_quota()
            print(f"[OK] 免费额度剩余约 {int(remain)} 天，可正常使用。")
        except RuntimeError as e:
            print(f"[STOP] {e}")
        sys.exit(0)
    img = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else "请详细描述这张图片的内容。如果是八字排盘或板书，请准确读出天干地支、十神等原文。"
    model = os.environ.get("QWEN_MODEL", "qwen-vl-max")
    try:
        print(analyze_image(img, prompt, model=model))
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
