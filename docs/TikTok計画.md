# TikTok 計画（第 1 版）

> **言語 / Language / 語言 / 语言**：[繁體中文](TikTok規劃.md) | [简体中文](TikTok规划.md) | [English](tiktok-plan.md) | 日本語

2026-10-16 の計画 Q&A で確定しました。公式の制限は 2026-10-16 に確認した公式ドキュメントに基づき、未確認の点は「実機で要確認」に挙げています。

## 前提

- TikTok for Developers（developers.tiktok.com）を使い、**審査には出しません**。審査は製品の位置づけに関わるため、オープンソース化の計画に含めて決めます。
- サイト全体で TikTok 連携は 1 組、アカウントは 1 つです。複数アカウントはマルチブランドの計画に回します。アカウントの種類は使える API に影響しないため、ビジネスアカウントに変える必要はありません。
- オープンソース化後は、各ユーザーが自分で TikTok のアプリを作成します。Meta、Threads、YouTube と同じです。
- 公式 API だけを使います。公式が提供していないデータのために、スクレイピングや非公式 API は使いません。

## 公式の制限（判断の根拠）

- 審査を通っていないアプリから直接投稿すると `SELF_ONLY` のみで、投稿するアカウントも非公開アカウントである必要があります。公開投稿には審査の通過が必要です。審査は私的または個人用途のアプリを受け付けません。出典：<https://developers.tiktok.com/doc/content-sharing-guidelines>、<https://developers.tiktok.com/doc/app-review-guidelines>
- 写真投稿は `PULL_FROM_URL` のみで、URL は認証済みドメインのものである必要があります。動画は `FILE_UPLOAD` でバックエンドから直接アップロードできます。出典：<https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide>
- 受信トレイへの送信（`video.upload`）は 24 時間以内に保留中のものが最大 5 本です。長さの上限はアカウントによって異なり、creator_info の `max_video_post_duration_sec` に従います。出典：<https://developers.tiktok.com/doc/content-posting-api-reference-upload-video>、<https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info>
- 投稿ステータスの照会で公開投稿の ID が返るのは、公開かつアプリが審査済みの場合だけです。出典：<https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status>
- access token は 24 時間、refresh token は 365 日です。更新時に返される refresh token は変わることがあります。出典：<https://developers.tiktok.com/doc/oauth-user-access-token-management>
- Display API の `video.list` は公開動画だけを返します。出典：<https://developers.tiktok.com/doc/tiktok-api-v2-video-list>
- コメントの取得は TikTok API for Business の Accounts API だけが提供しています。開発者登録には会社ドメインのメールアドレスと会社のウェブサイトが必要で（個人サイトと個人開発者は不可）、Accounts API の申請フォームには登記書類上の会社の正式名称を記入し、ビジネス認証（登記書類または認証済みの Business Center）を受ける必要があります。出典：<https://business-api.tiktok.com/portal/docs/register-as-a-developer/v1.3>、<https://business-api.tiktok.com/portal/docs/accounts-api/v1.3>

## アカウント連携とトークン

- 権限：`user.info.basic`、`user.info.stats`、`video.list`、`video.upload`。
- リダイレクト URL はまずワークベンチの Tailscale https URL を使います。TikTok が受け付けない場合は、デスクトップ方式のリダイレクト `127.0.0.1`（PKCE、code challenge は SHA256 hex）に切り替え、連携はワークベンチを実行しているパソコンで操作する必要があります。
- access token はバックエンドが呼び出しの前に自動で更新するため、ユーザーの操作は不要です。refresh token の期限 14 日前、または更新に失敗したときは、LINE で再連携を通知します。カードには「連携済み」／「まもなく期限切れ」／無効の状態と、台北時間の有効期限を表示します。

## データ

- 1 時間ごとに公開動画と再生回数、いいね数、コメント数、シェア数、およびフォロワー数を同期します。
- 全件リストを取得できたとき、リストにない動画は「削除済みまたは非公開に変更」とし、投稿データから非表示にします。リストが不完全または空の場合は判定しません。
- 投稿データとダッシュボードに統合します。公式が提供していない成果は、TikTok Studio からエクスポートした CSV でインポートできます。
- アイデア出しには TikTok タブを追加しません。アイデア出しはコメントを根拠にしますが、TikTok にはコメントのソースがないためです。

## 投稿

- 動画だけを投稿し、方法は TikTok の受信トレイへの送信（`MEDIA_UPLOAD`）です。ユーザーがアプリで編集して投稿します。ワークベンチは予約投稿の時刻に送信しますが、公開時刻は決めません。
- 画像投稿で TikTok にチェックを入れた場合はブロックし、「動画のみ投稿できます。画像の投稿はアプリから行ってください」と表示します。
- 共通の本文の流れに統合し、TikTok タブで本文を上書きできます。API で本文を渡せない場合は、投稿履歴に「キャプションをコピー」を用意します。
- 予約時と送信前に creator_info で長さの上限を確認します。受信トレイが満杯の場合は、送信時のエラーコードで理由を明記し、再試行できるようにします。
- ステータスはポーリングで追跡し、TikTok の Webhook は使わず、公開入口にパスを追加しません。終了状態は「TikTok の受信トレイに送信済み」で、検出できた場合は「アプリで投稿済み」に変えます。投稿 ID がない場合はリンクを付けず、その後に現れた動画との自動照合もしません。

## コメント

- 第 1 版では実装せず、案内だけを置きます：「TikTok のコメントを取得するには、法人として TikTok API for Business に申請する必要があります（個人開発者は申請できません）」。場所：プラットフォーム連携の TikTok カードの「コメント（任意）」欄、設定ガイドの「コメントの取得（法人のみ）」の節、投稿データの TikTok 動画のコメント欄。
- 将来、法人として申請が通った場合の方針：Business API はコメントだけを担当し、投稿とデータは引き続き TikTok for Developers を使います。読み取りのみで返信はしません。1 時間ごとに取得し、Webhook は使いません。連携後に初めてアイデア出しに TikTok タブが現れます。

## やらないこと

直接の公開投稿（審査が必要）、写真投稿（ドメイン認証が必要）、コメントの取得と返信（法人であることが必要）、非公式 API とスクレイピング。

## 提供の順序

各ステップの受け入れ確認に通ってから次へ進みます。

1. TikTok の設定ガイドを書き直し（コメントの案内を含む）、ユーザーのアプリ作成を手伝う。（2026-10-16 完了、ガイドに沿って Sandbox を作成済み）
2. アカウント連携、トークンの自動更新、期限切れの通知。カードに「コメント（任意）」の案内を追加。（2026-10-16 デプロイ、実機での連携に成功し、Tailscale https URL をリダイレクト URL に使えることを確認）リダイレクト URL はワークベンチに認可ルートができてからでないと実機テストできないため、元の第 3 ステップと順番を入れ替えました。先に連携機能を完成させ、デプロイ後にリダイレクト URL と読み取り権限を実機テストします。
3. 実機テスト（次の節を参照）。受信トレイと本文の 2 項目は第 5 ステップの投稿時に実機テストします。
4. データ同期、投稿データ（コメントの案内を含む）、ダッシュボード。1 時間に 1 回 `video.list`（1 ページ 20 本、最大 50 ページ）で投稿と期限が来た成果のスナップショットを同時に書き込み、1 本ずつの照会はしません。1 日 1 回 `user.info` の follower_count を取得します。完全かつ空でないリストのときだけ、消えた動画を削除済みまたは非公開に変更とみなして非表示にします。投稿画面の TikTok タブは「投稿はまだ利用できません」に変えます。
5. 投稿：動画を受信トレイに送ることだけを行います（`POST /v2/post/publish/inbox/video/init/` の FILE_UPLOAD。64 MB 以内は 1 チャンク、それ以外は 10 MB ずつ順に PUT）。publish_id は先に保存し、再試行時はまずステータスを照会して、受信トレイに入っていれば再送しません。送信後は最大 60 秒 SEND_TO_USER_INBOX を待ち、その後 7 日間 10 分ごとに PUBLISH_COMPLETE になったかを追跡します。受信トレイの API は本文を受け付けないため（確認済み）、投稿履歴に「キャプションをコピー」を用意します。長さの上限は公式のメディア転送ガイドに従って 10 分に固定します。アカウントごとの上限を照会する creator_info には video.publish が必要で、第 1 版では申請しません。

## 実機で要確認

- Tailscale https URL を Web のリダイレクト URL として使えるか。
- 審査を通っていないアプリから受信トレイに動画を送れるか（第 5 ステップのデプロイ後、ユーザーが同意したテスト動画で実機テスト）。
- ユーザーがアプリで投稿した後、ステータスが `PUBLISH_COMPLETE` になるか（公式のステータスのドキュメントではなると書かれているが、実機テスト待ち）。
- 受信トレイに送るときに本文を付けられるか：公式の init エンドポイントには本文のフィールドがなく、付けられないことが確定しました（2026-10-17 確認）。
