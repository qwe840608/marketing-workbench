# 給 AI Agent 的平台串接引導（瀏覽器協助）

這份文件是寫給 **AI agent** 看的。使用者第一次架好工作檯後，要把 Facebook 粉專、Instagram、Threads、YouTube、TikTok 連進來，得先在各平台的**開發者後台**建立自己的應用程式。步驟繁瑣，你可以操作瀏覽器替他填設定，他只做必須本人做的部分。

- 前提：已照 [`agent安裝引導.md`](agent安裝引導.md) 完成階段 1–5（工作檯能用內部 https 網址開啟、隱私權政策與服務條款已公開）。
- 你能操作瀏覽器時照這份做（例如 Claude in Chrome、Claude 內建瀏覽器、Codex 的瀏覽器工具）；不能時，就照同樣步驟用文字一步一步帶使用者自己點。
- 步驟與工作檯「設定 → 平台連線 → 設定教學」相同（來源 `frontend/src/platformGuides.ts`，用的是後台實際畫面的用語）；權限以 `backend/app/services/oauth.py` 為準；規定與出處見 [`平台政策.md`](平台政策.md)。三者不一致時以程式為準，並回報給維護者。

## 界線（一定要遵守）

可以做：在開發者後台導覽、點選、填寫**非機密**欄位（應用程式名稱、使用案例、回呼網址、權限、scopes、啟用 API、品牌名稱與聯絡 email、類別、說明、隱私權政策與服務條款網址），按「儲存」。

不可以做：

1. **登入、密碼、2FA、安全確認**一律由使用者本人輸入。遇到登入頁或「請輸入密碼」就停下來請他操作，完成後再繼續。
2. **不碰密鑰**：不按「顯示」應用程式密鑰／Client secret，不複製、不念出、不寫進對話或檔案、不截含密鑰的畫面。應用程式編號與密鑰由使用者自己貼進工作檯「設定 → 平台連線」對應卡片（會加密儲存），不要貼在對話裡。
3. **不按工作檯的「連結 ○○ 帳號」，不代按任何 OAuth 授權／同意畫面**，也不代為同意開發者條款（例如 TikTok「Target Users」的登入與同意）。
4. **不送審、不改上線模式**：不提交 Meta App Review 或商家驗證、Google 應用程式驗證、TikTok Production 審核；不把 Meta 應用程式切成 Live。TikTok 的 Direct Post 保持關閉。
5. **不發文、不回留言、不開任何送出或發佈開關**；不爬網頁、不用非官方 API。瀏覽器只用在開發者後台的設定頁。
6. **會建立資源或同意條款的按鈕先問**（建立應用程式、建立 Google Cloud 專案、Google「發布應用程式」），使用者同意才按。
7. **畫面跟這份不一樣時不要猜**：後台常改版。先截圖給使用者看並說明差異，必要時查官方文件，再決定下一步。
8. **用途不符就停**：要代操客戶帳號、管理多個不同公司的品牌、或開放別人註冊，先說明這不在支援範圍、可能違反平台規定（見 [`合規須知.md`](合規須知.md)），讓使用者決定。

## 開始前

1. 開新分頁工作，不動使用者原本的分頁。
2. 問要設定哪些平台，並確認帳號類型：Facebook 要是**粉專管理員**；Instagram 要是**專業帳號並連到該粉專**；Threads 個人帳號即可；YouTube 要用擁有頻道的 Google 帳號（品牌頻道選品牌帳戶）；TikTok 個人帳號即可。
3. 取得**回呼網址**：請使用者打開工作檯「設定 → 平台連線」，在該平台卡片的「設定教學」按複製鈕貼給你（回呼網址不是機密）；或你自己用瀏覽器開那個視窗讀。格式是 `<內部 https 網址>/api/oauth/<meta|threads|youtube|tiktok>/callback`。開頭不是 `https://` 就先停：工作檯要用內部 https 網址開啟才能連結。
4. 備好**隱私權政策與服務條款的公開網址**（TikTok Sandbox 也必填）。
5. **應用程式名稱**用使用者的網站或品牌名稱（例如「〈品牌〉 Workbench」），不能含 TikTok、Facebook、Instagram 等平台名稱，也不要只描述功能。

每做完一步就截圖確認，跟使用者說一句做了什麼；回呼網址與權限要逐字比對。

## Meta（Facebook 粉專＋Instagram）

後台：<https://developers.facebook.com/apps/>

1. （先問）「建立應用程式」<https://developers.facebook.com/apps/creation/>，名稱用品牌名；使用案例選跟粉絲專頁有關的項目，其餘按「下一步」。
2. 「應用程式設定 → 基本資料」：填隱私權政策網址、服務條款網址、資料刪除說明網址（可指向隱私權政策的 `#delete`）、類別與聯絡 email，儲存。應用程式編號與密鑰請使用者自己貼到工作檯 Meta 卡片的「應用程式 ID」與「應用程式密鑰」。
3. 「Facebook 登入 → 設定」（使用案例流程建立的叫「企業版 Facebook 登入 → 設定」）的「有效的 OAuth 重新導向 URI」貼上 meta 回呼網址，按「儲存變更」。
4. 「使用案例 → 自訂 → 權限和功能」逐一找到並按「新增」（沒有一次全部新增的功能，可用頁面搜尋）：`pages_show_list`、`pages_read_engagement`、`pages_read_user_content`、`pages_manage_metadata`、`pages_manage_posts`、`read_insights`。選用：`pages_manage_engagement`（影片自訂封面用；缺少時只停用封面功能）。
5. 有 Instagram：同頁再新增 `instagram_basic`、`instagram_manage_comments`、`instagram_manage_insights`、`instagram_content_publish`。同頁找不到就到「使用案例」新增「管理 Instagram 上的訊息和內容」，選「透過 Facebook 登入設定 API」後再新增。
6. 交給使用者：在工作檯按「連結 Meta 帳號」，授權畫面按「編輯設定」（或「編輯存取權限」）勾粉專和 Instagram。

只給自己用時，一般存取權限就夠，**不用送審**；連結的人要在應用程式上有角色。

### Meta Webhook（選用，要先完成 ngrok，WEBHOOK_PUBLIC_URL 有值）

1. 驗證權杖由使用者自己在工作檯 Meta 卡片「手動設定（進階）→ Webhook 驗證權杖」設定，並由他自己在後台輸入，你不經手。
2. 後台左側「Webhooks」選「Page」→「訂閱這個物件」，回呼網址填 `<WEBHOOK_PUBLIC_URL>/webhook/meta-inbound`；使用者填好權杖後按「驗證並儲存」。欄位訂閱「feed」。有 Instagram 時切到「Instagram」物件，同樣網址與權杖，訂閱「comments」。
3. 提醒：開發模式只收得到測試事件與有角色者自己的留言；Instagram 留言 Webhook 要 Live＋進階存取，不在這次範圍。沒有 Webhook 時工作檯仍會每小時自己抓。

## Threads（同一個 Meta 應用程式）

1. 開應用程式 →「使用案例」新增「存取 Threads API」→「自訂 → 設定」。
2. 「Threads 應用程式編號」「Threads 應用程式密鑰」（和 Facebook 的不同組）請使用者自己貼到工作檯 Threads 卡片。
3. 同頁「重新導向回呼網址」貼 threads 回呼網址並儲存。解除授權／刪除回呼若是必填，先問使用者要填什麼（可用隱私權政策網址）。
4. 「權限和功能」逐一新增：`threads_content_publish`、`threads_manage_replies`、`threads_manage_insights`、`threads_read_replies`（`threads_basic` 已預設加入）。
5. 「應用程式角色 → 角色 → 新增用戶」選「Threads 測試人員」，輸入使用者提供的 Threads 帳號名稱。
6. 交給使用者：手機 Threads App「設定 → 帳號 → 網站權限 → 邀請」按「接受」，再到工作檯按「連結 Threads 帳號」。

## YouTube（Google Cloud）

1. （先問）建立專案 <https://console.cloud.google.com/projectcreate>，名稱隨意；確認上方選的是這個專案。
2. 啟用兩個 API（都按「啟用」）：[YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com)、[YouTube Analytics API](https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com)。
3. [品牌](https://console.cloud.google.com/auth/branding)按「開始使用」：應用程式名稱、使用者支援電子郵件；「目標對象」選「外部」；聯絡 email；勾同意前先問，再按「建立」。可補首頁、隱私權政策、服務條款網址。
4. （先問）[目標對象](https://console.cloud.google.com/auth/audience)按「發布應用程式」改成「實際運作中」，不然授權每 7 天失效。這**不是**送驗證：100 人以下自用不需驗證，不要按任何「提交驗證」。
5. [資料存取權](https://console.cloud.google.com/auth/scopes)→「新增或移除範圍」→「手動新增範圍」貼上三行，按「新增至資料表」→「更新」→「儲存」：
   - `https://www.googleapis.com/auth/youtube.readonly`
   - `https://www.googleapis.com/auth/yt-analytics.readonly`
   - `https://www.googleapis.com/auth/youtube.upload`

   不要加 `youtube` 或 `youtube.force-ssl`。
6. [建立用戶端](https://console.cloud.google.com/auth/clients/create)選「網頁應用程式」，「已授權的重新導向 URI」貼 youtube 回呼網址，按「建立」。
7. **立刻停手**：密鑰只顯示這一次。請使用者自己把「用戶端 ID」「用戶端密鑰」貼到工作檯 YouTube 卡片（可先按「下載 JSON」備存），關掉對話框後你再繼續截圖或操作。
8. 交給使用者：在工作檯按「連結 YouTube 帳號」；出現「Google 尚未驗證這個應用程式」時由他按「進階 → 前往（應用程式名稱）」，權限全部勾選。

## TikTok（只用 Sandbox）

後台：<https://developers.tiktok.com/>（右上「Developer Portal」）

1. （先問）建立應用程式，名稱**不能含「TikTok」**，用品牌名。
2. 頁面上方切到「Sandbox」建立一個。
3. 「Add products」加入 **Login Kit** 與 **Content Posting API**；**Direct Post 保持關閉**。
4. Login Kit 的「Redirect URI」選 Web，貼 tiktok 回呼網址。
5. 「Scopes」用「Add scopes」加到這四個：`user.info.basic`、`user.info.stats`、`video.list`、`video.upload`。不要加 `video.publish`。
6. Basic information 的必填欄位：App icon（請使用者提供圖檔）、Category、Description（據實描述，例如「把自己的影片送到 TikTok 收件匣、讀取自己帳號的公開影片數據」）、服務條款與隱私權政策網址。按「Apply changes」，沒有紅字才算完成。「Verify domains」不用按。
7. 交給使用者：「Target Users」→「Add account」由他登入 TikTok 並同意開發者條款（可能要等最多 1 小時才出現）。
8. 交給使用者：Sandbox「Credentials」的 Client key 與 Client secret 由他自己貼到工作檯 TikTok 卡片，再按「連結 TikTok 帳號」。

**絕對不要**：送 Production 審核（TikTok 不收私人或自用工具）、開 Direct Post、申請 TikTok API for Business（只收公司身分）。提醒使用者：影片只會送到收件匣草稿（24 小時內最多 5 支待處理），文案與封面在 App 內處理，發佈時選「所有人」，之後用未登入的瀏覽器確認是公開的。

## 收尾

每個平台做完，跟使用者列出：已設定的回呼網址、已加的權限、還要他自己做的事（貼密鑰、按連結、接受邀請、Target Users）。工作檯卡片顯示帳號名稱與「已連結」就完成；卡片顯示缺少權限時，回後台補上再請他重新連結。

常見錯誤：

- 「網址不符」／`redirect_uri_mismatch`：回呼網址要整串貼上，不可多斜線或改成 http。
- 授權時找不到粉專：授權畫面按「編輯設定」勾選，而且本人必須是粉專管理員。
- Threads 說不是測試人員：到 Threads App 接受邀請。
- 「連結」按鈕是灰色：用內部 https 網址重新開啟工作檯。
- TikTok「Apply changes」紅字：App icon、Category、Description、兩個政策網址都要填，名稱不能含 TikTok。
