# UI translation glossary

> **Language / 語言 / 语言 / 言語**: [繁體中文](i18n術語表.md) | [简体中文](i18n术语表.md) | English | [日本語](i18n用語集.md)

Use this table to keep wording consistent when translating `frontend/src/locales/<語言>/` (`<language>`). Keys are the Traditional Chinese originals and must not be changed; `{變數}` placeholders (variables) and surrounding whitespace must be kept exactly. When adding UI text, add all three languages, using the terms in this table.

On 2026-10-19 the whole set was reviewed once from a native reader's perspective (AI review, not human proofreading). Button and field names in platform consoles follow each platform's official English / Japanese / Simplified Chinese interface; those that could not be found or differ between versions are listed under "To confirm" at the end.

## Writing conventions

| Item | English | 简体中文 | 日本語 |
|---|---|---|---|
| Sentence style | Sentence case; buttons start with a verb and take no period; full sentences take a period | Mainland usage, not Traditional Chinese vocabulary carried over directly; short buttons | Polite form (です・ます); buttons and labels end in a noun (体言止め) without「。」 |
| Quotation marks (for UI names) | “ ” | “ ” | 「 」 |
| Path arrow | → | → | → |
| In-progress status | Saving… | 正在保存… | 保存中… |
| Failure message | Couldn't load … | …加载失败 | …を読み込めませんでした |
| Asking the user to act | Use the imperative directly; rarely use Please | 请… | …してください |
| Between Latin characters/digits and CJK | — | Half-width space | Half-width space (following the source layout) |

## One source string, different translations

The translation tables are merged by group, so each key has only one translation, and later groups override earlier ones. The same key must therefore have the same translation in every file. When one place needs a different translation (for example Settings in the English navigation versus Set on a button), the code uses `tx('情境', '原文')` (context, source string) and the translation table adds a translation for `'情境|原文'`. Languages without a context translation fall back to the general translation automatically, and the Traditional Chinese screens are unaffected.

## General terms

| 繁中 | English | 简体中文 | 日本語 |
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
| 成效 | performance / insights (platform data) | 效果 / 数据 | 成果 / インサイト |
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

## Platform terms

| 繁中 | English | 简体中文 | 日本語 |
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

## To confirm

- The Japanese and Simplified Chinese button names in Meta for Developers, the Threads app settings path and some Google Cloud console names could not be checked one by one against the actual screens. LINE Official Account Manager has no Simplified Chinese interface, so the Simplified Chinese guides transliterate the Traditional Chinese names.

- Simplified Chinese 「串文」 for Threads: Threads has not launched in mainland China and has no official Simplified Chinese term; 「串文」 is used for now and kept consistent from its first appearance.
- Japanese and Simplified Chinese button names in Meta for Developers change as Meta redesigns its console; the quoted names in the guides follow what was found in 2026-10, and when users report something different, update them to match the screen.
