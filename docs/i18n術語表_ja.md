# UI 翻訳用語集

> **言語 / Language / 語言 / 语言**：[繁體中文](i18n術語表.md) | [简体中文](i18n術語表_zh-CN.md) | [English](i18n術語表_en.md) | 日本語

`frontend/src/locales/<言語>/` を翻訳するときは、この表で用語を統一します。キーは繁体字中国語の原文で、キーは変更できません。`{変数}` と前後の空白はそのまま残してください。新しい UI 文字列を追加するときは 3 言語すべてを補い、用語はこの表に従います。

2026-10-19 にネイティブの読み手の視点で全体を 1 回校正しました（AI による校閲で、人による校正ではありません）。プラットフォーム管理画面のボタンと項目名は、各プラットフォームの公式の英語／日本語／簡体字中国語の画面に従います。見つからないもの、またはバージョンによって表記が異なるものは末尾の「要確認」に挙げています。

## 表記ルール

| 項目 | English | 简体中文 | 日本語 |
|---|---|---|---|
| 文体 | 文頭のみ大文字（sentence case）。ボタンは動詞で始め、ピリオドを付けない。完全な文にはピリオドを付ける | 中国大陸の用語を使い、繁体字中国語の語彙をそのまま移さない。ボタンは簡潔に | 敬体（です・ます）。ボタンとラベルは体言止めにし、「。」を付けない |
| 引用符（UI 名の参照） | “ ” | “ ” | 「 」 |
| パスの矢印 | → | → | → |
| 処理中の状態 | Saving… | 正在保存… | 保存中… |
| 失敗メッセージ | Couldn't load … | …加载失败 | …を読み込めませんでした |
| ユーザーへの依頼 | 命令形をそのまま使い、Please はあまり使わない | 请… | …してください |
| 英数字と中国語・日本語の間 | — | 半角スペース | 半角スペース（原文の組版に従う） |

## 同じ原文、異なる訳

翻訳表はグループごとにマージされ、同じキーには訳文が 1 つしか残らず、後のグループが前のグループを上書きします。そのため、同じキーの訳文はどのファイルでも同じでなければなりません。ある場所だけ別の訳が必要な場合（たとえば英語のナビゲーションの Settings とボタンの Set）は、コードで `tx('情境', '原文')` を使い、翻訳表に `'情境|原文'` の訳文を追加します。文脈別の訳文がない言語は自動的に通常の訳文を使い、繁体字中国語の画面には影響しません。

## 一般用語

| 繁體中文 | English | 简体中文 | 日本語 |
|---|---|---|---|
| 工作檯 | workbench | 工作台 | ワークベンチ |
| 品牌 | brand | 品牌 | ブランド |
| 貼文 | post | 帖子 | 投稿 |
| 發佈（動作／功能） | publish / Publishing | 发布 | 投稿 |
| 排程 | schedule / scheduled | 定时发布 / 已定时 | 予約投稿 / 予約済み |
| 草稿 | draft | 草稿 | 下書き |
| 主題發想（頁面） | Ideation | 选题策划 | アイデア出し |
| 主題（發想出的） | idea | 选题 | テーマ |
| 腳本 | script | 脚本 | 台本 |
| 留言 | comment | 评论 | コメント |
| 觀眾 | audience | 观众 | 視聴者 |
| 貼文數據 | Post analytics | 帖子数据 | 投稿データ |
| 成效 | performance / insights（平台數據） | 效果 / 数据 | 成果 / インサイト |
| 儀表板 | Dashboard | 仪表盘 | ダッシュボード |
| 設定 | Settings | 设置 | 設定 |
| 我的帳號 | My account | 我的账号 | マイアカウント |
| 帳號（登入用） | username | 账号 | ユーザー名 |
| 帳號（平台） | account | 账号 | アカウント |
| 成員 | member | 成员 | メンバー |
| 管理員 | admin | 管理员 | 管理者 |
| 行銷人員 | marketer | 营销人员 | マーケティング担当者 |
| 檢視者 | viewer | 查看者 | 閲覧者 |
| 臨時密碼 | temporary password | 临时密码 | 仮パスワード |
| 復原碼 | recovery code | 恢复码 | リカバリーコード |
| 稽核紀錄 | audit log | 审计日志 | 監査ログ |
| 連結（平台帳號） | connect / connected | 连接 / 已连接 | 連携 / 連携済み |
| 中斷連結 | disconnect | 断开连接 | 連携を解除 |
| 授權（OAuth） | authorize / permissions | 授权 / 权限 | 認可 / アクセス許可 |
| 權杖 | token | 令牌 | トークン |
| 金鑰 | key | 密钥 | キー |
| 密鑰（app secret） | secret | 密钥 | シークレット |
| 同步 | sync | 同步 | 同期 |
| 匯入／匯出 | import / export | 导入 / 导出 | インポート / エクスポート |
| 上傳 | upload | 上传 | アップロード |
| 封面 | cover | 封面 | カバー画像 |
| 縮圖 | thumbnail | 缩略图 | サムネイル |
| 素材／媒體 | media | 素材 / 媒体 | メディア |
| 文案 | caption / copy | 文案 | 本文 / キャプション |
| 範本 | template | 模板 | テンプレート |
| 禁語 | banned words | 禁用词 | NGワード |
| 品牌禁止承諾 | banned promises | 品牌禁止承诺 | 禁止された約束表現 |
| 例會 | recurring meeting | 例会 | 定例会議 |
| 通知 | notification | 通知 | 通知 |
| 收訊（接收健康） | message delivery | 消息接收 | 受信 |
| 系統警示 | system alert | 系统告警 | システムアラート |
| 貼圖 | sticker | 贴纸 | スタンプ |
| 總開關（發佈功能） | Publishing switch | 发布总开关 | 投稿のマスタースイッチ |
| 確認視窗 | confirmation dialog | 确认弹窗 | 確認ダイアログ |
| 重試 | retry | 重试 | 再試行 |
| 載入中 | Loading… | 加载中… | 読み込み中… |
| 儲存 | save | 保存 | 保存 |
| 刪除 | delete | 删除 | 削除 |
| 取消 | cancel | 取消 | キャンセル |

## プラットフォーム用語

| 繁體中文 | English | 简体中文 | 日本語 |
|---|---|---|---|
| 粉絲專頁／粉專 | Facebook Page | Facebook 公共主页 | Facebook ページ |
| 限時動態 | story / stories | 快拍 | ストーリーズ |
| Reels | Reels | Reels | リール |
| 串文（Threads） | thread | 串文 | スレッド |
| 觸及 | reach | 覆盖人数 | リーチ |
| 曝光 | impressions | 展示次数 | インプレッション |
| 互動 | engagement | 互动 | エンゲージメント |
| 觀看（各平台 views 指標，含圖文） | Views | 浏览量 | ビュー |
| 觀看次數（影片） | video views | 播放量 | 再生回数 |
| 追蹤者 | followers | 粉丝 | フォロワー |
| Meta 開發者後台 | Meta for Developers | Meta 开发者平台 | Meta for Developers |
| 應用程式 | app | 应用 | アプリ |
| 應用程式編號 | App ID | 应用编号 | アプリID |
| 應用程式密鑰 | App secret | 应用密钥 | app secret |
| 使用案例 | Use cases | 用例 | ユースケース |
| Business Suite | Meta Business Suite | Meta Business Suite | Meta Business Suite |
| YouTube 公開／不公開／私人 | Public / Unlisted / Private | 公开 / 不公开列出 / 私享 | 公開 / 限定公開 / 非公開 |
| Shorts | Shorts | Shorts | ショート |
| TikTok 收件匣 | inbox | 收件箱 | 受信トレイ |
| TikTok 公開範圍 所有人／朋友／只有自己 | Everyone / Friends / Only you | 所有人 / 朋友 / 仅自己 | 全員 / 友達 / 自分のみ |
| LINE 官方帳號 | LINE Official Account | LINE 官方账号 | LINE公式アカウント |
| LINE 官方帳號管理後台 | LINE Official Account Manager | LINE 官方账号管理后台 | LINE Official Account Manager |

## 要確認

- Meta の開発者管理画面、Threads アプリの設定パス、Google Cloud コンソールの一部の名称について、日本語と簡体字中国語のボタン名を実際の画面と 1 つずつ照合できていません。LINE 公式アカウントの管理画面には簡体字中国語の UI がないため、簡体字中国語のガイドでは繁体字中国語の名称を書き換えて使っています。

- 簡体字中国語の Threads「串文」：Threads は中国大陸でサービスを提供しておらず、公式の簡体字中国語の用語がありません。当面「串文」を使い、初出の箇所から一貫させます。
- Meta の開発者管理画面の日本語と簡体字中国語のボタン名は、Meta の改修に伴って変わります。ガイド内の引用符で囲んだ名称は 2026-10 に確認したものを基準とし、ユーザーから違うと報告があった場合は画面を基準に更新します。
