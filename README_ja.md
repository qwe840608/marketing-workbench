# マーケティング・ワークベンチ（marketing-workbench）

個人クリエイターや自社ブランドがセルフホストするマーケティング用ワークベンチです。Facebook、Instagram、Threads、YouTube、TikTok の投稿データと視聴者のコメントを一か所で管理し、コメントからコンテンツのテーマを整理して、2 段階の確認を経て複数のプラットフォームへ投稿できます。

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)
![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)
![TypeScript](https://img.shields.io/badge/TypeScript-7-3178C6.svg)

[繁體中文](README.md) | [English](README_en.md) | [简体中文](README_zh-CN.md) | **日本語**

> 画面は繁体字中国語・簡体字中国語・英語・日本語に対応しています（スクリーンショットは繁体字中国語の画面です）。`docs/` 以下の詳しいドキュメントは繁体字中国語です。

![ダッシュボード](docs/images/dashboard.png)

| 投稿データ | アイデア出し |
|---|---|
| ![投稿データ](docs/images/posts.png) | ![アイデア出し](docs/images/ideation.png) |

<sub>ダッシュボードと投稿データは作者自身のアカウント ruidefilm の実際の画面です。アイデア出しは架空のデモデータです。</sub>

## 主な機能

- Facebook、Instagram、Threads、YouTube、TikTok の投稿成果を同期し、ダッシュボードで推移、成長比較、コンバージョンファネル、オーディエンス分析を表示します。
- 自分の投稿のコメントを 1 時間ごとに取得し、クラウドのモデルに送る前に個人情報をマスキングします。
- 選んだ投稿のコメントから根拠を整理し、視聴者の実際の言葉を添えた 15 個のテーマを作成します。
- テーマから台本を作成し、ブランドの NG ワードをチェックして、エクスポートできます。
- FB／IG／Threads／YouTube へ即時または予約投稿し、送信前に 2 段階で確認します。TikTok は App の受信トレイへの下書き送信のみです。
- MCP エンドポイント（Streamable HTTP）を内蔵し、Claude Code plugin、Claude デスクトップ版の拡張機能、Codex と連携できます。
- メンバーとロール権限（管理者／マーケティング担当者／閲覧者）、監査ログ、管理者用の使い捨てリカバリーコード。
- 繁体字中国語・簡体字中国語・英語・日本語の画面、幅 390px のスマートフォンに対応。
- 7-Zip による暗号化バックアップと LINE 通知（ブランド通知グループと受信のヘルスアラート）。

技術スタック：Python 3.13、uv、FastAPI、SQLAlchemy 2、Alembic、SQLite（WAL）、フロントエンドは React 19、TypeScript、Vite。

## セルフホスト前に必ずお読みください

このワークベンチをセルフホストすると、あなた自身が Meta、Google、TikTok アプリの開発者になり、各プラットフォームの規約上の義務を負います。

- **自分または自社ブランド専用です**（単一ブランド）。クライアントのアカウント運用代行や他人への登録開放には使わないでください。各プラットフォームの審査が必要で、TikTok は明確に受け付けていません。
- **アカウントの種類**：Facebook は Facebook ページ、Instagram はそのページと連携したプロアカウントが必要です。Threads、YouTube、TikTok は個人アカウントで使えます。
- **プライバシーポリシーと利用規約は自分で作成し**、自分のウェブサイトに掲載して各プラットフォームの開発者設定に入力してください。テンプレートは [`docs/templates/`](docs/templates/) にあります。
- **TikTok は受信トレイへの下書き送信のみ**です。キャプションは TikTok App 内で貼り付けます。
- **Google の同意画面は「本番環境」に設定してください。** そうしないと YouTube の認可が 7 日ごとに切れます。
- **プラットフォームのデータをモデルの学習に使わせないでください。** Gemini API の無料枠は送信内容を Google のサービス改善に使うため、ワークベンチは既定で Gemini にプラットフォームのデータを渡しません。Google Cloud プロジェクトに請求先を設定してから `GEMINI_PAID_TIER=true` にしてください。エージェントが個人向けサブスクリプション（Claude Pro／Max など）でログインしている場合、MCP で読み込んだコメントが会話に含まれるため、そのサービスで会話を学習に使う設定をオフにしてください。API キーを使うエージェントは対応不要です（Gemini は有料枠が必要）。

詳しくは [`docs/合規須知.md`](docs/合規須知.md)（コンプライアンスの注意事項）を、各ルールの公式出典は [`docs/平台政策.md`](docs/平台政策.md)（プラットフォームポリシー）をご覧ください。

## インストール

動作環境：Windows（起動とバックアップのスクリプトは PowerShell で、macOS／Linux は未対応）、Python 3.13、[uv](https://docs.astral.sh/uv/)、Node.js、7-Zip、ngrok。Tailscale の利用を推奨します。

コマンド操作に慣れていない場合は、[`docs/agent安裝引導_ja.md`](docs/agent安裝引導_ja.md)（エージェント向けインストールガイド）を自分の AI エージェントに渡すと、順を追って案内してくれます。ガイドは日本語、繁體中文、简体中文、English の 4 言語があり、エージェントがあなたの使う言語に合わせて選びます。

```powershell
# 1. 設定ファイルを作成し NGROK_AUTHTOKEN を入力（データのパスは空欄でも可。下の「環境変数」を参照）
copy .env.example .env

# 2. バックエンド：依存関係のインストール、暗号化マスターキーの生成、データベースの作成
cd backend
uv sync
uv run python ../scripts/initialize_ai_encryption.py
uv run alembic upgrade head

# 3. フロントエンド：ビルド
cd ../frontend
npm ci
npm run build

# 4. 起動
cd ..
./scripts/start-all.ps1
```

`start-all.ps1` は新規のデータベースにだけスキーマを作成し、既存のデータベースはアップグレードしません。アップグレード手順は [`docs/operations.md`](docs/operations.md) をご覧ください。

## 使い方

初回起動時にポート 8000 が他のプログラムに使われている場合、`start-all.ps1` が代わりのポートを尋ねて `.env` に保存します。

起動後、ワークベンチを動かしているコンピューターで <http://127.0.0.1:8000>（または変更したポート）を開きます。初回は「初回セットアップ」画面が表示されるので、管理者のユーザー名、パスワード、ブランド名を入力すると自動でログインします。その後、「設定」のプラットフォーム連携カードに各アプリのキーを入力して「〇〇 アカウントを連携」を押します。各カードの設定ガイドに、プラットフォームの開発者設定に入力するコールバック URL が表示されます。

Claude Code をワークベンチに接続する（アドレスは「設定 → マイアカウント → Agent をインストール」からコピー）：

```text
/plugin marketplace add <内部アドレス>/plugin/marketplace.json
/plugin install mwb@marketing-workbench
```

Codex と Claude デスクトップ版のインストール方法は [`docs/operations.md`](docs/operations.md#agent-連線) をご覧ください。

### エージェントでワークベンチを操作する（MCP）

ワークベンチは `<内部アドレス>/mcp` で MCP エンドポイント（Streamable HTTP）を提供しており、ローカルと Tailscale からのみ接続できます。上の plugin のほか、リモート MCP に対応したエージェントなら直接接続できます。「設定 → マイアカウント → Agent 接続」で接続トークンを作成して環境変数 `MWB_TOKEN` に入れ、エージェントの MCP 設定に次を追加してください（Claude Code の `.mcp.json` の書き方です。他のエージェントでも同じ URL とヘッダーを指定します）：

```json
{
  "mcpServers": {
    "mwb": {
      "type": "http",
      "url": "<内部アドレス>/mcp",
      "headers": { "Authorization": "Bearer ${MWB_TOKEN}" }
    }
  }
}
```

トークンは一度しか表示されません。会話に貼り付けたり git にコミットしたりしないでください。接続すると、エージェントはまずサーバー情報とブランドガイド（NG ワードを含む）を読み、`get_guide` で手順全体を取得するので、普段の言葉で頼めば大丈夫です：

| こう頼めます | エージェントが使うツール |
|---|---|
| 「`/mwb:report` 直近 30 日の各プラットフォームの成果をまとめて。一番よかった投稿は？」 | `get_dashboard`、`list_posts`、`get_post` |
| 「最近のコメントで、視聴者が一番よく聞いていることは？」 | `get_popular_questions`、`list_comments` |
| 「`/mwb:ideas` 直近 3 本の動画のコメントからテーマを考えて」 | `start_ideation`、`get_ideation_report`、`save_ideation_ideas` |
| 「`/mwb:script` テーマ 3 を 60 秒のショート動画の台本にして、決まったら保存して」 | `get_script`、`save_script` |
| 「`/mwb:post` この台本で Instagram と Threads のキャプションを書いて、この動画を添付して」 | `create_draft_from_idea`、`save_publish_draft`、`create_upload_link` |
| 「`/mwb:publish` 明日の夜 8 時に予約投稿して」 | `prepare_publish`、あなたの確認後に `confirm_publish` |

投稿は必ず 2 段階です。エージェントがプラットフォーム、アカウント、キャプション全文、素材、投稿日時を提示し、あなたがはっきり同意してから送信します。テーマと台本も、あなたが確定して「保存して」と伝えたときだけ保存されます。スラッシュコマンドは Claude Code plugin のショートカットで、他のエージェントでは普段の言葉で頼めば十分です。実際に使えるツールは、エージェントが読み込んだツール一覧のとおりです。

デプロイ、更新、バックアップ、トラブルシューティングは [`docs/operations.md`](docs/operations.md)、アーキテクチャは [`docs/architecture.md`](docs/architecture.md) にあります。

開発時はバックエンドとフロントエンドを別々に起動できます：

```powershell
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ../frontend
npm run dev
```

## 環境変数

`.env.example` を `.env` にコピーします。バックエンドの設定にはすべて既定値があり、空欄のパスは repo 内の `data/` に置かれます。全項目と説明は `.env.example` のコメントをご覧ください。

**起動前に必ず設定するもの：**

| 変数 | 説明 |
|---|---|
| `NGROK_AUTHTOKEN` | `start-all.ps1` が Webhook ゲートウェイを起動するときに必須で、ないと停止します。ngrok の実行ファイルは PATH に置くか、`NGROK_PATH` でフルパスを指定してください |
| `ACCOUNT_ENCRYPTION_KEY` | 画面でプラットフォームや AI のキーを保存する前に必要です。`backend/` で `uv run python ../scripts/initialize_ai_encryption.py` を実行すると自動で書き込まれます。`.env` は別途バックアップしてください。失うと暗号化済みのキーを読み戻せません |

**初回起動時に自動生成されるもの（入力不要）：** `INGEST_API_KEY`、`WEBHOOK_PROBE_SECRET`、`WEBHOOK_PUBLIC_URL`（ngrok が割り当てる固定アドレス）。

**推奨設定：**

| 変数 | 既定値 | 説明 |
|---|---|---|
| `DATABASE_PATH` | `data/db/mwb.db` | データベースの場所。絶対パスを推奨 |
| `EXPORT_ROOT` | `data/export` | エクスポート先フォルダ |
| `LOG_PATH` | `data/logs/backend.jsonl` | ログファイル |
| `APP_ORIGIN` | `http://127.0.0.1:8000` | 許可するオリジン。カンマ区切りで複数指定可。HTTPS のアドレス（Tailscale など）を加える場合は `SESSION_COOKIE_SECURE` を `true` にしないと起動しません |
| `BACKEND_INTERNAL_URL` | `http://127.0.0.1:8000` | バックエンドの待ち受けアドレス。ポートを変える場合は `APP_ORIGIN` のローカルアドレスも合わせて変更します。ポートが異なると `start-all.ps1` は起動しません。ポートを尋ねたときは両方を書き込みます |
| `ALLOWED_HOSTS` | `["127.0.0.1","localhost"]` | 許可するホスト名。ワイルドカードは使えず、1 つずつ列挙します |
| `TAILSCALE_ENABLED` | `false` | Tailscale を使う場合は `true` にし、`node scripts/tailscale.mjs configure` を実行するとオリジンとホストが自動で設定されます |
| `COMMENT_RETENTION_DAYS` | `365` | 他人のコメントの保存日数（30–3650）。期限切れのコメントは毎日の定期処理で削除されます |

**任意：**

| 変数 | 説明 |
|---|---|
| `GEMINI_API_KEY`／`OPENAI_API_KEY`／`ANTHROPIC_API_KEY` と対応する `*_MODEL` | 内蔵の AI プロバイダー。管理者が画面で検証して暗号化保存することもできます |
| `GEMINI_PAID_TIER` | 既定は `false`。Google Cloud プロジェクトに請求先を設定済みの場合のみ `true` にします。そうでない場合、Gemini はプラットフォームのデータを処理しません |
| `AI_MONTHLY_BUDGET_USD` | AI API の月間予算の上限 |
| `NOTIFY_LINE_*` | LINE 通知用の Messaging API 認証情報とグループ |
| `BACKUP_LOCAL_ROOT`／`BACKUP_DRIVE_ROOT`／`BACKUP_PASSWORD`／`SEVEN_ZIP_PATH` | 暗号化バックアップの保存先、パスワード、7-Zip のパス |

各プラットフォーム（Meta、Threads、YouTube、TikTok）のアプリのキーは、画面のプラットフォーム連携カードで入力すると暗号化してデータベースに保存されます。トークンは連携の流れで書き込まれるため、手で入力する必要はありません。キー、トークン、パスワードは git にコミットしないでください。

## コントリビューション

- PR を送る前に、`backend/` で `uv run pytest` を、リポジトリのルートで `npm --prefix frontend test`、`npm --prefix frontend run build`、`node --test scripts/*.test.mjs` を実行してください。すべての受け入れテストは `python scripts/verify_all.py` です（Chromium が必要）。
- テストでは常に隔離されたデータと HTTP の代替を使い、実際のプラットフォーム API を呼び出してはいけません。
- データベースの変更は必ず Alembic のマイグレーションで行います。
- 画面の文言を追加するときは `t('繁体字の原文')` で囲み、`frontend/src/locales/` に英語・簡体字中国語・日本語の訳を追加してください。用語は [`docs/i18n術語表.md`](docs/i18n術語表.md) に従います。
- プラットフォーム連携は公式 API のみを使い、スクレイピング、非公式 API、ブラウザー自動化は受け付けません。
- アーキテクチャとルール：[`docs/architecture.md`](docs/architecture.md)、[`docs/MCP規範.md`](docs/MCP規範.md)、[`docs/UI規格.md`](docs/UI規格.md)。

PR を歓迎します。大きな変更（新しいプラットフォーム、データベースの変更、権限ルール）は、先に issue で方向性を相談してください。返信までの時間はまちまちですので、ご了承ください。

ご質問や協業のご相談は support@ruidefilm.com まで。セキュリティの問題は公開 issue ではなく、メールでお知らせください。

## ライセンス

MIT License です。[`LICENSE`](LICENSE) をご覧ください。本プロジェクトを利用する場合も各プラットフォームの規約を守る必要があります。[`docs/合規須知.md`](docs/合規須知.md) をご覧ください。

## 謝辞

本プロジェクトは多くのオープンソースプロジェクトの上に成り立っています。特に [FastAPI](https://fastapi.tiangolo.com/)、[SQLAlchemy](https://www.sqlalchemy.org/)、[Alembic](https://alembic.sqlalchemy.org/)、[React](https://react.dev/)、[Vite](https://vite.dev/)、[uv](https://docs.astral.sh/uv/)、[Playwright](https://playwright.dev/)、[Model Context Protocol](https://modelcontextprotocol.io/) に感謝します。
