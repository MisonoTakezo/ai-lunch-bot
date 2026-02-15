# 🍱 ai-lunch-bot

**すみよしランチメニューの問い合わせ・注文ができるローカル MCP サーバー**

| サイト | URL |
|--------|-----|
| メニュー掲載 | https://sumiyoshi-bento.com/menu/ |
| 注文システム | https://sumiyoshi.azurewebsites.net/ |

メニュー PDF を自動取得し、Gemini で OCR → JSON 変換。
MCP (Model Context Protocol) サーバーとして起動し、Claude Code / GitHub Copilot 等の AI アシスタントから自然言語でメニュー確認・注文ができます。

---

## ✨ 機能

|    | 機能                | 説明                                                 |
| -- | ------------------- | ---------------------------------------------------- |
| 📥 | **PDF 自動取得**    | サイト掲載の全期間分メニュー PDF をダウンロード      |
| 🔍 | **Gemini OCR**      | PDF を直接アップロードし JSON に変換（画像変換不要） |
| 🗣️ | **自然言語検索**    | 「明日のメニューは？」「フライがある日は？」「魚料理のメニューはどっち？🐟️」          |
| 🛒 | **注文 / 取り消し** | すみよし注文システムにHTTP リクエスト                    |
| 🔌 | **MCP 対応**        | stdio / SSE 両トランスポート対応                     |

---

## 🚀 セットアップ

### 1. 依存パッケージのインストール

```bash
cd ai-lunch-bot
python3 -m venv .venv
.venv/bin/pip install -e .
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、API キーを設定:

```bash
cp .env.example .env
```

```dotenv
# Gemini API キー (必須: https://aistudio.google.com/apikey)
GOOGLE_API_KEY=your_google_api_key

# すみよし注文システム認証情報 (注文機能を使う場合)
BENTO_COMPANY_CD=your_company_cd
BENTO_USER_CD=your_user_cd
BENTO_PASSWORD=your_password
```

---

## 🔧 MCP ツール

| ツール           | 説明                   | 引数                                                                     |
| ---------------- | ---------------------- | ------------------------------------------------------------------------ |
| `get_lunch_menu` | 日付指定でメニュー取得 | `date_str`: `"2026-02-10"`, `"明日"`, `"来週の月曜日"`                   |
| `search_menu`    | キーワード検索         | `query`: `"フライ"`, `"ハンバーグ"`                                      |
| `list_all_menus` | 全メニュー一覧         | —                                                                        |
| `place_order`    | 注文                   | `date`, `menu_type` (`"和風"` / `"あいランチ"` / `"その他"`), `quantity` |
| `cancel_order`   | 取り消し               | `date`, `menu_type`                                                      |
| `get_order_status` | 注文状況確認         | `date_str`: `"今日"`, `"今月"`, `"2月"`                                  |

### 会話例

```
👤 明日のランチメニューを教えて
🤖 📅 2026-02-09 のランチメニュー
   🍱 あいランチ: ハムベーコンフライ, 切干大根煮, ...
   🐟 和風ランチ: ブリの漬け焼き, ...

👤 フライがある日はいつ？
🤖 「フライ」の検索結果 (7 件): ...

👤 明日のあいランチを 1 つ注文して
🤖 ✅ 2026-02-09 の あいランチ を 1 個注文しました。

👤 やっぱり取り消して
🤖 ✅ 2026-02-09 の あいランチ の注文を取り消しました。
```

---

## 🖥️ MCP クライアント接続設定

### Claude Code

プロジェクトルートの `.mcp.json` に設定を追加します:

```bash
cat > .mcp.json << 'EOF'
{
  "mcpServers": {
    "lunch-bot": {
      "type": "stdio",
      "command": "/path/to/ai-lunch-bot/.venv/bin/python",
      "args": ["-m", "lunch_bot", "--skip-ocr"]
    }
  }
}
EOF
```

> **Note**: `command` のパスは実際の絶対パスに置き換えてください。

このディレクトリで `claude` を起動すれば自動的に接続されます:

```bash
cd ai-lunch-bot
claude
# /mcp コマンドで接続状況を確認
```

### GitHub Copilot (VS Code)

プロジェクトに同梱の [`.vscode/mcp.json`](.vscode/mcp.json)
が自動で読み込まれます。\
設定変更不要でそのまま使えます。

<details>
<summary>手動で設定する場合</summary>

`.vscode/mcp.json`:

```json
{
    "servers": {
        "lunch-bot": {
            "type": "stdio",
            "command": "/path/to/ai-lunch-bot/.venv/bin/python",
            "args": ["-m", "lunch_bot", "--skip-ocr"]
        }
    }
}
```

</details>

### GitHub Copilot CLI

`.copilot/mcp-config.json` に設定を追加します:

```bash
mkdir -p .copilot
cat > .copilot/mcp-config.json << 'EOF'
{
  "mcpServers": {
    "lunch-bot": {
      "type": "sse",
      "url": "http://127.0.0.1:8765/sse",
      "tools": ["*"]
    }
  }
}
EOF
```

Copilot CLI は SSE 接続のため、**先にサーバーを起動**しておく必要があります:

```bash
# ターミナル 1: SSE サーバー起動
cd ai-lunch-bot
.venv/bin/python -m lunch_bot --sse --skip-ocr

# ターミナル 2: Copilot CLI で問い合わせ
cd ai-lunch-bot
gh copilot
```

> 💡 `--skip-ocr` で起動が高速に。メニュー更新時は外してください。

---

## 📖 サーバーの起動方法

### 1 コマンドで起動

```bash
# stdio モード（Claude Desktop 向け・デフォルト）
.venv/bin/python -m lunch_bot

# SSE モード（Web クライアント / Copilot CLI 向け）
.venv/bin/python -m lunch_bot --sse

# SSE + ポート指定
.venv/bin/python -m lunch_bot --sse --port 9000
```

### よく使うパターン

```bash
# 初回: フルパイプライン + サーバー起動
.venv/bin/python -m lunch_bot

# 2回目以降: OCR スキップで高速起動
.venv/bin/python -m lunch_bot --skip-ocr

# メニューデータだけ更新 (サーバー起動なし)
.venv/bin/python -m lunch_bot --pipeline-only

# 既存 PDF で再 OCR のみ
.venv/bin/python -m lunch_bot --skip-download --pipeline-only
```

### CLI オプション一覧

| オプション        | 説明                                  |
| ----------------- | ------------------------------------- |
| `--stdio`         | stdio モードで起動（デフォルト）      |
| `--sse`           | SSE モードで起動                      |
| `--host HOST`     | SSE ホスト（デフォルト: `127.0.0.1`） |
| `--port PORT`     | SSE ポート（デフォルト: `8765`）      |
| `--skip-download` | PDF ダウンロードをスキップ            |
| `--skip-ocr`      | OCR をスキップ（既存 JSON 使用）      |
| `--pipeline-only` | パイプラインのみ実行                  |
| `--log-file FILE` | ログをファイルに出力                  |
| `-v, --verbose`   | 詳細ログを表示                        |

---

## 📁 プロジェクト構成

```
ai-lunch-bot/
├── lunch_bot/
│   ├── __init__.py        パッケージメタ
│   ├── __main__.py        python -m lunch_bot エントリ
│   ├── cli.py             CLI (argparse)
│   ├── config.py          パス定数・環境変数
│   ├── downloader.py      メニュー PDF ダウンロード
│   ├── ocr.py             Gemini OCR (PDF → JSON)
│   ├── order.py           注文クライアント (HTTP)
│   └── server.py          MCP サーバー + ツール定義
├── .mcp.json              (要作成・gitignore対象) Claude Code MCP 設定
├── .vscode/
│   └── mcp.json           GitHub Copilot (VS Code) MCP 設定
├── .copilot/              (要作成・gitignore対象)
│   └── mcp-config.json    GitHub Copilot CLI MCP 設定 (SSE)
├── img/                   ダウンロード PDF 保存先
├── .env                   API キー・認証情報
├── .env.example           .env テンプレート
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 🛠️ 技術スタック

| 領域               | 技術                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------- |
| **MCP サーバー**   | [mcp (FastMCP)](https://github.com/modelcontextprotocol/python-sdk) — stdio / SSE     |
| **OCR**            | [Google Gemini 2.5 Flash](https://ai.google.dev/) — PDF 直接アップロード              |
| **HTTP**           | [httpx](https://www.python-httpx.org/) — 注文システム連携 & PDF ダウンロード          |
| **スクレイピング** | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — メニューページ解析 |
