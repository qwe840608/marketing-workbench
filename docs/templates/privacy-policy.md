# 隱私權政策範本 Privacy Policy template

使用方式：把 `{{…}}` 換成你的資料；刪掉你沒有連結的平台、沒有用到的處理者（`[選用]` 段落）；保存天數要與你的 `.env` 一致。放到你自己的網站，再把網址填進 Meta、Google、TikTok 後台。這是範本，不是法律意見。

| 佔位符 | 填什麼 |
|---|---|
| `{{TOOL_NAME}}` | 你的工作檯名稱（不能含 Facebook、Instagram、TikTok 等平台名稱） |
| `{{OWNER}}` | 架設者（你或你的品牌） |
| `{{BRAND}}` | 工作檯管理的品牌／帳號名稱 |
| `{{CONTACT_EMAIL}}` | 隱私與刪除請求的聯絡信箱 |
| `{{UPDATED}}` | 最後更新日期 |
| `{{RETENTION_DAYS}}` | `COMMENT_RETENTION_DAYS`（預設 365） |
| `{{AI_PROVIDERS}}` | 你實際設定的 AI 服務（例如 OpenAI、Anthropic、付費方案的 Google Gemini） |
| `{{PRIVACY_URL}}` | 隱私權政策網址（服務條款範本用） |

---

## 中文

最後更新：{{UPDATED}}

「{{TOOL_NAME}}」是 {{OWNER}} 自行架設、管理 {{BRAND}} 自己社群帳號的工具。本政策說明它透過各平台官方 API 取得哪些資料、如何使用與刪除。工作檯使用 YouTube API 服務；使用 YouTube 相關功能時，也適用 [Google 隱私權政策](https://policies.google.com/privacy)。

### 1. 取得的資料
- Facebook 粉絲專頁、Instagram、Threads：自己帳號的貼文、成效數字與粉絲數；貼文下的公開留言與回覆，包含留言者的名稱、帳號識別碼與留言內容。
- YouTube：自己頻道的影片資料、縮圖、成效數字，以及影片下的公開留言。
- TikTok：帳號的基本資料、粉絲數，以及公開影片與成效數字。不讀取 TikTok 留言、私訊或私人影片。
- 帳號擁有者主動上傳、準備發佈的文字、圖片與影片。
- 工作檯不讀取私訊，也不讀取其他人帳號的貼文。

### 2. 用途
只用於：顯示自己帳號的成效與粉絲變化；整理公開留言以了解觀眾常見問題、發想內容主題；在帳號擁有者確認後發佈內容。不用於廣告、不出售，也不建立個人剖析檔案。

### 3. 儲存與保護
資料存在帳號擁有者自己電腦上的資料庫，不放在公開伺服器；工作檯只能從本機或私人網路使用。平台存取權杖加密保存，不寫入日誌或匯出檔。

### 4. 委託處理與分享
資料不出售，也不分享給廣告商或資料仲介。只有為了提供上述功能，才會把必要內容交給下列服務處理；送出前會先遮蔽電話、Email 等個人資料：
- [選用] TypeSafe（jev）：替留言分類，依其政策不以輸入內容訓練模型。
- [選用] 帳號擁有者設定的 AI 服務（{{AI_PROVIDERS}}，例如 OpenAI、Anthropic，或已啟用付費方案的 Google Gemini）：撰寫主題與腳本。不使用會將內容拿去訓練模型的免費方案。
- [選用] 帳號擁有者自行連接的 AI Agent：透過工作檯讀取遮蔽後的貼文數據與留言。
- [選用] LINE：只把緊急留言的遮蔽摘要通知到帳號擁有者自己的 LINE 群組。

### 5. 保存期限
- 公開留言自工作檯取得起保存 {{RETENTION_DAYS}} 天，到期自動刪除。
- YouTube 留言 30 天內未再更新即刪除；在 YouTube 上已刪除的影片，相關資料在 30 天內刪除。
- 自己帳號的成效數字與粉絲數持續保存，用於比較歷史變化；YouTube 中斷連結時立即刪除。
- 主題報告保留撰寫出的主題，引用的留言原文會隨上述期限移除。

### 6. 撤銷授權與刪除資料
- 在工作檯中斷平台連結：YouTube 會撤銷授權，並立即刪除工作檯已存的 YouTube 資料。這只刪除工作檯的資料，不會刪除 YouTube 上的影片。
- Google 帳號可隨時在 [Google 安全性設定](https://security.google.com/settings/security/permissions) 撤銷工作檯的存取權；撤銷後 7 天內刪除相關資料。
- Facebook、Instagram、Threads、TikTok 可在各平台的應用程式權限設定中移除本工具。
- 曾在上述帳號留言的人，可寄信要求刪除工作檯保存的留言與名稱，收到後 7 天內處理。<a id="delete"></a>

### 7. 聯絡
隱私權相關問題、刪除要求或安全性問題回報：{{CONTACT_EMAIL}}。

---

## English

Last updated: {{UPDATED}}

{{TOOL_NAME}} is a self-hosted tool that {{OWNER}} uses to manage {{BRAND}}'s own social media accounts. This policy explains what it obtains through each platform's official API and how that data is used and deleted. The tool uses YouTube API Services; when YouTube features are used, the [Google Privacy Policy](https://policies.google.com/privacy) also applies.

### 1. Data we obtain
- Facebook Pages, Instagram, Threads: the owner's posts, statistics and follower counts; public comments and replies on those posts, including the commenter's name, account ID and comment text.
- YouTube: the owner's channel videos, thumbnails, statistics, and public comments on those videos.
- TikTok: basic profile, follower count, and public videos with their statistics. TikTok comments, direct messages and private videos are not accessed.
- Text, images and videos the owner uploads to publish.
- The tool does not read direct messages or other accounts' posts.

### 2. How it is used
Only to show the owner's performance and follower changes, to summarize public comments to understand audience questions and plan content, and to publish content after the owner confirms. It is not used for advertising, sold, or used for profiling.

### 3. Storage and security
Data is stored in a database on the owner's own computer, not on a public server, and the tool is reachable only from that computer or a private network. Platform access tokens are stored encrypted and never written to logs or exports.

### 4. Processors and sharing
Data is never sold or shared with advertisers or data brokers. Only to provide the features above, the necessary content is processed by these services, with phone numbers, emails and similar personal data masked first:
- [optional] TypeSafe (jev): classifies comments; per its policy it does not train models on input.
- [optional] AI services the owner configures ({{AI_PROVIDERS}}): drafts topics and scripts. Free tiers that use content for training are not used.
- [optional] AI agents the owner connects: read masked post statistics and comments through the tool.
- [optional] LINE: sends masked summaries of urgent comments only to the owner's own LINE group.

### 5. Retention
- Public comments are kept for {{RETENTION_DAYS}} days from when the tool obtained them, then deleted automatically.
- YouTube comments not refreshed within 30 days are deleted; data about videos deleted on YouTube is deleted within 30 days.
- The owner's statistics and follower counts are kept to compare history; YouTube's are deleted immediately on disconnect.
- Topic reports keep the written topics; quoted comment text is removed on the schedule above.

### 6. Revoking access and deleting data
- Disconnect a platform in the tool. For YouTube this revokes access and immediately deletes the YouTube data the tool stored. It does not delete videos on YouTube.
- Google users can revoke the tool's access at any time on the [Google security settings page](https://security.google.com/settings/security/permissions); related data is deleted within 7 days.
- Facebook, Instagram, Threads and TikTok users can remove this tool in each platform's app permission settings.
- Anyone who commented on these accounts can email us to delete their stored comments and name; requests are handled within 7 days.

### 7. Contact
Privacy questions, deletion requests or security reports: {{CONTACT_EMAIL}}.
