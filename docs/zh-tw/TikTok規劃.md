# TikTok 規劃（第一版）

> **語言 / Language / 语言 / 言語**：繁體中文 | [简体中文](../cn/TikTok规划.md) | [English](../en/tiktok-plan.md) | [日本語](../jp/TikTok計画.md)

2026-10-16 規劃問答定案。官方限制以 2026-10-16 查核的官方文件為準，未確認處列在「實測待確認」。

## 前提

- 走 TikTok for Developers（developers.tiktok.com），**不送審**。送審牽涉產品定位，併入開源規劃再決定。
- 全站一組 TikTok 連線、一個帳號；多帳號留給多品牌規劃。帳號類型不影響可用 API，不需改成商業帳號。
- 開源後每位使用者自建 TikTok 應用程式，與 Meta、Threads、YouTube 相同。
- 只用官方 API；官方不開放的資料不用爬蟲或非官方 API。

## 官方限制（決定依據）

- 未審核應用程式直接發佈只能 `SELF_ONLY`，且發文帳號須為私人帳號；公開發佈須通過審核。審核不收私人或個人用途應用程式。來源：<https://developers.tiktok.com/doc/content-sharing-guidelines>、<https://developers.tiktok.com/doc/app-review-guidelines>
- 相片貼文只能 `PULL_FROM_URL`，網址須屬已驗證網域；影片可 `FILE_UPLOAD` 由後端直接上傳。來源：<https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide>
- 送到收件匣（`video.upload`）24 小時內最多 5 支待處理；長度上限依帳號而異，以 creator_info 的 `max_video_post_duration_sec` 為準。來源：<https://developers.tiktok.com/doc/content-posting-api-reference-upload-video>、<https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info>
- 發佈狀態查詢只在公開且應用程式已審核時回傳公開貼文 ID。來源：<https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status>
- access token 24 小時、refresh token 365 天，續期回傳的 refresh token 可能更換。來源：<https://developers.tiktok.com/doc/oauth-user-access-token-management>
- Display API `video.list` 只回公開影片。來源：<https://developers.tiktok.com/doc/tiktok-api-v2-video-list>
- 讀留言只有 TikTok API for Business 的 Accounts API 提供。開發者註冊須公司網域 email 與公司網站（不收個人網站與個人開發者），Accounts API 申請表須填登記文件上的公司全名並做商業驗證（登記文件或已驗證的 Business Center）。來源：<https://business-api.tiktok.com/portal/docs/register-as-a-developer/v1.3>、<https://business-api.tiktok.com/portal/docs/accounts-api/v1.3>

## 連結帳號與權杖

- 權限：`user.info.basic`、`user.info.stats`、`video.list`、`video.upload`。
- 回呼網址先用工作檯的 Tailscale https 網址；TikTok 不接受時改用桌面模式回呼 `127.0.0.1`（PKCE，code challenge 為 SHA256 hex），連結時須在執行工作檯的電腦上操作。
- access token 由後端在呼叫前自動續期，使用者不需操作。refresh token 到期前 14 天或續期失敗時以 LINE 通知重新連結；卡片顯示已連結／即將到期／失效與台北時間到期日。

## 數據

- 每小時同步公開影片與觀看、按讚、留言數、分享數，以及粉絲數。
- 取得完整清單時，清單中沒有的影片標為「已刪除或改為私人」並自貼文數據隱藏；清單不完整或為空時不判定。
- 併入貼文數據與儀表板；官方不開放的成效可用 TikTok Studio 匯出的 CSV 匯入。
- 主題發想不加 TikTok 頁籤：主題發想以留言為依據，TikTok 沒有留言來源。

## 發佈

- 只發影片，方式為送到 TikTok 收件匣（`MEDIA_UPLOAD`）；使用者在 App 編輯並發佈。工作檯依排程時間送出，不決定公開時間。
- 圖文勾選 TikTok 時擋下並提示「僅支援影片發布，圖文需從APP上傳」。
- 併入共用文案流程，TikTok 分頁可覆寫文案；若 API 帶不過文案，發佈紀錄提供「複製文案」。
- 排程時與送出前以 creator_info 檢查長度上限；收件匣額滿以送出時的錯誤碼寫明原因並可重試。
- 以輪詢追蹤狀態，不接 TikTok Webhook，公開入口不新增路徑。終點狀態為「已送到收件匣」，偵測得到時改為「已在 App 發佈」；沒有貼文 ID 時不附連結，也不自動比對之後出現的影片。

## 留言

- 第一版不實作，只放提示：「讀取 TikTok 留言需要以公司身分申請 TikTok API for Business（個人開發者無法申請）」。位置：平台連線 TikTok 卡片的「留言（選用）」區塊、設定教學「讀取留言（需要公司身分）」一節、貼文數據 TikTok 影片的留言區。
- 日後取得公司身分並通過申請時的方向：Business API 只負責留言，發佈與數據仍走 TikTok for Developers；只讀不回；每小時抓取、不接 Webhook；連上後主題發想才出現 TikTok 頁籤。

## 不做

直接公開發佈（需審核）、相片貼文（需驗證網域）、留言讀取與回覆（需公司身分）、非官方 API 與爬蟲。

## 交付順序

每步驗收通過才進下一步。

1. 改寫 TikTok 設定教學（含留言提示），協助使用者建立應用程式。（2026-10-16 完成，Sandbox 已依教學建立）
2. 連結帳號、權杖自動續期、到期提醒；卡片加入「留言（選用）」提示。（2026-10-16 部署，實機連結成功，確認 Tailscale https 網址可作回呼網址）回呼網址只能在工作檯有授權路由後實測，所以與原第 3 步對調：先完成連結功能、部署後實測回呼網址與讀取權限。
3. 實測（見下節）；收件匣與文案兩項留到第 5 步發佈時實測。
4. 數據同步、貼文數據（含留言提示）、儀表板。每小時一次 `video.list`（每頁 20 支、最多 50 頁）同時寫入貼文與到期的成效快照，不逐支查詢；每日一次 `user.info` 的 follower_count。完整且非空的清單才把消失的影片標為已刪除或改為私人並隱藏；發佈頁 TikTok 分頁改為「發佈尚未開放」。
5. 發佈：只送影片到收件匣（`POST /v2/post/publish/inbox/video/init/` 的 FILE_UPLOAD，64 MB 內一段、其餘 10 MB 一段依序 PUT）。publish_id 先保存，重試先查狀態、已進收件匣就不重送；送出後最多等 60 秒到 SEND_TO_USER_INBOX，之後每 10 分鐘追蹤 7 天看是否變成 PUBLISH_COMPLETE。收件匣 API 不收文案（已查證），發佈紀錄提供「複製文案」。長度上限依官方媒體傳輸指南固定 10 分鐘：依帳號查上限的 creator_info 需要 video.publish，第一版不申請。

## 實測待確認

- Tailscale https 網址可否作為 Web 回呼網址。
- 未審核應用程式可否送影片到收件匣（第 5 步部署後以使用者同意的測試影片實測）。
- 使用者在 App 發佈後，狀態是否變為 `PUBLISH_COMPLETE`（官方狀態文件寫會變，待實測）。
- 送到收件匣時可否帶文案：官方 init 端點沒有文案欄位，確定不能帶（2026-10-17 查證）。
