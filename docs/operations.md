# 部署與維運

資料庫、匯出、日誌、備份及 MCP 稽核路徑透過設定提供；不依賴開發者的磁碟或主機名稱。`.env.example` 為設定欄位參考，憑證只在本機填入。各功能的設計規則見 [architecture](architecture.md)；這裡只記操作步驟。各次變更的驗收細節記錄在 git 歷史，不再寫入本頁。

## 部署順序

開發 session 不停止／重啟正在執行的服務，不修改實機送出開關，也不送平台訊息。由有權限的操作人在確認工作樹與回退資料後執行：

1. **備份**：先執行 `./scripts/backup.ps1`，另外安全備份 `.env`、服務部署設定及舊版本；核對資料庫、匯出可讀，記錄帳號送出開關與 `publishing.enabled`。備份包含歷史內容及秘密，限操作人存取，不放入開源封存。
2. **停止服務**：執行 `./scripts/stop-all.ps1`，確認 PID 屬於這個專案並已釋放服務埠。權限不足就停止部署，不啟動第二套收訊服務。
3. **結構升級**：在 backend 目錄執行 `uv run alembic upgrade head`。個別 migration 的前置檢查與降版限制見下方「Migration 注意事項」。
4. **啟動**：先 `npm --prefix frontend run build`，再 `./scripts/start-all.ps1 -SuppressSystemAlerts`。ngrok 使用新控制標頭及 probe 路徑 `/webhook/mwb-gateway-probe`。若此次仍禁推播，以程序環境停用 `SCHEDULER_NOTIFY_ENABLED`、`RECEIVE_HEALTH_ALERTS_ENABLED`，並保持付費工作符合當次授權。
   - `start-all.ps1` 啟動後端前比對 `alembic current` 與 `alembic heads`：資料庫結構不是最新就停止並指回第 1–3 步，不會自動升級（沒有版本紀錄的全新資料庫除外，直接建立結構）。服務仍在執行時，這個檢查在停止服務前就做，不會先停掉舊服務。第 1–3 步完成後，也可以用 `-ApplyMigrations` 讓腳本代為執行第 3 步的 upgrade。
   - 後端與 Webhook 閘道以 `Win32_Process` 建立成獨立程序（父程序是 WMI，不在呼叫端的 job 內），關閉啟動視窗、Agent 的背景 shell 或排程工作結束都不會連帶停止服務；呼叫端當下的環境變數（包括上面的停用設定）會整份傳給服務。WMI 不可用時退回 `Start-Process` 並顯示警告。
5. **驗證**：`node scripts/webhooks.mjs check` 的全部公開邊界案例、`./scripts/check_runtime.ps1`、Tailscale 登入、名稱各顯示處、Word 頁首、範本預覽／稽核。核對帳號 `send_enabled` 與 `publishing.enabled` 前後相同，檢查新匯出及外鍵。新帳號登記前設定 REGISTRATION_BRAND_SLUG 或傳入 --brand。

前後端與 `plugin/` 一律成套部署；隔離驗收不代表已部署。

## Migration 注意事項

正式 migration 前先以 SQLite `mode=ro` 開啟正式庫、用 backup API 複製到 `.runtime/`，在副本執行 upgrade／downgrade／upgrade，核對各表筆數、外鍵與帳號送出開關。副本含真實內容，禁止提交、上傳或截圖原文，也不得部署演練副本；不要以 `immutable=1` 忽略仍在使用的 WAL。

| 版本 | 注意事項 |
|---|---|
| 0021 | 停用供應者改為 JSON null；管理員須在 AI 設定驗證金鑰並重選預設供應商。`downgrade 0020` 只恢復仍為未設定的欄位。 |
| 0024 | 移除七個業務表的舊資料來源標記；任一表仍有 true 即中止整次升級並列出表名與筆數，需另行確認處理方式。 |
| 0025 | 結束所有舊留言工作與回補探索，保留業務資料；downgrade 不復活舊工作，退回舊程式時須另外停用舊自動留言排程。 |
| 0026 | 降至 0025 會刪除粉絲快照表，先備份。 |
| 0027 | `downgrade 0026` 移除三家備援模型設定，等待後續輪次的 AI 工作標為 skipped；回退前備份工作排程與品牌 AI 設定。 |
| 0030 | 刪除退休的 `auto_draft_jobs`；降版只重建空表。 |
| 0031 | 平台／jev 憑證可存 DB；已存平台覆寫時 `downgrade 0030` 拒絕遺失設定，回退優先還原升級前備份。 |
| 0032 | 成員管理；既有帳號 `must_change_password=false`。 |
| 0033 | Meta／Threads OAuth。 |
| 0035–0043 | 發佈（0035）、caption_job_json（0036，已不使用）、Agent 授權（0037）、Agent 草稿上傳（0038）、刪除偵測（0039）、Facebook 未發佈（0040）、平台選項與 Threads 串文（0041）、限時動態（0042，有限動時拒絕降版）、YouTube 發佈與縮圖（0043，有 YouTube 發佈或縮圖時拒絕降版）。0041 降版會移除選項／串文進度，已送出串文時不可在未備份下降版。 |
| 0046 | 貼文縮圖快取 `post_thumbnails`。降版直接刪表（只是平台圖片的快取），升版後每小時排程會重新抓取。 |
| 0048 | Instagram Reels 封面：`publish_media.role` 加入 `cover`，不改既有資料列；已有封面時拒絕降版。 |
| 0049 | Facebook 影片／Reels 封面：`publish_media.role` 加入 `fb_cover`，不改既有資料列；已有 FB 封面時拒絕降版。FB 封面需要 `pages_manage_engagement`：既有 Meta 連結要重新連結一次才會取得（不重新連結也能照常發佈，只是封面不會套用）。 |

## 驗收

**一個指令跑完全部驗收**：在專案根目錄 `python scripts/verify_all.py`。依序執行 ruff、tsc、建置到 `.runtime/verify-dist`，再平行執行 pytest、前端測試、`scripts/*.test.mjs`、全部隔離介面檢查（自動收錄 `scripts/check_*.py`，排除 `*_live.py`）與補充檢查（清單在 `verify_all.SUPPLEMENTARY`），平行步驟全部結束後單獨執行 `runtime-clean`（`scripts/test_runtime_clean.py`），最後掃描禁止字串與寫死顏色（`git grep` 本身失敗也算不通過）。每步輸出在 `.runtime/verify/<步驟>.log`，最後一行 `ALL PASS` 才算通過。開工前用 `python scripts/verify_all.py snapshot-data <檔案>` 記錄 `data/` 清單，收尾加 `--data-baseline <檔案>` 比對；開發中用 `--only pytest,check_xxx` 只跑指定步驟，`--jobs 1` 依序執行以排查干擾；步驟名稱打錯會直接報錯並列出可用名稱。`--only` 沒有包含 `build` 時，介面檢查用的是上次建置的 `.runtime/verify-dist`（會印出提醒），改過前端要一起選 `build`。新增檢查只要放進 `scripts/check_*.py` 就會被收錄，不需在文件記數量。

介面檢查用 Playwright 開本機安裝的 Google Chrome（`runtime_tmp.py` 指定 `channel="chrome"`），驗收機器需先安裝 Chrome。

隔離規則：

- 每支 check 的 DATABASE_PATH／EXPORT_ROOT／媒體與日誌由 `browser_harness` 或 `runtime_tmp` 指到 `.runtime/tmp/<唯一名稱>/`；純 CSS 檢查與 helper 不開庫。不讀正式設定或憑證、不呼叫真實 AI 或平台、不連外（平台一律 HTTP mock）。
- 不覆寫正在供應的 `frontend/dist`：建置到 `.runtime/` 並以 `FRONTEND_DIST_DIR` 指向該處。

  ```powershell
  npm --prefix frontend run build -- --outDir ../.runtime/verification-dist
  $env:FRONTEND_DIST_DIR = (Resolve-Path .runtime/verification-dist).Path
  cd backend
  uv run python ../scripts/check_ui_scale.py
  ```

- `runtime_tmp.runtime_check` 以 `temporary_dir()` 管理暫存；取得引擎、日誌或子程序後立即登記 `cleanup()`，例外與 KeyboardInterrupt 同樣清理，刪除失敗只印警告。Node 建置由 `runtime_tmp.mjs` 登記 after hook。清理行為由 `scripts/test_runtime_clean.py` 驗證；它比對 `.runtime/tmp` 是否清空，必須在其他檢查都結束後單獨執行，`verify_all.py` 的 `runtime-clean` 步驟已照這個順序排。
- 截圖、Word 樣本與 JSON 報告只保留最近一次，放 `.runtime/check-output/<入口腳本名稱>/`，每次開始清空；跨執行的 before／after 對照需另存。
- 驗收腳本只停止自己建立的隔離程序。`*_live.py` 不在驗收範圍，執行需另有明確授權。
- 對比檢查只讀 CSS：文字 ≥4.5:1，圖示／焦點／圖表 ≥3:1。
- `eval_jev_questions.py` 預設只跑離線 transport 替身，通過只驗證管線，不代表模型品質；`--live` 與 `evaluate_jev_hard.py` 會呼叫付費 API，需明確指定。

平行驗收的穩定性：預設 `--jobs 4` 會讓 pytest 與瀏覽器檢查搶 CPU，檢查不得依賴「單獨跑時夠快」。

1. `test_dashboard_trends_scale_read_only` 的查詢數與無寫入是結構斷言；時間門檻只比暖機後連跑五次的最佳值。
2. 上傳端點的資料庫步驟一律以 threadpool 執行：在事件迴圈上等 SQLite 寫入鎖會凍結伺服器，形成約 15 秒互鎖後回 503（`test_upload_waits_for_write_lock_off_event_loop` 固定重現）。發佈頁的媒體上傳／移除與存檔共用同一佇列。
3. 開啟草稿而內容未改時，自動檢查只呼叫 `/check` 不存檔，避免無故遞增 version 讓 Agent 的 `prepare_publish` 衝突。
4. 隔離檢查伺服器以 `ports.KEEP_ALIVE_SECONDS` 停用閒置連線關閉，避免 Playwright 重用連線時出現 `socket hang up`；新增啟動 uvicorn 的檢查須沿用此設定。

## 後端測試

在 `backend/` 執行。平行模式用於日常驗收，單線程用於除錯與量測：

```powershell
uv run pytest -q -n auto --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
uv run pytest -q --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
```

- 每個測試工作階段（平行時為每個 worker）只執行一次 `alembic upgrade head` 產生範本資料庫，各測試以 SQLite backup API 複製到自己的 `tmp_path`。範本綁定 migration 內容指紋，不跨執行快取。實作在 `backend/tests/migration_database.py`。
- 驗證 migration 本身的測試必須標記 `@pytest.mark.migration`，標記後改為逐測試真實執行 migration。
- 測試期間對外連線與 DNS 查詢會直接失敗（僅允許 loopback），新測試需以 mock 取代外部呼叫。
- 共用輔助在 `tests/conftest.py`：`login()`（取 CSRF、登入並回傳後續標頭）與 `seed_records()`（合成資料加歷史價目列），新測試直接 `from conftest import ...`，不要再複製一份。
- 新測試不得依賴固定檔名、固定連接埠或模組層級的共享狀態。
- uv／pytest 快取目錄受限時，將 UV_CACHE_DIR、TEMP、TMP 與 `--basetemp` 指到允許寫入的隔離目錄，不變更正式資料設定。

## Agent 連線

工作檯提供內部 `/mcp`（Streamable HTTP），與網頁同埠；僅本機與 Tailscale 可到達，公開來源維持 404。介面規範見 [MCP規範](MCP規範.md)。成員先加入 Tailscale，以內部 HTTPS 網址開啟「設定 → 我的帳號 → 安裝 Agent」；不需私人 GitHub repo 權限。localhost 下載只供參考與測試，Claude 託管 marketplace 的 archive 必須 HTTPS。

**Claude Code**（至少 v2.1.224）：

```text
/plugin marketplace add <內部網址>/plugin/marketplace.json
/plugin install mwb@marketing-workbench
```

到 `/plugin → Marketplaces` 選 marketing-workbench，開啟 Enable auto-update（須成員自行操作）；首次使用 MCP 時以自己的工作檯帳號登入並核准。手動更新用 `/plugin marketplace update marketing-workbench`，更新後重新開始對話。使用者本人也可在 repo 根目錄以 `claude --plugin-dir plugin/mwb` 載入開發檔，本機 URL 為 http://127.0.0.1:8000/mcp。

**Codex**（skills＋config）：在安裝區切到 Codex，下載並解壓縮，將 skills 下五個資料夾放到 `~/.agents/skills/`（已有同名內容先備份），把 ZIP 的 config.toml 合併到 `~/.codex/config.toml`，再執行 `codex mcp login mwb` 以自己的帳號核准。唯讀工具 approval_mode=approve，所有寫入及 confirm_publish 為 prompt；用戶端核准設定不取代後端權限與發佈確認。更新時重新下載並合併。採此方式的原因：Codex plugin 的 installed server policy 需使用者在 config 設定，且 `codex plugin marketplace add` 不接受託管 JSON URL。

**Claude 桌面版**：切到 Claude 桌面版下載 `.mcpb`，在桌面版「設定 → 擴充功能 → 安裝擴充功能」選該檔。工作檯網址從安裝區複製（本機可填 http://127.0.0.1:8000），到「Agent 連線」建立連線權杖貼到擴充設定。更新需下載新版重新安裝；移除擴充不代替工作檯撤銷。官方格式查證及人工 mcpb 驗證命令見 `plugin/README.md`。

**Hermes**：見 [MCP規範](MCP規範.md) 的「Hermes 連線」。

**發佈新版 plugin**：改 `plugin/mwb/` → 提高 `.claude-plugin/plugin.json` version 並同步開發 `.mcp.json` header → 在 backend 執行 `uv run python ../scripts/update_plugin_hash.py` → 跑測試 → 由授權操作人部署前後端及 `plugin/`。version 唯一來源為 plugin.json；更新工具拒絕同版本覆寫不同雜湊。相容新增不改 MCP API 版本；plugin 最低相容 0.3.0，較舊只能讀 get_server_info／get_guide。部署者以 `claude plugin validate <解壓縮路徑>` 驗證套件，本人試用後再提供成員。

**撤銷與期限**：自己的 OAuth／連線權杖在「我的帳號 → Agent 連線」撤銷；管理員可在成員頁確認後全部撤銷。停用、重設或變更密碼會撤銷連線。兩種連線 30 天未使用失效；OAuth 存取權杖 1 小時、refresh 30 天且每次輪換，重用舊 refresh 撤銷整筆授權。排程每小時清除過期授權資料。稽核記成員、連線名稱與授權 id，不記秘密。

## 發佈

- 發佈總開關為 Setting `publishing.enabled`，預設 false，只有管理員可在發佈頁確認後切換；部署不得改動其現值。
- 排程與媒體清理需 SCHEDULER_ENABLED、SCHEDULER_PUBLISH_ENABLED 皆開啟。PUBLISH_POLL_SECONDS 預設 5、PUBLISH_POLL_TIMEOUT 預設 300 秒；Threads 未完成的容器至少每 60 秒才再查詢，均有逾時且不自動重新發佈。
- 媒體存於 PUBLISH_MEDIA_ROOT（預設 `data/publish-media`）。IG／Threads 需要 WEBHOOK_PUBLIC_URL 的 HTTPS origin 讓平台下載 `/media/<權杖>`；公開邊界與 ngrok 政策只多允許精確的媒體權杖路徑（含 IG 轉檔的 `.jpg`）。
- 發佈紀錄的「檢查平台貼文」（`POST /api/publish/presence-check`，管理員與行銷）會重新抓完整清單並經過 Meta 呼叫配額；同一品牌 60 秒內只能手動檢查一次。
- 結果無法確認（逾時、中斷）時，先到平台確認是否已發佈，再按「只重試失敗平台」。
- 部署後第一篇真實發佈須在使用者在場且當次同意下進行：Facebook 先用未發佈貼文、YouTube 先用「私人」影片、TikTok 先送一支測試影片到收件匣（不在 App 內按發佈就不會公開）。未經使用者當次同意不得按下任何發佈。

**限時動態**：Facebook Login 路徑的 IG Stories 需商業帳號及 instagram_content_publish、instagram_manage_insights。Meta App 後台 Instagram Webhooks 勾選 `story_insights`，並確認該 IG 帳號已訂閱 App。接收端只寫本機已知限動 ID 的 final 快照，不儲存原始事件。

**Facebook 限動成效唯讀核對**（尚未執行）：先取得使用者對帳號、既有未過期限動及唯讀範圍的同意；重新讀官方 Page Stories／insights 文件，僅在文件明確支持時對已存在限動 ID 發 GET，不上傳、不建立、不發佈。記錄版本、端點、HTTP／錯誤碼與欄位是否可用，不記 token、帳號或原始回應。文件仍不明確則停止，維持「Facebook 不提供限時動態成效」。

**部署前待核對的平台規格**：FB Reels 3–90 秒／9:16、Threads emoji 位元組計數、published_posts 是否涵蓋 Reels、IG Stories 3–60 秒與 JPEG 規格。這些值集中在 `publish_rules.RULES`，核對後只需改該處。

## Meta／Threads 首次連結

回呼只允許內部登入中的管理員；公開入口的 `/api/oauth/*` 一律 404。ACCOUNT_ENCRYPTION_KEY 由部署者提供。

1. 在 Meta 開發者後台「Facebook 登入 → 設定」，把「有效的 OAuth 重新導向 URI」加上 `<內部 https 網址>/api/oauth/meta/callback`（工作檯「設定教學」視窗會顯示並可複製）。
2. 確認使用案例包含 `pages_manage_posts`、`instagram_content_publish`，以及讀取所需的 `pages_show_list`、`pages_read_engagement`、`pages_read_user_content`、`pages_manage_metadata`、`read_insights`、`instagram_basic`、`instagram_manage_comments`、`instagram_manage_insights`；不再要求已退場的私訊權限。
3. 在內部工作檯「平台連線 → Meta → 手動設定（進階）」設定應用程式編號與密鑰，按「連結 Meta 帳號」。只有一個粉專自動採用；多個粉專需選擇。沒有 IG 時仍可連結 FB。

Threads：在「使用案例 → Threads API → 設定」取得獨立的應用程式編號與密鑰，加入 `<內部 https 網址>/api/oauth/threads/callback`，確認 `threads_basic`、`threads_content_publish`、`threads_manage_replies`、`threads_manage_insights`、`threads_read_replies`，回工作檯設定兩欄並按「連結 Threads 帳號」。既有連結缺數據權限時，Threads 卡片顯示「需要重新連結以取得數據與回覆權限」；在重新連結前貼文清單與發佈照常，成效與回覆暫不抓取。

state 綁管理員與登入 session、10 分鐘一次性。Facebook 使用者權杖剩不到七天只能重新連結，粉專權杖不另設到期。Threads 每日檢查，剩不到七天且更新已滿 24 小時才續期；失敗與到期提醒排入既有品牌 LINE 通知群組，沒有設定群組則只留稽核。

Threads 部署後第一次實機請確認：六項 insights 能一次請求（官方文件將 views、shares 標為開發中）、conversation 接受 limit 參數、回覆的 username 缺漏比例。Threads 不經 Meta 呼叫配額與 usage headers；每輪上限為清單 50 頁、成效 300 篇。

## TikTok 連結

只用 TikTok for Developers 的 Sandbox，不送審（見 `docs/TikTok規劃.md`）。照平台連線 TikTok 卡片的「設定教學」建立應用程式：Sandbox 加入 Login Kit 與 Content Posting API（Direct Post 關閉），Redirect URI 選 Web 填 `<BACKOFFICE_ORIGIN>/api/oauth/tiktok/callback`，Scopes 為 `user.info.basic`、`user.info.stats`、`video.list`、`video.upload`，Target Users 加入要連結的帳號，必填欄位含公開的服務條款與隱私權政策網址。Client key／Client secret 在卡片加密入庫（`.env` 的 `TIKTOK_*` 只作後備）。

連結採與其他平台相同的兩段式導回。access token 24 小時，呼叫前不足 5 分鐘即以 refresh token 換發並保存 TikTok 回傳的新 refresh token；卡片顯示 refresh token 到期日。每日 OAuth 維護會預先換發，換發失敗（`invalid_grant`）標記需重新連結並以 LINE 通知一次，refresh token 到期前 14 天同樣通知。「中斷連結」呼叫 TikTok revoke（權杖已失效時照常清除），刪除 TikTok 權杖與已同步資料，帳號列保留並改名為「TikTok」。

連結後，每小時的數據排程以 `POST /v2/video/list/` 讀公開影片（含觀看、按讚、留言、分享數），同一份清單寫入貼文與到期的成效快照；粉絲數由每日粉絲排程以 `GET /v2/user/info/` 的 follower_count 記錄。從第一頁走到最後一頁且非空的清單，才把消失的影片標為已刪除（TikTok 上可能是刪除或改為私人）並自貼文數據隱藏，重新出現即恢復；清單中斷或為空不判定。授權需重新連結時排程直接略過 TikTok、不呼叫 API。TikTok 留言一律不讀。

發佈：TikTok 只支援影片，送到使用者的 TikTok 收件匣（未審核應用程式不能直接公開），收件匣 API 不收文案，發佈紀錄提供「複製文案」。需要 `video.upload`；publish_id 先保存，重試先查狀態，已進收件匣就不再送。收件匣 24 小時內最多 5 支待處理，超過回 `inbox_full`。送出後由發佈排程每 10 分鐘查一次狀態（最多 7 天），使用者在 App 發佈後顯示「已在 App 發佈」。migration 0047 放寬 publish_targets 的平台限制；降版前若已有 TikTok 發佈目標會拒絕。

## YouTube 串接與發佈

1. 在 Google Cloud Console 建立專案，「API 和服務 → 程式庫」啟用 **YouTube Data API v3** 與 **YouTube Analytics API**。
2. 「Google Auth Platform → 品牌」建立同意畫面；「目標對象」選 **外部**、發布狀態改為 **實際運作中（In production）**（Testing 的 refresh token 通常七天到期）。
3. 「資料存取權」加入 `https://www.googleapis.com/auth/youtube.readonly`、`https://www.googleapis.com/auth/yt-analytics.readonly`；要從發佈頁上傳影片另加 `https://www.googleapis.com/auth/youtube.upload`。
4. 「用戶端 → 建立用戶端」選 **網頁應用程式**，授權重新導向 URI 必須完整符合 `<內部 HTTPS 網址>/api/oauth/youtube/callback`。
5. 管理員在「設定 → 平台連線 → YouTube」填入用戶端 ID／密鑰並儲存，按「連結 YouTube 帳號」（或「重新連結」並保留「上傳影片」勾選）。
6. 選擇擁有目標頻道的 Google 帳號；未驗證警告確認是自己的應用後按「進階 → 前往（應用程式名稱）（不安全）」，不繞過組織政策。頻道屬品牌帳戶時選該品牌頻道。一次只登記一個頻道；多品牌時須先登記頻道的品牌歸屬。
7. 回到工作檯確認頻道名稱與「已連結」，並在同一張卡片設定「上傳類別」（預設「人物與網誌」）。invalid_grant 會標記「需重新連結」；中斷連結會向 Google 撤銷授權並清除本地權杖，保留歷史資料。

配額：讀取以持久化的 `youtube.quota` 依美西日曆每天限制 8,000 單位（預留 2,000 給人工操作），每輪最多清單 50 頁、成效 300 篇；`videos.insert` 每日 100 次另計 `youtube.uploads`；`thumbnails.set` 約 50 單位計入 `youtube.quota`。未驗證頻道的影片超過 15 分鐘會被拒收；縮圖失敗最常見是頻道尚未通過電話驗證，完成驗證後按「重新套用縮圖」即可（只換縮圖，不重傳影片；素材 30 天後清除就無法再套用）。縮圖上限先採保守的 2 MB（`RULES.youtube.thumbnail_bytes`）。若 Google 對未稽核專案限制公開狀態，發佈紀錄會標示「YouTube 實際為…」。

## 成員管理與帳號復原

- 管理員在「設定 → 成員 → 新增成員」輸入帳號、顯示名稱、角色及品牌。臨時密碼只顯示一次，直接安全轉交，勿貼入稽核、日誌或文件；新成員首次登入須先改密碼。
- 「編輯 → 重設密碼」產生新的臨時密碼並撤銷所有登入；停用亦立即撤銷。最後一位啟用中的管理員不可停用或降級，管理員不可停用自己。
- 所有角色在「設定 → 我的帳號」改密碼（至少 12 字元，新舊不可相同）；成功後保留目前登入、撤銷其他登入。
- 同一帳號連續失敗五次鎖定 15 分鐘；存在與不存在的帳號均回「帳號或密碼不正確」。
- 其他成員須加入同一 Tailscale 網路；登入後若顯示「尚未指派品牌，請聯絡管理員」，由管理員補上品牌。
- 登入頁「忘記密碼？」說明成員找管理員重設，並提供管理員復原碼表單與下方的主機指令。工作檯沒有寄信或簡訊管道，所以前端不提供不需事先準備的自助重設。
- 管理員可在「設定 → 我的帳號 → 密碼復原碼」輸入目前密碼產生一次性復原碼（只顯示一次，資料庫只存雜湊），請保存在密碼管理工具，不要和密碼放一起。重新產生即作廢舊碼。
- 用復原碼重設成功後：設定新密碼、作廢復原碼、撤銷該帳號所有登入與 Agent 連線、清除登入鎖定。只有啟用中的管理員可用；錯誤一律回「帳號或復原碼不正確」，並與登入共用五次鎖定 15 分鐘。

忘記最後一位管理員密碼又沒有復原碼時，由有正式庫操作權限的人在服務主機的互動終端執行：

1. 確認部署版本及正式 `.env` 指向正確資料庫，依備份流程建立備份。
2. 在 `backend` 執行 `uv run python ../scripts/set_password.py <管理員帳號>`，在隱藏輸入提示輸入兩次新密碼（12–128 字元）；不要把密碼放命令參數或管線。既有管理員復原不加 `--create-admin`。
3. 工具撤銷該帳號所有 session，清除須改密碼與登入鎖定；重新登入後確認角色與品牌。工具不會啟用已停用帳號或改動角色。`--create-admin` 只供首次初始化，資料庫還沒有品牌時會一併建立唯一品牌（`--brand` 或互動詢問）。

## 資料轉換工具

資料轉換一律預設唯讀乾跑，確認結果後才加 `--apply`；正式 apply 由部署操作人在備份後執行。

### 私訊資料清理（purge_direct_messages.py）

LINE inbound 驗簽後 200 丟棄；LINE_CHANNEL_ACCESS_TOKEN／LINE_BOT_USER_ID、SCHEDULER_DM_ENABLED／META_DM_* 已退休，既有 env 可保留但不使用。LINE 通知及 NOTIFY_LINE_*、`/webhook/line-notify` 不變。

部署操作人須先備份 SQLite 與匯出資料夾，安排停止寫入的維護時段，再明確指定同一套資料庫／匯出目錄，先乾跑核對清單後才 apply：

```powershell
cd backend
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄>
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄> --apply
```

腳本不載入 .env 或應用設定；database 必填且須已存在，export-root 未提供就不刪檔。預設唯讀乾跑列各表筆數、檔案與無法判定的 raw event ID。apply 使用單一 BEGIN IMMEDIATE，依外鍵順序刪除 DM 及相依資料、所有歷史草稿、只出現在 DM 的 contacts，保留混合聯絡人、留言、貼文、ideation 報告、audit_log 與設定。混合通知 delivery 含快取私訊時刪該快取，公開留言 notification 保留並解除 delivery 關聯。純 DM raw payload 才刪；混合或未知來源保留供另行決定。

匯出只刪 DM 專屬聯絡人目錄內對應 Markdown／Word，以及以 DM thread ID 命名的歷史 Word；ideation 檔不刪。與保留聯絡人前綴衝突的檔案不刪；遇到符號連結或 junction 中止。檔案失敗會回滾資料庫並回存本輪已刪位元組；檔案系統和 SQLite 無法共同保證斷電原子性，部署備份不可省略。刪除前後外鍵檢查須為空，稽核 `data.purge_dm` 只記各表／檔案筆數；重跑刪除數為零且不再寫稽核。刪除前備份是資料回復來源。

### 平台資料保留（data_retention.py）

依平台條款刪除不再允許保存的資料：所有平台自工作檯取得起超過 `COMMENT_RETENTION_DAYS`（預設 365）天的留言（以取得時間計，不是留言發布時間）與相依資料（分類、通知與投遞快取、無人引用的聯絡人）、同期限 webhook 原始事件的內容（只清原文，保留平台事件 ID，平台重送舊事件時視為已處理、不重建留言）；YouTube 30 天未再取得的留言，以及在 YouTube 上已刪除超過 30 天的影片（含數據快照與縮圖）。主題發想報告只移除被刪的引用原文與貼文說明，主題保留；使用者自己的發佈紀錄保留。已匯出的 Markdown／Word 不會被改動，需要時由操作人另行刪除。

每日排程預設關閉。部署操作人先在 master 上部署並執行 `./scripts/backup.ps1`，再在**專案根目錄**乾跑查看筆數（只讀，不印原文）。`--project backend` 讓 uv 使用後端的環境；設定一律讀專案根目錄的 `.env`，與目前所在資料夾無關：

```powershell
uv run --project backend python scripts/data_retention.py
uv run --project backend python scripts/data_retention.py --enable
```

貼文數據的留言區會依同一份設定顯示各平台的保存期限，以及每日刪除是否已啟用。確認 `would_delete` 後才加 `--enable` 啟用；之後每天最多執行一次，每批最多 500 筆、各自提交（第一次啟用資料量大時也不會長時間鎖住資料庫），每批寫入一筆 `data.retention` 稽核（只記各表筆數）。

留言者寄信要求刪除時（隱私權政策承諾 7 天內處理），先備份，再依名稱找出聯絡人、預覽、確認後刪除；只刪該人自己的留言與聯絡人，別人在其下的回覆保留，報告移除其引用原文，稽核 `data.delete_request` 只記筆數：

```powershell
uv run --project backend python scripts/data_retention.py --find-commenter <名稱>
uv run --project backend python scripts/data_retention.py --delete-contact <id>
uv run --project backend python scripts/data_retention.py --delete-contact <id> --apply
```

YouTube「中斷連結」會撤銷 Google 授權，並立即刪除已同步的 YouTube 影片、快照、縮圖、留言與報告中的 YouTube 引用，頻道帳號列保留但名稱改為「YouTube」（YouTube API 政策要求撤銷後 7 天內刪除）。

Gemini 免費方案的內容會被 Google 用於改善產品並可能由真人審閱，工作檯因此不讓它處理任何資料：`GEMINI_PAID_TIER` 預設 false 時，Gemini 在選單顯示不可用，後端執行回 `provider_unpaid_tier`，排程報告改用品牌的背景供應者或第一個可用 API。只有在 Google Cloud 專案已綁定帳單後才設為 true。

### 分類指紋重標（restamp_classifications.py）

部署者先備份，核對歷史版本後執行 `uv run python ../scripts/restamp_classifications.py --database <資料庫路徑> --shared-revision <版本> --brand-revision <版本>`。兩個版本皆必填，0 表示當時無該 scope 的 prompt；正數從 prompt_versions 讀取，缺少版本則整次失敗。多品牌逐一依自己的 scope 找相同版本號，只有完全符合舊指紋的列會處理。確認 total／matched／updated／unmatched 後才加 `--apply`；單一 BEGIN IMMEDIATE 交易只改相符列的 input_hash，每列寫 `classification.restamp` 稽核，重跑不再更新。此工具不讀 .env、不啟動 worker、不呼叫平台或模型。

## 功能設定與操作備忘

**AI 供應商與 Agent 撰寫**：文字模型只用 Gemini、OpenAI、Anthropic 官方 API 金鑰；本機 CLI 已移除，讀到舊 CLI 設定一律視為未設定，管理員到「設定 → AI → 基本」選 API 供應者並儲存。主題發想可選「交給 Agent 撰寫」，報告停在「等待 Agent 撰寫主題」後在 Claude Code 用 `/mwb:ideas` 或其他 Agent 用 `get_guide("ideas")` 接手；報告頁的「交給 Claude Code」「開啟 Claude 對話」「開啟 Codex」按鈕用官方 `claude://`、`codex://` 連結開啟桌面 App 並預填含報告編號的指令（仍需自己送出），Antigravity 等其他 Agent 用「複製給其他 Agent」，24 小時內未存回會失敗。例會排程報告固定用 Gemini API。舊 `mode=subscription` 用量紀錄保留顯示、不計入預算。

**AI 備援與配額**：每家備援模型可留空停用；`AI_API_TIMEOUT_SECONDS` 控制整次主備援時間（規則見 architecture 的「AI 與訊息分類」）。Gemini 免費方案額度用完不重試也不切備援，持續使用建議在 Google AI Studio 為專案設定付費帳務；更換同專案金鑰或備援模型不能解除額度。

**留言按需讀取**：只有使用者在貼文按「抓取留言」才建立一次性工作；`SCHEDULER_COMMENTS_ENABLED`／`COMMENTS_WAKE_ENABLED` 控制執行與喚醒，`META_API_CALLS_PER_HOUR` 控制共享呼叫預算。`META_COMMENTS_AUTO_DAYS` 已忽略。

**粉絲數**：metrics 排程每天每帳號一次 GET。沒有第一筆快照時，檢查排程結果的 `followers.errors`、帳號登記、官方欄位權限及預算／冷卻；不要把 `fan_count` 填成粉絲數或以零值替代。需 `SCHEDULER_ENABLED`、`SCHEDULER_METRICS_ENABLED` 與 UI 的 metrics 排程開關。

**Obsidian 留言匯出**：路徑存 Setting，預設 `<專案根目錄>/社群留言`（已忽略），管理員可改為通過寫入檢查的獨立資料夾；與一般匯出共用 EXPORT_WORKER_ENABLED。`backup.py` 的加密備份包含 Obsidian 文件與雜湊；還原的資料在新目的地的 `obsidian/`，由部署操作人核對後另行設定路徑，不自動覆寫既有筆記。備份目的地不得與留言資料夾重疊。

**平台憑證**：平台及 jev 憑證可由管理員在設定儲存並即時生效；主金鑰需部署者先設定，未設定時安全拒絕儲存。移除 DB 值即回到 env。`platform_credentials.py`／`platform-credentials.mjs` 是本機設定橋接 helper，只在操作者另行執行平台工具時使用。

### 登入 Windows 後自動啟動

工作區設定的「開機自動啟動」預設關閉，僅管理員可檢視與切換；狀態直接查詢 Windows 工作排程器。開啟建立根目錄工作 `MWB-AutoStart`：目前 Windows 使用者登入時（AtLogOn）延遲 45 秒，Interactive、Limited、不要求提升權限，允許電池執行，MultipleInstances IgnoreNew，上限 30 分鐘。動作為 `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`，參數 `-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "<專案>\scripts\start-all.ps1"`，工作目錄為專案根目錄。需要先登入 Windows，網路與 Google Drive 也必須就緒；不補回離線期間通知。登入當下網路常常還沒好：`tailscale.mjs check` 會每 10 秒重試、最多約 2 分鐘，仍失敗只顯示警告，服務照常執行（本機網址可用）；Webhook 公開邊界檢查 `webhooks.mjs check` 同樣重試，仍失敗就停止此次啟動的服務。重開機後殘留的 `.runtime/*.pid` 若指向比紀錄更晚建立的程序，視為過期紀錄自動移除。

以「工作排程器程式庫」找到 MWB-AutoStart 核對上述設定。關閉開關會移除此工作，不停止已啟動的服務。同名工作任一設定不同時，開啟與關閉均回 `autostart_conflict`，請先人工確認歸屬。專案搬移後需人工確認舊工作再重新建立。參考 [New-ScheduledTaskSettingsSet](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)、[New-ScheduledTaskPrincipal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal)。

## 資料位置

正式資料集中在專案的 `data/`（git 忽略）：`data/db`（資料庫）、`data/export`（匯出）、`data/logs`（後端與 MCP 稽核日誌）、`data/manual-backups`（部署前手動備份）、`data/legacy`（待清理的舊殘留）。本機加密備份放在專案外的 `BACKUP_LOCAL_ROOT`，另一份在 `BACKUP_DRIVE_ROOT`。匯出資料夾不可放在程式目錄，`.runtime/` 與 `data/` 的子資料夾除外（`data/` 本身不可）。禁止 `git clean -x` 等會刪除被忽略檔案的指令。

## 備份與回退

`backup.ps1` 使用 SQLite backup API 和 7-Zip AES-256，目的地由 `BACKUP_LOCAL_ROOT`／`BACKUP_DRIVE_ROOT` 指定，各保留最近 14 份。`install-backup-task.ps1` 安裝每日排程；若已有舊名稱任務，核對並移除舊任務後再安裝，避免重複執行。

備份格式為 `mwb-backup-v1`；舊格式請用備份當時的程式在隔離目錄還原，不直接覆寫現用庫。`backup.ps1 -Action restore -Archive <ARCHIVE> -Destination <NEW_DIRECTORY>` 只接受尚不存在的目的地。

回退先停止服務、備份轉換後增量，再用自動備份和相符程式版本恢復於獨立目錄。保留服務切換後的新資料，不可直接覆蓋丟失。Git 歷史不改寫。

## 健康監測與排錯

後端每五分鐘檢查排程器、公開簽章 probe、驗簽失敗量，保存 24 小時歷史；中斷／恢復警示各一次。整台主機離線需要外部監控。

- 登入失敗：檢查 APP_ORIGIN、ALLOWED_HOSTS、Tailscale 網域及 Secure Cookie。
- 無法收訊：檢查固定公開網址、ngrok policy、控制標頭、簽章與後端健康。不得暴露 UI/API 來繞過防護。
- 背景工作無進度：檢查 SCHEDULER_* 開關、租約、平台官方限速與權限，不重置游標冒充完成。
- 匯出失敗：檢查獨立絕對路徑、PROTECTED_PATHS、寫入權限、加密主金鑰與可用磁碟空間。

### AI 錯誤代碼

| 原始代碼 | 使用者說明 |
|---|---|
| provider_http_503（Gemini） | Gemini 目前流量過高（Google 端問題）；等待中顯示自動重試時間 |
| provider_http_429 | 目前請求過多或配額已達上限 |
| provider_quota_free_tier | Gemini 免費方案額度已用完，請到 Google AI Studio 開啟付費方案，或稍後再試 |
| provider_rate_limited | 供應商請求過於頻繁或配額已達上限；有建議秒數時顯示約 N 秒後可再試 |
| provider_quota_exhausted | 供應商額度不足，請檢查供應商帳務與用量上限 |
| provider_time_exhausted | 模型回應逾時，請稍後再試 |
| provider_http_500／502／503／504 | 供應商服務暫時無法使用 |
| provider_http_408／provider_timeout | 供應商回應逾時 |
| provider_connection_error | 暫時無法連線至供應商 |
| provider_http_401／provider_invalid_key | API 金鑰無效，請到 AI 設定更新 |
| provider_http_403 | API 權限不足，請檢查金鑰與模型存取權限 |
| provider_http_402 | API 額度不足，請檢查供應商帳務 |
| configuration_missing／provider_unavailable | 尚未設定或供應商尚未開放，請到 AI 設定更新 |
| provider_unpaid_tier | Gemini 免費方案不能處理平台資料；改用其他供應商，或綁定帳單後設 `GEMINI_PAID_TIER=true` |
| monthly_budget_exceeded | 本月 AI 預算已達上限 |
| incomplete_output／empty_output | 模型未完成／內容遭拒，或未回傳文字 |
| input_too_large／output_too_large | 輸入或回應過長 |
| provider_failed／generation_failed | AI 內容產生失敗，請確認設定 |

錯誤欄位可附 `;retry_after_seconds=N`，UI 顯示向上取整的約 N 秒；這是建議重試時間而非可用性保證。

### 資料庫鎖定的日誌判讀

`scheduler_tick_failed`、`receive_health_check_failed`、原生 worker、Webhook、匯入與匯出等例外均記錄 `error_type`；SQLite busy／locked 另有 `error_code="database_locked"` 及數字 `sqlite_errorcode`。只記類別與代碼，不記例外訊息、traceback、SQL、參數、第三方原文或生成內容。`DatabaseBusy` 是有限等待耗盡後的安全 503，原始 SQLite 類別／數字可在同次 `database_lock_exhausted` 事件查到。

- `sqlite_errorcode=517`：WAL 讀取快照已過期，寫入升級立即失敗；不要只提高 busy timeout，應檢查該路徑是否先結束讀取交易、在查詢前使用寫入邊界。
- 基礎代碼 5（BUSY）、6（LOCKED），或擴充代碼的低八位為 5／6：鎖競爭。檢查是否有長交易、批次匯入或同時工作的 worker。
- `database_lock_retry` 的 `attempt` 為 1–3；最後失敗另記 `database_lock_exhausted`。這是 BEGIN 取得鎖的三次上限，不會再次呼叫模型／平台。持續發生時由授權部署者核對所有寫入者版本及交易範圍，不直接改正式資料或送出開關。

503 中文訊息由前端錯誤區顯示，可待鎖解除後重試。非同步報告已回 202 時，持續鎖定可能連 failed 狀態也無法存入庫；同一程序會保留 processing、顯示暫時存檔錯誤並允許重試（最多 128 筆記憶體標記，重新啟動後回到原有租約到期判斷）。未保存的結果需人工重試。
