<div align="right">
<a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.md">English</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh.md">简体中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh-TW.md">繁體中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.ja.md">日本語</a>
</div>

# Google Translate Bridge

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

A zero-dependency local proxy that wraps **Google Cloud Translation API** into **OpenAI-compatible and Anthropic-compatible endpoints**. Point Immersive Translate — or any AI translation app that only speaks OpenAI / Anthropic format — at this bridge to use your own Google CloudTranslation API and your $300 free-trial credit.

> This bridge calls the official Google Cloud Translation API (v2). Usage is billed to your Google Cloud account. The free trial includes a 500,000-character monthly free tier.

## Why a bridge?

Google Cloud Translation API is a proprietary REST API (`{q, target}` → `{data:{translations:[...]}}`), not an OpenAI chat format. Apps like Immersive Translate only accept `/v1/chat/completions` or `/v1/messages`. This bridge converts between them.

## Features

- **Zero dependencies** — Python standard library only
- **OpenAI-compatible** — `GET /v1/models`, `POST /v1/chat/completions` (SSE streaming simulated)
- **Anthropic-compatible** — `POST /v1/messages`
- **Auto language detection** from the prompt (e.g. "Translate to Japanese")
- **HTML tag preservation** via `mimeType: text/html`
- **Multi-paragraph `%%` handling** for Immersive Translate
- **Usage stats** at `GET /health` (characters translated, estimated cost)

## How it works

```
[Immersive Translate / AI app] → [local bridge] → Google Cloud Translation API v2 → billed to your $300 credit
```

## Setup

### 1. Google Cloud side (one-time)

1. Enable **Cloud Translation API** (Basic/v2 is enough — supports API keys)
2. Make sure the project is linked to the billing account with your $300 trial credit
3. Create an API key: APIs & Services → Credentials → Create credentials → API key
4. Restrict the key to the Cloud Translation API

### 2. Start the bridge

```bash
export GOOGLE_TRANSLATE_API_KEY="AIza..."
export TARGET_LANG="zh-CN"        # default target language
export PORT=8080                  # 8080 if free
python google_translate_bridge.py
```

### 3. Immersive Translate setup

Settings → Translation Service → Add custom service (OpenAI compatible):

| Field | Value |
|---|---|
| Service name | Google-NMT |
| API URL | `http://127.0.0.1:8080/v1/chat/completions` (full path) |
| API Key | `index` (any value; real key lives in env var) |
| Model | `Google-NMT` (enter custom model name) |

### 4. Anthropic-format apps

Base URL `http://127.0.0.1:8080`, model `Google-NMT` — the `/v1/messages` endpoint is implemented.

## Cost note

NMT is $20 / million characters (first 500,000 chars/month free). $300 buys roughly 15–16.5 million billable characters. Multi-target-language translation multiplies characters by language count. Check `GET /health` to track usage.

## Limitations

- Cloud Translation is a pure translation engine, not an LLM — complex translation instructions in the prompt are stripped or ignored
- For terminology control use glossaries (Advanced/v3), which requires service-account auth

## Test

A mock-upstream end-to-end test is included (no real API calls, no credit used):

```bash
python test_bridge_mock.py
```

## License

MIT
