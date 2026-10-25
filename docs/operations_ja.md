# デプロイと運用

> **言語 / Language / 語言 / 语言**：[繁體中文](operations.md) | [简体中文](operations_zh-CN.md) | [English](operations_en.md) | 日本語

データベース、エクスポート、ログ、バックアップ、MCP 監査のパスは設定で指定します。開発者のディスクやホスト名には依存しません。`.env.example` は設定項目の参考で、認証情報はローカルでのみ入力します。各機能の設計ルールは [architecture](architecture_ja.md) を参照してください。ここには操作手順だけを記載します。各変更の検証の詳細は git の履歴に残し、このページには書きません。

## デプロイの順序

開発 session では、稼働中のサービスを停止／再起動せず、本番環境の送信スイッチも変更せず、プラットフォームへのメッセージも送信しません。権限を持つ操作担当者が、作業ツリーとロールバック用データを確認したうえで実行します：

1. **バックアップ**：まず `./scripts/backup.ps1` を実行し、別途 `.env`、サービスのデプロイ設定、旧バージョンを安全にバックアップします。データベースとエクスポートが読み取れることを確認し、アカウントの送信スイッチと `publishing.enabled` を記録します。バックアップには過去のコンテンツと秘密情報が含まれるため、操作担当者だけがアクセスでき、オープンソースのアーカイブには含めません。
2. **サービスの停止**：`./scripts/stop-all.ps1` を実行し、PID がこのプロジェクトのものであること、サービスのポートが解放されたことを確認します。権限が足りない場合はデプロイを中止し、2 つ目の受信サービスは起動しません。
3. **スキーマの更新**：backend ディレクトリで `uv run alembic upgrade head` を実行します。個別の migration の事前チェックとダウングレードの制約は、下の「Migration の注意事項」を参照してください。
4. **起動**：先に `npm --prefix frontend run build` を実行し、次に `./scripts/start-all.ps1 -SuppressSystemAlerts` を実行します。ngrok は新しい制御ヘッダーと probe パス `/webhook/mwb-gateway-probe` を使います。今回もプッシュ通知を禁止する場合は、プロセスの環境変数で `SCHEDULER_NOTIFY_ENABLED`、`RECEIVE_HEALTH_ALERTS_ENABLED` を無効にし、有料の処理が今回の許可の範囲内に収まるようにします。
   - `start-all.ps1` はバックエンドを起動する前に `alembic current` と `alembic heads` を比較します。データベースのスキーマが最新でなければ停止して手順 1–3 を案内し、自動では更新しません（バージョン記録のない新規データベースは例外で、そのままスキーマを作成します）。サービスがまだ動いている場合、このチェックはサービスを停止する前に行うため、旧サービスを先に止めてしまうことはありません。手順 1–3 を終えた後は、`-ApplyMigrations` を付けて手順 3 の upgrade をスクリプトに実行させることもできます。
   - バックエンドと Webhook ゲートウェイは `Win32_Process` で独立したプロセスとして作成されます（親プロセスは WMI で、呼び出し元の job には含まれません）。そのため、起動ウィンドウを閉じても、Agent のバックグラウンド shell やスケジュールタスクが終了しても、サービスは一緒に停止しません。呼び出し元のその時点の環境変数（上の無効化設定を含む）はすべてサービスに引き継がれます。WMI が使えない場合は `Start-Process` にフォールバックし、警告を表示します。
5. **検証**：`node scripts/webhooks.mjs check` の公開境界ケースすべて、`./scripts/check_runtime.ps1`、Tailscale でのログイン、名前の各表示箇所、Word のヘッダー、テンプレートのプレビュー／監査。アカウントの `send_enabled` と `publishing.enabled` が前後で同じであることを確認し、新しいエクスポートと外部キーをチェックします。新しいアカウントを登録する前に REGISTRATION_BRAND_SLUG を設定するか、--brand を渡します。

フロントエンド、バックエンド、`plugin/` は必ず一式でデプロイします。隔離検証が済んだことはデプロイ済みを意味しません。

## Migration の注意事項

本番の migration の前に、SQLite の `mode=ro` で本番データベースを開き、backup API で `.runtime/` にコピーします。そのコピーで upgrade／downgrade／upgrade を実行し、各テーブルの件数、外部キー、アカウントの送信スイッチを確認します。コピーには実際のコンテンツが含まれるため、コミット、アップロード、原文のスクリーンショットは禁止で、リハーサル用のコピーをデプロイしてもいけません。使用中の WAL を `immutable=1` で無視しないでください。

| バージョン | 注意事項 |
|---|---|
| 0021 | 無効化したプロバイダーを JSON null に変更。管理者は AI 設定でキーを検証し、既定のプロバイダーを選び直す必要があります。`downgrade 0020` は未設定のままの項目だけを復元します。 |
| 0024 | 7 つの業務テーブルから旧データソースのフラグを削除。いずれかのテーブルに true が残っていれば upgrade 全体を中止し、テーブル名と件数を表示します。処理方法は別途確認が必要です。 |
| 0025 | 旧コメント処理と遡及探索をすべて終了し、業務データは保持。downgrade しても旧処理は復活しないため、旧プログラムに戻す場合は旧自動コメントのスケジュールを別途無効にする必要があります。 |
| 0026 | 0025 に下げるとフォロワーのスナップショットテーブルが削除されるため、先にバックアップしてください。 |
| 0027 | `downgrade 0026` で 3 社分のフォールバックモデル設定が削除され、後続ラウンドを待つ AI 処理は skipped になります。戻す前にジョブスケジュールとブランドの AI 設定をバックアップしてください。 |
| 0030 | 廃止された `auto_draft_jobs` を削除。ダウングレードでは空のテーブルだけを再作成します。 |
| 0031 | プラットフォーム／jev の認証情報を DB に保存可能に。プラットフォームの上書き設定が保存済みの場合、`downgrade 0030` は設定の消失を拒否します。戻すときは upgrade 前のバックアップの復元を優先してください。 |
| 0032 | メンバー管理。既存アカウントは `must_change_password=false`。 |
| 0033 | Meta／Threads OAuth。 |
| 0035–0043 | 投稿（0035）、caption_job_json（0036、現在は未使用）、Agent の認可（0037）、Agent の下書きアップロード（0038）、削除検知（0039）、Facebook の非公開投稿（0040）、プラットフォームのオプションと Threads のスレッド（0041）、ストーリーズ（0042、ストーリーズがある場合はダウングレードを拒否）、YouTube の投稿とサムネイル（0043、YouTube の投稿またはサムネイルがある場合はダウングレードを拒否）。0041 のダウングレードではオプション／スレッドの進捗が削除されるため、スレッドを送信済みの場合はバックアップなしでダウングレードできません。 |
| 0046 | 投稿サムネイルのキャッシュ `post_thumbnails`。ダウングレードではテーブルをそのまま削除します（プラットフォーム画像のキャッシュにすぎません）。アップグレード後は毎時のスケジュールが再取得します。 |
| 0048 | Instagram リールのカバー画像：`publish_media.role` に `cover` を追加し、既存の行は変更しません。カバー画像がある場合はダウングレードを拒否します。 |
| 0049 | Facebook 動画／リールのカバー画像：`publish_media.role` に `fb_cover` を追加し、既存の行は変更しません。FB のカバー画像がある場合はダウングレードを拒否します。FB のカバー画像には `pages_manage_engagement` が必要です。既存の Meta 連携は一度連携し直さないと取得されません（連携し直さなくても通常どおり投稿できますが、カバー画像は適用されません）。 |

## 検証

**1 つのコマンドですべての検証を実行**：プロジェクトのルートで `python scripts/verify_all.py` を実行します。ruff、tsc、`.runtime/verify-dist` へのビルドを順に実行し、続いて pytest、フロントエンドのテスト、`scripts/*.test.mjs`、すべての隔離 UI チェック（`scripts/check_*.py` を自動で収集し、`*_live.py` は除外）と補足チェック（一覧は `verify_all.SUPPLEMENTARY`）を並列で実行します。並列の手順がすべて終わった後に `runtime-clean`（`scripts/test_runtime_clean.py`）を単独で実行し、最後に禁止文字列とハードコードされた色をスキャンします（`git grep` 自体の失敗も不合格扱い）。各手順の出力は `.runtime/verify/<手順>.log` にあり、最終行が `ALL PASS` のときだけ合格です。作業前に `python scripts/verify_all.py snapshot-data <ファイル>` で `data/` の一覧を記録し、最後に `--data-baseline <ファイル>` を付けて比較します。開発中は `--only pytest,check_xxx` で指定した手順だけを実行し、`--jobs 1` で順番に実行して干渉を切り分けます。手順名を間違えるとすぐにエラーになり、使える名前が表示されます。`--only` に `build` を含めない場合、UI チェックは前回ビルドした `.runtime/verify-dist` を使います（注意が表示されます）。フロントエンドを変更したときは `build` も一緒に選んでください。新しいチェックは `scripts/check_*.py` に置くだけで収集されるため、文書に数を書く必要はありません。

UI チェックは Playwright でローカルにインストールされた Google Chrome を開きます（`runtime_tmp.py` が `channel="chrome"` を指定）。検証用のマシンには先に Chrome をインストールしておく必要があります。

隔離のルール：

- 各チェックの DATABASE_PATH／EXPORT_ROOT／メディアとログは、`browser_harness` または `runtime_tmp` によって `.runtime/tmp/<一意の名前>/` に向けられます。CSS だけのチェックと helper はデータベースを開きません。本番の設定や認証情報を読まず、実際の AI やプラットフォームを呼び出さず、外部に接続しません（プラットフォームは常に HTTP mock）。
- 稼働中の `frontend/dist` を上書きしない：`.runtime/` にビルドし、`FRONTEND_DIST_DIR` でそこを指定します。

  ```powershell
  npm --prefix frontend run build -- --outDir ../.runtime/verification-dist
  $env:FRONTEND_DIST_DIR = (Resolve-Path .runtime/verification-dist).Path
  cd backend
  uv run python ../scripts/check_ui_scale.py
  ```

- `runtime_tmp.runtime_check` は `temporary_dir()` で一時ファイルを管理します。エンジン、ログ、子プロセスを取得したらすぐに `cleanup()` を登録し、例外や KeyboardInterrupt のときも同じく片付けます。削除に失敗した場合は警告を表示するだけです。Node のビルドは `runtime_tmp.mjs` が after hook を登録します。片付けの動作は `scripts/test_runtime_clean.py` で検証します。これは `.runtime/tmp` が空になったかを比較するため、ほかのチェックがすべて終わってから単独で実行する必要があり、`verify_all.py` の `runtime-clean` 手順はこの順番で組まれています。
- スクリーンショット、Word のサンプル、JSON レポートは最新の 1 回分だけを `.runtime/check-output/<エントリースクリプト名>/` に保存し、毎回開始時に空にします。実行をまたいだ before／after の比較が必要な場合は別に保存してください。
- 検証スクリプトは自分が作成した隔離プロセスだけを停止します。`*_live.py` は検証の対象外で、実行には別途明確な許可が必要です。
- コントラストのチェックは CSS だけを読みます：文字は 4.5:1 以上、アイコン／フォーカス／グラフは 3:1 以上。
- `eval_jev_questions.py` は既定ではオフラインの transport の代替だけを実行します。合格してもパイプラインの検証にすぎず、モデルの品質を示すものではありません。`--live` と `evaluate_jev_hard.py` は有料 API を呼び出すため、明示的に指定する必要があります。

並列検証の安定性：既定の `--jobs 4` では pytest とブラウザチェックが CPU を奪い合うため、チェックは「単独実行なら十分速い」ことに依存してはいけません。

1. `test_dashboard_trends_scale_read_only` のクエリ数と書き込みなしは構造的なアサーションです。時間のしきい値は、ウォームアップ後に 5 回連続実行した最良値とだけ比較します。
2. アップロードエンドポイントのデータベース処理は必ず threadpool で実行します。イベントループ上で SQLite の書き込みロックを待つとサーバーが固まり、約 15 秒のデッドロックの後に 503 を返します（`test_upload_waits_for_write_lock_off_event_loop` で再現を固定）。投稿ページのメディアのアップロード／削除と保存は同じキューを共有します。
3. 下書きを開いて内容を変更していない場合、自動チェックは `/check` を呼び出すだけで保存しません。理由なく version が増えて Agent の `prepare_publish` が衝突するのを防ぐためです。
4. 隔離チェック用のサーバーは `ports.KEEP_ALIVE_SECONDS` でアイドル接続の切断を無効にし、Playwright が接続を再利用したときの `socket hang up` を防ぎます。uvicorn を起動するチェックを新しく追加する場合は、この設定を引き継いでください。

## バックエンドのテスト

`backend/` で実行します。並列モードは日常の検証に、シングルスレッドはデバッグと計測に使います：

```powershell
uv run pytest -q -n auto --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
uv run pytest -q --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
```

- テストセッションごと（並列時は worker ごと）に `alembic upgrade head` を 1 回だけ実行してテンプレートのデータベースを作り、各テストは SQLite backup API で自分の `tmp_path` にコピーします。テンプレートは migration の内容のフィンガープリントに紐づき、実行をまたいでキャッシュしません。実装は `backend/tests/migration_database.py` にあります。
- migration そのものを検証するテストには `@pytest.mark.migration` を付ける必要があり、付けるとテストごとに実際の migration を実行する方式に切り替わります。
- テスト中は外部への接続と DNS 解決が即座に失敗します（loopback のみ許可）。新しいテストでは外部呼び出しを mock に置き換えてください。
- 共通のヘルパーは `tests/conftest.py` にあります：`login()`（CSRF を取得してログインし、以降のヘッダーを返す）と `seed_records()`（合成データと過去の料金行を追加）。新しいテストでは `from conftest import ...` でそのまま使い、コピーを作らないでください。
- 新しいテストは固定のファイル名、固定のポート、モジュールレベルの共有状態に依存してはいけません。
- uv／pytest のキャッシュディレクトリが制限されている場合は、UV_CACHE_DIR、TEMP、TMP と `--basetemp` を書き込み可能な隔離ディレクトリに向け、本番のデータ設定は変更しません。

## Agent 接続

ワークベンチは内部向けの `/mcp`（Streamable HTTP）を Web 画面と同じポートで提供します。到達できるのはローカルと Tailscale からだけで、公開側からは 404 のままです。インターフェースの仕様は [MCP規範](MCP規範_ja.md)（MCP 仕様）を参照してください。メンバーはまず Tailscale に参加し、内部の HTTPS URL で「設定 → マイアカウント → Agent をインストール」を開きます。非公開の GitHub repo へのアクセス権は不要です。localhost からのダウンロードは参考とテスト用で、Claude がホストする marketplace の archive は HTTPS でなければなりません。

**Claude Code**（v2.1.224 以上）：

```text
/plugin marketplace add <內部網址>/plugin/marketplace.json
/plugin install mwb@marketing-workbench
```

`/plugin → Marketplaces` で marketing-workbench を選び、Enable auto-update をオンにします（メンバー本人が操作する必要があります）。初めて MCP を使うときは、自分のワークベンチのアカウントでログインして承認します。手動で更新するには `/plugin marketplace update marketing-workbench` を実行し、更新後は会話を新しく始めます。本人なら repo のルートで `claude --plugin-dir plugin/mwb` を使って開発中のファイルを読み込むこともでき、ローカルの URL は <http://127.0.0.1:8000/mcp> です。

**Codex**（skills＋config）：インストール欄で Codex に切り替えてダウンロード・展開し、skills 内の 5 つのフォルダを `~/.agents/skills/` に置きます（同名のものがあれば先にバックアップ）。ZIP の config.toml を `~/.codex/config.toml` にマージし、`codex mcp login mwb` を実行して自分のアカウントで承認します。読み取り専用のツールは approval_mode=approve、すべての書き込みと confirm_publish は prompt です。クライアント側の承認設定は、バックエンドの権限と投稿の確認の代わりにはなりません。更新するときはダウンロードし直してマージします。この方式にした理由：Codex plugin の installed server policy はユーザーが config で設定する必要があり、また `codex plugin marketplace add` はホストされた JSON URL を受け付けないためです。

**Claude デスクトップ版**：Claude デスクトップ版に切り替えて `.mcpb` をダウンロードし、デスクトップ版の「設定 → 拡張機能 → 拡張機能をインストール」でそのファイルを選びます。ワークベンチの URL はインストール欄からコピーし（ローカルなら <http://127.0.0.1:8000> も可）、「Agent 接続」で接続トークンを作成して拡張機能の設定に貼り付けます。更新は新しい版をダウンロードして再インストールします。拡張機能を削除しても、ワークベンチ側の取り消しの代わりにはなりません。公式フォーマットの確認と手動での mcpb 検証コマンドは `plugin/README.md` を参照してください。

**Hermes**：[MCP規範](MCP規範_ja.md) の「Hermes の接続」を参照してください。

**plugin の新しい版のリリース**：`plugin/mwb/` を変更 → `.claude-plugin/plugin.json` の version を上げ、開発用 `.mcp.json` の header も合わせる → backend で `uv run python ../scripts/update_plugin_hash.py` を実行 → テストを実行 → 許可された操作担当者がフロントエンド、バックエンド、`plugin/` をデプロイ。version の唯一の情報源は plugin.json で、更新ツールは同じ version で異なるハッシュによる上書きを拒否します。互換性のある追加では MCP API のバージョンを変えません。plugin の最低互換バージョンは 0.3.0 で、それより古いものは get_server_info／get_guide しか読めません。デプロイ担当者は `claude plugin validate <解壓縮路徑>` でパッケージを検証し、本人が試してからメンバーに提供します。

**取り消しと有効期限**：自分の OAuth／接続トークンは「マイアカウント → Agent 接続」で取り消します。管理者はメンバーページで確認後、すべてを取り消せます。無効化、パスワードのリセットや変更でも接続は取り消されます。どちらの接続も 30 日間使わないと失効します。OAuth のアクセストークンは 1 時間、refresh は 30 日で毎回ローテーションされ、古い refresh を再利用すると認可全体が取り消されます。スケジュールが毎時、期限切れの認可データを削除します。監査にはメンバー、接続名、認可 id を記録し、秘密情報は記録しません。

## 投稿

- 投稿のマスタースイッチは Setting の `publishing.enabled` で、既定は false です。切り替えられるのは管理者だけで、投稿ページで確認したうえで行います。デプロイでその現在値を変えてはいけません。
- 予約投稿とメディアの片付けには、SCHEDULER_ENABLED と SCHEDULER_PUBLISH_ENABLED の両方がオンである必要があります。PUBLISH_POLL_SECONDS の既定は 5、PUBLISH_POLL_TIMEOUT の既定は 300 秒です。Threads の未完了のコンテナは最短でも 60 秒ごとにしか再照会しません。いずれもタイムアウトがあり、自動で再投稿はしません。
- メディアは PUBLISH_MEDIA_ROOT（既定は `data/publish-media`）に保存されます。IG／Threads では、プラットフォームが `/media/<權杖>` をダウンロードできるよう WEBHOOK_PUBLIC_URL の HTTPS origin が必要です。公開境界と ngrok のポリシーで追加で許可するのは、メディアトークンの正確なパス（IG 用に変換した `.jpg` を含む）だけです。
- 投稿履歴の「プラットフォームの投稿を確認」（`POST /api/publish/presence-check`、管理者とマーケティング担当者）は一覧全体を取得し直し、Meta の呼び出し枠を消費します。同じブランドで手動確認できるのは 60 秒に 1 回です。
- 結果が確認できない場合（タイムアウト、中断）は、まずプラットフォームで投稿済みかどうかを確認してから「失敗したプラットフォームのみ再試行」を押します。
- デプロイ後の最初の実際の投稿は、ユーザーが立ち会い、その場で同意したうえで行います：Facebook はまず非公開投稿、YouTube はまず「非公開」の動画、TikTok はまずテスト動画を受信トレイに送ります（アプリ内で投稿を押さなければ公開されません）。ユーザーのその場での同意なしに、投稿ボタンを押してはいけません。

**ストーリーズ**：Facebook ログイン経由の IG ストーリーズには、ビジネスアカウントと instagram_content_publish、instagram_manage_insights が必要です。Meta App の管理画面の Instagram Webhooks で `story_insights` にチェックを入れ、その IG アカウントが App をサブスクライブしていることを確認します。受信側はローカルで既知のストーリーズ ID の final スナップショットだけを書き込み、元のイベントは保存しません。

**Facebook ストーリーズのインサイトの読み取り専用確認**（未実施）：まずアカウント、期限切れでない既存のストーリーズ、読み取り専用の範囲についてユーザーの同意を得ます。公式の Page Stories／insights のドキュメントを読み直し、ドキュメントが明確にサポートしている場合に限り、既存のストーリーズ ID に GET を送ります。アップロード、作成、投稿はしません。バージョン、エンドポイント、HTTP／エラーコード、各項目が使えるかを記録し、token、アカウント、元のレスポンスは記録しません。ドキュメントがまだ不明確なら中止し、「Facebook はストーリーズのインサイトを提供しない」のままにします。

**デプロイ前に確認すべきプラットフォームの仕様**：FB リールの 3–90 秒／9:16、Threads の絵文字のバイト数の数え方、published_posts がリールを含むか、IG ストーリーズの 3–60 秒と JPEG の仕様。これらの値は `publish_rules.RULES` にまとめてあり、確認後はそこだけを変更すれば済みます。

## Meta／Threads の初回連携

コールバックを受け付けるのは、内部でログイン中の管理者だけです。公開側の `/api/oauth/*` はすべて 404 です。ACCOUNT_ENCRYPTION_KEY はデプロイ担当者が用意します。

1. Meta for Developers の「Facebookログイン → 設定」で、「有効なOAuthリダイレクトURI」に `<內部 https 網址>/api/oauth/meta/callback` を追加します（ワークベンチの「設定ガイド」ウィンドウに表示され、コピーできます）。
2. ユースケースに `pages_manage_posts`、`instagram_content_publish` と、読み取りに必要な `pages_show_list`、`pages_read_engagement`、`pages_read_user_content`、`pages_manage_metadata`、`read_insights`、`instagram_basic`、`instagram_manage_comments`、`instagram_manage_insights` が含まれていることを確認します。廃止済みの DM の権限はもう要求しません。
3. 内部のワークベンチの「プラットフォーム連携 → Meta → 手動設定（詳細）」でアプリID と app secret を設定し、「Meta アカウントを連携」を押します。Facebook ページが 1 つだけなら自動で採用され、複数ある場合は選択します。IG がなくても FB は連携できます。

Threads：「ユースケース → Threads API → 設定」で別のアプリID と app secret を取得し、`<內部 https 網址>/api/oauth/threads/callback` を追加します。`threads_basic`、`threads_content_publish`、`threads_manage_replies`、`threads_manage_insights`、`threads_read_replies` を確認し、ワークベンチに戻って 2 つの欄を設定して「Threads アカウントを連携」を押します。既存の連携にインサイトの権限が足りない場合、Threads のカードに「インサイトと返信の権限を得るには連携し直してください」と表示されます。連携し直すまで投稿一覧と投稿は通常どおり動きますが、成果と返信は取得しません。

state は管理者とログイン session に紐づき、10 分間有効の一回限りです。Facebook のユーザートークンは残り 7 日未満になると連携し直すしかなく、ページトークンには別途有効期限を設けません。Threads は毎日チェックし、残り 7 日未満かつ前回の更新から 24 時間以上たっている場合だけ延長します。失敗と期限切れの通知は既存のブランドの LINE 通知グループに送られ、グループが設定されていなければ監査に残すだけです。

Threads のデプロイ後、最初の本番環境で次を確認してください：6 項目の insights を 1 回のリクエストで取得できるか（公式ドキュメントでは views、shares が開発中とされています）、conversation が limit パラメーターを受け付けるか、返信の username が欠ける割合。Threads は Meta の呼び出し枠と usage headers を経由しません。1 ラウンドの上限は一覧 50 ページ、成果 300 件です。

## TikTok の連携

TikTok for Developers の Sandbox だけを使い、審査には出しません（`docs/TikTok規劃.md` を参照）。プラットフォーム連携の TikTok カードにある「設定ガイド」に沿ってアプリを作成します：Sandbox で Login Kit と Content Posting API を追加し（Direct Post はオフ）、Redirect URI は Web を選んで `<BACKOFFICE_ORIGIN>/api/oauth/tiktok/callback` を入力、Scopes は `user.info.basic`、`user.info.stats`、`video.list`、`video.upload`、Target Users に連携するアカウントを追加します。必須項目には公開された利用規約とプライバシーポリシーの URL が含まれます。Client key／Client secret はカードで暗号化して保存します（`.env` の `TIKTOK_*` は予備としてだけ使います）。

連携はほかのプラットフォームと同じ 2 段階のリダイレクトです。access token は 24 時間で、呼び出し前に残りが 5 分を切っていれば refresh token で更新し、TikTok が返す新しい refresh token を保存します。カードには refresh token の有効期限が表示されます。毎日の OAuth メンテナンスで事前に更新し、更新に失敗した場合（`invalid_grant`）は再連携が必要とマークして LINE で 1 回通知します。refresh token の期限の 14 日前にも同様に通知します。「連携を解除」は TikTok の revoke を呼び出し（トークンがすでに無効でも通常どおり削除）、TikTok のトークンと同期済みデータを削除します。アカウントの行は残し、名前を「TikTok」に変更します。

連携後は、毎時のデータスケジュールが `POST /v2/video/list/` で公開動画（再生、いいね、コメント、シェアの数を含む）を読み取り、同じ一覧を投稿と期限の来た成果スナップショットに書き込みます。フォロワー数は毎日のフォロワースケジュールが `GET /v2/user/info/` の follower_count で記録します。最初のページから最後のページまで取得でき、かつ空でない一覧の場合に限り、消えた動画を削除済みとマークし（TikTok 上で削除されたか非公開に変更された可能性があります）、投稿データから非表示にします。再び現れれば元に戻します。一覧が途中で途切れた場合や空の場合は判定しません。認可の再連携が必要な間、スケジュールは TikTok をスキップし、API を呼び出しません。TikTok のコメントは一切読み取りません。

投稿：TikTok は動画だけに対応し、ユーザーの TikTok の受信トレイに送ります（未審査のアプリは直接公開できません）。受信トレイの API はキャプションを受け付けないため、投稿履歴に「キャプションをコピー」を用意しています。`video.upload` が必要です。publish_id を先に保存し、再試行の前に状態を確認して、すでに受信トレイに入っていれば再送しません。受信トレイには 24 時間以内に保留中の動画を最大 5 本までしか置けず、超えると `inbox_full` が返ります。送信後は投稿スケジュールが 10 分ごとに状態を確認し（最長 7 日）、ユーザーがアプリで投稿すると「アプリで投稿済み」と表示されます。migration 0047 で publish_targets のプラットフォーム制限を緩めました。ダウングレード前に TikTok の投稿先がすでにある場合は拒否されます。

## YouTube の連携と投稿

1. Google Cloud Console でプロジェクトを作成し、「API とサービス → ライブラリ」で **YouTube Data API v3** と **YouTube Analytics API** を有効にします。
2. 「Google Auth Platform → ブランディング」で同意画面を作成します。「対象」で **外部** を選び、公開ステータスを **本番環境（In production）** に変更します（Testing の refresh token は通常 7 日で期限切れになります）。
3. 「データアクセス」に `https://www.googleapis.com/auth/youtube.readonly`、`https://www.googleapis.com/auth/yt-analytics.readonly` を追加します。投稿ページから動画をアップロードする場合は、さらに `https://www.googleapis.com/auth/youtube.upload` を追加します。
4. 「クライアント → クライアントを作成」で **ウェブ アプリケーション** を選びます。承認済みのリダイレクト URI は `<內部 HTTPS 網址>/api/oauth/youtube/callback` と完全に一致している必要があります。
5. 管理者が「設定 → プラットフォーム連携 → YouTube」にクライアント ID／シークレットを入力して保存し、「YouTube アカウントを連携」を押します（または「再連携」を押し、「動画をアップロード」のチェックを入れたままにします）。
6. 対象のチャンネルを所有する Google アカウントを選びます。未確認の警告が出たら、自分のアプリであることを確認して「詳細 → （アプリ名）（安全ではないページ）に移動」を押します。組織のポリシーは回避しません。チャンネルがブランド アカウントに属する場合は、そのブランドのチャンネルを選びます。一度に登録できるのは 1 チャンネルだけです。複数ブランドの場合は、先にチャンネルのブランドの帰属を登録する必要があります。
7. ワークベンチに戻ってチャンネル名と「連携済み」を確認し、同じカードで「アップロードカテゴリ」を設定します（既定は「ブログ」（People & Blogs））。invalid_grant の場合は「再連携が必要」とマークされます。連携を解除すると Google 側の認可を取り消し、ローカルのトークンを削除しますが、過去のデータは残します。

クォータ：読み取りは永続化された `youtube.quota` で、米国西部の暦日ごとに 1 日 8,000 ユニットまでに制限します（2,000 は手動操作用に確保）。1 ラウンドの上限は一覧 50 ページ、成果 300 件です。`videos.insert` は 1 日 100 回で、別に `youtube.uploads` として数えます。`thumbnails.set` は約 50 ユニットで `youtube.quota` に含めます。未確認のチャンネルでは 15 分を超える動画は受け付けられません。サムネイルの失敗で最も多い原因はチャンネルの電話番号確認が済んでいないことで、確認後に「サムネイルを再適用」を押せば済みます（サムネイルだけを差し替え、動画は再送しません。素材が 30 日後に削除されると再適用できなくなります）。サムネイルの上限はひとまず控えめに 2 MB（`RULES.youtube.thumbnail_bytes`）としています。Google が未監査のプロジェクトの公開設定を制限した場合、投稿履歴に「YouTube での実際の公開設定：…」と表示されます。

## メンバー管理とアカウントの復旧

- 管理者は「設定 → メンバー → メンバーを追加」でユーザー名、表示名、ロール、ブランドを入力します。仮パスワードは一度しか表示されないので、安全な方法で直接渡してください。監査、ログ、文書に貼り付けないでください。新しいメンバーは初回ログイン時にまずパスワードを変更する必要があります。
- 「編集 → パスワードをリセット」は新しい仮パスワードを発行し、すべてのログインを取り消します。無効化してもすぐに取り消されます。有効な最後の管理者は無効化も降格もできず、管理者は自分自身を無効化できません。
- すべてのロールが「設定 → マイアカウント」でパスワードを変更できます（12 文字以上、新旧は同じにできません）。成功すると現在のログインは維持され、ほかのログインは取り消されます。
- 同じアカウントで 5 回続けて失敗すると 15 分間ロックされます。存在するアカウントでも存在しないアカウントでも「ユーザー名またはパスワードが正しくありません」を返します。
- ほかのメンバーは同じ Tailscale ネットワークに参加する必要があります。ログイン後に「ブランドがまだ割り当てられていません。管理者に連絡してください」と表示された場合は、管理者がブランドを割り当てます。
- ログイン画面の「パスワードをお忘れですか？」では、メンバーには管理者にリセットを依頼するよう案内し、管理者向けにはリカバリーコードのフォームと下記のホスト上のコマンドを示します。ワークベンチにはメールや SMS の送信手段がないため、フロントエンドでは事前準備なしのセルフリセットを提供しません。
- 管理者は「設定 → マイアカウント → パスワードのリカバリーコード」で現在のパスワードを入力し、一回限りのリカバリーコードを発行できます（一度しか表示されず、データベースにはハッシュだけを保存）。パスワード管理ツールに保存し、パスワードと一緒には置かないでください。発行し直すと古いコードは無効になります。
- リカバリーコードでのリセットに成功すると：新しいパスワードを設定し、リカバリーコードを無効にし、そのアカウントのすべてのログインと Agent 接続を取り消し、ログインのロックを解除します。使えるのは有効な管理者だけです。誤りの場合は常に「ユーザー名またはリカバリーコードが正しくありません」を返し、ログインと共通で 5 回失敗すると 15 分ロックされます。

最後の管理者のパスワードを忘れ、リカバリーコードもない場合は、本番データベースの操作権限を持つ人がサービスのホストの対話型ターミナルで実行します：

1. デプロイされたバージョンと本番の `.env` が正しいデータベースを指していることを確認し、バックアップ手順に従ってバックアップを作成します。
2. `backend` で `uv run python ../scripts/set_password.py <管理員帳號>` を実行し、非表示の入力プロンプトで新しいパスワードを 2 回入力します（12–128 文字）。パスワードをコマンドの引数やパイプに入れないでください。既存の管理者の復旧では `--create-admin` を付けません。
3. ツールはそのアカウントのすべての session を取り消し、パスワード変更の要求とログインのロックを解除します。再ログイン後にロールとブランドを確認してください。ツールは無効化されたアカウントを有効にしたり、ロールを変更したりはしません。`--create-admin` は初回初期化の予備手段で（通常は Web 画面の初回設定を使います）、データベースにまだブランドがない場合は唯一のブランドも一緒に作成します（`--brand` または対話で入力）。

## データ変換ツール

データ変換はすべて既定で読み取り専用のドライランです。結果を確認してから `--apply` を付けます。本番での apply は、デプロイ担当者がバックアップ後に実行します。

### DM データの削除（purge_direct_messages.py）

LINE の inbound は署名検証後に 200 を返して破棄します。LINE_CHANNEL_ACCESS_TOKEN／LINE_BOT_USER_ID、SCHEDULER_DM_ENABLED／META_DM_* は廃止済みで、既存の env は残してもかまいませんが使われません。LINE 通知と NOTIFY_LINE_*、`/webhook/line-notify` は変わりません。

デプロイ担当者は先に SQLite とエクスポートフォルダをバックアップし、書き込みを止めるメンテナンス時間を設けてから、同じ一式のデータベース／エクスポートディレクトリを明示的に指定します。まずドライランで一覧を確認してから apply します：

```powershell
cd backend
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄>
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄> --apply
```

スクリプトは .env もアプリの設定も読み込みません。database は必須で既存である必要があり、export-root を指定しなければファイルは削除しません。既定の読み取り専用ドライランでは、各テーブルの件数、ファイル、判定できない raw event ID を表示します。apply は単一の BEGIN IMMEDIATE を使い、外部キーの順に DM と依存データ、過去の下書きすべて、DM にしか現れない contacts を削除します。混在する連絡先、コメント、投稿、ideation レポート、audit_log、設定は残します。混在する通知の delivery にキャッシュされた DM が含まれる場合はそのキャッシュを削除し、公開コメントの notification は残して delivery との関連を解除します。DM だけの raw payload は削除し、混在または出所不明のものは別途判断できるよう残します。

エクスポートで削除するのは、DM 専用の連絡先ディレクトリ内の対応する Markdown／Word と、DM の thread ID で名付けられた過去の Word だけです。ideation のファイルは削除しません。残す連絡先のプレフィックスと衝突するファイルは削除せず、シンボリックリンクや junction に当たったら中止します。ファイルの処理に失敗するとデータベースをロールバックし、このラウンドで削除したバイトを書き戻します。ファイルシステムと SQLite は停電時の原子性を共同で保証できないため、デプロイ時のバックアップは省略できません。削除前後の外部キーチェックは空である必要があり、監査 `data.purge_dm` には各テーブル／ファイルの件数だけを記録します。再実行すると削除数は 0 で、監査も書き込みません。削除前のバックアップがデータ復旧の拠り所です。

### プラットフォームデータの保持（data_retention.py）

プラットフォームの規約に従い、保存が認められなくなったデータを削除します。対象は、すべてのプラットフォームでワークベンチが取得してから `COMMENT_RETENTION_DAYS`（既定 365）日を超えたコメント（コメントの投稿日時ではなく取得日時で数えます）とその依存データ（分類、通知と配信のキャッシュ、どこからも参照されない連絡先）、同じ期限を過ぎた webhook の元イベントの内容（原文だけを消し、プラットフォームのイベント ID は残します。プラットフォームが古いイベントを再送しても処理済みとみなし、コメントは再作成しません）、YouTube で 30 日間再取得されていないコメント、YouTube 上で削除されてから 30 日を超えた動画（データのスナップショットとサムネイルを含む）です。アイデア出しのレポートでは、削除された引用原文と投稿の説明だけを取り除き、テーマは残します。ユーザー自身の投稿履歴は残します。エクスポート済みの Markdown／Word は変更されないため、必要に応じて操作担当者が別途削除します。

毎日のスケジュールは既定でオフです。デプロイ担当者はまず master でデプロイして `./scripts/backup.ps1` を実行し、次に**プロジェクトのルート**でドライランして件数を確認します（読み取りのみで、原文は表示しません）。`--project backend` で uv がバックエンドの環境を使います。設定は常にプロジェクトのルートの `.env` から読み込み、現在いるフォルダには関係しません：

```powershell
uv run --project backend python scripts/data_retention.py
uv run --project backend python scripts/data_retention.py --enable
```

投稿データのコメント欄には、同じ設定に基づいて各プラットフォームの保存期間と、毎日の削除が有効かどうかが表示されます。`would_delete` を確認してから `--enable` を付けて有効にします。その後は 1 日に最大 1 回実行され、1 バッチ最大 500 件でそれぞれコミットします（初回の有効化でデータ量が多くても、データベースを長時間ロックしません）。バッチごとに `data.retention` の監査を 1 件書き込みます（各テーブルの件数だけを記録）。

コメント投稿者からメールで削除を求められた場合（プライバシーポリシーで 7 日以内の対応を約束しています）は、先にバックアップし、名前で連絡先を探してプレビューし、確認してから削除します。削除するのはその人自身のコメントと連絡先だけで、その下にあるほかの人の返信は残します。レポートからはその人の引用原文を取り除き、監査 `data.delete_request` には件数だけを記録します：

```powershell
uv run --project backend python scripts/data_retention.py --find-commenter <名稱>
uv run --project backend python scripts/data_retention.py --delete-contact <id>
uv run --project backend python scripts/data_retention.py --delete-contact <id> --apply
```

YouTube の「連携を解除」は Google の認可を取り消し、同期済みの YouTube の動画、スナップショット、サムネイル、コメント、レポート内の YouTube の引用をすぐに削除します。チャンネルのアカウント行は残しますが、名前は「YouTube」に変わります（YouTube API ポリシーで、取り消し後 7 日以内の削除が求められています）。

Gemini の無料プランのコンテンツは Google の製品改善に使われ、人が確認する場合もあるため、ワークベンチはどのデータの処理にも使わせません。`GEMINI_PAID_TIER` が既定の false のとき、Gemini はメニューで利用不可と表示され、バックエンドで実行すると `provider_unpaid_tier` を返し、スケジュールのレポートはブランドのバックグラウンドプロバイダーか最初に利用できる API を使います。Google Cloud プロジェクトに請求先アカウントを紐づけた後にだけ true にしてください。

### 分類フィンガープリントの再付与（restamp_classifications.py）

デプロイ担当者は先にバックアップし、過去のバージョンを確認してから `uv run python ../scripts/restamp_classifications.py --database <資料庫路徑> --shared-revision <版本> --brand-revision <版本>` を実行します。2 つのバージョンはどちらも必須で、0 は当時その scope の prompt がなかったことを表します。正の数は prompt_versions から読み取り、バージョンが見つからなければ全体が失敗します。複数ブランドの場合はそれぞれ自分の scope で同じバージョン番号を探し、旧フィンガープリントと完全に一致する行だけを処理します。total／matched／updated／unmatched を確認してから `--apply` を付けます。単一の BEGIN IMMEDIATE トランザクションで一致する行の input_hash だけを変更し、行ごとに `classification.restamp` の監査を書き込みます。再実行しても更新されません。このツールは .env を読まず、worker を起動せず、プラットフォームやモデルを呼び出しません。

## 機能の設定と操作メモ

**AI プロバイダーと Agent による作成**：テキストモデルには Gemini、OpenAI、Anthropic の公式 API キーだけを使います。ローカル CLI は削除済みで、古い CLI の設定を読み込んだ場合はすべて未設定とみなします。管理者は「設定 → AI → 基本」で API プロバイダーを選んで保存します。アイデア出しでは「Agent に作成を任せる」を選べます。レポートが「Agent によるテーマ作成待ち」で止まった後、Claude Code では `/mwb:ideas`、ほかの Agent では `get_guide("ideas")` で引き継ぎます。レポートページの「Claude Code に渡す」「Claude チャットを開く」「Codex を開く」ボタンは、公式の `claude://`、`codex://` リンクでデスクトップアプリを開き、レポート番号を含む指示を事前入力します（送信は自分で行う必要があります）。Antigravity などほかの Agent では「他の Agent 用にコピー」を使います。24 時間以内に保存されなければ失敗になります。定例会議のスケジュールレポートは常に Gemini API を使います。古い `mode=subscription` の使用量記録は表示用に残し、予算には含めません。

**AI のフォールバックとクォータ**：各社のフォールバックモデルは空欄にすると無効になります。`AI_API_TIMEOUT_SECONDS` はメインとフォールバックを合わせた全体の時間を制御します（ルールは architecture の「AI とメッセージ分類」を参照）。Gemini の無料プランの枠を使い切った場合は再試行もフォールバックへの切り替えもしません。継続して使うなら、Google AI Studio でプロジェクトに有料の請求設定をすることをおすすめします。同じプロジェクトのキーやフォールバックモデルを替えても枠の制限は解除されません。

**コメントのオンデマンド取得**：ユーザーが投稿で「コメントを取得」を押したときだけ、一回限りのジョブを作成します。`SCHEDULER_COMMENTS_ENABLED`／`COMMENTS_WAKE_ENABLED` が実行と起動を、`META_API_CALLS_PER_HOUR` が共有の呼び出し予算を制御します。`META_COMMENTS_AUTO_DAYS` は無視されます。

**フォロワー数**：metrics スケジュールが 1 日に 1 アカウントあたり 1 回 GET します。最初のスナップショットがない場合は、スケジュール結果の `followers.errors`、アカウントの登録、公式の項目の権限、予算／クールダウンを確認してください。`fan_count` をフォロワー数として入れたり、0 で代用したりしないでください。`SCHEDULER_ENABLED`、`SCHEDULER_METRICS_ENABLED` と UI の metrics スケジュールのスイッチが必要です。

**Obsidian へのコメントのエクスポート**：パスは Setting に保存され、既定は `<專案根目錄>/社群留言`（無視対象）です。管理者は書き込みチェックを通る独立したフォルダに変更できます。通常のエクスポートと EXPORT_WORKER_ENABLED を共有します。`backup.py` の暗号化バックアップには Obsidian の文書とハッシュが含まれます。復元したデータは新しい保存先の `obsidian/` に置かれ、デプロイ担当者が確認した後で別途パスを設定します。既存のノートを自動で上書きすることはありません。バックアップ先はコメントのフォルダと重なってはいけません。

**プラットフォームの認証情報**：プラットフォームと jev の認証情報は、管理者が設定画面で保存でき、すぐに反映されます。マスターキーは事前にデプロイ担当者が設定する必要があり、未設定の場合は安全のため保存を拒否します。DB の値を削除すると env に戻ります。`platform_credentials.py`／`platform-credentials.mjs` はローカルの設定ブリッジ用 helper で、操作担当者が別途プラットフォームのツールを実行するときだけ使います。

### Windows ログイン後の自動起動

ワークスペース設定の「PC 起動時に自動起動」は既定でオフで、表示と切り替えができるのは管理者だけです。状態は Windows のタスク スケジューラに直接問い合わせます。オンにするとルートにタスク `MWB-AutoStart` を作成します：現在の Windows ユーザーのログイン時（AtLogOn）に 45 秒遅延、Interactive、Limited、昇格不要、バッテリー駆動時も実行、MultipleInstances IgnoreNew、上限 30 分。操作は `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`、引数は `-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "<專案>\scripts\start-all.ps1"`、作業ディレクトリはプロジェクトのルートです。先に Windows にログインしている必要があり、ネットワークと Google Drive も準備できている必要があります。オフラインだった間の通知は後から送りません。ログイン直後はネットワークがまだつながっていないことがよくあります：`tailscale.mjs check` は 10 秒ごとに最大約 2 分間再試行し、それでも失敗すれば警告を表示するだけで、サービスは通常どおり動きます（ローカルの URL は使えます）。Webhook の公開境界チェック `webhooks.mjs check` も同様に再試行し、それでも失敗すればこの起動で立ち上げたサービスを停止します。再起動後に残った `.runtime/*.pid` が記録より後に作成されたプロセスを指している場合は、古い記録とみなして自動で削除します。

「タスク スケジューラ ライブラリ」で MWB-AutoStart を見つけ、上記の設定を確認できます。スイッチをオフにするとこのタスクは削除されますが、起動済みのサービスは停止しません。同名のタスクの設定が 1 つでも異なる場合、オンにしてもオフにしても `autostart_conflict` を返すので、先に手動で所有者を確認してください。プロジェクトを移動した後は、古いタスクを手動で確認してから作り直す必要があります。参考：[New-ScheduledTaskSettingsSet](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)、[New-ScheduledTaskPrincipal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal)。

### 別のポートを使う

バックエンドの既定は `127.0.0.1:8000` です。初回の起動時（`.runtime/start-fingerprint.txt` がまだない）に対話型ウィンドウで実行していると、`start-all.ps1` はポートが使用中の場合にどのポートに変えるかを尋ね、下記の 2 つの値を一緒に `.env` に書き込みます。それ以降の起動や非対話での実行では、エラーを出して止まるだけです。同じパソコンでワークベンチを 2 つ並行させる場合（たとえば初回インストールを試すためにもう 1 つ入れる場合）は、片方の `.env` で `BACKEND_INTERNAL_URL`（例：`http://127.0.0.1:8010`）と `APP_ORIGIN` のローカル URL を両方変更します。2 つのポート番号が違うと `start-all.ps1` は起動を拒否します。Tailscale を設定済みの場合は `tailscale serve --bg --https=443 --yes <新網址>` を実行し直してください（`tailscale.mjs configure` は古いポートを指すプロキシを上書きしません）。ngrok の 4040 管理ポートは固定のままなので、2 つで同時に Webhook ゲートウェイを起動することはできません。

## データの場所

本番データはプロジェクトの `data/`（git の無視対象）にまとめてあります：`data/db`（データベース）、`data/export`（エクスポート）、`data/logs`（バックエンドと MCP 監査のログ）、`data/manual-backups`（デプロイ前の手動バックアップ）、`data/legacy`（片付け待ちの古い残留物）。ローカルの暗号化バックアップはプロジェクト外の `BACKUP_LOCAL_ROOT` に置き、もう 1 部を `BACKUP_DRIVE_ROOT` に置きます。エクスポートフォルダはプログラムのディレクトリに置けません。ただし `.runtime/` と `data/` のサブフォルダは例外です（`data/` そのものは不可）。`git clean -x` など無視対象のファイルを削除するコマンドは禁止です。

## バックアップとロールバック

`backup.ps1` は SQLite backup API と 7-Zip AES-256 を使い、保存先は `BACKUP_LOCAL_ROOT`／`BACKUP_DRIVE_ROOT` で指定し、それぞれ最新 14 個を保持します。`install-backup-task.ps1` は毎日のスケジュールをインストールします。旧名のタスクがすでにある場合は、確認して旧タスクを削除してからインストールし、重複実行を防ぎます。

バックアップの形式は `mwb-backup-v1` です。古い形式は、バックアップ当時のプログラムで隔離ディレクトリに復元してください。使用中のデータベースを直接上書きしてはいけません。`backup.ps1 -Action restore -Archive <ARCHIVE> -Destination <NEW_DIRECTORY>` は、まだ存在しない保存先だけを受け付けます。

ロールバックでは、まずサービスを停止し、変換後の増分をバックアップしてから、自動バックアップと対応するバージョンのプログラムで独立したディレクトリに復元します。サービス切り替え後の新しいデータは残し、直接上書きして失わないようにします。Git の履歴は書き換えません。

## ヘルスモニタリングとトラブルシューティング

バックエンドは 5 分ごとにスケジューラー、公開署名の probe、署名検証の失敗数をチェックし、24 時間分の履歴を保存します。中断／復旧のアラートはそれぞれ 1 回ずつ出します。ホスト全体がオフラインになった場合の検知には外部の監視が必要です。

- ログインできない：APP_ORIGIN、ALLOWED_HOSTS、Tailscale のドメイン、Secure Cookie を確認します。
- 受信できない：固定の公開 URL、ngrok policy、制御ヘッダー、署名、バックエンドの状態を確認します。保護を回避するために UI/API を公開してはいけません。
- バックグラウンド処理が進まない：SCHEDULER_* のスイッチ、リース、プラットフォーム公式のレート制限と権限を確認します。カーソルをリセットして完了を装ってはいけません。
- エクスポートが失敗する：独立した絶対パス、PROTECTED_PATHS、書き込み権限、暗号化のマスターキー、ディスクの空き容量を確認します。

### AI のエラーコード

| 元のコード | ユーザー向けの説明 |
|---|---|
| provider_http_503（Gemini） | Gemini は現在混雑しています（Google 側の問題）。待機中は自動再試行の時刻を表示 |
| provider_http_429 | 現在リクエストが多すぎるか、クォータの上限に達しています |
| provider_quota_free_tier | Gemini の無料プランの枠を使い切りました。Google AI Studio で有料プランを有効にするか、しばらくしてから再試行してください |
| provider_rate_limited | プロバイダーへのリクエストが多すぎるか、クォータの上限に達しています。推奨秒数がある場合は約 N 秒後に再試行できると表示 |
| provider_quota_exhausted | プロバイダーの枠が不足しています。プロバイダーの請求設定と使用量の上限を確認してください |
| provider_time_exhausted | モデルの応答がタイムアウトしました。しばらくしてから再試行してください |
| provider_http_500／502／503／504 | プロバイダーのサービスが一時的に利用できません |
| provider_http_408／provider_timeout | プロバイダーの応答がタイムアウトしました |
| provider_connection_error | 一時的にプロバイダーに接続できません |
| provider_http_401／provider_invalid_key | API キーが無効です。AI 設定で更新してください |
| provider_http_403 | API の権限が不足しています。キーとモデルへのアクセス権を確認してください |
| provider_http_402 | API の枠が不足しています。プロバイダーの請求設定を確認してください |
| configuration_missing／provider_unavailable | 未設定か、プロバイダーがまだ利用できません。AI 設定で更新してください |
| provider_unpaid_tier | Gemini の無料プランではプラットフォームのデータを処理できません。別のプロバイダーを使うか、請求先を紐づけた後に `GEMINI_PAID_TIER=true` を設定してください |
| monthly_budget_exceeded | 今月の AI 予算が上限に達しました |
| incomplete_output／empty_output | モデルが完了しなかった／内容が拒否された、またはテキストが返されませんでした |
| input_too_large／output_too_large | 入力または応答が長すぎます |
| provider_failed／generation_failed | AI によるコンテンツ生成に失敗しました。設定を確認してください |

エラー項目には `;retry_after_seconds=N` を付けられ、UI では切り上げた約 N 秒を表示します。これは推奨の再試行時間であり、利用できることを保証するものではありません。

### データベースロックのログの読み方

`scheduler_tick_failed`、`receive_health_check_failed`、ネイティブの worker、Webhook、インポートとエクスポートなどの例外では、すべて `error_type` を記録します。SQLite の busy／locked にはさらに `error_code="database_locked"` と数値の `sqlite_errorcode` が付きます。記録するのは種類とコードだけで、例外メッセージ、traceback、SQL、パラメーター、第三者の原文、生成されたコンテンツは記録しません。`DatabaseBusy` は有限の待機を使い切った後の安全な 503 で、元の SQLite の種類／数値は同じ回の `database_lock_exhausted` イベントで確認できます。

- `sqlite_errorcode=517`：WAL の読み取りスナップショットが古くなり、書き込みへの昇格が即座に失敗しています。busy timeout を上げるだけで済ませず、そのパスが先に読み取りトランザクションを終えているか、クエリの前に書き込みの境界を使っているかを確認してください。
- 基本コード 5（BUSY）、6（LOCKED）、または拡張コードの下位 8 ビットが 5／6：ロックの競合です。長いトランザクション、一括インポート、同時に動いている worker がないか確認してください。
- `database_lock_retry` の `attempt` は 1–3 で、最終的に失敗すると別に `database_lock_exhausted` を記録します。これは BEGIN でロックを取得する 3 回の上限で、モデル／プラットフォームを再度呼び出すことはありません。継続して発生する場合は、許可されたデプロイ担当者がすべての書き込み元のバージョンとトランザクションの範囲を確認します。本番データや送信スイッチを直接変更してはいけません。

503 のメッセージはフロントエンドのエラー表示欄に表示され、ロックが解除されてから再試行できます。非同期レポートがすでに 202 を返している場合、ロックが続くと failed の状態すらデータベースに保存できないことがあります。同じプロセスでは processing のまま保持し、一時的な保存エラーを表示して再試行できるようにします（メモリ上のマークは最大 128 件で、再起動後は元のリース期限による判定に戻ります）。保存されなかった結果は手動で再試行する必要があります。
