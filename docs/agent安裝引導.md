# 給 AI Agent 的安裝引導

這份文件是寫給 **AI agent** 看的（例如 Claude Code、Codex 這類能在使用者電腦上讀檔、執行指令的 agent）。使用者把這份文件交給你，請你**一步一步帶他把工作檯架起來**。使用者不一定是工程師：你負責執行指令、檢查結果、用白話解釋；需要本人操作的步驟，清楚告訴他要點哪裡、要貼什麼回來。

開始前先讀 [`合規須知.md`](合規須知.md)。這份文件只寫流程；平台規定與官方出處在 [`平台政策.md`](平台政策.md)，進階操作細節在 [`operations.md`](operations.md)。

## 給 agent 的規則（一定要遵守）

1. **祕密只進本機 `.env`**：金鑰、權杖、密碼不要請使用者貼在對話裡，不要印在畫面上、不要寫進日誌、不要提交到 git。需要使用者提供金鑰時，請他自己貼進 `.env`；或你在本機寫入檔案，但不要回顯數值。
2. **密碼由本人輸入**：管理員密碼、各平台登入、授權同意畫面，一律由使用者本人操作，你不代打、不代按。
3. **不送出任何平台內容**：架設過程不發文、不回留言、不開啟任何送出開關。發佈只能由使用者在工作檯的確認視窗按下。
4. **每一步先講、再做、再驗證**：先用一兩句話說明要做什麼、為什麼，執行後檢查結果，成功才進下一步。
5. **安裝軟體、建立帳號、按下同意前，先問使用者**：例如用 winget 安裝 Node.js、註冊 ngrok 帳號，都要先取得同意。
6. **畫面跟文件不一樣時不要用猜的**：平台後台會改版。先查官方文件，或請使用者截圖給你，再判斷下一步。
7. **不要刪除 `data/`**：裡面是正式資料。不要執行 `git clean -x` 這類會刪除被忽略檔案的指令。
8. **用途不符就停下來**：使用者想代操客戶帳號、管理多個不同公司的品牌、或開放別人註冊，先說明這不在支援範圍、可能違反平台規定（見合規須知），請他決定是否繼續。

## 階段 0：確認用途與準備

先問使用者這些問題，答案會決定後面要做哪些步驟：

- 要管理哪些平台？Facebook 粉專、Instagram、Threads、YouTube、TikTok，可以只選一部分。
- 這些帳號是**他自己的**（或他自己的品牌）嗎？
- 有沒有自己的網站可以放隱私權政策和服務條款？各平台都要求公開網址。沒有的話，要先想辦法架一個簡單的頁面。
- 要不要用 AI 功能（主題發想、寫腳本、留言分類）？要用哪家的 API？
- 要不要 LINE 緊急留言通知？

## 階段 1：安裝環境

目前只支援 **Windows**（啟動腳本是 PowerShell）。檢查並安裝以下軟體；已經有的就跳過：

| 軟體 | 用途 | 怎麼確認 |
|---|---|---|
| Git | 下載程式 | `git --version` |
| uv | 管理 Python 3.13 與後端套件 | `uv --version` |
| Node.js（LTS） | 建置前端、執行連線閘道 | `node --version`、`npm --version` |
| 7-Zip | 加密備份 | `C:\Program Files\7-Zip\7z.exe` 存在 |
| ngrok | 接收平台 Webhook 的公開入口（啟動時必要） | `ngrok version` |
| Tailscale | 給工作檯一個內部 HTTPS 網址，平台授權回呼與其他裝置連線都靠它 | `tailscale version` |

**需要使用者本人做的**：註冊 ngrok 帳號並複製 authtoken；註冊並登入 Tailscale。這兩個帳號都由本人建立，你只負責說明步驟。

## 階段 2：取得程式與建立 `.env`

1. 下載程式：`git clone <repo 網址>`，進入資料夾。
2. 複製設定檔：把 `.env.example` 複製成 `.env`。
3. 路徑類設定（`DATABASE_PATH`、`EXPORT_ROOT`、`LOG_PATH`、`PUBLISH_MEDIA_ROOT`）**可以先留白**，會自動使用專案內的 `data/`。
4. 請使用者把 ngrok authtoken 貼到 `.env` 的 `NGROK_AUTHTOKEN=` 後面。
5. 產生加密主金鑰（平台金鑰會用它加密儲存）：在 `backend` 資料夾執行
   ```bash
   uv run python ../scripts/initialize_ai_encryption.py
   ```
   它會自動寫入 `ACCOUNT_ENCRYPTION_KEY`，不會顯示數值。提醒使用者：**`.env` 要另外備份到安全的地方**，主金鑰遺失，已加密的平台金鑰就讀不出來了。
6. 備份設定（建議）：`BACKUP_LOCAL_ROOT`（本機資料夾）、`BACKUP_DRIVE_ROOT`（例如 Google Drive 電腦版的資料夾）、`BACKUP_PASSWORD`（請使用者自己設一組長密碼，自己貼進去）。
7. `.env` 裡的 `*_INITIAL_PASSWORD` **不用填**，那是測試資料專用的。

## 階段 3：第一次啟動與建立管理員

1. 安裝套件並建立資料庫（在 `backend`）：
   ```bash
   uv sync
   uv run alembic upgrade head
   ```
2. 建立第一個管理員。這一步會在終端機要求輸入密碼，而且**必須在互動式終端機執行**，所以請使用者在自己的終端機輸入，帳號名稱由他決定：
   ```bash
   uv run python ../scripts/set_password.py <帳號名稱> --create-admin
   ```
   密碼 12–128 個字元，建議用長的通關片語，不要跟其他網站共用。
3. 啟動（回到專案根目錄）：
   ```bash
   ./scripts/start-all.ps1
   ```
   它會自動安裝前端套件、建置畫面、啟動後端與 Webhook 閘道。看到「啟動完成：http://127.0.0.1:8000」就成功了。
   **注意**：腳本會把後端與 Webhook 閘道建立成獨立程序（`Win32_Process`），所以即使你（agent）在自己的背景工作或暫時的 shell 裡執行，工作結束時服務也不會跟著停掉。若輸出出現「無法以獨立程序啟動」的警告，代表退回一般啟動，服務仍可能被綁在你的工作底下，這時請使用者在他自己的 PowerShell 視窗重新執行。啟動後輪詢 `http://127.0.0.1:8000/api/health` 確認。失敗時，錯誤訊息會指出要看 `.runtime/` 裡哪個日誌，照著讀。
4. 請使用者用瀏覽器打開 `http://127.0.0.1:8000`，用剛建立的帳號登入。
5. 驗證：`./scripts/check_runtime.ps1` 全部通過。

## 階段 4：設定 Tailscale 內部 HTTPS

1. 確認使用者已登入 Tailscale。
2. 在專案根目錄執行 `node scripts/tailscale.mjs configure`，它會把內部 HTTPS 網址寫進 `.env`。
3. 重新啟動：`./scripts/start-all.ps1 -Restart`。
4. 記下內部網址（`https://<裝置>.<網路>.ts.net`），後面設定平台授權回呼時要用。

## 階段 5：隱私權政策與服務條款

1. 依 [`templates/`](templates/) 的範本，**照使用者的實際設定**起草兩頁：連了哪些平台、用了哪些 AI 服務、`COMMENT_RETENTION_DAYS` 是幾天、聯絡信箱。沒用到的段落刪掉，不要照抄別人的政策。
2. 請使用者確認內容後，放到他自己的網站，取得兩個公開網址。
3. 應用程式名稱不能包含平台名稱（例如不能叫「我的 TikTok 工具」），建議用網站或品牌名稱。

## 階段 6：連結平台

先確認使用者有對的帳號類型，沒有的話先請他準備：

| 平台 | 需要的帳號 |
|---|---|
| Facebook | **粉絲專頁**。Meta API 不能讀寫個人檔案，工作檯只連粉專 |
| Instagram | **專業帳號**（創作者或商家，在 IG App 設定裡免費切換），並**連結到上面的 FB 粉專**；工作檯透過粉專找到 IG 帳號，一般個人 IG 連不到 |
| Threads | 個人帳號即可 |
| YouTube | 有頻道的 Google 帳號 |
| TikTok | 個人帳號即可，要加進 Sandbox 的 Target Users |

每個平台都是：**使用者在平台的開發者後台建立應用程式 → 把金鑰填進工作檯 → 在工作檯按「連結」並在平台同意授權**。工作檯「設定 → 平台連線」每張卡片都有「設定教學」按鈕，會顯示要填的回呼網址，可以直接複製。詳細步驟見 [`operations.md`](operations.md) 對應段落。

| 平台 | 使用者在後台要做的事 | 重點 |
|---|---|---|
| Meta（FB／IG） | 在 Meta 開發者後台建立應用程式，加入 Facebook 登入，回呼網址填 `<內部網址>/api/oauth/meta/callback`；基本資料填政策網址 | 自己用只需一般存取權限，不必送審；連結的人要在應用程式上有角色 |
| Threads | 同一個 Meta 應用程式加入 Threads API 使用案例，回呼 `<內部網址>/api/oauth/threads/callback`；把自己的 Threads 帳號加為測試人員並接受邀請 | 有獨立的應用程式編號與密鑰 |
| YouTube | Google Cloud 建立專案、啟用 YouTube Data API v3 與 YouTube Analytics API、建立網頁應用程式用戶端，回呼 `<內部網址>/api/oauth/youtube/callback` | 同意畫面發佈狀態要改成**正式版**，否則每 7 天要重新連結；授權時的「未經驗證」警告按「進階 → 繼續」 |
| TikTok | TikTok for Developers 建立應用程式，Sandbox 加入 Login Kit 與 Content Posting API（Direct Post 關閉），Scopes 勾 `user.info.basic`、`user.info.stats`、`video.list`、`video.upload`，回呼 `<內部網址>/api/oauth/tiktok/callback`，Target Users 加入自己的帳號 | 影片只能送到收件匣草稿（24 小時內最多 5 支待處理），文案要在 App 內貼上；App 發佈時選「所有人」，發佈後用未登入的瀏覽器確認是公開的。Sandbox 的 App name 填網站或品牌名稱，不能有 TikTok。不要送審 Production：TikTok 不收個人或自用工具 |

金鑰與密鑰請使用者自己貼進工作檯的卡片（會加密儲存），不要貼在對話裡。連結後，卡片會顯示帳號名稱與「已連結」。

## 階段 7：AI 與通知（選用）

- **AI 服務**：管理員在工作檯「設定 → AI」填 API 金鑰並驗證（加密儲存）。Gemini 只能用付費方案（`.env` 的 `GEMINI_PAID_TIER=true`）。提醒使用者：如果用 Claude、ChatGPT 等個人方案當 agent，到各自的隱私設定關閉「用對話訓練模型」。
- **LINE 通知**：需要 LINE Messaging API 的頻道與群組，設定 `.env` 的 `NOTIFY_LINE_*`，品牌通知群組在「設定 → 工作區」指定。Push 有月額度。

## 階段 8：日常維運設定

1. **每日備份**：`./scripts/install-backup-task.ps1` 安裝每日排程，再手動跑一次 `./scripts/backup.ps1` 確認成功。
2. **資料保留**：先預覽會刪除多少筆（只讀）`uv run --project backend python scripts/data_retention.py`，跟使用者確認後再加 `--enable` 啟用每日刪除。
3. **開機自動啟動**（選用）：管理員在「設定 → 工作區」開啟「開機自動啟動」。
4. **發佈總開關**：發佈頁右上角的「開啟發佈」預設是關閉的。要不要開由使用者自己決定、自己按。

## 階段 9：讓 agent 連上工作檯（選用）

工作檯提供 MCP 介面，讓 agent 幫忙寫主題、腳本與發佈草稿。請使用者在工作檯「設定 → 我的帳號 → 安裝 Agent」依畫面安裝，第一次使用時以自己的工作檯帳號登入核准。細節見 [`operations.md`](operations.md) 的「Agent 連線」。發佈一律兩段式確認：agent 準備好明細給使用者看，使用者明確同意後才送出。

## 完成檢查清單

- [ ] `./scripts/check_runtime.ps1` 全部通過，`http://127.0.0.1:8000` 能登入
- [ ] Tailscale 內部 HTTPS 網址能打開工作檯
- [ ] 隱私權政策與服務條款已公開，網址已填進各平台後台
- [ ] 需要的平台都顯示「已連結」
- [ ] Google 同意畫面是正式版
- [ ] 每日備份排程已安裝，手動備份成功
- [ ] 資料保留已預覽，並在使用者同意後啟用
- [ ] `.env` 已另外備份到安全的地方
- [ ] 管理員已在「設定 → 我的帳號 → 密碼復原碼」產生復原碼，並自己存到密碼管理工具（agent 不要經手復原碼）
- [ ] 跟使用者說明：發佈總開關、TikTok 只能送草稿、多品牌與代操不支援

## 卡住時

- 啟動失敗：錯誤訊息會指出 `.runtime/` 的日誌檔，讀最後幾行再判斷；常見原因是連接埠被佔用、ngrok authtoken 沒填、套件沒裝。
- 平台連結失敗：先看卡片上的錯誤說明，再對照 `operations.md` 與 `平台政策.md`；權限名稱或回呼網址不符最常見。
- 忘記管理員密碼：有復原碼就在登入頁「忘記密碼？」重設；沒有就照 `operations.md` 的「成員管理與帳號復原」在主機執行指令。
