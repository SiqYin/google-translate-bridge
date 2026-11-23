#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桥接代理端到端测试：用一个本地 mock 上游模拟 Google Translation v2 API，
验证 OpenAI / Anthropic 两种入口的协议转换、多段落、HTML、流式、用量统计。
不访问真实 Google API，不消耗赠金。
"""

import json
import os
import sys
import time
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WORKDIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(WORKDIR, "google_translate_bridge.py")
MOCK_PORT = 8098
BRIDGE_PORT = 8080
LOG = os.path.join(WORKDIR, "bridge_e2e.log")


class MockGoogle(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(n).decode("utf-8"))
        q = req.get("q", [])
        target = req.get("target", "")
        fmt = req.get("format", "text")
        translations = [
            {"translatedText": "[t=%s|f=%s]%s" % (target, fmt, t)} for t in q
        ]
        body = json.dumps(
            {"data": {"translations": translations}}, ensure_ascii=False
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def http(url, data=None):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    raw = None
    if data is not None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw, headers=headers, method="POST" if raw else "GET"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")


passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  PASS  " + name)
    else:
        failed += 1
        print("  FAIL  " + name + "  -> " + str(detail)[:300])


def main():
    mock = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockGoogle)
    threading.Thread(target=mock.serve_forever, daemon=True).start()

    env = os.environ.copy()
    env["GOOGLE_TRANSLATE_API_KEY"] = "test-key"
    env["GOOGLE_TRANSLATE_URL"] = "http://127.0.0.1:%d/translate" % MOCK_PORT
    env["TARGET_LANG"] = "zh-CN"
    env["PORT"] = str(BRIDGE_PORT)

    logf = open(LOG, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, BRIDGE], cwd=WORKDIR, env=env,
        stdout=logf, stderr=subprocess.STDOUT,
    )
    try:
        base = "http://127.0.0.1:%d" % BRIDGE_PORT
        for _ in range(60):
            try:
                http(base + "/health")
                break
            except Exception:
                time.sleep(0.1)

        print("\n[1] 健康检查")
        r = json.loads(http(base + "/health"))
        check("status=ok", r.get("status") == "ok", r)
        check("上游指向 mock", "8098" in r.get("upstream", ""), r.get("upstream"))
        check("api_key_configured", r.get("api_key_configured") is True, r)

        print("\n[2] 模型列表")
        r = json.loads(http(base + "/v1/models"))
        check("含 Google-NMT", any(m["id"] == "Google-NMT" for m in r["data"]), r)

        print("\n[3] OpenAI 单段 + 指令剥离 + 目标语言解析")
        r = json.loads(http(base + "/v1/chat/completions", {
            "model": "Google-NMT",
            "messages": [{"role": "user", "content": "Translate to Chinese (Simplified):\nHello world"}],
        }))
        c = r["choices"][0]["message"]["content"]
        check("译文正确", c == "[t=zh-CN|f=text]Hello world", c)
        check("OpenAI 响应结构", r.get("object") == "chat.completion", r.get("object"))

        print("\n[4] OpenAI 多段落 %% 分隔 + 目标语言 ja")
        r = json.loads(http(base + "/v1/chat/completions", {
            "model": "Google-NMT",
            "messages": [{"role": "user", "content": "Translate to Japanese:\n段落A %% 段落B"}],
        }))
        c = r["choices"][0]["message"]["content"]
        check("两段都被翻译", c.count("[t=ja|f=text]") == 2, c)
        check("用 %% 拼回", "%%" in c, c)

        print("\n[5] HTML 格式保留")
        r = json.loads(http(base + "/v1/chat/completions", {
            "model": "Google-NMT",
            "messages": [{"role": "user", "content": "<p>Hello</p>"}],
        }))
        c = r["choices"][0]["message"]["content"]
        check("format=html", "f=html" in c, c)

        print("\n[6] Anthropic messages 入口")
        r = json.loads(http(base + "/v1/messages", {
            "model": "Google-NMT", "max_tokens": 100,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Translate to Korean:\nGood morning"}]}],
        }))
        c = r["content"][0]["text"]
        check("译文正确", c == "[t=ko|f=text]Good morning", c)
        check("Anthropic 响应结构", r.get("type") == "message" and r.get("stop_reason") == "end_turn", r)

        print("\n[7] 流式 SSE")
        req = urllib.request.Request(
            base + "/v1/chat/completions",
            data=json.dumps({"model": "Google-NMT", "stream": True,
                             "messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            sse = resp.read().decode("utf-8")
        check("含 chunk", "chat.completion.chunk" in sse, sse[:200])
        check("含 [DONE]", "[DONE]" in sse, sse[-120:])

        print("\n[8] 用量统计")
        r = json.loads(http(base + "/health"))
        s = r["stats"]
        check("请求计数 >=5", s["requests"] >= 5, s)
        check("源字符累计 >0", s["source_chars"] > 0, s)
        check("无错误", s["errors"] == 0, s)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        mock.shutdown()
        logf.close()
        print("\n桥接运行日志 -> " + LOG)
        print("结果: %d PASS, %d FAIL" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
