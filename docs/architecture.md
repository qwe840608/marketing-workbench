# Architecture / 現行架構

> **語言 / Language / 语言 / 言語**：繁體中文 | [简体中文](architecture_zh-CN.md) | [English](architecture_en.md) | [日本語](architecture_ja.md)

Marketing Workbench 提供多品牌的內部行銷工作空間。品牌、帳號、內容及 prompt 彼此隔離；後台使用者有 admin／marketing／viewer 權限。

## Agent 入口

內部 `/mcp` 使用 MCP SDK 的 Streamable HTTP，與 FastAPI 網頁服務同埠，公開邊界仍只放行既有 Webhook／媒體。Agent 以成員自己的 OAuth 授權或連線權杖登入；Bearer 僅用於 `/mcp`，網頁 API 維持 session、CSRF 與 Origin 檢查。每次工具呼叫重新讀取成員狀態、角色與品牌範圍；依 `docs/MCP規範.md` 提供查詢及行銷／管理員的主題、腳本存回，介面版本仍為 1。

`agent_tools` 統一工具說明、輸入驗證、稽核與回應大小；`agent_queries` 明確投影遮蔽內容，`agent_content` 沿用領域服務。Agent 報告 provider=agent，來源存於 data_json.source（連線名與 grant id）。既有留言 worker、jev 分類與彙整完成後停在 awaiting_ideas，不呼叫文字 AI；既有 ideation 排程將等待逾 24 小時的報告標為失敗。使用者在對話定案後存回十五題，沿用 ready／編輯／匯出流程，保留 Agent 來源。腳本每次新增 VideoScript 與 ScriptVersion，同主題舊稿保留。沒有資料表變更或新 migration。

0037 新增用戶端、授權、待核准請求、授權碼與權杖資料表；秘密只存雜湊。授權碼綁定用戶端／回呼／S256 PKCE，refresh 每次輪換且重用會撤銷整個授權。連線閒置 30 天失效，停用或重設密碼立即撤銷；使用時間每分鐘最多寫入一次，既有排程每小時清理過期資料。舊 Hermes stdio MCP 已移除，Hermes 改以檢視者帳號連 `/mcp`（見 `docs/MCP規範.md`）。

## noinbox 範圍

收件匣、回覆草稿／檢查／送出、價目表、轉人工條件、主管與路由指派、待回覆／期限提醒及成交進度已移除。工作檯只接收貼文留言。留言 Webhook、分類佇列、公開留言緊急通知、主題發想、腳本及匯出保留；私訊資料由部署者備份後以獨立 purge 腳本刪除，不新增 migration。

分類繼續保存 Classification 的意圖、原始回應、signals、版本與指紋；新 action 為 classified（垃圾／無文字為 skip），不再指派人員。歷史欄位及表格保留。排程只有 classify、notify、comments、metrics、ideation。腳本禁止承諾檢查改由 content_safety 共用。緊急通知只涵蓋公開留言的客訴、高急迫與公開聲譽風險，無工作檯對話連結；舊一般／期限通知不再送出。

## 技術與資料

- FastAPI 對原始位元組驗簽；LINE inbound 通過後一律 200 丟棄，不保存或查詢 profile。Meta messaging 丟棄，feed comments／IG comments 成功持久化才 ACK。LINE notify 仍由獨立憑證接收群組事件。
- SQLite WAL 為唯一業務來源；SQLAlchemy 2 管理資料存取，結構升級用 Alembic。事件以平台外部 ID 唯一鍵 upsert，重送不重複。
- 後端內建分類、通知、數據、主題發想排程；留言 worker 僅接續使用者已按按鈕建立的一次性工作。各自持久化租約、游標、排程開關與結果，不依賴外部工作流引擎。
- ngrok 導向後端 loopback；Traffic Policy 及後端雙層阻擋公開 UI/API、路徑穿越與轉送來源偽裝。管理介面只供本機／Tailscale。
- 公開留言在貼文頁唯讀；DM worker、回補服務與 API 已移除。歷史 DM 表格／欄位保留以相容既有 schema，資料刪除使用 scripts/purge_direct_messages.py。主題發想的來源選取保持本次基準，既有報告不刪除。

### 介面語言

- 支援繁中（預設）、简中、English、日本語。`frontend/src/i18n.ts` 的 `t('繁中原文', 變數)` 以繁中原文當鍵，繁中不查表；其他語言查 `frontend/src/locales/<語言>/` 的翻譯表，缺翻譯時退回繁中。翻譯表依語言動態載入，`main.tsx` 先 `initLanguage()` 再載入頁面，模組層級常數因此也會是正確語言；切換語言時重新整理頁面。同一原文在不同位置需要不同譯法時用 `tx('情境', '原文')`；用詞以 `docs/i18n術語表.md` 為準。
- 語言偏好存在 `staff.language`（0051，可為空），由 `PUT /api/auth/language` 設定，所有角色都能改自己的；登入前記在 localStorage。
- 後端仍回繁中錯誤，`api.ts` 把 `detail` 拿去查表（`locales/*/backend.ts` 收錄固定訊息）；需要比對特定錯誤時用原文比。日期與數字格式跟著介面語言，時區仍固定 Asia/Taipei。

### SQLite 交易與鎖定

SQLAlchemy 統一發出 BEGIN，連線初始化的 PRAGMA 在交易外執行；維持 WAL、外鍵及五秒 busy timeout。`session_factory()` 的明確 `session.begin()`／`factory.begin()` 是寫入邊界，以 `BEGIN IMMEDIATE` 在第一個查詢前取得寫鎖；普通 `factory()` 的自動交易則使用 `BEGIN` 保留讀取快照，不占用寫鎖。寫入不得沿用可能過期的讀取快照；一般請求先結束乾淨的讀取交易，透過 `ensure_write()` 建立寫入交易並重新讀取／驗證。此函式拒絕丟棄尚未提交的變動。新增寫入路徑必須使用這些邊界，巢狀交易仍由 SAVEPOINT 處理。

WAL 的讀取快照若在另一連線提交後升級寫入，SQLite 會回 `SQLITE_BUSY_SNAPSHOT`（517），busy timeout 無法解決。取得寫鎖時最多嘗試三次，每次沿用五秒 timeout，中間等待 0.05／0.15 秒，最長約 15.2 秒（不含系統排程）。只重試尚未執行任何業務 SQL 的 BEGIN；不重播已執行的 SQL、模型或平台呼叫，亦不增加背景工作的業務重試輪數。耗盡回 `503`、`Retry-After: 1` 與中文可重試說明；其他錯誤照原規則處理。

外部服務、jev、模型都在寫入交易提交後執行；結果與用量紀錄另開短寫入交易。腳本／發想內容先保存在當次執行的記憶體，取得存檔鎖的有限重試不再產生內容。權限、版本、租約／claim 與遲到結果的檢查仍在寫鎖內。讀取交易不得被當成寫入交易，唯讀 GET 不為此取得寫鎖。

非同步發想報告若連失敗狀態也無法入庫，只在程序記憶體保留最多 128 筆「資料庫位置、報告 ID、該次租約」的存檔失敗標記，不保留例外或生成內容。查詢維持資料庫的 processing 狀態並顯示中文錯誤、允許人工重試；新租約或完成結果不套用舊標記。重新啟動會清除標記，仍依資料庫原有的 30 分鐘租約到期規則恢復重試。這是暫時的操作狀態，SQLite 仍為唯一業務資料來源。

依據：[SQLite 隔離與 BUSY_SNAPSHOT](https://www.sqlite.org/isolation.html)、[SQLAlchemy SQLite 交易控制](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#enabling-non-legacy-sqlite-transactional-modes-with-the-sqlite3-or-aiosqlite-driver)。不新增資料表或 migration；Alembic 連線設定配合由 SQLAlchemy 管理 BEGIN，升降版驗證仍必須通過。


## 私訊視窗與留言同步範圍

私訊 messages 由新到舊讀取；含早於日期下限的頁面先匯入視窗內訊息，再結束該對話。conversations 請求保留 `id,updated_time`，略過日期下限以前的對話；回應時間持續由新到舊時在邊界結束探索，缺少時間或順序反轉則保守續頁。全部歷史不套日期停止條件。同一 messages 游標連續逾時／5xx 計數持久化於進度，成功讀頁歸零；達 `META_DM_CURSOR_RETRY_LIMIT`（預設 5）後結束該對話，計入平台未回應的部分未完成對話，其他對話繼續，工作可完成。提示沿用等待樣式。

留言只由貼文詳細頁「抓取留言」建立單篇一次性讀取，管理員／行銷可抓取及停止，檢視者唯讀；品牌權限、CSRF 與 `comments.request`／`comments.stop` 稽核均由後端執行。同篇唯一狀態在寫鎖下去重。沒有手動工作時排程不執行留言 worker；貼文清單與成效指標仍由 metrics worker 同步。舊批次同步／回補 POST 回應 410，不再探索貼文或排隊。舊 `META_COMMENTS_AUTO_DAYS` 由設定解析忽略。

cwindow：手動抓取依留言日期篩選設定 `window_start`，`window_end` 固定為所選迄日次日與請求時間的較早值，使用半開區間；只有明確 period=all 才令起點為 null。主題發想同樣傳入獨立留言範圍，貼文發佈期間仍只用於選文；舊留言資料不刪除。IG 使用 `comments?fields=id,text,timestamp,from{id,username},replies.limit(50){id,text,timestamp,from{id,username}}`；FB 使用 `comments?filter=toplevel&order=reverse_chronological&fields=id,message,created_time,from{id,name},parent{id},comments.filter(stream).order(reverse_chronological).limit(50){id,message,created_time,from{id,name},parent{id}}`。頂層及巢狀各要求最多 50 筆。巢狀邊不存在代表沒有可見回覆，不逐則補查；僅巢狀 `paging.next` 存在時保存其 `cursors.after`，以該留言的 replies／comments edge 續頁。不使用平台回傳的 next URL，避免攜帶憑證或導向非官方主機；游標缺少、重複或過長則報錯。

主留言與回覆分別在非空整頁皆早於 window_start 時停止續頁；混合頁繼續，缺少時間則報錯。已讀頁的舊父留言仍可保存範圍內回覆，但停止主留言續頁後不再探查更早父留言的回覆。FB 明確使用 reverse_chronological；IG 沿用平台原生排序，無新增未列於官方 SDK 的排序參數。完成立即解除手動排隊，不再續抓。每次 worker 限 35 次 GET／50 秒，預算或平台限速時保留固定視窗、游標、已處理頁數及已存筆數，沿用每小時配額、用量標頭、退避與等待原因接續同一工作。可處理的網路暫時故障亦保留重試；權限、憑證或無效回應等需人介入的錯誤結束本次讀取，由使用者處理後重新按鈕。

停止會先撤銷 run_id／租約並清除手動排隊，保留訊息與已保存進度。已在網路中的 GET 無法撤回，其結果在撤銷後不能寫入留言，也不能再核發下一個 GET。重新抓取從新固定視窗及第一頁開始，依平台 ID 去重。0025 migration 安全結束所有舊留言工作及回補探索，清空舊游標與排程所有權，保留所有業務資料及最後成功時間，不復活舊工作。

顯示只查 DB：詳細頁預設近 30 天，提供 7／30／90 天台北日曆篩選；每頁 50 組並附範圍內回覆，「顯示更多」只讀下一批。父留言不在範圍或未入庫時，具有相同明確父 ID 的回覆合為一組並標示父留言不可見，不補造或抓取父正文。舊 API 的全部／自訂日期保留供既有報告定位與查詢，詳細頁不提供該選項。狀態輪詢只讀 DB，不觸發 Meta。

官方參考：[Field Expansion](https://developers.facebook.com/docs/graph-api/guides/field-expansion/)、[IG media comments](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/comments/)、[IG comment replies](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-comment/replies/)、[FB object comments](https://developers.facebook.com/docs/graph-api/reference/object/comments/)。本次上述參考頁回應 429，未宣稱成功讀取；欄位／edge 交叉查核 [Meta 官方 IGComment SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/igcomment.py) 與 [Comment SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/comment.py)，並以三次 IG 唯讀 GET 確認巢狀讀取、空邊省略及獨立分頁。正式庫副本無 FB 貼文；另兩次 FB 唯讀 GET 取得一篇貼文，展開查詢回應 200 但沒有留言，未宣稱實測到 FB 回覆分頁。FB 回覆以官方 SDK 與 HTTP mock 覆蓋，部署者須核對有留言貼文的實際回覆與平台可用性。

## 粉絲數追蹤

`follower_snapshots`（0026）保存帳號、UTC 觀測時間及非負整數粉絲數，帳號／時間唯一鍵避免重送重複。資料表與每日記錄流程不變。`GET /api/posts/followers` 必填 `platform`，可傳 `brand_id`、`account_id`、`year`、`month`、`week`；省略年月週時選台北今天所在年月週。沿用貼文的登入及品牌權限，admin／marketing／viewer 均可讀，查詢只讀本機 DB，不觸發平台或模型。

回傳平台串接狀態、具有快照的年份（至少今年）、月內週次日期、目前數量、所選週／月增減及是否當週／當月；另保留各帳號數值，支援單帳號篩選。平台工具列合計可見帳號，任一帳號缺少該期資料時該合計為 null，避免把未知當零。快照輸入採共用平台型別，未來平台抓取器可沿用同一資料表、寫入服務、API 與顯示，不需複製計算邏輯。

週一為週起點，且以台北月份邊界切開：2026 年 10 月第 1 週為 10/1–10/4、第 2 週為 10/5–10/11、第 5 週為 10/26–10/31；2027 年 1 月第 1 週為 1/1–1/3。週月邊界採台北 00:00，結束含末日並最多計算至查詢當下。每日期取最後一筆；基準沿用邊界快照或此前最後一筆，起點早於首次記錄時以第一筆原始快照為基準。完全沒有該期快照回傳 null；負值保留負號，不補造缺日資料。目前數量永遠取最新快照。

粉絲數放於各平台分頁下方，FB／IG／Threads 共用精簡粉絲工具列，桌面下拉與三項行內數字併為一列，768／390px 下拉一列、數字一列；年份、月份、週次切換即查詢，選擇歷史週月改用「該週／該月」標籤。未串接平台顯示指定提示。區塊自然撐高、使用共用尺寸／內距變數；手機可換列。自訂日期、每日序列、折線圖、起記／快照時間及基準說明已移除；舊 `date_from`／`date_to` 查詢回應 422，無其他粉絲數 API 使用者需保留此功能。貼文成效的日期篩選與圖表不變。

既有每小時 metrics 排程先檢查粉絲快照，再同步貼文指標，沒有當日快照才呼叫 FB／IG 的 `GET /{account-id}?fields=id,followers_count`，或 Threads 的 `GET /v1.0/{threads-user-id}/threads_insights?metric=followers_count`。Threads 使用獨立權杖與既有數據權限閘門，缺權限略過、權限錯誤暫停；不經 Meta 配額，格式／數值異常不寫入且記錯。正常每日每帳號額外一次 GET（FB＋IG 為兩次），不需讀取任何 Insights 歷史；失敗可於後續排程重試，仍受共享每小時呼叫上限、usage headers 及 Retry-After／退避限制。啟動時請求一次 metrics 排程，以免持久化的下次執行時間延後第一筆；停用排程時不執行。發佈成功與貼文數據的「立即同步」也各請求一次：立即同步限管理員／行銷，後端以 `scheduler.manual.metrics` 記最近請求時間，60 秒內再按回 429；已排入或執行中不重複排入、不計冷卻；稽核 `scheduler.request`。實際呼叫仍受上述共享每小時上限與用量標頭退避限制。欄位失敗不妨礙可執行的貼文同步，排程結果另列 `followers` 錯誤，既有快照保留。

IG 與 FB 均只用 `followers_count`。官方欄位參考：[IG User](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/)、[Page](https://developers.facebook.com/docs/graph-api/reference/page/)。本次文件頁回應 429，欄位以 [Meta 官方 IGUser SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/iguser.py) 與 [Page SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py) 交叉核對，兩者皆列出 `followers_count`。本次未呼叫實機 Meta API；平台授權可用性仍由部署者核對。未回傳欄位時記錄失敗，不寫零值；`fan_count` 為不同語意的粉專欄位，不自動混入序列。

## 受眾分析（0052）

`audience_insights` 每個帳號、每種分布（`metric` followers／viewers／online × `breakdown` age／gender／country／city／hour）只存最新一份，含狀態（ready／unavailable）、缺資料代碼（permission_missing／not_available／no_data）、平台統計期間、單位（count／percent）、`items_json` 與取得時間；每天覆寫，不保留歷史。抓取掛在每小時 metrics 排程的縮圖之後（`Workers.audience`），每帳號每個台北自然日一次：同一帳號的各項全部拿到結果才一起寫入；網路、限流、5xx 或格式異常不寫入，下一輪重試；平台明確拒絕（權限、門檻、指標不支援）存成 unavailable，當天不再試。沒事做時回 0，排程視為空跑。斷開帳號的資料刪除會一併刪除。

- **Instagram**：`GET /{ig-user-id}/insights?metric=follower_demographics&period=lifetime&timeframe=this_month&metric_type=total_value&breakdown=age|gender|country|city`，四次；另 `metric=online_followers&period=lifetime&since&until`（近 7 天）一次。online_followers 每天一組 0–23 時（太平洋時間的一天，`end_time` 為隔天太平洋午夜），換成台北時段後取平均。權限沿用 `instagram_manage_insights`；追蹤者未滿 100 人時平台不回資料。
- **Facebook 粉專**：`GET /{page-id}/insights?metric=page_follows_country,page_follows_city&period=day` 一次，取最新一天。`page_fans_gender_age` 等年齡／性別指標 Meta 已於 2024-03-14 停用、沒有替代；`page_fans_country／city` 於 2025-11-15 停用，官方替代為 `page_follows_*`。
- **Threads**：`GET /{threads-user-id}/threads_insights?metric=follower_demographics&breakdown=…`，四次（官方一次只允許一種 breakdown），沿用 Threads 數據權限閘門；權限錯誤時暫停並保留前一天的資料，一般 API 錯誤（多半是未滿 100 人）存成 not_available。
- **YouTube**：YouTube Analytics `reports`，近 28 天（太平洋時間兩天前為止）`dimensions=ageGroup,gender&metrics=viewerPercentage` 與 `dimensions=country&metrics=views&sort=-views&maxResults=10` 兩次，計入既有 `youtube.quota`。年齡／性別只含登入觀眾。
- **TikTok、LINE**：不呼叫。Display API 沒有受眾資料；LINE 只用於通知。介面直接顯示原因。

Meta 呼叫經 `meta_api` 記錄並受每小時上限、冷卻與 usage headers 限制，限流後同一輪不再呼叫其他 Meta 帳號；正常每天 IG 五次、FB 一次。`GET /api/dashboard/audience` 可選 `brand_id`，沿用帳號的品牌權限，admin／marketing／viewer 都可讀，只讀本機 DB。儀表板「受眾分析」卡片以平台分段切換（網址 `audience_platform`），能取得的項目以長條（人數換算占比）或 24 時直條呈現，缺資料或平台不提供時顯示原因。國家代碼以 `Intl.DisplayNames` 依介面語言顯示。實機回應格式未驗證：FB `page_follows_*` 的值格式比照舊 `page_fans_country`（`{代碼: 人數}`）、Threads `follower_demographics` 比照 IG 的 `total_value.breakdowns`，部署後須核對。

## AI 與訊息分類

官方 Gemini／OpenAI／Anthropic 共用應用層重試，SDK 內建重試關閉。408、一般 429、500、502、503、504 與連線／讀取逾時最多嘗試 4 次，等待 2／5／10 秒各加 0–0.25 秒抖動；優先採 Retry-After（秒或 HTTP 日期）及 Google `google.rpc.RetryInfo.retryDelay`。供應商建議等待超過剩餘時間時立即回報，不空等、不提早重送、不延長上限。

Google 429 的錯誤內容含 `free_tier` 時回傳 `provider_quota_free_tier`，視為短時間重試無效，立即結束且不切同供應商備援；其他 429 回傳 `provider_rate_limited`。OpenAI 429 的 `insufficient_quota` 或帳務／支出上限代碼回傳 `provider_quota_exhausted`，不重試、不切備援；Anthropic 429 的 `rate_limit_error` 回傳一般限速代碼，不憑該代碼推斷帳務原因。只保存代碼與有限非負等待秒數，以既有錯誤欄位的 `;retry_after_seconds=N` 附記供 UI 使用，不保存供應商錯誤原文或絕對單調時鐘，無資料表變更。

品牌 `ai.brand.<id>` 設定新增三家 `*_fallback_model`，沿用品牌寫入權限、版本衝突檢查與 `ai.settings` 稽核。Gemini 預設 `gemini-3.7-flash`，其他供應商預設空白；明確空白停用備援，主備援相同不重複切換。主模型重試後仍為 408／一般 429／5xx／逾時／連線故障才切同供應商備援，永久錯誤及未完成／遭拒內容立即結束。主備援共用 `AI_API_TIMEOUT_SECONDS`（預設 60 秒）；有備援時預留 `max(20 秒, 總時限 / 3)`，預設主模型最多 40 秒。退避後不足 10 秒發出下一次請求時停止主模型重試並交給備援；主模型提早結束的時間亦可供備援使用。備援最多 4 次，各次 SDK timeout 為階段剩餘時間。每次請求前剩餘少於 10 秒時禁止建立請求，回傳 `provider_time_exhausted`。較短總時限可能直接略過主模型，且無法保證超過總時限的 20 秒；總時限不足 10 秒則全程不發請求。最後一次回應的 Retry-After 也適用於備援；若等待會侵占備援保留時間，直接回報限速／供應商錯誤，不空等也不提早請求。

Gemini 配額以專案管理，實際限制依模型與方案不同；不將個別錯誤中的限額當成全體預設。免費方案額度失敗採保守停止策略，不能假設備援模型會解除限制。持續使用建議到 Google AI Studio 為該專案設定付費帳務，再核對有效配額、用量與預算。官方說明：[Gemini 配額](https://ai.google.dev/gemini-api/docs/rate-limits)、[帳務設定](https://ai.google.dev/gemini-api/docs/billing)、[OpenAI 錯誤代碼](https://developers.openai.com/api/docs/guides/error-codes)、[Anthropic 錯誤代碼](https://platform.claude.com/docs/en/api/errors)。

文字模型與背景任務只使用 Gemini、OpenAI、Anthropic 官方 API 金鑰；本機 CLI 已移除，寫作改由 Agent 處理。所有雲端文字先遮蔽個資，模型用量按品牌追蹤。共用與品牌 prompt 具有版本、差異及還原，不能放寬後端護欄。

jev 使用 TypeSafe v1 的 Choice／Noul／Score；每題以反引號引用具名 state 欄位，客人文字與待審內容視為資料。同一 state 的獨立問題一次送出，全部經 `redact.scrub` 與 `jev.valid_response`。Choice 保留不符合出口；Noul 是條件成立機率，接近 0.5 並非中等強度；Choice／Score confidence 是分布集中度。既有政策與閾值不變，調整須先用標記資料評估。依據：[提問](https://docs.typesafe.ai/primitives)、[state](https://docs.typesafe.ai/concepts/state)、[confidence](https://docs.typesafe.ai/confidence)。

品牌類別補充說明以 `classification.intents.brand.<id>` 存入 Setting，九個意圖代碼固定，每段去頭尾空白且最多 200 字，未知欄位拒絕。`GET/PUT /api/classifications/intents?brand_id=` 沿用品牌權限、設定版本衝突 409 與 `classification.intents` before／after 稽核。通用服務說明後附加品牌範例，明示範例不是指令；送雲端前仍經 redact。`QUESTION_VERSION=triage-2026-10-23-v3`，raw_json 保存 `intent_notes_version`；補充說明不加入 context／fingerprint，指紋固定沿用 `triage-2026-09-26-v3`，既有結果保持有效，不重算、不重排工作，新設定只影響後續新訊息與手動重新分流。

分流 state 明定 sender 為客人，訊息與遮蔽計數不受 context 同名欄位覆蓋；提問版本與 input hash 版本分開，措辭改版保留既有結果效力。人工重分流或新的既有工作才採新題目；政策重算仍僅套用已存訊號。主題分類的提問版本同樣獨立於指紋，不因措辭改版觸發付費重算，既有分類流程仍受原 limit／預算限制。

代表原話 Choice 可回 none，此時保留已選來源並停止，不湊滿五筆；後續選取依已選結果更新 state，故仍逐次請求。CSV state 使用 `columns.column_<index>`，question ID 與回傳欄索引不變，保留 ignore。`scripts/eval_jev_questions.py` 以五組合成資料（分流十六例、其餘各八例）比較固定舊問法與現行 builders；預設 transport 替身，只有 `--live` 才連官方 API，輸出限 `.runtime/`。替身通過只證明管線可運作，不代表品質改善。

## 品牌中立設定

`settings.workspace.display_name`（實際 key 為 `workspace.display_name`）保存產品名稱。公開的內部登入識別 API 只回名稱及版本；修改限管理員且稽核。登入頁、導覽、頁首、分頁標題、Word 頁首共用此值。

`ideation.brand.<id>` 保存例會與主題；新預設停用、星期／時間空白、主題只有「其他」。`brand.rules.<id>` 保存禁語；預設空清單。歷史價目資料保留但沒有操作入口。

範本是版控 JSON；管理員先預覽差異，再以包含品牌狀態及範本內容的雜湊確認。套用在單一資料庫交易中更新主題、禁語、品牌 prompt 新版本，保留例會及送出權限。任何資料變動使舊預覽失效。

內容研究只使用真實證據；報告須引用同主題實際訊息 ID，不足數量不補造。品牌內容直接來自設定與 prompt，不讀特定外部知識庫。腳本可編輯、重檢及保存版本，不能發佈平台內容。

## 儀表板行銷摘要與每日趨勢

`GET /api/dashboard` 依台北週一 00:00 至查詢當下，回傳 new_messages（既有非歷史私訊）、new_comments（公開 comment_thread 的 direction=in／author_type=fan 訊息數，含期間內補抓留言）、top_intent（本週非歷史客人訊息的最新且指紋有效分類，排除 spam／未知代碼）。熱門分類包含私訊與公開留言，同數依代碼排序；無資料回 null。每個品牌只建立一次分類 context。問題分布維持本週新私訊的最近分類。移除 pending_threads、first_reply_seconds、first_reply_samples、stages 與相關查詢。

`GET /api/dashboard/trends?days=30` 可選 brand_id，沿用 Access；days 僅 7／30。回應 `{days, timezone: "Asia/Taipei", series: [{date, new_messages}]}`，按台北自然日補齊零值。摘要及趨勢共用 incoming_messages，依 sent_at 計算、排除歷史私訊，不計未來訊息。

趨勢只做一次批次 SELECT，記憶體按日聚合，不開寫入交易、不觸發平台／模型。沿用索引、沒有 migration。test_workspace 保留 2,000 則／500 段、唯讀及 300ms 上限（CI 1 秒），改驗一次 SELECT。匯出報表原本沒有上述客服 KPI，格式不變。

### 成長比較與轉換漏斗（2026-10-16 補上延後項目）

- 摘要多回 `previous: {start, end, new_comments}`：上週一 00:00 到七天前的此刻（與本週等長，終點不含）。趨勢多回 `previous_total`：緊接在窗前、等長的前 7／30 天新留言總數，與序列同一次 SELECT 取得。前期為 0 時前端不算百分比。
- `GET /api/dashboard/funnel?days=30` 可選 brand_id，權限同趨勢；days 僅 7／30。母體是近 N 天（台北自然日）發佈、未刪除、最新快照有 reach 的貼文；四階依序為觸及（reach 合計）、互動（likes＋comments＋shares＋saves 次數合計，可能多於觸及）、留言（這些貼文的客人入站留言數）、消費詢問（其中最新且指紋有效分類為 price／booking／model_question）。回應 `{days, timezone, posts, stages: [{key, value}]}`，轉換率由前端以上一階計算。原規劃的「成交」階段已隨 noinbox 移除，不再出現。

## 貼文縮圖快取（0046）

平台 CDN 圖片網址會過期，所以每篇貼文另存一張縮小的 JPEG（最長邊 480px）在 `post_thumbnails`（每篇一列，data 延遲載入）。抓取掛在每小時的 metrics 排程後面，由 `post_thumbnails.hourly` 每輪最多處理 20 篇（新貼文優先）：FB 讀 `GET /{post-id}?fields=full_picture`、IG 讀 `media_type,media_url,thumbnail_url`（影片只取封面）、Threads 讀同名欄位，TikTok 用 Display API `POST /v2/video/query/`（`fields=id,cover_image_url`，需 `video.list`，連結條件與 TikTok 同步相同）取當下有效的封面網址後立刻下載（封面網址會過期；清單沒有該影片代表已刪除或改為私人，標 unavailable；限流或授權失效時整輪略過 TikTok、不扣重試次數），YouTube 直接用公開的 `i.ytimg.com/vi/{id}/hqdefault.jpg`，不耗 Data API 配額。FB／IG 每篇一次 Meta 呼叫，經 `meta_api` 記錄並受每小時上限與冷卻限制，冷卻中整輪略過 Meta。圖片只從 `fbcdn.net`／`cdninstagram.com`／`ytimg.com`／`tiktokcdn.com`／`tiktokcdn-us.com`／`tiktokcdn-eu.com` 的 https 網址下載（其他主機記 `thumbnail_untrusted_host` 警告，只含主機名稱；TikTok 封面網域文件沒寫，遇到未知網域走重試而非直接放棄），不跟隨轉址、來源上限 8 MB，以 Pillow 縮圖後轉 JPEG（透明底轉白）。純文字或已刪除標 unavailable 不再嘗試；網路、限流等暫時失敗依 1／6／24 小時重試，第四次仍失敗即停止。`GET /api/posts/{id}/thumbnail` 沿用貼文的品牌權限回傳圖片；貼文清單、單篇與儀表板排行回 `thumbnail_url`（含摘要片段作快取破壞），沒有縮圖時為 null。只讀官方 GET，不寫平台；驗收以替身 HTTP 進行。

## 匯出與稽核

Markdown／Word 位於可設定根目錄下的品牌子目錄。Word 使用工作區名稱，匯出過濾秘密；路徑防穿越。MCP 工具回傳一律遮蔽個資，每次呼叫留 agent.tool.read／write 稽核（見 `docs/MCP規範.md`）。

正常修改保留稽核與 prompt 版本；歷史內容的清除須另經明確授權、預覽及備份，不自動改寫稽核。


## 文字模型執行方式（nocli）

寫作內容交給 Agent（`/mcp`、Claude Code plugin、Codex、Claude 桌面擴充、Hermes）。2026-10-12 起移除 `codex_cli`、`claude_cli`、`agy_cli` 三種本機 CLI 的執行、偵測、登入檢查、模型列舉、更新、設定頁與相關 API；工作檯不再啟動任何 codex／claude／agy 程序。所有文字 AI 只用 Gemini、OpenAI、Anthropic 官方 API 金鑰，金鑰、模型、備援、用量與月預算規則不變，送出的文字仍先經 `redact.py`。`ai.run` 只接受三個 API 供應者，其他值回 `provider_unavailable`；新用量紀錄一律 `mode=api`。

舊資料一律相容、不改寫、不做 migration：
- 讀到 CLI 類型的設定值（品牌 `ai.brand.<id>` 的 `default_provider`、`manual_provider`、`background_provider`）時視為未設定，`ai.config` 只在讀取時轉換，資料庫原值保留；`AISettings` 寫入只接受三個 API 供應者與空值，舊值不擋預算或備援模型的儲存。全域 `ai.local_cli`、`ai.cli.*` Setting 不再被讀取，也不刪除。
- `ai_runs` 的 `mode=subscription` 舊紀錄（含 token 為 null）仍在「本月用量」表顯示，名稱標為已停用的舊 CLI；月預算只計 `mode=api`，不受影響。
- 舊報告的 provider 若是 CLI 仍可檢視與匯出；不可重試（`can_retry` 為 false），錯誤文字顯示「本機 CLI 已不再支援（舊紀錄）」。排程與重試只處理 API 與 agent 報告。

`GET /api/ai/settings` 只回設定、可用 API 選項、預算與用量，不再有頂層 `draft_provider`；`GET /api/ai/execution-options` 的 `draft_provider` 是品牌 `default_provider`（未設定為空字串），選項只含三個 API 供應者。「預設 AI」現在只決定主題發想的預設執行方式。

網頁主題發想建立報告時的 `provider` 可為三個 API 供應者或 `agent`。選 API 照原流程：抓留言、jev 分類、彙整證據，再由 API 一次產生十五題（`compose_prompt` 只剩發想使用，提示欄位順序不變）。選 `agent` 則在彙整證據後停在既有的 `awaiting_ideas`，不呼叫任何文字 AI；畫面說明請在 Claude Code 用 `/mwb:ideas`，或在其他 Agent 使用 `get_guide("ideas")` 接手，24 小時內存回，沿用 `agent_content` 的證據、存回與逾時規則。網頁建立的 agent 報告沒有連線來源標記，失敗（含逾時）時允許重試。例會排程報告（`trigger="background"`）固定使用 Gemini API。畫面預設順序：瀏覽器 `ideation-choice:<brandId>` 記憶（人工更改才寫入）、品牌預設 AI、第一個可用 API、交給 Agent 撰寫；CLI 記憶與預設值一律略過。

已移除：主題卡片的「重新生成」「延伸主題」與「產生腳本」，以及 `POST /api/ideation/reports/{id}/ideas/regenerate`、`.../ideas/{index}/extend`、`POST /api/ideation/reports/{id}/scripts`、`idea_actions.request／process` 與 `video_scripts.generate／compose_prompt`（路由已自 `permissions.py` 移除，呼叫回 404 或 405）。保留：主題編輯與還原上一版（Agent 的 `edit_idea` 共用 `idea_actions.edit`）、腳本檢視與編輯、`video_scripts.review`、Agent 的 `save_script`。卡片只剩右上「編輯」；底部有腳本時多一顆「查看腳本」，其餘為「建立發佈草稿」或已有草稿時的「開啟發佈草稿」。報告 `data_json` 中舊的 `ideas_job` 與 `regenerated`／`extended_from` 標記只供顯示歷史，不再有進度或錯誤介面；升級時仍排隊的舊工作不再執行，報告處理時直接回到原題目並移除該工作欄位。`video_scripts.view` 新增 `topic_index`，供卡片找出該主題的最新腳本。

發佈草稿不再用 AI 撰寫文案：`POST /api/publish/ideation-draft` 以主題標題、開場與 hashtag（`publish.idea_caption`）組成初稿，不參考腳本；`include_script` 欄位被忽略，舊畫面送出也不會失敗。已移除 `GET /api/publish/ideation-preview`、`POST /api/publish/posts/{id}/caption/retry`、`.../caption/apply`、`publish_caption` 服務與啟動時對中斷文案任務的標記。`publish_posts.caption_job_json` 欄位保留（不做破壞性 migration），程式不再讀寫，`view` 與列表也不輸出；舊草稿帶有文案任務資料時，發佈頁不顯示任何 AI 狀態，也不因此列出空白草稿。Agent 的 `create_draft_from_idea` 行為不變（直接使用傳入文案）。

`services/processes.hidden_process_kwargs()` 仍由開機自動啟動與備份 7-Zip 共用，不屬於 CLI 專用。

## 發佈

平台：Facebook 粉專、Instagram、Threads、YouTube、TikTok（只送到收件匣，需在 App 內完成發佈）；格式：短影片、圖片、輪播、純文字、限時動態。目標帳號跟隨目前品牌在「平台連線」設定的帳號。

- **規則與檢查**：一份主文案，可逐平台覆寫。規則集中在 `backend/app/services/publish_rules.py`：`RULES`（文案、時長等，原樣回給前端）與 `MEDIA_RULES`／`IMAGE_BYTES`／`VIDEO_BYTES`（媒體比例、寬度、大小、mime），`GET /api/publish/options`、Agent `get_publish_options`、上傳檢查與 Agent 上傳共用同一份（字數、hashtag、影片長度／比例、檔案大小、mime、寬度）。不符合的平台標紅並擋發佈；系統不自動截斷、改寫或轉檔（唯一例外：送 Instagram 的 PNG 轉 JPEG）。平台不支援的格式直接停用並說明（例如 Instagram 不支援純文字、YouTube 只支援影片）。
- **排程**：立即或指定台北時間，由工作檯排程器每分鐘執行，到期貼文交給背景執行緒發佈（排程器不等上傳完成，長時間上傳不會讓其他同時到期的貼文被標成已錯過）；排程前一分鐘起鎖定編輯／取消。逾期超過五分鐘不補發，標「已錯過」並通知，由使用者決定立即發佈或重新排程。總開關關閉時暫停所有排程，重新開啟後未到期者照常、已過期者標已錯過。
- **部分成功與重試**：成功平台永不重送；只能「只重試失敗平台」。服務啟動把中斷的 publishing 標為 interrupted，不自動重送，使用者先到平台確認再決定重試。多段內容（Threads 串文、限時動態多則）每成功一段即以短交易保存平台 ID，失敗後重試只接續剩餘段；已有成功段時鎖定分段、素材與帳號。結果無法確認的逾時須人工核對平台，避免重複發文。發佈途中的非預期錯誤會把未完成的平台標為 `unknown`（請至平台確認）並結算貼文，不會卡在發佈中。取消排程或標為已錯過時，未送出的平台從未嘗試者移除、嘗試過者回到失敗；每次送出只送這次選定且仍勾選的平台。
- **媒體**：以隨機檔名存於 PUBLISH_MEDIA_ROOT；全部平台成功後 30 天清除，其他狀態保留。IG／Threads 需要公開網址時建立 `/media/<權杖>` 臨時連結（15 分鐘或取用完成即撤銷，最多 32 次，無效一律 404，納入公開邊界檢查）；YouTube 由工作檯直接上傳，不用臨時連結。
- **Facebook 未發佈貼文**：`facebook_unpublished` 以 `published=false` 建立，只影響 Facebook；Facebook 已成功或發佈中後鎖定，重試沿用原選項。不會出現在 `/published_posts`，因此不抓成效；已刪除判定改為逐篇查詢（先確認讀得到粉專，回 100/33 或 10 才算不存在，其他錯誤不判定）。
- **Reels 與 Threads 串文（composer1，0041）**：FB Reels 走 start → rupload → finish；與未發佈同選時改以 feed 建立並提示。IG `share_to_feed=false` 才明確送出。IG Reels 封面（0048，`publish_media.role=cover`，綁在 `instagram.cover_media_id`，由伺服端維護）以限時公開連結當 `cover_url` 送出，PNG 走 `.jpg` 衍生檔（官方只收 JPEG）；沒有封面時請求維持原樣（平台用第一格）。IG 已成功／發佈中後不能換封面。FB 影片／Reels 封面（0049，`role=fb_cover`，綁 `facebook.cover_media_id`）在貼文成功並保存後才以 `POST /{video-id}/thumbnails`（`source`＋`is_preferred=true`）套用，結果寫在目標 `detail.cover`；失敗不影響貼文，可「重新套用封面」（`POST /api/publish/posts/{id}/facebook-cover`，絕不重傳影片）。需要選用權限 `pages_manage_engagement`（`oauth.META_OPTIONAL_SCOPES`）：授權時一併請求，缺少時不影響連結狀態與發佈就緒，發佈選項只回 `cover_hint`。Threads 第一段附素材，後續以 reply_to_id 串接；自動分段優先空行／換行、再句末標點、最後硬切，不加編號，emoji 依 UTF-8 位元組計。平台 ID 與刪除偵測只看第一段；FB 影片與 Reels 記影片 ID，和 `/videos` 清單比對。
- **限時動態（composer3，0042）**：`format=story`，1–10 則，每則一張圖或一支影片，只限 FB／IG，不帶文字或貼文選項。IG 已成功各則 24 小時內每小時讀 insights，或收到驗簽的 `story_insights` 最終快照即停止；不支援的指標留空不補零。FB 限動暫無成效。限動不做已刪除判定。
- **YouTube（ytpublish，0043）**：需 `youtube.upload` 範圍（不要求更廣的 `youtube`／`force-ssl`），缺少時發佈分頁灰色並引導重新連結。官方 resumable upload：8 MiB 分段，中斷或 5xx 以 1／2／4／8／16 秒退避最多 5 次，每次先詢問已收位元組再續傳；工作階段 404 重新開始一次；工作階段網址存 `detail_json.upload`，不回瀏覽器或 MCP。影片完成後先保存 `video_id` 與實際公開狀態，之後縮圖成敗或中斷都不會重傳影片。縮圖另行 `thumbnails.set`，失敗不影響影片成功，可「重新套用縮圖」；會被歸為 Shorts（直式／正方形且 ≤180 秒）的影片停用縮圖（`RULES.youtube.shorts_thumbnail`）。`videos.insert` 呼叫前扣 `youtube.uploads` 每日額度，縮圖扣共用的 `youtube.quota`。
- **已刪除偵測**：只以「完整清單中不存在」判定，不以單篇查詢錯誤判定（FB 未發佈貼文例外，見上）；任何一頁失敗、達分頁上限、格式異常或帳號變更一律不判定。重新出現於清單時清除 deleted_at。
- **安全**：「允許發佈到平台」總開關（Setting `publishing.enabled`）預設關閉，只有管理員可切換；每次發佈或排程前顯示確認視窗；每次發佈寫稽核；成功、部分成功、失敗、已錯過與權杖即將到期排入既有品牌 LINE 通知群組（不含媒體網址或憑證）。發佈後只保留平台連結，不從工作檯修改或刪除平台貼文。

| 功能權限（`services/roles.py`） | 管理員 | 行銷 | 檢視者 |
|---|---|---|---|
| 儀表板、貼文數據（讀取，不需權限） | ✓ | ✓ | 唯讀 |
| `posts.sync` 立即同步、抓取留言 | ✓ | ✓ | ✗ |
| `reports.export` 匯出 Word 報告 | ✓ | ✓ | ✗ |
| `ideation.edit` 主題發想、腳本 | ✓ | ✓ | ✗ |
| `publish.edit` 發佈草稿 | ✓ | ✓ | ✗ |
| `publish.submit` 立即發佈、排程、重試、取消、重新套用縮圖／封面 | ✓ | ✓ | ✗ |
| `connections.manage` 平台連線與憑證 | ✓ | ✗ | ✗ |
| `ai.manage` AI 金鑰、prompt、模型 | ✓ | ✗ | ✗ |
| `settings.manage` 訊息分類、工作區、排程、通知、匯出、總開關 | ✓ | ✗ | ✗ |
| 成員與角色、復原碼、全部品牌（路由政策 `admin`） | ✓ | ✗ | ✗ |

自訂角色（0053 `roles`）：管理員在「設定 → 成員」新增角色並勾選上表的功能權限，成員的 `staff.role` 存內建鍵或自訂角色鍵 `custom_<id>`。內建三種角色寫在程式裡、不可修改；自訂角色一律只看得到被指派品牌，不能勾選成員管理，避免替自己升級成管理員。勾選 `publish.submit` 時後端自動補上 `publish.edit`。沒有任何權限的角色與檢視者相同，整體唯讀。仍有成員使用的角色不能刪除；角色已不存在時視為沒有任何權限，Agent 連線失效。降版 0053 會把自訂角色的成員改成檢視者。MCP 寫入工具各自對應功能權限（`agent_tools.TOOL_PERMISSIONS`），`get_server_info.user.permissions` 列出目前成員的權限。

## 平台憑證（creds）

0031 新增 platform_credentials（provider／encrypted_key／version／時間）；所有欄位含 ID／官方 base URL 均 Fernet 加密，主金鑰仍只在 .env。既有 ai_credentials 的 jev 密文與版本搬到 JEV_API_KEY，不解密、不遺失原值；舊 AI jev API 保留相容並共用新表。移除以空密文保留版本，防止刪除重建讓過期畫面通過版本檢查。

credentials.resolve(name, settings, session) 是平台設定唯一解析入口，DB 優先、無覆寫才 env；錯誤密文不降級使用 env。無值快取，每個新請求／worker 操作取最新值。Webhook 簽章、身分、Meta Graph token／帳號、LINE profile／通知、健康通知與 jev 都經此入口；webhook_normalize.secret 對平台欄位委派它。Python 評估工具及 Node 平台設定腳本同樣使用共用解析；Node 透過本機 Python 子程序取得設定，單次 AES-GCM IPC 金鑰只傳 stdin、stdout 只有密文，錯誤固定文案，沒有公開解密 API。

GET／PUT／DELETE /api/credentials 與 POST /api/credentials/{group}/test 僅 admin。寫入檢查版本，稽核只存欄位名、動作、操作者；API 只回 configured／source／mask／version／error。連線測試由管理員明確點擊才執行，寫入本身不連外；Meta /me、LINE bot info 為單次 GET，jev 沿既有 post_json 與 redact。固定 timeout、禁 redirect、無原始回應／例外回傳，jev URL 限官方端點。測試全用 HTTP／CLI 替身。
