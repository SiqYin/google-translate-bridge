<div align="right">
<a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.md">English</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh.md">简体中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.zh-TW.md">繁體中文</a> · <a href="https://github.com/SiqYin/google-translate-bridge/blob/main/README.ja.md">日本語</a>
</div>

# Google Translate ブリッジ

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

**Google Cloud Translation API** を **OpenAI / Anthropic 互換エンドポイント** にラップする、依存関係ゼロのローカルプロキシです。Immersive Translate や、OpenAI / Anthropic 形式しか扱えない AI 翻訳アプリから、自身の Google Cloud Translation API と $300 無料トライアル枠を利用できます。

> 本ブリッジは公式 Google Cloud Translation API（v2）を呼び出します。使用量は Google Cloud アカウントに請求されます。無料トライアルには月 50 万文字の無料枠が含まれます。

## なぜブリッジが必要か

Google Cloud Translation API は独自の REST API（`{q, target}` → `{data:{translations:[...]}}`）であり、OpenAI chat 形式ではありません。一方 Immersive Translate などのアプリは `/v1/chat/completions` または `/v1/messages` しか受け付けません。本ブリッジが両者を変換します。

## 特徴

- **依存関係ゼロ** — Python 標準ライブラリのみ
- **OpenAI 互換** — `GET /v1/models`、`POST /v1/chat/completions`（SSE ストリーミングをシミュレート）
- **Anthropic 互換** — `POST /v1/messages`
- **自動言語検出** — prompt から解析（例: "Translate to Japanese"）
- **HTML タグ保持** — `mimeType: text/html` 経由
- **複数段落 `%%` 対応** — Immersive Translate 用
- **使用量統計** — `GET /health` で翻訳文字数と推定コストを確認

## 仕組み

```
[Immersive Translate / AI アプリ] → [ローカルブリッジ] → Google Cloud Translation API v2 → $300 枠に請求
```

## セットアップ

### 1. Google Cloud 側（初回のみ）

1. **Cloud Translation API** を有効化（Basic/v2 で十分、API キー対応）
2. プロジェクトが $300 トライアル枠の課金アカウントに紐付いていることを確認
3. API キーを作成: API とサービス → 認証情報 → 認証情報を作成 → API キー
4. キーを Cloud Translation API に制限

### 2. ブリッジを起動

```bash
export GOOGLE_TRANSLATE_API_KEY="AIza..."
export TARGET_LANG="zh-CN"        # デフォルト目標言語
export PORT=8080                  # 8080 が空いていれば
python google_translate_bridge.py
```

### 3. Immersive Translate の設定

設定 → 翻訳サービス → カスタムサービスを追加（OpenAI 互換）:

| 項目 | 値 |
|---|---|
| サービス名 | Google-NMT |
| API URL | `http://127.0.0.1:8080/v1/chat/completions`（完全なパス） |
| API Key | `index`（任意の値。実際のキーは環境変数） |
| モデル | `Google-NMT`（カスタムモデル名を入力） |

### 4. Anthropic 形式アプリ

ベース URL に `http://127.0.0.1:8080`、モデル `Google-NMT` を指定 — `/v1/messages` エンドポイントを実装済みです。

## コストについて

NMT は 100 万文字あたり $20（月間最初の 50 万文字は無料）。$300 で約 1,500～1,650 万課金文字に相当します。複数目標言語の場合は言語数だけ文字数が倍増します。`GET /health` で使用量を追跡できます。

## 制限

- Cloud Translation は純粋な翻訳エンジンであり LLM ではありません — prompt 内の複雑な翻訳指示は除去・無視されます
- 用語制御には用語集（Advanced/v3）を使用してください（サービスアカウント認証が必要）

## テスト

モック上流による端到端テストを同梱（実際の API を呼ばず、枠も消費しません）:

```bash
python test_bridge_mock.py
```

## ライセンス

MIT
