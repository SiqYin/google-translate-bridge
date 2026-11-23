<div align="right">
<a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.md">English</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh.md">简体中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh-TW.md">繁體中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.ja.md">日本語</a>
</div>

# Google Translate 桥接

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

一个零依赖的本地代理，把 **Google Cloud Translation API** 包装成 **OpenAI / Anthropic 兼容接口**。让沉浸式翻译——或任何只认 OpenAI / Anthropic 格式的 AI 翻译 App——通过它调用你自己的 Google Cloud Translation API，费用走你的 $300 试用金。

> 本桥接调用官方 Google Cloud Translation API（v2），用量记入你的 Google Cloud 账号。免费试用含每月 50 万字符免费额度。

## 为什么要桥接？

Google Cloud Translation API 是私有 REST 接口（`{q, target}` → `{data:{translations:[...]}}`），不是 OpenAI chat 格式。而沉浸式翻译这类 App 只接受 `/v1/chat/completions` 或 `/v1/messages`。本桥接负责两者之间的转换。

## 特性

- **零依赖**——仅使用 Python 标准库
- **OpenAI 兼容**——`GET /v1/models`、`POST /v1/chat/completions`（模拟 SSE 流式）
- **Anthropic 兼容**——`POST /v1/messages`
- **自动语言识别**——从 prompt 解析（如 "Translate to Japanese"）
- **HTML 标签保留**——通过 `mimeType: text/html`
- **多段落 `%%` 处理**——适配沉浸式翻译
- **用量统计**——`GET /health` 查看翻译字符数与估算花费

## 工作原理

```
【沉浸式翻译 / AI App】→【本地桥接】→ Google Cloud Translation API v2 → 计入你的 $300 赠金
```

## 使用步骤

### 1. Google Cloud 侧（一次性）

1. 启用 **Cloud Translation API**（Basic/v2 即可，支持 API Key）
2. 确认项目绑定了带 $300 赠金的结算账号
3. 创建 API Key：API 和服务 → 凭据 → 创建凭据 → API 密钥
4. 将 Key 限制为仅允许 Cloud Translation API

### 2. 启动桥接

```bash
export GOOGLE_TRANSLATE_API_KEY="AIza..."
export TARGET_LANG="zh-CN"        # 默认目标语言
export PORT=8080                  # 8080 空闲时
python google_translate_bridge.py
```

### 3. 沉浸式翻译配置

设置 → 翻译服务 → 添加自定义服务（OpenAI 兼容）：

| 配置项 | 值 |
|---|---|
| 服务名称 | Google-NMT |
| 接口地址 | `http://127.0.0.1:8080/v1/chat/completions`（完整路径） |
| API Key | `index`（任意填写；真实 Key 在环境变量里） |
| 模型 | `Google-NMT`（勾选输入自定义模型名称） |

### 4. Anthropic 格式 App

基址填 `http://127.0.0.1:8080`，模型 `Google-NMT`——`/v1/messages` 入口已实现。

## 成本说明

NMT 单价 $20/百万字符（每月前 50 万字符免费）。$300 约可买 1,500～1,650 万计费字符。多目标语言按语言数翻倍计费。用 `GET /health` 跟踪用量。

## 限制

- Cloud Translation 是纯翻译引擎，不是 LLM——prompt 里复杂翻译指令会被剥离或忽略
- 需要术语控制请用术语表（Advanced/v3），那需要服务账号认证

## 测试

附带 mock 上游的端到端测试（不调用真实 API、不消耗赠金）：

```bash
python test_bridge_mock.py
```

## 许可证

MIT
