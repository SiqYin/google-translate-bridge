#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Cloud Translation API 本地桥接代理

把 Google Cloud Translation (v2) 包装成两种通用 AI 接口：
  - OpenAI 兼容:  GET  /v1/models , POST /v1/chat/completions
  - Anthropic 兼容: POST /v1/messages

这样沉浸式翻译(自定义 OpenAI 兼容服务)、或任何只认 OpenAI / Anthropic
格式的 AI 翻译界面，都可以通过 http://127.0.0.1:8080 间接调用
Google Translation API，费用走你 Google Cloud 的 $300 赠金。

零第三方依赖，仅用 Python 标准库。

用法:
  export GOOGLE_TRANSLATE_API_KEY="你的Google Cloud API密钥"
  export TARGET_LANG="zh-CN"          # 目标语言代码，默认简体中文
  export PORT=8080                    # 监听端口，默认 8080
  python google_translate_bridge.py
"""

import json
import os
import re
import sys
import time
import uuid
import threading
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ----------------------------- 配置 -----------------------------
API_KEY = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "").strip()
TARGET_LANG = os.environ.get("TARGET_LANG", "zh-CN").strip()
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "127.0.0.1")
MODEL_NAME = os.environ.get("MODEL_NAME", "Google-NMT")
GOOGLE_V2_URL = os.environ.get(
    "GOOGLE_TRANSLATE_URL",
    "https://translation.googleapis.com/language/translate/v2",
).strip()

# 单次请求分批参数（Google v2 限制 q 数组 <=1024 项，这里取保守值）
BATCH_MAX_ITEMS = 80
BATCH_MAX_CHARS = 18000

# 字符累计统计（用于对照 $300 用量）
_stats_lock = threading.Lock()
_stats = {"requests": 0, "source_chars": 0, "translated_chars": 0, "errors": 0}

# 语言名 -> Google 语言代码（覆盖沉浸式翻译 prompt 里常见的 {{to}} 取值）
LANG_NAME_TO_CODE = {
    "chinese (simplified)": "zh-CN", "chinese simplified": "zh-CN",
    "simplified chinese": "zh-CN", "简体中文": "zh-CN", "中文": "zh-CN",
    "中文(简体)": "zh-CN", "zh-cn": "zh-CN", "chinese": "zh-CN",
    "chinese (traditional)": "zh-TW", "traditional chinese": "zh-TW",
    "繁體中文": "zh-TW", "zh-tw": "zh-TW",
    "english": "en", "英语": "en", "英文": "en", "en-us": "en", "en": "en",
    "japanese": "ja", "日语": "ja", "日文": "ja", "ja": "ja",
    "korean": "ko", "韩语": "ko", "韩文": "ko", "ko": "ko",
    "french": "fr", "法语": "fr", "fr": "fr",
    "german": "de", "德语": "de", "de": "de",
    "spanish": "es", "西班牙语": "es", "es": "es",
    "russian": "ru", "俄语": "ru", "ru": "ru",
    "portuguese": "pt", "葡萄牙语": "pt", "pt": "pt",
    "italian": "it", "意大利语": "it", "it": "it",
    "arabic": "ar", "阿拉伯语": "ar", "ar": "ar",
    "thai": "th", "泰语": "th", "th": "th",
    "vietnamese": "vi", "越南语": "vi", "vi": "vi",
    "indonesian": "id", "印尼语": "id", "id": "id",
    "hindi": "hi", "印地语": "hi", "hi": "hi",
    "turkish": "tr", "土耳其语": "tr", "tr": "tr",
    "dutch": "nl", "荷兰语": "nl", "nl": "nl",
    "polish": "pl", "波兰语": "pl", "pl": "pl",
    "swedish": "sv", "瑞典语": "sv", "sv": "sv",
}

# 沉浸式翻译 prompt 里的翻译指令行（需要从正文中剥离）
INSTRUCTION_PREFIXES = (
    "translate to", "translate into", "translate the following",
    "请将以下内容翻译", "请翻译", "翻译为", "翻译成",
)


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def dump_request(messages):
    """把收到的原始 messages 追加到日志，便于排查 prompt 格式。"""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "request_dump.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("=== %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            f.write(json.dumps(messages, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        pass


def normalize_lang(name):
    """把语言名或代码统一成 Google 语言代码。"""
    if not name:
        return TARGET_LANG
    key = name.strip().lower()
    if key in LANG_NAME_TO_CODE:
        return LANG_NAME_TO_CODE[key]
    # 已是代码形式（如 zh-CN / en-US）直接返回
    if len(key) <= 10 and key.replace("-", "").isalnum():
        return name.strip()
    return TARGET_LANG


# 预编译：用已知语言名做精确匹配，避免把 "日语：正文" 整串误当语言名
_LANG_ALTERNATES = "|".join(
    sorted((re.escape(k) for k in LANG_NAME_TO_CODE.keys()), key=len, reverse=True)
)
# 指令头：中英文翻译指令 + 精确语言名 + 可选的括号说明 + 冒号
# 例: "Translate to Chinese (Simplified):" / "请翻译成日语：" / "翻译为 English:"
_INSTR_HEAD = re.compile(
    r"^\s*(?:translate\s+(?:to|into)\s+|translate\s+the\s+following[^\n:：]{0,40}?to\s+|"
    r"请(?:将以下内容)?翻译(?:成|为)\s*|翻译(?:成|为)\s*)"
    r"(" + _LANG_ALTERNATES + r")"
    r"\s*(?:\([^)]{0,30}\)|（[^）]{0,30}）)?\s*[:：]?\s*",
    re.IGNORECASE,
)
# 整行都是指令（语言名后无正文），例如 "Translate to Japanese"
_INSTR_LINE_ONLY = re.compile(
    r"^\s*(?:translate\s+(?:to|into)|请(?:将以下内容)?翻译(?:成|为)|翻译(?:成|为))\s+"
    r"(?:" + _LANG_ALTERNATES + r")\s*[:：]?\s*$",
    re.IGNORECASE,
)


def detect_target_lang(messages):
    """从 prompt 中精确解析目标语言；识别不到则用 TARGET_LANG。"""
    blob = ""
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            blob += c + "\n"
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and isinstance(b.get("text"), str):
                    blob += b["text"] + "\n"
    # 优先在整段里找指令头（覆盖指令独占一行、或与正文同行的情况）
    m = _INSTR_HEAD.search(blob)
    if m:
        lang = normalize_lang(m.group(1))
        if lang != TARGET_LANG:
            return lang
    # 兜底：任意位置出现已知语言名（如 system prompt 里的 "professional Chinese native translator"）
    for name, code in LANG_NAME_TO_CODE.items():
        if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", blob, re.IGNORECASE):
            return code
    return TARGET_LANG


def extract_text(messages):
    """
    提取真正要翻译的文本：剥离「指令 + 语言名 + 冒号」前缀（同行或独占行均可），
    保留 %% 多段落分隔。返回 (文本, 是否HTML, 段落数)
    """
    raw = ""
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            raw = c
        elif isinstance(c, list):
            parts = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif isinstance(b, dict) and "text" in b:
                    parts.append(str(b["text"]))
            raw = "\n".join(parts)
        if raw:
            break

    is_html = "<" in raw and ">" in raw

    lines = raw.split("\n")
    cleaned = []
    for i, line in enumerate(lines):
        if i < 6:
            m = _INSTR_HEAD.match(line)
            if m:
                remainder = line[m.end():]
                if remainder.strip():
                    cleaned.append(remainder.lstrip())
                continue
            if _INSTR_LINE_ONLY.match(line):
                continue
        cleaned.append(line)

    text = "\n".join(cleaned).strip()
    if not text:
        text = raw.strip()

    parts = [p for p in text.split("%%")]
    return text, is_html, len(parts)


def split_batches(parts):
    """把段落列表切成符合 Google 限制的小批。"""
    batches, cur, cur_chars = [], [], 0
    for p in parts:
        n = len(p)
        if cur and (len(cur) >= BATCH_MAX_ITEMS or cur_chars + n > BATCH_MAX_CHARS):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(p)
        cur_chars += n
    if cur:
        batches.append(cur)
    return batches


def google_translate(texts, target, is_html):
    """调用 Google Cloud Translation v2，返回译文列表。"""
    if not API_KEY:
        raise RuntimeError("未配置 GOOGLE_TRANSLATE_API_KEY 环境变量")

    results = []
    for batch in split_batches(texts):
        payload = {
            "q": batch,
            "target": target,
            "format": "html" if is_html else "text",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = GOOGLE_V2_URL + "?key=" + urllib.parse.quote(API_KEY, safe="")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError("Google API HTTP %s: %s" % (e.code, detail))
        except urllib.error.URLError as e:
            raise RuntimeError("无法连接 Google API: %s" % e.reason)

        if "data" not in body or "translations" not in body["data"]:
            raise RuntimeError("Google API 返回异常: %s" % json.dumps(body, ensure_ascii=False)[:500])
        results.extend([t.get("translatedText", "") for t in body["data"]["translations"]])
    return results


def do_translation(messages):
    """核心流程：提取 -> 翻译 -> 统计。返回 (译文, 目标语言, 段落数)。"""
    text, is_html, n_parts = extract_text(messages)
    target = detect_target_lang(messages)
    parts = text.split("%%") if n_parts > 1 else [text]

    translated = google_translate(parts, target, is_html)

    # 用 %% 拼回，保持与沉浸式翻译多段落 prompt 一致
    out = "%%".join(translated) if n_parts > 1 else (translated[0] if translated else "")

    src_chars = sum(len(p) for p in parts)
    dst_chars = sum(len(t) for t in translated)
    with _stats_lock:
        _stats["requests"] += 1
        _stats["source_chars"] += src_chars
        _stats["translated_chars"] += dst_chars
        s = dict(_stats)

    log("翻译 target=%s 段落=%d 源字符=%d -> 累计源字符=%d (约 $%.4f @ $20/百万)"
        % (target, n_parts, src_chars, s["source_chars"], s["source_chars"] / 1000000.0 * 20))
    return out, target, n_parts


# ----------------------------- HTTP 处理 -----------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 用自定义 log()

    def _send(self, code, obj, content_type="application/json; charset=utf-8"):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/v1/models", "/models"):
            self._send(200, {
                "object": "list",
                "data": [{
                    "id": MODEL_NAME,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "google-cloud-translation",
                }],
            })
        elif path in ("/", "/health"):
            self._send(200, {
                "status": "ok",
                "upstream": GOOGLE_V2_URL,
                "api_key_configured": bool(API_KEY),
                "target_lang": TARGET_LANG,
                "stats": _stats,
            })
        else:
            self._send(404, {"error": {"message": "not found"}})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            req = self._read_json()
        except Exception as e:
            self._send(400, {"error": {"message": "invalid json: %s" % e}})
            return

        try:
            if path in ("/v1/chat/completions", "/chat/completions"):
                self._handle_openai(req)
            elif path in ("/v1/messages", "/messages"):
                self._handle_anthropic(req)
            else:
                self._send(404, {"error": {"message": "not found: %s" % path}})
        except Exception as e:
            with _stats_lock:
                _stats["errors"] += 1
            log("ERROR: %s" % e)
            self._send(500, {"error": {"message": str(e), "type": "bridge_error"}})

    def _handle_openai(self, req):
        messages = req.get("messages", [])
        stream = bool(req.get("stream", False))
        out, target, n_parts = do_translation(messages)
        model = req.get("model", MODEL_NAME)

        if not stream:
            self._send(200, {
                "id": "chatcmpl-" + uuid.uuid4().hex[:12],
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": out},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": max(1, len(out) // 4),
                    "completion_tokens": max(1, len(out) // 4),
                    "total_tokens": max(2, len(out) // 2),
                },
            })
            return

        # SSE 流式：Google 本身不支持流式，这里按块模拟
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        cid = "chatcmpl-" + uuid.uuid4().hex[:12]
        chunk_size = 24
        for i in range(0, len(out), chunk_size):
            piece = out[i:i + chunk_size]
            chunk = {
                "id": cid, "object": "chat.completion.chunk",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()
        final = {
            "id": cid, "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self.wfile.write(("data: " + json.dumps(final, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _handle_anthropic(self, req):
        messages = req.get("messages", [])
        out, target, n_parts = do_translation(messages)
        model = req.get("model", MODEL_NAME)
        self._send(200, {
            "id": "msg_" + uuid.uuid4().hex[:12],
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": out}],
            "model": model,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": max(1, len(out) // 4),
                "output_tokens": max(1, len(out) // 4),
            },
        })


def main():
    if not API_KEY:
        log("警告: 未设置 GOOGLE_TRANSLATE_API_KEY，启动后调用会失败。")
        log("设置方法: export GOOGLE_TRANSLATE_API_KEY='你的密钥'")
    log("Google Translation 桥接代理启动")
    log("监听: http://%s:%d/v1" % (HOST, PORT))
    log("上游: %s" % GOOGLE_V2_URL)
    log("默认目标语言: %s" % TARGET_LANG)
    log("OpenAI 入口: POST /v1/chat/completions")
    log("Anthropic 入口: POST /v1/messages")
    log("用量统计: GET /health")
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        server.serve_forever()
    except KeyboardInterrupt:
        log("已停止")


if __name__ == "__main__":
    main()
