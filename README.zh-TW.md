<div align="right">
<a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.md">English</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh.md">简体中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh-TW.md">繁體中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.ja.md">日本語</a>
</div>

# Google Translate 橋接

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

一個零依賴的本機代理，把 **Google Cloud Translation API** 包裝成 **OpenAI / Anthropic 相容介面**。讓沉浸式翻譯——或任何只認 OpenAI / Anthropic 格式的 AI 翻譯 App——透過它呼叫你自己的 Google Cloud Translation API，費用走你的 $300 試用金。

> 本橋接呼叫官方 Google Cloud Translation API（v2），用量記入你的 Google Cloud 帳號。免費試用含每月 50 萬字元免費額度。

## 為什麼要橋接？

Google Cloud Translation API 是私有 REST 介面（`{q, target}` → `{data:{translations:[...]}}`），不是 OpenAI chat 格式。而沉浸式翻譯這類 App 只接受 `/v1/chat/completions` 或 `/v1/messages`。本橋接負責兩者之間的轉換。

## 特性

- **零依賴**——僅使用 Python 標準程式庫
- **OpenAI 相容**——`GET /v1/models`、`POST /v1/chat/completions`（模擬 SSE 串流）
- **Anthropic 相容**——`POST /v1/messages`
- **自動語言辨識**——從 prompt 解析（如 "Translate to Japanese"）
- **HTML 標籤保留**——透過 `mimeType: text/html`
- **多段落 `%%` 處理**——適配沉浸式翻譯
- **用量統計**——`GET /health` 查看翻譯字元數與預估花費

## 運作原理

```
【沉浸式翻譯 / AI App】→【本機橋接】→ Google Cloud Translation API v2 → 計入你的 $300 贈金
```

## 使用步驟

### 1. Google Cloud 端（一次性）

1. 啟用 **Cloud Translation API**（Basic/v2 即可，支援 API Key）
2. 確認專案綁定了含 $300 贈金的帳單帳號
3. 建立 API Key：API 與服務 → 憑證 → 建立憑證 → API 金鑰
4. 將金鑰限制為僅允許 Cloud Translation API

### 2. 啟動橋接

```bash
export GOOGLE_TRANSLATE_API_KEY="AIza..."
export TARGET_LANG="zh-CN"        # 預設目標語言
export PORT=8080                  # 8080 空閒時
python google_translate_bridge.py
```

### 3. 沉浸式翻譯設定

設定 → 翻譯服務 → 新增自訂服務（OpenAI 相容）：

| 欄位 | 值 |
|---|---|
| 服務名稱 | Google-NMT |
| 介面網址 | `http://127.0.0.1:8080/v1/chat/completions`（完整路徑） |
| API Key | `index`（任意填寫；真實金鑰在環境變數裡） |
| 模型 | `Google-NMT`（勾選輸入自訂模型名稱） |

### 4. Anthropic 格式 App

基底網址填 `http://127.0.0.1:8080`，模型 `Google-NMT`——`/v1/messages` 入口已實作。

## 成本說明

NMT 單價 $20/百萬字元（每月前 50 萬字元免費）。$300 約可買 1,500～1,650 萬計費字元。多目標語言按語言數翻倍計費。用 `GET /health` 追蹤用量。

## 限制

- Cloud Translation 是純翻譯引擎，不是 LLM——prompt 裡複雜翻譯指令會被剝離或忽略
- 需要術語控制請使用術語表（Advanced/v3），那需要服務帳號驗證

## 測試

附 mock 上游的端到端測試（不呼叫真實 API、不消耗贈金）：

```bash
python test_bridge_mock.py
```

## 授權

MIT
