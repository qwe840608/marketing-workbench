# UI 規格

## Agent 安裝（agentpack）

- 我的帳號密碼表單與 Agent 連線之間加入 `.agent-install`，h3「安裝 Agent」與 compact `SegmentedControl` 同列切換 Claude Code／Codex／Claude 桌面版；所有角色可見，窄版控制項換到下一列，寬度對齊卡片。
- 每個 `.agent-install-command` 僅一行指令 code 與 `.secondary` 複製，窄版指令可斷行；複製成功按鈕改為「已複製」。Claude Code 兩個安裝指令依目前 location.origin 組成，下面只保留一句自動更新說明。
- Codex 使用 `.secondary.agent-install-download` 下載 skills／config 套件，列解壓指令、一句 skills 放置及 config 合併說明與 OAuth 登入指令；不在介面列出所有工具設定。版本由既有 workspace/identity API 提供。
- http://127.0.0.1 顯示 `.notice.agent-install-origin` 指示其他成員使用內部 HTTPS，連結由同一 API 的 backoffice_origin 提供，不寫死主機。
- 指令 text-main／bg-subtle／ui-font-mono／help，說明 text-subtle／bg-surface；圓角使用 control Token，其餘沿用 P1-1 與共用元件，零外部資源。1440／768／390px 不水平溢出，check_agent_auth 等資料、字型與版面穩定才量測，check_ui_contrast 涵蓋所有新增配對。
- Claude 桌面版只有 `.secondary`「下載桌面擴充」與三步清單：安裝檔案、填工作檯網址、貼連線權杖；網址與複製按鈕同列，顯示 location.origin，HTTPS 可直接複製。127.0.0.1 HTTP 沿用來源提示，第二步同列建議成員使用內部 HTTPS、本機使用 http://127.0.0.1:8000；不增小標題，沿用上述文字與底色 Token。

## Agent 主題與腳本（agentquery）

- 報告列表 `.report-row-state` 與報告頁 `.report-heading-meta` 同列顯示 `.agent-source-chip`「來自 <連線名稱>」；腳本 `.script-heading` 在 h2 旁使用相同膠囊，寬度對齊所在區塊並自然換行。
- awaiting_ideas 顯示「等待 Agent 撰寫主題」，報告頁用一段 `.agent-awaiting` 說明證據已彙整、在對話定案後存回及 24 小時期限；此狀態不顯示匯出或重新產生，可刪除。輪詢能接收 MCP 存回的 ready 狀態。
- 來源使用 text-subtle／bg-subtle、help 字級與 control 圓角；等待說明使用 text-subtle／bg-surface。只用 P1-1 Token，零外部資源；1440／768／390px 無水平溢出，配對納入 check_ui_contrast。
- 主題／腳本頁提交用 primary；取消、重新標註、分鏡增減、套用歷史、腳本檢視與下載、建立／開啟發佈草稿採 secondary；刪除 primary danger。本節覆蓋下方歷史按鈕規則。

## 新版本提醒

- 已登入畫面每 5 分鐘及視窗重新取得焦點時，比對伺服器 `index.html` 引用的主程式檔名；與目前載入的不同時，右下角顯示 `.update-notice`：「工作檯已更新」＋`.secondary`「重新整理」。手機版放在底部導覽上方。開發模式不檢查。

## Agent 連線與核准（agentauth）

- 核准畫面為 `.agent-approval-page > .section-card.agent-approval`，只有 h1 與 `.agent-approval-details`；應用程式自稱、回呼位址、目前成員／角色、可做的事各同列。檢視者只列查詢；管理員與行銷列查詢、建立草稿及發佈另需確認。核准 primary、拒絕 secondary，以同源表單帶既有 CSRF 值提交；未登入與須改密碼沿用原畫面，網址保留授權請求。回應 DENY 防框架嵌入，核准頁 same-origin referrer policy 保留原生表單的 Origin 檢查。
- 我的帳號密碼表單後加入 `.agent-connections`，標題與 secondary「建立連線權杖」同列，寬度對齊卡片。建立沿用 `.member-dialog`，只有名稱與 primary 建立；成功後 `.agent-token-row` 顯示一次完整權杖、secondary 複製／關閉。值只留元件記憶體，關閉或卸載即清除；不放網址或瀏覽器儲存。
- `.list-box.agent-connection-list` 每列 `.agent-connection-row` 同列名稱、OAuth／連線權杖膠囊與 primary danger 撤銷；建立、最後使用及到期時間合併一列，Asia/Taipei 顯示，30 天未使用失效。撤銷使用 ConfirmDialog，取消先取得焦點，支援 Escape／Tab 與焦點還原。
- 成員列新增 `.member-connections`，連線數與 secondary 全部撤銷同列；零筆停用，提交前使用 ConfirmDialog。900px 以下列自然排列兩欄，390px 連線控制佔整列；回呼、名稱及權杖可斷行。
- 只引用 P1-1 色彩／字體、control／card 圓角 Token，零外部資源；1440／768／390px 無水平溢出。文字與底色配對列入 check_ui_contrast；check_agent_auth 等資料與字型穩定後量測，截圖的一次性權杖以中性遮罩顯示。

## 發佈（publish）

- Agent 草稿、編輯與排程在既有格式列同列顯示 `.agent-source-chip.publish-agent-source`「來自 <連線名稱>」；發佈紀錄優先顯示確認發佈的連線名，否則顯示草稿來源。主題來源膠囊保留。編輯來源放在 `.publish-editor-heading`，不新增小標題或說明列。使用 text-subtle／bg-subtle、help 字級與 control 圓角；長名稱自然斷行，1440／768／390px 無溢出。

桌面側欄與手機底部依序為儀表板、貼文數據、主題發想、發佈、設定，共五項。發佈以 `view=publish` 保留重整與返回狀態；本節覆蓋下方舊版四項導覽規則。

- `.publish-page.settings-page` 保留唯一 PageHeader「發佈」，右側 `.publish-switch` 為 ready／neutral 膠囊及管理員 secondary 開關。關閉時頂部 `.notice.warning` 顯示「發佈功能尚未開啟，貼文只能存成草稿」。品牌與各帳號同列，自然換行。
- `.publish-tabs` 為底線 tablist，依序新增貼文／限時動態／草稿／排程中／發佈紀錄，以 tab、tabpanel、aria-controls、roving tabindex 關聯，支援左右鍵、Home／End。檢視者只呈現發佈紀錄。
- composer2：新增貼文／草稿編輯上方 `.publish-composer-tabs` 為共用、Facebook、Instagram、Threads、YouTube、TikTok 六分頁，支援 tab／tabpanel、方向鍵與 Home／End；平台標籤併入發佈開關。已就緒平台綠色，未連結／權杖失效及未支援平台灰色，開關停用但分頁可進入，顯示「尚未連結」及 secondary「設定 → 平台連結」，沿用 settings_tab=connections 導覽；TikTok 分頁與 YouTube 同樣只支援影片：非影片格式時開關停用（title「僅支援影片發布，圖文需從APP上傳」）、分頁只顯示同一句；影片時顯示 TikTok 文案與 `.notice.tiktok-caption-notice`「收件匣不會帶入文案…」，沒有其他選項。確認視窗的 TikTok 項目為「影片 · 送到 TikTok 收件匣（文案不會送出，需在 App 內貼上並發佈）」。發佈紀錄的 TikTok 成功列加 `.status-badge`「已送到收件匣」（pending）／「已在 App 發佈」（ready）／「TikTok 處理中」，與 secondary「複製文案」（複製 TikTok 文案，未覆寫用共用文案，按後顯示「已複製」）。平台未開啟仍可編輯並標示「未開啟」。
- composer3：限時動態僅 Facebook／Instagram 兩個平台分頁與標籤開關，連線顏色、停用及設定引導沿用 composer2。每份 1–10 則，一則一張圖或一支影片，支援拖曳、secondary 上移／下移及 primary danger 移除；沒有文案、格式或貼文選項欄位，沿用自動保存，只保留發佈／排程提交按鈕；規格原因合併在同一處紅字。9:16 預覽以 secondary 上一則／下一則切換並顯示則數；非 9:16 僅提示加邊，IG 影片 3–60 秒、圖片 ≤8MB（PNG 以警告提示「Instagram 會自動把 PNG 轉成 JPEG，透明背景會變白底」，其他非 JPEG 格式為錯誤）、FB 影片 ≤60 秒錯誤以紅字阻擋發佈。立即／排程確認列平台、帳號、則數、素材及時間。紀錄標「限時動態」，展開逐則 IG 成效／最終值，缺值顯示「—」；FB 顯示「Facebook 不提供限時動態成效」，不增加儀表板資訊。部分成功後鎖定素材，重試顯示已發則數與失敗位置。
- `.publish-composer-grid` 左編輯右預覽；共用放格式、共用素材及主文案，平台放預設跟隨共用的文案，修改即專屬，secondary「還原為共用文案」回復跟隨。FB 影片形式為影片貼文／Reels（新草稿預設 Reels、舊稿沿用 feed），未公開選項放 FB 分頁；IG 影片用「同時顯示在動態」開關，預設開；其下 `.publish-thumbnail.publish-cover` 同列放「Reels 封面」、54px 高 9:16 封面預覽、檔名與大小（尚無封面時為 text-subtle 小字「JPG／PNG · 8 MB 內 · 建議 9:16 · 未上傳則用影片第一格」）、secondary「上傳封面」／「更換封面」與 primary danger「移除封面」（檔案輸入 aria-label「上傳 Reels 封面」）；封面當 IG 預覽影片的 poster，非 9:16 或 PNG 只以 `.notice.warning` 提示。IG 已成功／發佈中時封面按鈕停用。確認視窗的 IG 影片項目為「Reels · 同時顯示在動態／不顯示在動態 · 自訂封面／預設封面」。FB 影片在「存成 FB 草稿」下方有 `.publish-thumbnail.publish-cover.publish-facebook-cover`「影片封面」列（54px 高、依原比例、最寬 96px；尚無封面時小字「JPG／PNG · 8 MB 內 · 建議與影片同比例 · 未上傳則由 Facebook 自動選」；按鈕同 IG，檔案輸入 aria-label「上傳 Facebook 影片封面」），缺 pages_manage_engagement 時列內加 `.notice.publish-cover-hint`（中性提示，不是警告）「自訂封面需要 pages_manage_engagement 權限，請重新連結 Meta」；封面當 FB 預覽影片的 poster，比例與影片不同只提示。確認視窗 FB 影片項目為「影片貼文／Reels · 自訂封面／預設封面（· 草稿）」。發佈紀錄 FB 成功但封面失敗時同列顯示 `.status-badge.pending`「封面未套用」、中文原因與 secondary「重新套用封面」（確認視窗「重新套用封面到 Facebook？只會更換封面，不會重傳影片。」；檢視者看不到按鈕）。已成功／發佈中平台及已部分送出的 Threads 選項鎖定。
- `.publish-preview` 使用品牌首字頭像、帳號名稱、文字與本機素材，不載入外部資源。共用預覽只列已開啟平台的 secondary 小按鈕；平台分頁固定本平台。文字依簡化字數／行數門檻折疊，以 secondary「更多／收合」切換；@／hashtag 使用 link-color，Threads 顯示第一個主題標籤及首段／回覆串文，素材只在首段。IG 圖片用 4:5／正方形用 1:1，Reels 用 9:16，FB 影片貼文／Threads 沿原比例。影片一律完整顯示（contain），框與影片比例不同時以 `--media-letterbox` 補邊（例如直式框裡的橫式影片上下補邊），因為送出的是原檔、平台不裁切；圖片維持填滿。≤767px 預覽放編輯區頂部，1440／768／390px 無水平溢出。
- Threads 分段優先空行、換行、句號再硬切；Unicode 計數資料與測試向量放 shared/publish_threads_vectors.json，由 pytest 與前端共同驗證。自動模式即時跟隨來源文案，手動修改／新增／刪除即停止重算，最少顯示一段；每段一列段數／字數／primary danger 刪除段。secondary「依主文案重新分段」先用 ConfirmDialog 確認覆蓋，發出文案不加編號。
- 平台分頁以紅字顯示字數、hashtag、@、素材長度／比例規則錯誤，分頁標籤加紅點；後端提示以 notice warning 顯示。任何已開啟平台阻擋錯誤均停用發佈。錯誤只顯示在一處：`.publish-footer` 第一列的 `#publish-disabled-reason`（紅字、獨占一列，位於「立即發佈／排程」與送出按鈕上方），依「平台：原因」以「；」串接，列出已開啟平台，加上目前正在看但未開啟的平台分頁；分頁內不另列錯誤清單，只保留分頁標籤紅點。Threads 字數超限只標在輸入框下方，不在這裡重複；只剩這類錯誤時顯示「請先修正上方標示的錯誤」。發佈功能未開啟時只顯示「發佈功能尚未開啟」；沒有開啟任何平台時以「請開啟要發佈的平台」開頭，後面接目前分頁的錯誤。按鈕 title 保留完整原因。publish-actions 保留唯一 primary 發佈／排程及 secondary 存成草稿；確認視窗逐平台列形式、IG 動態選項、FB 未公開、Threads 段數及帳號／文案／素材／時間。紀錄的 Threads detail 進度顯示「已發 N／M 段」。
- 新增貼文初始僅為空白表單。首次文案／平台輸入後延遲自動保存，首次上傳或存成草稿立即保存；切換分頁／導覽前完成未儲存內容。格式選取不單獨建草稿。`publish_post_id` 在跨頁網址保留目前草稿；secondary「新貼文」先保存再清空，單純重整不增草稿。
- 發佈頁沒有 AI 撰寫文案的介面：主文案上方沒有進度、未通過或完成提示，也沒有「重新撰寫」「套用 AI 文案」，草稿列表沒有「AI 撰寫中」。舊草稿即使資料庫帶有文案任務資料，畫面也不顯示 AI 狀態。從主題建立的草稿，主文案是標題、開場與 hashtag 組成的初稿，可直接修改。
- 草稿使用 `.list-box.publish-records`，每列最後修改時間、格式／來自主題／AI 撰寫中膠囊、單行省略文案、媒體數量、平台與 secondary 編輯／primary danger 刪除。刪除需 ConfirmDialog。無文案、媒體、平台的歷史空白草稿只隱藏；發佈紀錄只列已送出、失敗或錯過的貼文。
- `.list-box.publish-records` 內 `.list-row.publish-record` 同列時間、格式、文案開頭、平台、狀態；排程在前一分鐘鎖定。平台名稱後以「 · 未公開」標示以「不公開到粉專」發出的 Facebook（清單列與各平台結果都有）。紀錄可展開 `.publish-targets` 的成功連結／安全中文原因，Facebook 未公開且成功的結果膠囊為 `.status-badge.neutral`「Facebook · 成功 · 未公開」（與「已在平台刪除」同色系，失敗或進行中仍用原本顏色並加同樣後綴），失敗僅重試失敗平台，已錯過可立即發佈或重新排程。刪除草稿為 primary danger 並確認，其餘動作為 secondary。
- 色彩、字體、圓角只引用 P1-1／共用 Token，零外部資源；文字與底色配對納入 check_ui_contrast。1440／768／390px 無水平溢出，手機五欄導覽保留安全區，check_publish 等資料、字型與版面穩定後量測。

## 平台 OAuth 連結（metaoauth）

- 平台連線依序呈現 Meta、Threads、YouTube、TikTok、LINE 通知、jev。Meta／Threads 卡片頂部 `.oauth-account` 同列帳號名稱、IG 使用者名稱、狀態膠囊與台北到期時間；ready 已連結、pending 即將到期、neutral 未連結、failed 缺權限／失敗。缺權限列在 `.notice.danger.oauth-permissions`，權限名稱自然折行。
- 每張卡片保留次要「測試連線」，強制重新檢查；連結／重新連結為主要按鈕（Threads 只缺數據權限時改為次要，見 threadsdata）。多粉專時 `.oauth-page-choice` 用下拉與主要「使用這個粉專」取代連結按鈕。非內部 HTTPS 來源停用連結並顯示 `.notice.oauth-origin`，網址由 API 提供。
- 首次設定步驟與回呼網址已移到「設定教學」彈出視窗（見 guides），卡片上不再重複顯示；`.oauth-manual` 收合「手動設定（進階）」，保留原具名稱的憑證表單、遮罩、版本與密碼輸入。Threads 應用程式編號與密鑰直接顯示，其餘欄位收合。回呼結果僅使用固定中文 `.notice.success`／`.notice.danger`，移除結果網址參數，不保存權杖至瀏覽器。
- 採 P1-1 色彩與系統字體 Token、既有 control／card 圓角，零外部資源。控制列自然換行，網址與權限 overflow-wrap；1440／768／390px 不水平溢出。新增配對納入 check_ui_contrast，check_meta_oauth 驗證連結、選粉專、缺權限、Threads、非後台來源與教學。

## 平台設定教學視窗（guides）

- Meta、Threads、YouTube、LINE 通知卡片與 TikTok 卡片的標題列右側，在「測試連線」前各有一顆次要「設定教學」（jev 沒有），按下開啟站內彈出視窗，不開新瀏覽器分頁；卡片與頁面本身不得有 `target="_blank"` 連結（只有視窗內的後台超連結例外，見下方）。回呼網址與 Webhook 網址只在視窗內顯示與複製，卡片不重複。
- `.ideation-modal-backdrop > .guide-dialog` 掛在 body：`role="dialog"`、`aria-modal`、`aria-labelledby` 指向標題；標題列固定，右上次要「關閉」，內容 `.guide-body` 自行捲動。開啟時焦點在「關閉」，Tab 在視窗內循環，Esc、關閉、點遮罩都能關閉，關閉後焦點回到「設定教學」按鈕。390px 滿版（無遮罩邊距、高度 100dvh），內容可捲動且不水平溢出。
- 內容在 `frontend/src/platformGuides.ts`，寫給第一次碰開發者後台的人（guides2 改寫）：每份教學有預估時間 `minutes`、「開始前你需要」`needs`、可收合的「名詞小辭典」`glossary`，以及分節步驟；每步只做一件事，按鈕與選單用「」標出實際介面用語，不確定時附「（英文介面為 …）」。步驟可帶 `check`（「✅ 完成後會看到」，`.notice.success`）與 `trouble`（「⚠️ 常見問題」，`.notice.warning`）。Meta 分「Facebook 粉專」「Instagram」「連結帳號」三節。除 TikTok 外最後一步都是「回到工作檯…」：Meta、Threads、YouTube 說明「已連結」與每小時同步，LINE 說明「測試連線」「連線成功」。
- 視窗開頭 `.guide-intro`：「大約需要 N 分鐘」、「開始前你需要」清單與預設收合的 `details.guide-glossary`（「名詞小辭典」）。步驟 `.guide-steps` 用小方塊編號（`::before` 計數，跨小節連續）；網址或權限以 `.guide-copy`（`<code>` 加次要「複製」，成功顯示「已複製」）呈現，回呼網址取自 `/api/oauth/status` 的 callbacks，LINE Webhook 網址取自設定的 WEBHOOK_PUBLIC_URL，未設定時顯示「尚未設定」並停用複製。步驟可帶 `links`，在 `.guide-links` 列出直達平台後台的超連結（developers.facebook.com、console.cloud.google.com、manager.line.biz、developers.line.biz、developers.tiktok.com 等），`target="_blank"`、`rel="noopener noreferrer"`。內容不放真實帳號、姓名或本機路徑。
- TikTok 卡片與 YouTube 相同排版（`.connection-card`）：帳號列與狀態膠囊、「存取權杖自動換發」說明、refresh token 的台北到期時間；Client key／Client secret 兩個憑證欄位直接列在卡片（無「手動設定」收合），未設定前「連結 TikTok 帳號」停用；已連結時 secondary「中斷連結」經 ConfirmDialog 說明會刪除已同步資料、不影響 TikTok 上的影片。卡片最後一列 `.notice.tiktok-comments`「留言（選用）」說明讀留言需要公司身分。教學帶使用者在 Sandbox 建立應用程式並連結，回呼網址與四個權限各自可複製；範圍見 `docs/TikTok規劃.md`。
- 配色只用既有 Token：內文與開頭資訊 text-main／bg-surface，辭典說明 text-subtle／bg-surface，網址區塊與「常見問題」text-subtle／bg-subtle，「完成後會看到」state-success／bg-subtle，步驟編號 bg-surface／brand-primary；圓角 control／card；零外部資源，已納入 check_ui_contrast。檢查見 `check_platform_guides.py`（五份教學的標題、開始前需要、確認點、辭典展開、複製、Esc／遮罩／關閉、焦點還原、卡片無新分頁連結與視窗內後台連結的網域及 `target`／`rel`，三種寬度下展開辭典仍無水平溢出、捲到底看得到最後一步且標題列固定；截圖 `.runtime/guides2-screens/`）與前端 `platformGuides.test.mjs`。

## 貼文數據立即同步（metricsync）

- 管理員／行銷的貼文數據頁首以 secondary「立即同步」取代「重新整理 ↻」，排一輪貼文與成效同步；檢視者仍只有「重新整理 ↻」（只重讀工作檯資料）。執行中顯示「同步中…」、已排入顯示「已排入同步…」，冷卻中顯示「立即同步（N 秒）」並停用，秒數以後端 `retry_after` 為準。完成後自動重新整理並以 sync-notice 告知；每小時排程跑完不自動重新整理。

## 貼文數據成效面板寬度（metricwidth）

- 2026-10-23 起由下方 postcenter 取代：成效改放中間。原規則：桌面單篇詳細右側成效面板（`.post-metrics`）固定 380px，左側列表 320px、中間留言欄自動。數據快照表沿用每格 16px 文字內距，抓取時間「2026/10/21 13:04」與指標欄名在 1440px 寬都排在同一行；百萬級數字時抓取時間可在日期與時間之間換行，但不可拆開日期或水平溢出。

## Threads 貼文數據（threadsdata）

- 貼文數據的 Threads 分頁與 FB／IG 行為一致：貼文清單與發文日期篩選、單篇「貼文成效」與唯讀「留言與回覆」（留言日期、顯示更多同其他平台）；管理員／行銷同樣有「抓取留言」「完整重抓」「停止」，留言同步卡標題為「Threads 回覆」。沒有新增控制項、小標題或說明列。
- 成效只顯示 Threads 有的六項，依序「觀看、按讚、回覆、轉發、引用、分享」（回覆即 comments 欄位，轉發與引用讀快照 extra_json）；觸及與收藏不顯示。數據變化曲線的指標下拉為同六項、預設「觀看」，快照表欄位為「抓取時間、觀看、按讚、回覆」。「—」代表平台尚未提供，0 代表平台回傳零；FB／IG 維持原六項與欄位。
- 設定頁 Threads 卡片：已連結且發佈權限齊全，但缺少 `threads_manage_insights`、`threads_read_replies`（既有連結尚未取得）時，`.oauth-account` 下方顯示 `.notice.warning.oauth-permissions`「需要重新連結以取得數據與回覆權限」，狀態膠囊維持「已連結」，連結按鈕「重新連結」改為 `.secondary`；發佈不受影響。取得權限後提示消失，按鈕回到主要。缺少發佈權限時仍為 `.notice.danger` 與主要按鈕。
- 主題發想的貼文選單：期間內有 Threads 貼文時才多一個「Threads」頁籤（FB／IG 頁籤不變），貼文列平台膠囊為「Threads」，第 3 步摘要在 IG 後附「、Threads N 篇」；沒有 Threads 貼文時畫面與先前相同。
- 回覆讀取等待時顯示 Threads 文字（「Threads 暫時限制呼叫…」「Threads 回應逾時或暫時錯誤…」），不顯示 Meta 用量。
- 只用 P1-1 色彩與系統字體 Token、control／card 圓角，零外部資源；權限提示的 text-subtle／bg-subtle 已列入 check_ui_contrast。check_posts_batch2（Threads 分頁清單、指標名稱、回覆，1440／768／390px）、check_meta_oauth（重新連結提示）、check_ideation_fixes（Threads 頁籤）與 check_followers_frontend（Threads 分頁會讀貼文清單）覆蓋，沒有新增檢查入口。

## 成員與角色權限（members）

本節覆蓋舊版設定頁籤與非管理員唯讀設定的呈現規則。管理員的設定頁籤依序為 AI、平台連線、訊息分類、工作區、成員、我的帳號；其他角色依功能權限顯示（平台連線＝`connections.manage`、AI＝`ai.manage`、訊息分類與工作區＝`settings.manage`，成員只限管理員），行銷與檢視者僅呈現「我的帳號」，書籤連至其他設定時亦顯示此頁籤。側欄品牌選單只列可存取品牌；沒有品牌的非管理員顯示「尚未指派品牌，請聯絡管理員」。手機保留 `.mobile-logout`。

- 成員編輯的角色改為 `fieldset.member-role-options` 單選清單：每列原生 radio，名稱（字重 600，作為 radio 名稱）下方 text-subtle 小字列出可做的事（`aria-describedby`）；內建三種在前，自訂角色在後。成員清單下方 `.member-roles` 為「角色」區：`.role-row` 排列名稱（內建加 neutral「內建」徽章）、權限摘要、「N 位成員」，自訂角色另有 secondary 編輯／刪除（仍有成員時刪除停用並以 title 說明）。新增／編輯角色沿用 `.member-dialog`：角色名稱與「可使用的功能」勾選清單，勾「送出、重試與取消發佈」會一併勾「編輯發佈草稿」，取消後者也取消前者。發佈頁沒有 `publish.submit` 時以 muted 文字取代「發佈／排程」按鈕，並隱藏取消排程、重試與重新套用按鈕。
- 成員頁使用 `.section-card.members-card`，標題列右側一顆「新增成員」primary；`.list-box.member-list` 內的 `.list-row.member-row` 排列名稱／帳號、角色、品牌、狀態及 secondary 編輯。名稱字重 600，帳號 text-subtle；品牌逗號列出、單行省略並提供完整 title。狀態採 ready／neutral／pending。390px 名稱與角色同列，編輯置右，其餘自然換行。
- 新增與編輯沿用既有 modal 外框，`.member-dialog` 具 dialog／aria-modal、標題關聯、Esc、Tab 焦點循環與關閉後焦點還原。角色使用 `.member-role-options` 單選清單；非管理員顯示品牌 checkbox，單一品牌預設勾選。管理員隱藏品牌 checkbox，顯示「管理員可存取全部品牌」。
- 提交用 primary，取消／複製／重設密碼／啟用用 secondary，停用用 primary danger 並經 ConfirmDialog 二次確認。保護規則錯誤用 `.notice.danger`，不使用 window.confirm。每個提交區塊只放一顆主要提交按鈕。
- 我的帳號密碼表單後，管理員多一段 `.recovery-code`：h3「密碼復原碼」與狀態膠囊（已設定 `.ready`／尚未設定 `.neutral`）同列，說明、「確認目前密碼」欄位與 secondary「產生復原碼／重新產生復原碼」。成功後沿用 `.member-dialog` 與 `.temporary-password` 顯示一次復原碼，secondary 複製與「我已保存」。
- 登入頁在「限已授權的團隊成員使用」下方放收合的 `.login-forgot`「忘記密碼？」：成員說明、展開後才渲染的管理員復原碼表單（管理員帳號、復原碼、設定新密碼兩次、primary「重設密碼」；標籤不和登入表單重名）、無復原碼時的主機指令 `.login-command` 與鎖定提醒。成功後以 `.notice.success` 取代表單，不自動登入。
- 臨時密碼對話框使用 `.temporary-password`、ui-font-mono，提供 secondary 複製，顯示「只會顯示這一次，請轉交給對方；對方第一次登入時需改密碼」。關閉清除記憶體中的值，不保存在網址或瀏覽器儲存。
- 我的帳號以同一列顯示帳號、名稱、角色、可存取品牌，下方先是 `.language-picker.account-language`「介面語言」下拉（選項以各語言自己的寫法顯示，選了立即存到帳號並重新整理），再是三個密碼欄位與一顆主要「變更密碼」。登入頁在 `.login-panel` 右上角放 `.login-language` 同款下拉（手機改在表單上方靠右），登入前只記在 localStorage，登入後若帳號沒有語言偏好就把它存到帳號。須改密碼時顯示 `.password-required` 全頁「請設定新密碼」，只有表單與登出，無側欄／底部導覽；成功後才進入工作檯。
- 檢視者的主題發想保留品牌選擇、既有列表與卡片，隱藏發想表單、編輯、還原、查看腳本、建立／開啟發佈草稿及刪除；腳本仍可從「腳本版本」列表檢視。所有角色限制同時由 API 執行。

新增樣式只引用 P1-1 色彩、系統字體與 ui-radius-control／ui-radius-card；不載入外部資源。1440／768／390px 無水平溢出，新增文字底色配對納入 check_ui_contrast。

## 全站統一第二輪（uniform2）

本節覆蓋 uniform 第一輪的按鈕與工作區收合規則；僅改呈現，API、文字語意及權限沿用。

- 工作區五群組各是一張 `details.workspace-group.section-card`，整列 summary 可點，section-title／600，右側展開圖示。summary／內容使用 panel-padding；外層不重複內距。展開內容用 `.workspace-subsection` 與 h3，標題下 12px、小節間 24px，可用 border-subtle 分隔；卡片之間 24px，與開機自動啟動一致。獨立表單保留各自提交，不以整個群組限制主要按鈕數。
- 核取方塊列與下一個欄位標籤至少 16px，套用設定區所有同類列，主題發想既有內容區幾何不變。
- 貼文清單使用 `.post-items.list-box` 外框；每個 `.post-card.list-row` 的 `.post-card-meta` 同列平台膠囊、帳號與類型，內文最多兩行、日期 text-subtle。列間 1px border-subtle，選中為 bg-subtle／左側 3px brand-primary 色條；列本身不另成圓角卡片。分頁在容器外下方，發文與自訂日期篩選保留。
- 粉絲數年／月／週採精簡工具列，1440px 下拉與數字同列，768／390px 下拉一列、數字一列。週次顯示「第 N 週」，完整日期保留在選項 title；選單所有選項須容納文字、內距及原生箭頭，不只檢查元素 scrollWidth。
- 390px 全域 `.mobile-settings-controls` 位於主內容最上方、所有 h1 之上，保留 `.mobile-brand-picker` 與 `.mobile-logout` 行為／viewer 登出。底部目前頁使用 aria-current="page"、brand-primary 實心／bg-surface 白字／opacity 1；保留 enabled，重複點擊不重置目前頁，hover 與選取當下保持同底色。
- 手機貼文明細、成效與留言卡片以容器 16px gap 排列，移除疊加的上下 margin；桌面卡片間 24px。
- 平台憑證保留具名稱的 form，`.credential-heading` 第一列 label（`.credential-name`＋`.credential-env`），第二列 `.credential-status`（狀態膠囊＋遮罩＋右側更換／設定）。手機名稱不斷字，環境變數可折行；展開輸入與密碼行為不變。
- 動作按鈕採實心 primary；取消、返回、分頁、移除等次要動作採 quiet。只用 P1-1 色彩／系統字體與 control／card 圓角 Token，不載入外部資源。新增配對納入 check_ui_contrast。

主題發想內容樣式不改；手機共用品牌列會改變整張畫面，與整張截圖零差異的要求衝突，實際像素與幾何比較在 uniform2 報告列出。


## Obsidian 留言與主題操作（obsidian）

- 工作區 → 資料加入 `.obsidian-settings`，單一欄位「Obsidian 留言資料夾」與 `.obsidian-actions` 的「儲存 Obsidian 資料夾」「立即同步到 Obsidian」實心 primary 按鈕；名稱與匯出資料夾的儲存動作區分。僅管理員可檢視與操作，其他角色只見「我的帳號」；載入或操作中停用，結果沿用 status／alert，控制列自然換行。
- `.ideation-card` 左上 `.idea-card-heading` 放序號（`.idea-number`，text-subtle）及舊資料的「已重新生成」「延伸自 #序號」標記；不再有選取 checkbox，卡片區頂端也沒有批次動作列。
- 底部 `.idea-card-actions` 只放 secondary：有腳本時先「查看腳本」，再「建立發佈草稿」（已有未發佈草稿時為「開啟發佈草稿」），間距 8px、靠左、flex-wrap。可還原時顯示獨立 secondary「還原上一版」，沒有省略選單。
- 重新生成與延伸主題已移除：卡片沒有進度、骨架或失敗提示；報告 JSON 裡舊的 ideas_job 只保留在資料中，不影響畫面，舊報告的「已重新生成」「延伸自 #序號」標記仍顯示。報告處理中時停用卡片動作與刪除。
- 貼文留言範圍增加「全部」；沒有範圍參數仍預設近 30 天，來源留言連結預設近 90 天，明確 comment_range=all 才選全部，重整保留所選範圍。只有全部範圍顯示次要「完整重抓」，確認後送 full_rescan=true。一般抓取與立即發想採增量；首次抓取讀到底。原 7／30／90 天與顯示更多仍保留。
- 全部沿用 P1-1 的色彩／字體與 control／card 圓角 Token，390px 無溢出；新增文字底色配對納入 check_ui_contrast。check_ideation_fixes、check_workspace、check_comment_sync_frontend 覆蓋操作與手機，既有隔離檢查入口數量不變。

## 主題建立發佈草稿（ideadraft）

- 主題卡片右上 `.idea-card-tools` 只有 secondary.small「編輯」，非 ready 或正在編輯時停用，檢視者隱藏；底部 `.idea-card-actions` 見上。既有未發佈草稿改顯示「開啟發佈草稿」，直接開啟。兩組均 flex-wrap，窄卡片自然換行。
- 點編輯後 `.idea-editor` 就地替換主題內容，五個具標籤欄位依序標題、開場、切角、可拍畫面、關鍵字，各最多 1000 字、不可空白；底部 primary 儲存、secondary 取消。儲存後標籤列顯示 `.ideation-chip.idea-edited`「已編輯」，原話保持可讀；secondary 還原上一版沿用 history，Markdown／Word 重新匯出使用編輯後內容。
- 「建立發佈草稿」直接建立草稿並開啟發佈頁，沒有確認對話框與「參考腳本」勾選，也不呼叫 AI；草稿主文案是標題、開場與 hashtag 的初稿。
- 建立後切至同品牌發佈頁的「新增貼文」，載入指定草稿；頂部 `.notice.success` 顯示「已從主題建立草稿，請上傳影片並確認平台」。草稿 ID 保存於網址 `publish_post_id`，重整仍載入；載入期間停用編輯及自動儲存。
- 發佈紀錄／排程中的 `.publish-record-heading` 在格式膠囊旁同列放 `.publish-source`「來自主題」，不另增說明列。預覽使用 text-main／bg-surface、body 字級；來源使用 text-subtle／bg-surface、help 字級；成功提示沿用 notice 的 state-success／bg-subtle。全部採 P1-1 Token、既有 control／card 圓角與本機資源，1440／768／390px 無水平溢出。
- 發佈紀錄清單上方一列 `.publish-presence`：左側 text-subtle／help 字級「上次檢查：<台北時間>」（取各平台結果最近的 presence_checked_at，沒有則「尚未檢查」），右側實心 `.primary`「檢查平台貼文」（使用者指定實心，為此分頁唯一主要按鈕；檢視者隱藏）。檢查中按鈕顯示「檢查中…」並停用；完成後以 `.notice.success`／`.notice.warning` 顯示「已檢查 N 篇，M 篇已在平台刪除」，有無法判定的平台時用 warning 並附中文原因，429 以 `.notice.danger` 顯示「剛檢查過，請稍後再試」。各平台結果 `deleted_at` 有值時膠囊為 `.status-badge.neutral`「<平台> · 已在平台刪除」，不顯示「查看貼文」，改顯示「偵測於 <台北時間>」；清單列整篇成功且成功平台全部刪除時，狀態膠囊改為 neutral「已在平台刪除」，只有部分刪除則維持原狀態並加「· 部分已刪除」。已刪除的平台仍算成功，不會被重試或重新排程重送。只用既有 Token，1440／768／390px 無水平溢出。

- composer1（改版 1／3）僅新增後端：既有發佈頁保持原版型，API 額外回 platform_options、effective_platform_options、warnings 與串文進度；前端後續改版再將平台影片選項、逐段預覽及提示併入既有區塊，不新增說明列。本輪沒有新增文字／底色組合或按鈕，不需擴充對比斷言；既有 390px 與按鈕三層規則維持。

## 色彩與字體 Token（P1-1）

色彩與字體集中於 `frontend/src/style.css :root`，CSS 與 inline／SVG 使用 Token；不載入外部字體、CDN 或遠端 `@font-face`。預設內文／標題使用 `--text-main`，品牌面才使用 `--brand-primary`。字級、尺寸、間距及圓角 Token 維持原值。

| Token | 定義 | 用途 |
|---|---|---|
| `--bg-app` | `#F8FAFC` | 全站畫布 |
| `--bg-surface` | `#FFFFFF` | 卡片、控制項、反白字 |
| `--bg-subtle` | `#F1F5F9` | 淡底、hover、選取列 |
| `--border-subtle` | `#E2E8F0` | 邊框與分隔線 |
| `--brand-primary` | `#0F3A2E` | 側欄、主要按鈕、深色選取列 |
| `--brand-accent` | `#10B981` | 僅互動高亮、選取、成功裝飾 |
| `--text-main` | `#0F172A` | 內文與標題 |
| `--text-muted` | `#64748B` | 白底／畫布上的輔助文字 |
| `--text-subtle` | `#475569` | 淡底上的文字與中性標籤 |
| `--state-pending` | `#F59E0B` | 待處理、警告裝飾 |
| `--state-pending-text` | `#B45309` | 待處理、警告文字／邊線 |
| `--state-pending-bg` | `#FEF3C7` | 警告淡底 |
| `--state-danger` | `#B91C1C` | 錯誤、需修改、危險動作、紅燈 |
| `--state-danger-bg` | `#FEE2E2` | 錯誤淡底 |
| `--state-success` | `#047857` | 成功、已回覆文字、綠燈 |
| `--state-success-bg` | `#D1FAE5` | 成功淡底 |
| `--state-info` | `#1D4ED8` | 處理中標籤 |
| `--state-info-bg` | `#EFF6FF` | 處理中淡底 |
| `--sidebar-text` | `#F8FAFC` | 深色品牌面文字 |
| `--sidebar-muted` | `#CBD5E1` | 深色品牌面輔助文字 |
| `--sidebar-border` | `#94A3B8` | 深色面控制項邊線 |
| `--sidebar-selected` | `color-mix(in srgb, var(--brand-primary) 85%, var(--bg-surface))` | 側欄選取／控制項底 |
| `--brand-hover` | `color-mix(in srgb, var(--brand-primary) 88%, var(--bg-surface))` | 主要按鈕 hover |
| `--focus-ring`、`--link-color` | `var(--state-success)` | 焦點與連結；亮綠不足對比時使用深綠 |
| `--list-red`、`--list-green`、`--list-black` | danger／success／text-main 別名 | 名單圓點與框線 |
| `--media-letterbox` | text-main 別名 | 發佈預覽影片與框比例不同時的補邊 |
| `--chart-line`、`--chart-point`、`--chart-intent` | success／info／pending-text 別名 | 圖表獨立線色、點色、意圖長條 |
| `--ui-font-family` | `system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif` | 全站系統無襯線字體，標題依字重區分 |
| `--ui-font-mono` | `ui-monospace, Consolas, "Cascadia Mono", Menlo, monospace` | 需要等寬時使用的系統字體 |

舊名保持別名：`--ink:var(--brand-primary)`、`--paper:var(--bg-surface)`、`--line:var(--border-subtle)`、`--muted:var(--text-muted)`。`--accent:var(--state-pending-text)` 僅為相容別名，新樣式不得引用；既有引用已全部依語意替換。

綠色只表示互動與成功；警告用琥珀色，錯誤、需修改與危險用紅色。焦點外框使用達到 3:1 的深綠，連結與成功文字達到 4.5:1；亮綠不得當白底小字。淡底中性標籤使用 `--text-subtle`，避免輔助文字在淡底不足 4.5:1。`transparent` 與 `currentColor` 保留 CSS 的透明／繼承語意；其餘衍生色由 `color-mix()` 引用 Token。

主要組合的 WCAG 2.1 對比（依上表數值計算，供調整 Token 時參考；以 `check_ui_contrast.py` 實算為準）：

| 文字 | 底色 | 對比 | 備註 |
|---|---|---|---|
| `--text-main` | `--bg-surface` | 17.85:1 | |
| `--text-muted` | `--bg-surface` | 4.76:1 | |
| `--text-muted` | `--bg-app` | 4.55:1 | 接近 4.5 下限，不可再調淡 |
| `--text-subtle` | `--bg-subtle` | 6.92:1 | 淡底文字改用此 Token 的原因 |
| `--bg-surface` | `--brand-primary` | 12.61:1 | 主要按鈕、側欄 |
| `--state-pending-text` | `--state-pending-bg` | 4.51:1 | 接近 4.5 下限 |
| `--state-success` | `--bg-surface` | 5.48:1 | 連結、焦點、成功文字 |
| `--state-danger` | `--state-danger-bg` | 5.30:1 | |

驗收使用 `scripts/check_ui_contrast.py` 從 CSS 讀取 Token 計算 WCAG，文字門檻 4.5:1、圖示／焦點／圖表門檻 3:1；`check_ui_scale.py` 另檢查實際計算字體、狀態標籤對比、紅燈／警告／錯誤 Token 與零外部請求。

## 行銷導覽與 DOM（nav）

預設儀表板。桌面側欄與手機底部均恰好四項，依序為儀表板、貼文數據、主題發想、設定。設定以 `.settings-hub` 包含唯一 PageHeader「設定」、`.settings-tabs` 與四個 tabpanel，依序為 AI、平台連線、訊息分類、工作區；原頁首移除，內容、品牌欄位及角色權限沿用。手機品牌選擇與登出使用全域 `.mobile-settings-controls` 同列，在所有頁名上方，不夾在設定分頁下方，不再提供更多選單。沒有收件匣計數、對話選取、回覆區、未儲存對話提示或成交進度跳轉。主題發想既有報告原話仍呈現文字，公開留言可定位回貼文；來源選取遵循下方 ideaui 規格。


設定分頁使用 tablist／tab／tabpanel，id、aria-controls、aria-labelledby 相連，aria-selected 與 roving tabindex 維持單一 Tab 焦點；左右鍵循環，Home／End 切首末頁。選取為 primary，其他為 quiet；沿用色彩、字體與 control 圓角 Token。四分頁等寬並對齊內容，390px 不溢出。非作用面板 hidden，內容沿用原頁切換的卸載行為。

第一次由導覽進入設定預設 AI；`view=settings&settings_tab=ai|connections|policy|workspace` 保留最後分頁，重新整理、切至其他頁後返回與 popstate 均恢復。舊 `view=ai`、`view=policy`、沒有 settings_tab 的 `view=settings` 分別導向 AI、訊息分類、工作區；非法 settings_tab 回 AI。保留 brand_id、ai_tab、其他網址參數與 hash。工作區捷徑改切設定分頁。

`check_view_refresh` 驗證四項導覽、四分頁、鍵盤循環、網址／重整／舊連結、單一標題、手機品牌登出及 390px；`ui_navigation` 統一經可見導覽及分頁操作。`check_ui_scale` 維持原六種內容情境的尺寸、文字、內距驗證；手機品牌／登出改驗設定頁控制項。新增配色組合納入 `check_ui_contrast`。

儀表板保留 KPI、客人正在問什麼、趨勢、排行與右上角匯出；意圖分布獨占原雙欄所在列，成交進度已移除。AI 設定保留行銷內容指示的版本編輯，移除回覆 prompt 組裝／預覽。工作區保留公開留言緊急通知、匯出、品牌、例會與自動啟動，移除私訊回補。

## 工作區開機自動啟動（autostart）

- 開機自動啟動（uiorder 起）放在「系統」群組內、收訊健康監測之前：`.settings-section.workspace-subsection.autostart-settings`，不再是工作區最上方的獨立卡片；包含 h3「開機自動啟動」、`.autostart-row` 的原生 checkbox／label「登入 Windows 後自動啟動工作檯」與同列狀態，以及一行登入條件說明。卡片以 aria-labelledby 連結標題，操作中 aria-busy；不增加儲存按鈕。
- 預設沒有排程即關閉；載入完成前停用，僅管理員可檢視與切換。工作區 status 與 autostart GET／PUT 均限管理員，其他角色不掛載此卡片。處理中停用並顯示「處理中…」，成功採用後端狀態；錯誤使用繁體中文 alert，連線失敗另讀實際狀態，讀取失敗停用並顯示未知狀態。非 Windows 顯示「僅支援 Windows」並停用。
- 小節沿用群組卡的外框與圓角，使用系統字體；文字 text-main／bg-surface、說明與狀態 text-muted／bg-surface、錯誤 danger／danger-bg、勾選 brand-primary。納入 check_ui_contrast；390px 同列資訊可換行，不水平溢出。check_workspace 使用替身檢查四個狀態、唯讀、不支援與連線失敗，1440×900／390×844 最新截圖在 `.runtime/check-output/check_workspace/`。

## 主題發想第二輪（ideapolish）

- 第一步 `.ideation-source-fields` 同列品牌、開始時間、結束時間：桌機三等分、768px 兩欄換行、390px 單欄。步驟標題使用 section-title／600，序號為 24px 品牌底白字圓標，間距 8px；步驟間 32px，標題下 12px。
- `.ideation-platform-tabs` 為底線式 tablist，Facebook／Instagram 附篇數；預設較多貼文的平台，零篇停用，方向鍵與 Home／End 選取可用頁籤。跨頁保留勾選，三態全選只作用目前平台；摘要同列列出全部 FB／IG 選取篇數與留言範圍。
- 貼文列 `.ideation-post-row` 包含可點選 label 與獨立展開鈕；aria-expanded／aria-controls 連結留言預覽。只讀已存留言，依目前範圍最新在前，每批 20 則；作者遮蔽、正文 redact，顯示台北時間與「載入更多」。切換範圍重載、卸載取消過期請求，不抓取平台。
- 第三步摘要在 `.ideation-execution-row` 上方，左側執行方式約 320px，右側立即發想 primary／重新標註 secondary quiet，控制項 40px 並底線對齊，覆寫 primary 上邊距；手機自然換列。
- 提示框 `.ideation-notice` 使用 bg-subtle／text-subtle、左側 3px border-subtle；警示與品牌覆核用 state-pending 色條。control 圓角、12px 16px 內距、help 字級、上下 12px。未產生的 Markdown／Word 為兩個 chip。
- 類型分組上 40px、標題下 16px。卡片按鈕一律共用 `.secondary`，`.secondary.brand` 已移除。
- 動作列與報告列表每秒顯示階段及「已執行 m:ss」，完成／失敗停時計時，報告標題列顯示耗時。UTC started_at／comments_synced_at／finished_at 來自報告 JSON，重整續算；舊報告無欄位則不補造時間。前端與新匯出不呈現「全部主題與代表原話」，資料及卡片原話保留。
- 所有色彩／字體沿用 P1-1 Token；新增配對納入 check_ui_contrast，check_ideation_fixes 驗分頁、預覽、計時、重整、尺寸與無外連，check_ui_scale 同步驗新尺寸及提示內距。

## 儀表板與快照曲線（P1-2）

tmpclean 僅調整驗收檔案位置，DOM、呈現、Token 與既有斷言不變。儀表板截圖改存 `.runtime/check-output/ui_dashboard/`，其他頁面依入口腳本命名；每次執行僅保留最近一次。退休回覆控制項由 `check_polish_frontend` 驗證，不依賴歷史截圖基準。

- 兩張 KPI 依序為「本週新留言」「最多人問的類別」，合併原新訊息／新留言重複指標。期間沿用台北週一 00:00 至現在，只計公開留言串的客人入站訊息；熱門類別取本週留言最新且指紋有效的分類，排除 spam，中文類別與則數同列，無有效分類顯示「尚無資料」。`.dashboard-kpis` 直接包含兩張 `section.kpi`，共用 `--bg-surface`、`--border-subtle`、`--ui-radius-card`；數字為 page-title／600，類別與空值為 section-title。桌面等寬兩欄、390px 單欄；除下方成長比較一行外不增加說明列。
- 頁首 `PageHeader` 操作區並排「匯出報表」與「重新整理 ↻」，保留頁首下方期間說明。匯出按鈕只對 `canExport` 顯示，不再占用內容區卡片。
- 匯出以原生 `.inbox-dialog.report-export` 呈現，包含 `.sheet-heading` 與 `.sheet-content`；日期預設、限制、提示、錯誤與下載請求／檔名沿用既有規則。下載中停用下載按鈕；關閉、Esc 與背景點擊均關閉並恢復觸發按鈕焦點，Tab 留在對話框。
- 問題分布長條使用 `--brand-primary` 與 `--bg-subtle` 軌道，沿用原統計及點擊行為；區塊空資料沿用 `.empty-data`。
- KPI 下方的 `.dashboard-card.dashboard-trend` 顯示「每日趨勢」，標題右側 7／30 天選擇預設 30，選取為實心 primary、次要為 quiet；`trend_days` 網址參數保留重新整理與導覽狀態。品牌切換、重新整理與每 15 秒輪詢讀取 `/api/dashboard/trends`，卡片錯誤不影響其他摘要。
- 趨勢使用純 SVG 的 620×220 viewBox，ResizeObserver 補償軸文字到 minimum Token；只保留新留言長條與左側留言軸。30 天每五天標一次 MM/DD，7 天逐日標示；單日置中。全零時顯示「累積留言後會顯示每日趨勢」，不畫軸。
- `.trend-day` 採單一 Tab 焦點，左右鍵逐日、Home／End 到首末日，深綠外框顯示焦點；滑鼠與焦點共用 `.trend-tooltip`，只含日期與新留言數。圖下單行圖例為「長條＝新留言 · 台北時間」，手機自然換行，390px 不水平溢出。
- 長條用 `--brand-primary`，白底圖形對比 ≥3:1。軸與圖例用 text-muted／bg-surface，提示用 text-subtle／bg-subtle，錯誤用 state-danger／state-danger-bg，圓角與字體沿用共用 Token；配對納入 `check_ui_contrast.py`。`ui_dashboard.py` 驗證有資料、空資料、切換、網址、焦點、提示、錯誤隔離與手機尺寸。
- 成長比較（2026-10-16）：「本週新留言」數字下方一行 `.kpi-compare`（text-muted、help 字級）「比上週同期增加／減少 N%（小於 10% 保留一位小數）· 上週同期 M 則」，相同為「與上週同期持平」，上週同期為 0 時「上週同期沒有，無法比較」或「上週同期也沒有」，不用紅綠色暗示好壞。每日趨勢圖例下方 `.trend-compare` 同規則顯示「近 N 天共 X 則 · 比前 N 天…（前 N 天 Y 則）」。
- 轉換漏斗：趨勢卡下方 `.dashboard-card.dashboard-funnel`（region「轉換漏斗」），標題右側 7／30 天選擇與趨勢同款，`funnel_days` 網址參數保留狀態，輪詢、品牌切換、重新整理與錯誤隔離同趨勢。說明行「近 N 天發佈、有觸及數據的 K 篇貼文」；`ol.funnel-stages` 四列依序觸及人數、互動次數、留言、消費詢問，每列標籤與千分位數字同列，下方 12px `.funnel-track`（bg-subtle 軌道、brand-primary 長條，寬度以第一階為 100%，非零最少 2%），第二階起 `.funnel-rate`「上一階的 N%」，上一階為 0 時「上一階為 0，無轉換率」。卡底 `.funnel-note`（text-subtle）說明互動是次數、消費詢問的分類。沒有貼文時只顯示「近 N 天沒有提供觸及數據的貼文」。`ui_dashboard.py` 的 `check_growth_funnel` 驗證文字、長條比例、7／30 切換、網址、錯誤、空狀態、1440／390 無水平溢出。
- 受眾分析（2026-10-19）：漏斗卡下方 `.dashboard-card.dashboard-audience`（region「受眾分析」），標題下方六格平台分段（Instagram、Facebook、Threads、YouTube、TikTok、LINE；桌面一列六格最寬 640px，600px 以下三格兩列、滿寬），網址 `audience_platform` 記住選擇。各項以 `.audience-grid`（最小 260px 自動欄）排列：分布用 `--brand-primary`／`--bg-subtle` 的 8px 軌道長條，右側占比加 text-muted 人數；上線時段為 24 根直條，人數最多的三個時段用 `--brand-primary`、其他用 `--text-subtle`，下方列出台北時間高峰。缺資料的項目、TikTok 與 LINE 以 `.audience-hint`（bg-subtle、help 字級）說明原因；平台共通說明用 `.audience-note`。
- 貼文縮圖：貼文清單有縮圖的 `.post-card` 加 `.has-thumb`，左側 56px 方形 `.post-thumb`（object-fit cover、control 圓角）跨三列，平台膠囊、內文、日期在右欄；無縮圖的卡片維持原樣。單篇介紹在類型行下方顯示 `.post-detail-thumb`（最寬 320px、最高 240px、contain、card 圓角）。儀表板排行在名次後顯示 48px `.rank-thumb`。圖片載入失敗即隱藏，不顯示破圖。
- `MetricChart` 保留純 SVG，空陣列或全 null 不畫座標軸，以一行文字引導累積快照；單筆或相同時間將資料點置中，不產生 NaN 座標。指標缺值不跨段連線，軸標籤仍維持最低字級補償。

## AI 設定分頁（creds）

- 本機 CLI 已移除（nocli）：基本頁預設 AI 只列三個 API 供應者，沒有「尚未偵測」狀態。

- 用量沿用 `.usage-table > table > tbody > tr > td[data-label]`，桌面表格、390px 卡片。本機 CLI 已移除，但歷史紀錄保留：供應商名稱標為「（已停用）」，有數字（含 0）沿用「輸入 / 輸出」，兩者皆缺顯示「未回報」，單邊缺值僅該邊顯示「未回報」，美元估算一律「訂閱」；API 格式不變。表格下方的 `.muted` 費用說明不再提 CLI。文字沿用 text-main、說明 text-muted，搭配桌面 bg-app／手機 bg-surface，納入 check_ui_contrast，不新增樣式或控制項。

- 三個子分頁「基本」「品牌說明」「AI 金鑰」保留 tablist／tab／tabpanel、aria 關聯、單一 Tab 焦點、方向鍵、Home／End。非作用面板 hidden；分頁切換保留未儲存輸入。桌面等寬，390px 不水平溢出；主設定分頁同列。
- 基本放預設 AI、每月預算、用量。品牌說明沿用版本、差異與還原。AI 金鑰只含 Gemini、OpenAI、Anthropic，備援模型放對應供應商卡片下方；管理員保留驗證後儲存、更換及刪除金鑰。非管理員不讀金鑰 API，備援模型仍沿用原品牌權限。
- `ai_tab=basic|brand|keys` 可重整及 popstate 還原；舊 usage→basic、prompt→brand、advanced→keys，keys 回自己的位置；已移除的 cli 與非法值回 basic，保留其餘 query 與 hash。
- 金鑰 password 為 uncontrolled，不存 React state 或瀏覽器儲存。主動作 primary，次要 quiet。

## 平台連線（creds）

`.platform-connections` 放三張 `.settings-section.connection-card`：Meta（FB／IG）、LINE 通知、jev；標題列右方為實心「測試連線」。每欄 `.credential-field` 是有名稱的 form，`.credential-heading` 同列顯示環境變數名、DB／env／未設定來源與遮罩，`.credential-controls` 放 password 與儲存／取消，已設定時改顯示更換；僅 DB 值可移除。移除回 env；版本衝突清空機密輸入並顯示中文錯誤，重新整理取得新版本。測試連線僅測已儲存設定，送出空物件。

平台 API 與設定頁全部僅管理員；其他角色不顯示平台分頁、不發出憑證請求，只見「我的帳號」。末張 `.connection-endpoints` 唯讀顯示 WEBHOOK_PUBLIC_URL 及 meta-inbound、line-notify 兩條網址（line-inbound 已退役，不再顯示）；其下僅一段列出 .env 專屬名稱與原因，無實際值。所有 password 不讀回明文、不進瀏覽器儲存；Webhook 網址是特別允許公開複製的唯讀設定。

名稱／欄位用 text-main／bg-surface，遮罩 text-subtle／bg-surface，來源 success／success-bg，說明 muted／bg-surface，錯誤 danger／danger-bg；供應商淡底遮罩改 text-subtle／bg-subtle。圓角用 control／card Token，不載入外部資源；390px 以名稱與變數名為第一列、狀態／遮罩／動作為第二列，名稱不斷字，變數名可折行，無水平溢出。配對納入 check_ui_contrast。

## 工作區內容（creds）

`.general-settings` 上方保留目前品牌 label／select。下方五個原生 `details.workspace-group.section-card`，依序「品牌範本」「主題發想」「資料」「通知」「系統」（uiorder 調整順序），summary 是卡片標題列，內容在同卡的 `.workspace-group-content`，不得巢狀 section-card。data-group 為 ideation／data／notifications／system／brand，預設全部收合，展開不互斥，重整回收合。

主題發想含例會與主題；資料含 CSV、私訊回補、匯出；通知含通知政策；系統含開機自動啟動與接收健康；品牌範本含工作區名稱、範本預覽／套用與禁語。展開／收合保留輸入，品牌及角色權限不變，沒有舊單一進階設定與上班時間欄位。摘要使用 text-main／bg-surface、card 圓角與共用內距，卡片寬度對齊。

check_all_features 操作全部 16 欄的儲存、遮罩、重整、409、移除及四組連線成功／失敗替身；viewer 驗證平台唯讀。check_ai_resilience_frontend 驗三個子分頁（沒有本機 CLI）、未儲存資料、舊網址與鍵盤、舊 CLI 用量列及預設 AI；check_view_refresh 驗主四分頁；check_workspace 驗五分組預設收合及獨立開啟；check_ui_scale 保留各控制項原尺寸／文字／捲動驗證。

## 手動 AI 與預設 AI（ai-unify-2；本機 CLI 已於 nocli 移除）




- 預設 AI 在基本頁（「預設 AI（主題發想）」），只列三個 API 供應者；未設定顯示「請選擇 API 供應者」，舊 CLI 值視為未設定，選單寬度對齊所在區塊。三家 API 備援模型在 AI 金鑰，預算與用量在基本。
- 主題發想 `.policy-grid` 的執行方式使用原生 select，不分 optgroup：已設定的 API 供應者（不可用項停用並標「（未配置）」），最後是「交給 Agent 撰寫」。預設順序為可用的 `ideation-choice:<brandId>` 瀏覽器記憶、品牌預設 AI、第一個可用 API、交給 Agent 撰寫；CLI 記憶與預設值一律略過。選「交給 Agent 撰寫」時，報告停在「等待 Agent 撰寫主題」，`.agent-awaiting` 說明請在 Claude Code 用 /mwb:ideas，或在其他 Agent 使用 get_guide("ideas") 接手。資料載入前停用選單，避免品牌切換時沿用舊值；不新增說明列。

## 訊息分類（noinbox）

設定頁「訊息分類」分頁內有品牌選擇與一張 `.settings-section.intent-notes`；只有「類別說明」及九列 label／input。每欄最多 200 字，儲存為 primary；唯讀停用輸入並隱藏按鈕。409 保留輸入，品牌切換重新載入。分類門檻、轉人工、主管與路由設定已移除。

沿用 text-main／bg-surface、placeholder text-muted／bg-surface、danger／danger-bg、primary 及 control／card 圓角 Token；390px 欄位不溢出。補充說明只影響後續分類，不自動重算歷史。

## 主題發想選文、列表與卡片（ideadesign／ideaui）

- 同一張 `.ideation-form` 保留標題與原說明，內含三個 `.ideation-step`：「1 選擇貼文」「2 留言範圍」「3 產生」，小節相距 32px。品牌與開始／結束時間依 ideapolish 三／二／一欄排列；第 3 步保留執行方式、選文摘要及動作。欄位標籤 help／muted／500，與控制項相距 8px。
- 共用 `SegmentedControl` 使用 radiogroup／radio／aria-checked、單一 Tab 焦點；左右／上下鍵循環並選取，Home／End 到首末項。外框 surface／border-subtle、control 圓角、3px 內距，五段等寬、輸入框高度；整組 520px 且不超過父容器，390px 內部橫向捲動。未選 main／透明底、hover subtle；已選 surface／brand-primary／600。自訂日期下方 8px 出現兩個約 200px 日期欄與「～」。
- `.ideation-posts` 為帶邊框、card 圓角、最高 360px 的捲動容器；44px sticky 標題列同列放三態 checkbox、「已選 X / Y 篇」與範圍內留言合計。整列原生 label 切換選取，列間分隔線、hover subtle；平台 FB／IG 淡底標籤、單行省略內文、右側日期與範圍留言數。正數 brand-primary／600，零為 subtle；390px 右側資訊改放內文下方一行。無資料置中保留原空狀態。
- 摘要即時呈現全部 FB／IG 所選篇數與留言範圍；動作間距 12px。「立即發想」primary；「重新標註所選留言」使用 `.secondary.quiet`。共用 `.secondary` 在 style.css 定義 surface 底、border-subtle 1px 邊框、main 文字、hover subtle、button 高度與 control 圓角。
- `.report-row` 最低 48px，手機計時可換行撐高；白底邊框、control 圓角、列間 8px。選中為 subtle 底、左側 3px brand-primary 色條及文字 600。狀態膠囊完成 success、失敗 danger、進行中 pending-text，搭配各狀態淡底。刪除沿用 primary danger，改為 small button 32px／help 字級。
- 三個 `.ideation-goal[data-goal]` 標題左側 4px 色條依序 success／info／pending，題數同列。類型膠囊使用 success／info／pending-text 與對應淡底。卡片順序為標籤、兩行標題、`dl.ideation-fields` 的開場／切角／可拍畫面、關鍵字、收合原話、靠左次要動作；欄位 dt caption／muted、dd body，間距 12px。「延伸主題」膠囊 title「證據不足，依主題延伸」。卡片 padding 20px、grid gap 16px／stretch／等高，flex column 的動作 margin-top:auto；1440／768／390 分別三／二／一欄，不水平溢出。

- cwindow：開始／結束時間僅篩選貼文發佈期間，可選任意歷史貼文。第 2 步 `.ideation-comment-window.post-date-filter` 保留「留言範圍」group；內部共用分段控制項依序近 90／60／30／7 天、自訂日期，預設近 30 天。自訂才顯示 `.post-date-inputs` 的留言起日／留言迄日；title 說明台北時間與含起訖日，不另加說明列。
- 留言範圍列使用透明底色並沿用外層表單內距，不建立第二層卡片內距；其標籤、日期欄與上方 `.policy-grid` 左右對齊。尺寸檢查同時驗證零額外內距與文字距外層底色邊界。
- `comment_range`、`comment_from`、`comment_to` 保存在網址，重整及 popstate 恢復。自訂日期必填且起日 ≤ 迄日 ≤ 今天；尚未有效時停用發想／重新標註。留言範圍改變保留所選貼文，重新載入期間內計數；品牌／貼文期間變更才全選。每篇呈現「範圍內 N 則留言」，title 保留已存總數。
- 報告期間段落以 br 分兩行「貼文期間」「留言範圍」，顯示台北時間與不含結束時間；舊報告缺少 comment_range 時留言範圍沿用貼文期間。Markdown／Word 同樣保留兩行，無歷史資料回填。重新標註採用目前留言範圍與所選貼文。
- 貼文數據目前提供留言 7／30／90 天；手動抓取傳目前選項，原說明改為「按『抓取留言』只讀取目前留言日期範圍內的留言與回覆，完成後結束」。沒有新增動作或說明列。留言範圍的文字、日期、計數、實心選取底色沿用 P1-1 Token、control 圓角，納入 check_ui_contrast。

- no90：開始時間不限歷史長度，結束須晚於開始且不得晚於現在（後端保留五秒容差）。第 3 步 `.ideation-actions` 同列放 primary「立即發想」與 secondary quiet「重新標註所選留言」與操作完成時的 status；重新標註只送目前期間與勾選貼文，不依賴內容生成模型，未載入／未選文時停用。工作區不再提供全品牌重新標註。沿用 Token，390px 自然折行、無水平溢出。
- 報告及匯出前期提示為「前期有部分時間早於所選貼文發佈，變化僅供參考」。前期為留言範圍往前同長度，舊報告內容與既存比較標記仍可顯示，不回填歷史資料。

- 頂部「從留言發想主題」只使用所選貼文的客人留言。品牌與執行方式依三步驟分開；時間欄位沿用 `.policy-grid`，日期 label 的 title 說明台北時區及不含結束時間。`.ideation-posts` 內為三態全選 checkbox 與 `.ideation-post-list` 原生 checkbox 清單，平台、內文、日期與留言數依上述版型排列。品牌或期間改變後重新載入並全選；載入中、無貼文或未勾選時停用立即發想，空資料顯示「此期間沒有貼文」。
- 「主題列表」的 `.report-history > .report-row` 包含左側 `.report-select` 及右側小型 `primary danger` 刪除按鈕；禁止巢狀 button。選取列保留 `aria-current="true"`，清單約六列高度後內捲。pending／processing／syncing_comments 的刪除停用並附 title；viewer 不顯示刪除。抓取期間狀態顯示「抓取留言中」。
- `.ideation-modal-backdrop > .ideation-delete-dialog` 是置中自製 modal，具 `role="dialog"`、`aria-modal` 與文字標題關聯，開啟聚焦取消、Tab 循環、Esc／取消／背景點擊關閉並還原原按鈕焦點。確認文字為「刪除主題列表 #id？由此產生的腳本也會一併隱藏，已匯出的檔案不受影響。」刪除為危險色實心、取消為主要色實心；不使用 window.confirm。內容區不再有刪除或兩段式確認列。
- 刪除成功移除列，若刪除的是選取報告，選取下一份（末項改前一份）、清空腳本並同步網址；最後一份回空狀態。刪除其他列不影響目前閱讀。錯誤維持 alert，輪詢不得復活已刪除項目。
- `.ideation-goal` 依變現型／流量型／引流型排列，h2 顯示實際題數，`.ideation-grid` 內每題一張 `article.settings-section.ideation-card`。桌面三欄、1100px 以下兩欄、600px 以下一欄。舊報告照實際題數呈現，不強制補足。
- 卡片順序依 ideadesign 規則；題目 title 可讀完整文字，開場／切角／可拍畫面完整折行；原索引保留腳本對應。沒有 quote_ids 標示「延伸主題」。`.ideation-evidence` 置於所有卡片之後且預設收合，保留主題統計、備援標示與代表原話；不呈現退休預約欄位。
- 公開留言原話以連結定位貼文並保留返回報告／腳本參數；舊報告缺少可用公開來源時顯示原話文字與「來源已無法存取」，不再顯示退休來源類型文字。
- 報告與腳本共用 `.ideation-exports > .export-card`，保留 Markdown／Word 下載及不可用／錯誤狀態；不顯示磁碟路徑。報告匯出依三類分組，每題欄位順序與卡片一致，附佐證原話；不再附全部主題統計。
- 色彩與字體只引用 P1-1 Token；一般 chip 使用 text-subtle／bg-subtle，類型與狀態使用對應 state 淡底，日期 text-subtle／bg-surface、分類 text-muted／bg-surface，卡片與 modal text-main／bg-surface，刪除 bg-surface／state-danger，其餘實心動作 bg-surface／brand-primary。圓角為 control／card Token，不載入外部資源，390px 不水平溢出。配對由 check_ui_contrast 驗證。
- check_ideation_fixes 與 check_all_features 使用合成資料與替身，保留下載、來源定位、權限、表單保存、409／422、失敗與舊報告驗證，量測前等待資料與 DOM 掛載。chip／平台膠囊左右內距 8px、卡片 20px，ui_padding 依各容器用途量測；check_ui_scale 同時驗證 8px 正確內距通過與零內距失敗，不排除量測。

尺寸定義集中於 `frontend/src/style.css` 的 `:root`。新增或修改畫面時，使用下表共用變數；不在頁面、inline style 或 SVG 寫死字級及表單／按鈕高度。頁面框架樣式集中於 `frontend/src/ui-shell.css`，各頁保留自己的內容配置、捲動與操作功能。

| 變數 | 桌面值 | 用途 |
|---|---:|---|
| `--ui-font-page-title` | 26px | 頁面 h1、登入標題、大型統計數值 |
| `--ui-font-section-title` | 18px | h2／h3 區塊與對話標題 |
| `--ui-font-body` | 14px | 內文、欄位標籤、表格內容 |
| `--ui-font-help` | 13px | 說明、時間、提示與來源資訊 |
| `--ui-font-minimum` | 12px | 全站最低字級、緊湊徽章、圖表軸標籤 |
| `--ui-font-caption` | 引用 minimum | 緊湊中繼資訊 |
| `--ui-font-button` | 引用 body | 按鈕文字 |
| `--ui-font-conversation` | 16px | 訊息泡泡、回覆框、貼文留言正文 |
| `--ui-font-input` | 引用 body | input／select／textarea 文字 |
| `--ui-choice-size` | 16px | checkbox／radio 寬高 |
| `--ui-choice-line` | 1.5 | 選項標籤行高，換行仍對齊第一行 |
| `--ui-height-button` | 36px | 一般操作按鈕 |
| `--ui-height-button-small` | 32px | 篩選、資料來源切換、平台、階段及標籤按鈕 |
| `--ui-height-input` | 40px | 單行輸入框、下拉選單 |
| `--ui-height-reply-min` | 56px | 回覆框縮小時的下限 |
| `--ui-height-prompt-min` | 150px | 多行 system prompt 編輯框最低高度 |

> 已移除的歷史規格：
> 手機 `<600px` 時，`:root` 將 `--ui-font-input` 改為 `--ui-font-conversation`（16px）。回覆框在所有尺寸均為 16px。單行控制項仍高 40px；多行文字框依內容／rows 決定高度，保留既有拖曳功能與回覆區不超過對話欄 35% 的上限。

## 全站頁面框架

四個主頁使用 PageHeader，設定的三分頁共用一個頁首：桌面標題在左、頁面動作在右；手機可換列。桌面側欄 220px，內容起點 252px；外框、左右 padding 及頁首由 ui-shell.css 共用。主題發想使用相同框架，不另訂外框尺寸。

手機頂部 56px、頁首 152px，底部預留 --ui-mobile-nav-space（64px 加安全區）。內容可捲到固定導覽上方，接收健康警示出現時亦同。手機設定頁保留品牌選擇與登出，切回桌面改用側欄控制項，選取品牌不變。

頁面動作 primary、次要動作 quiet，表單及狀態沿用系統字體與色彩 Token。表格數字靠右、等寬數字；空資料與未知值不捏造零。控制項使用共用高度、字級及圓角；390px 不得水平溢出，不以裁切隱藏實際文字。

## 收訊健康橫幅與文字完整性

`--ui-health-banner-height`（72px）定義全站紅色收訊警示，位於頁面框架上方；工作區可用高度扣除此值，手機對話也保留橫幅可見。字級沿用 body，內距沿用 content-padding／shell-gap。回覆狀態不得 flex 收縮到文字行高以下；名稱與摘要可換行。

`check_ui_scale.py` 現在輸出至 `.runtime/dm-only/`：除了既有尺寸斷言，也檢查文字自身的 scrollWidth 與 overflow:hidden／clip 祖先裁切，包括省略號。刻意以 clip 隱藏的無障礙表頭不屬於可見文字，垂直捲動容器允許捲動閱讀。偵測器另以水平省略號、垂直 hidden 兩個負向案例驗證會失敗。三種尺寸逐一截圖行銷六頁、腳本、匯出、貼文留言與全站異常橫幅。


## 核取方塊與單選框

帶 checkbox／radio 的 label 使用共用橫向排列、左對齊。控制項寬高引用 `--ui-choice-size`，標籤字級引用 body、行高引用 `--ui-choice-line`；與文字的間距引用 brand-gap。長標籤在手機可換行，控制項對齊第一行文字。

`check_ui_scale.py` 逐一量測所有已呈現（包含可捲動區域）的 checkbox／radio，以 `input.labels` 找標籤、DOM Range 量測第一行可見文字，要求垂直中心差 ≤6px，控制項右緣不超過文字左緣。不存在可見文字標籤也視為失敗。另驗證 checkbox／radio 各自的直向錯排、左右顛倒與正確橫排，共 6 個偵測器案例。收尾截圖與報告見 `.runtime/polish/`。

## 全站區塊內距（2026-09-27）

水平內距集中於 `style.css :root`，手機覆寫集中於 `ui-shell.css :root`，實際套用由 `ui-padding.css` 統一管理。六頁共用下列規則，不依頁面另訂數值。

| 變數 | 桌面 ≥600px | 手機 <600px | 用途 |
|---|---:|---:|---|
| `--ui-panel-padding` | 24px | 16px | 卡片、面板、橫條、資訊欄、訊息泡泡、留言、提示、圖表、篩選工具列 |
| `--ui-list-padding` | 20px | 16px | 貼文列表列 |
| `--ui-small-padding` | 12px | 12px | 貼文成效等小型數據格 |
| `--ui-metric-min-width` | `9ch + 2 × small-padding` | 同桌面 | 依數值字級容納百萬級數字；小格不足寬度時整格換列 |

`check_ui_scale.py` 載入 `scripts/ui_padding.js`，在 1440×900、1609×914、390×844 對七頁及開啟的對話、資訊欄、貼文、留言、工具列與下方內容量測。DOM Range 檢查可見文字每一行，從文字本身向上找最近具有非透明底色、背景圖或可見邊框的容器；桌面至少 20px、手機至少 14px；新分類的小型數據格為至少 12px。原面板／列表門檻不變。排除操作按鈕、chips／徽章、表單控制項（含搜尋圖示）內部；內容型按鈕不排除。等待字型、React 畫面與有限動畫完成後才量測與截圖。

> 已移除的歷史規格：
> 另逐一檢查面板／列表左右 padding 等於共用值（±1px），跨七頁同類容器差距 ≤2px。既有字級、高度、水平溢出、文字裁切、核取方塊、頁首、側欄、三欄與回覆區比例斷言維持原預期值；新增 SVG 文字不得被圖表 viewport 裁切，以及 18 個內距偵測器正負案例。

最新輸出預設為 `.runtime/padding/after/`，可用 `UI_SCALE_ARTIFACT_DIR` 指定目錄。`report.json` 的 `measurements[].padding.rows` 為文字距離，`containers` 為逐區塊左右內距，`padding_violations` 為違規清單；量測輸出只保存在本機忽略目錄。

數字完整性由 `scripts/ui_numbers.js` 以 DOM Range 計算文字行數：只含數字、逗號、小數點、百分號與貨幣符號的可呈現文字，一律不得多行，包含可捲動區域的內容。三種尺寸與七頁全數檢查；另以 IG 最新觀看 `1,234,567` 的隔離資料走真實數據格與快照表，並以 8 個正反例驗證偵測器。回歸驗收透過 `UI_SCALE_ARTIFACT_DIR=.runtime/padding-fix` 存放。

## 共用元件（uniform）

以主題發想的既有設計為基準，樣式集中於 `frontend/src/ui-components.css`，由 `main.tsx` 匯入；只引用 P1-1 色彩與字體 Token，不載入外部資源。主題發想保留原 class 別名及尺寸，側邊欄不變。

1. `.section-card`：surface 底、subtle 邊框 1px、card 圓角、panel 內距；卡片間與標題區到內容皆 24px。h2 為 section-title、600；既有說明使用 help／subtle，與標題距 4–8px。區塊動作置右上，不補無必要的說明。
2. 小節 h3：section-title、600、下距 12px。序號圓點僅用於主題發想的順序流程。
3. 第一層 `.tabs`：subtle 底線 1px，間距 16px，依文字寬度排列；未選 subtle，選中 primary 文字、600 與 3px 底線，底色透明。保留 tablist／tab／aria-selected、方向鍵及 Home／End；手機在列內捲動。
4. 第二層及日期範圍使用 `SegmentedControl`；外框內距 3px、選中實心。其他頁使用 compact 依內容寬度；AI 第二層保留 tab 語意，其餘為 radio。主題發想原寬度不變。
5. 欄位標籤置上，help／muted、500、下距 8px；輸入與選單高度 height-input。桌面兩／三欄 grid、欄距 16px，390px 一欄；品牌工具列不超過 360px。
6. 提交動作 `.primary` 實心 primary，每張卡片最多一顆；非提交（更換、測試、更新、取消、重新整理、匯出）使用白底框線 `.secondary`；刪除使用 `.primary.danger`。共用樣式消除同列 primary 的舊 margin-top。底部 action-row 靠右，主要置次要右側、間距 12px，手機可換行。
7. `.list-box`：subtle 1px 邊框、card 圓角、overflow hidden；標題列 subtle 底、44px 高、左右 16px、help／subtle。內容列內距 12px 16px、1px 分隔；可選列 hover subtle，選中 subtle 底、左側 primary 3px 色條及600。空狀態置中 muted、上下32px。表格同規則，手機既有用量表轉直列。
8. `.status-badge` 沿用 `.report-status`，ready 成功、failed 失敗、pending 處理中；neutral 為 subtle 底與 subtle 文字，表示未設定、env 或未安裝。
9. `.notice`：subtle 底、左側3px色條、help字級；warning 用 pending，danger 用 danger 色條與文字，success 用 success。全域 `.error` 使用 danger 提示外觀，保留 class／role。
10. `.stat-tile` 使用卡片外框、20px內距、help／muted標籤；數值28px、600、tabular-nums，無資料「—」用subtle。數字卡間距16px、手機一欄；文字類分類 KPI 沿 section-title 避免長文字截斷。
11. `details` 的 summary 使用 body、600、pointer 與可見原生展開標記；收合標題不獨立畫成空卡片。
12. 確認對話框共用主題發想 backdrop／delete-dialog 外觀；不得使用 window.confirm，保留 Escape、焦點限制與關閉後焦點恢復。

儀表板：日期說明在共用 PageHeader 下，兩張數字卡同列；趨勢與提問清單各一張卡片，範圍切換位於標題右側，清單使用 list-box，圖表顏色不變。

貼文數據：平台底線分頁；粉絲工具列左側年份／月份／週次三個精簡下拉，高度與一般控制項相同；右側以「粉絲數 1,234」「本週 +5」「本月 +12」行內呈現，歷史週月顯示「該週／該月」。不使用數字卡、額外標題或說明列。1440px 一列（控制項高度加上下各12px內距），768／390px 最多兩列且不水平溢出。正成長 state-success、負成長 state-danger、無資料 text-subtle「—」，一般數字 text-main，均配 bg-surface；圓角沿用 card Token。FB／IG／Threads 共用工具列，YouTube／TikTok 以同寬精簡區塊顯示「尚未串接，串接後開始記錄粉絲數」。釋出高度供下方三欄使用，欄寬不變。左欄的範圍分段控制項與自訂日期依列表內容對齊，貼文列表有分隔、平台膠囊、兩行內文與日期。右側介紹、留言與數據分別卡片，手機保持數據在留言前、返回與分頁行為。

- 工具列內嵌篩選（例外）：發文日期篩選併入粉絲工具列（期間、發文日期、統計同列），分段控制項整組外框與下拉同為 40px，扣掉 3px 內距與框線後按鈕為 32px，不套用分段按鈕 40px 的規則；這段篩選不另加面板內距，沿用外層工具列。起日／迄日字樣只給螢幕閱讀器（視覺隱藏，不用 font-size:0）。窄於 1100px 時發文日期自成一列，不計入「最多兩列」。`check_ui_scale` 與 `ui_padding.js` 依此列為例外。

設定：第一層底線分頁、AI 第二層分段外觀，品牌選單在獨立工具列。基本設定與本月用量分卡；品牌說明、金鑰、分類、平台、工作區沿用共用卡片。平台憑證列按更換才展開輸入，單一平台同時只開一列以保留一顆儲存；取消不變更資料。工作區原五組收合保留語意，移除 summary 自身外框，實際設定仍置於組內卡片。Obsidian 儲存為主要、立即同步為次要。

PageHeader 標題與動作垂直置中，工作區小字在動作左側；1440×900、768×1024、390×844 均不得頁面水平溢出。主題發想抽出前後以相同隔離資料截圖及關鍵尺寸比對。

## 已移除的回覆介面

## 已移除的回覆介面

收件匣、回覆草稿／檢查／送出、價目表、轉人工條件、主管與路由指派、待回覆／期限提醒及成交進度已移除。回覆請使用 LINE／Facebook 原生 App。Webhook、訊息保存、分類佇列、私訊回補、緊急通知、主題發想、腳本及匯出保留；沒有資料刪除或新增 migration。

### 私訊退場（nodm）

工作區分頁移除 DmBackfill 元件及全部操作／狀態 DOM；匯出、品牌、例會、通知分組維持對齊。平台連線不顯示 LINE 官方帳號或其三個憑證欄位，保留獨立 LINE 通知卡片；Meta 沒有僅供 Messenger 的欄位，共用連線欄位保留。CSV 僅接受 Facebook／Instagram 公開留言。除主題發想既有內容外，前端不再使用「私訊」字樣。

新留言 KPI 與趨勢沿用既有色彩／字體 Token，無新色彩；文字配對列入 check_ui_contrast。check_dm_backfill_frontend 保留入口名稱，改驗退休元件不存在、零回補 API、平台三卡與 390px 無溢出；不新增隔離介面檢查入口。

## 移除本機 CLI 與網頁 AI 撰寫（nocli）

- 設定 → AI 只有「基本」「品牌說明」「AI 金鑰」；沒有本機 CLI 分頁、啟用／更新／偵測／模型按鈕，預設 AI 與執行方式只列 API 供應者。
- 主題發想建立區的「執行方式」為 API 供應者加「交給 Agent 撰寫」，兩者都用既有 `.policy-grid` 與原生 select；選後者不呼叫 AI，報告停在「等待 Agent 撰寫主題」並顯示接手說明。可編輯者另見 `.agent-handoff`：三個 secondary 連結「交給 Claude Code」（`claude://code/new?q=/mwb:ideas …`）、「開啟 Claude 對話」（`claude://claude.ai/new?q=`）、「開啟 Codex」（`codex://new?prompt=…&mode=codex`），加 secondary「複製給其他 Agent」；四顆等寬等高，手機版兩欄；指令帶報告編號，連結只預填不送出。Codex 與 ChatGPT 同一個 App，`mode` 參數（chat／work／codex）文件未列，2026-10-21 實測 `mode=codex` 才會開到 Codex 模式；Antigravity 桌面版無官方帶指令連結，只能複製。
- 主題卡片右上只剩「編輯」，底部只有 secondary 的「查看腳本」（有腳本才顯示）與「建立發佈草稿」／「開啟發佈草稿」；舊報告的「已重新生成」「延伸自 #序號」標記保留顯示。
- 建立發佈草稿不再有對話框，發佈頁沒有 AI 文案狀態、「重新撰寫」或「套用 AI 文案」。
- 新增或保留的文字與底色配對（卡片序號 text-subtle／bg-surface、卡片 secondary 按鈕 text-main／bg-surface、Agent 接手說明 text-subtle／bg-surface、舊 CLI 報告錯誤說明 danger／bg-subtle、舊 CLI 用量列 text-main）已納入 check_ui_contrast；390px 不水平溢出，不載入外部資源。

## YouTube 讀取串接（ytdata）

- 平台連線在 Threads 後新增 YouTube；同列頻道、連結狀態、權杖自動換發／失效提示及到期時間。用戶端 ID／密鑰沿用憑證具名表單、遮罩與儲存；僅一顆連結／重新連結primary，中斷與測試為secondary；未設定／非內部HTTPS時停用連結。教學改為卡片上的次要「設定教學」按鈕開啟站內視窗（見 guides），不再外開分頁，卡片不顯示回呼網址。
- 貼文數據 YouTube 與FB／IG同清單及日期篩選；Shorts用既有類型文字標籤，其餘為影片。成效七項依序觀看、按讚、留言、分享、平均觀看時長（秒）、觀看總時數（小時）、新增訂閱；後四項旁標「約晚1～2天」。快照表為抓取時間／觀看／按讚／留言，曲線預設觀看；未知為—，已知零為0。
- 訂閱工具列沿用年／月／週與本週／本月增減，名稱改訂閱數；頻道隱藏時顯示—，說明按鈕提示原因。未連結提示開始記錄訂閱數。留言沿用抓取／完整重抓／停止與日期視窗，顯示代號與遮蔽正文；主題發想有YouTube貼文才顯示其頁籤並加入摘要。
- 色彩／字體／圓角全沿用P1-1與共用Token；延遲說明text-subtle／bg-surface，教學視窗見 guides，Shorts膠囊text-subtle／bg-subtle，已納入check_ui_contrast。check_youtube_data驗四種連結狀態、清單、成效、留言、訂閱與1440／768／390無溢出；只拍修改後1440×900與390×844。

## YouTube 發佈（ytpublish）

- 發佈頁 YouTube 分頁（`#composer-panel-youtube`）在已連結、具上傳權限且共用格式為影片時啟用。頂列為頻道名稱與「未開啟」膠囊，依序是標題欄（`aria-label=YouTube 標題`，旁註 N／100 字；空白時以灰色 placeholder 顯示預設標題＝說明第一行）、說明欄（`aria-label=YouTube 說明`，旁註 N／5,000 位元組，沿用「還原為共用文案」與 Markdown 提示）、`公開狀態` 分段控制（公開／不公開／私人，預設公開）、兒童內容勾選框「這是為兒童製作的內容」（預設不勾）與 `.publish-thumbnail` 縮圖列。類別只在設定頁，發佈頁不出現。
- `.publish-thumbnail` 同列放「自訂縮圖」、96px 寬 16:9 縮圖預覽、檔名與大小（尚無縮圖時為 text-subtle 小字「JPG／PNG · 2 MB 內 · 未上傳則用自動縮圖」）、secondary「上傳縮圖／更換縮圖」與 primary danger「移除縮圖」，手機自動換行不水平溢出。縮圖不進共用素材清單。
- 共用格式為圖片／輪播／純文字時，YouTube 開關停用（title「YouTube 只支援影片」）並從已選平台移除，分頁只顯示 `.notice.warning`「YouTube 只支援影片」，分頁標籤不加紅點。直式或正方形且 ≤3 分鐘時顯示 `.notice.warning`「將被歸為 Shorts…」；縮圖列改為「Shorts 不支援自訂縮圖」並停用上傳，已有縮圖則以紅字要求移除並擋發佈，預覽改 9:16 且不套用縮圖。標題超過 100 字、說明超過 5,000 位元組以紅字擋發佈，分頁標籤加紅點。
- 既有連結缺少上傳權限：YouTube 開關灰色，分頁顯示「需要重新連結以取得上傳權限」與 secondary「設定 → 平台連結」（未連結仍是「尚未連結」）。設定頁 YouTube 卡片以 `.notice.warning.oauth-permissions`「需要重新連結以取得上傳權限」提示，狀態膠囊維持「已連結」，「重新連結」改為 secondary，其餘讀取功能不受影響；已連結時另有「上傳類別」下拉（預設「人物與網誌」，選取即儲存並提示「已儲存上傳類別」）。
- YouTube 預覽 `.publish-preview-post` 依序為影片（一般 16:9，Shorts 9:16，縮圖當封面 poster）、粗體 `.publish-preview-title` 標題、`.publish-preview-identity` 頻道名稱、`.publish-preview-actions.is-youtube` 互動列（讚／分享／儲存，只畫外觀）、`.publish-preview-caption` 說明（bg-subtle 圓角框，仍可折疊並以 link-color 標示 hashtag）。
- 確認視窗的 YouTube 項目為「影片 · 公開狀態 · 兒童內容／非兒童內容 · 自訂縮圖／自動縮圖（· Shorts）」與「標題：…」。
- 發佈紀錄：YouTube 結果連結為「查看影片」。縮圖失敗時同列顯示 `.status-badge.pending`「縮圖未套用」、安全中文原因與 secondary「重新套用縮圖」（檢視者不顯示，需發佈總開關開啟，先經 ConfirmDialog「只會更換縮圖，不會重傳影片」）；影片仍是成功。YouTube 回報的實際公開狀態與選擇不同（例如被限制為私人）時加 `.status-badge.pending`「YouTube 實際為私人」。
- 色彩、字體、圓角全沿用 P1-1 Token，未新增寫死顏色；新文字／底色組合已納入 check_ui_contrast。check_publish 驗 YouTube 分頁欄位與上限、縮圖、Shorts、非影片停用、預覽順序／粗體／比例／封面、缺權限引導、確認視窗與紀錄的縮圖失敗／重新套用，check_youtube_data 驗連結卡片的上傳權限提示與類別儲存，皆含 1440／768／390 無水平溢出。只拍修改後的 1440×900 與 390×844。

## 介面排列調整（uiorder）

只改排列，不改功能與文字；覆蓋前文相關描述。

- 發佈（新增貼文、限時動態同規則）：`.publish-footer` 把「立即發佈／排程」切換（排程時含日期時間欄，`.publish-schedule`）與右側 `.publish-submit`（`.publish-actions` 按鈕列加其下的 `#publish-disabled-reason`）放在同一個底部動作列。桌機同列、時間設定靠左、按鈕靠右，停用原因在按鈕下方右對齊；390px 分兩列但仍在同一動作列內，原因左對齊。「新貼文／新限時動態」按鈕在 `.publish-editor-heading` 右側，位於平台分頁之上。
- 主題發想：留言範圍順序為近 7、30、60、90 天、自訂日期（預設仍為 30 天）；390px 分段按鈕換行，不橫向溢出、不裁切。第 3 步按鈕順序為 secondary「重新標註所選留言」在左、primary「立即發想」在最右。頁首不再顯示無標籤數字，「主題列表」標題顯示為「主題列表（N）」。
- 貼文數據：留言同步區 `.comment-sync`（狀態、「抓取留言」「完整重抓」「停止」）位於「留言與回覆」卡片內、留言日期篩選與範圍總數之後；右側「貼文成效」只留成效數字、圖表與快照。FB／IG／Threads／YouTube 一致。「留言與回覆」標題下方一行 `.comment-retention.muted` 依 `/api/posts/platforms` 的設定說明觀眾留言保存期限（FB／IG／Threads 自取得起 N 天；YouTube 30 天內未重新抓取即刪除；TikTok 不讀留言），每日刪除未啟用時同句說明；這是平台條款要求的揭露，是此卡片唯一的說明列，設定讀不到就不顯示。

### 品牌選單整合與文字（uiorder 第二輪）

- 品牌只在側邊欄（手機為 `.mobile-brand-picker`）選擇；AI「套用品牌」、訊息分類「套用品牌」、主題發想第 1 步「品牌」、發佈「品牌」、工作區「目前品牌」全部移除，各頁用 App 傳入的 brand。送給後端的 brand_id 參數不變。
- 使用者只看得到一個品牌時，側邊欄與手機都不顯示品牌選單，App 的有效品牌直接用該品牌（網址仍帶 brand_id）；多於一個品牌時照舊含「全部可見品牌」。儀表板、貼文數據可用「全部」；主題發想、發佈、設定的 AI、訊息分類改顯示 `.need-brand`「請先在左側選擇品牌」（手機「請先在上方選擇品牌」，以 CSS 依 600px 切換），不顯示編輯內容；工作區在「全部」時只保留與品牌無關的資料、系統群組。網址 brand_id 照舊有效。
- 文字：全站「工作檯」；側邊欄移除「品牌工作區」標籤與底部標語，只留「品牌營運工作檯」；頁首右上不再重複工作區名稱；標題為「儀表板」「貼文數據」；發佈標題列移除「已開啟／未開啟」膠囊（保留頂部提醒、開關按鈕與按鈕下方原因）；成員列「Agent 連線 N 個」「撤銷全部 Agent 連線」；Webhook 欄位標籤為「公開網址」「Meta 留言通知網址」「LINE 通知網址」；憑證欄位的 .env 名稱改為小號 text-subtle 等寬字。
- 設定分頁順序為平台連線、AI、訊息分類、工作區、成員、我的帳號；預設分頁為平台連線（網址指定 settings_tab 時照舊）。貼文數據粉絲數列加小標「粉絲數期間」（YouTube 為「訂閱數期間」）。主題發想報告狀態為已完成但匯出檔不存在或未全部產生時，標題顯示「已完成・匯出未完成」。
- check_brand_scope 驗證單一品牌無選單、多品牌「全部」提示與選擇後內容、文字新值、分頁順序與預設分頁；多品牌以瀏覽器端替身 /api/brands 加第二個品牌，不寫入資料庫。

## 貼文數據成效置中與完整貼文（postcenter）

覆蓋前文 metricwidth、YouTube「成效七項」與內文「展開全文／收合」的描述。

- 桌面（≥1280px）三欄：左貼文列表 280px、中間 `.post-metrics`「貼文成效」自動寬度（最寬）、右側 360px `.post-conversation`（貼文摘要卡＋留言與回覆）。成效數字格依寬度自動排列（每格至少 120px）。
- 600～1279px 與手機一樣單欄：貼文摘要、貼文成效、留言與回覆依序排列。
- 貼文摘要卡：72px 縮圖（裁切填滿）在左，右側帳號・類型、兩行內文（`p.post-caption.collapsed`，內文不是標題，不用 h2）、時間；下方一列 secondary「完整貼文」與「開啟原始貼文 ↗」。不再有「展開全文／收合」。
- 「完整貼文」開啟 `.guide-dialog.post-full-dialog` 視窗（沿用設定教學視窗的外框、焦點進出、Tab 循環、Esc 與「關閉」）：帳號・類型、原比例圖片、完整內文（保留換行）、發文時間、原始貼文連結。手機全螢幕。
- 「觀看表現」區（`.watch-metrics`，h4）接在成效數字格之後，只在影片貼文出現（FB／IG 影片與 Reels、YouTube 全部、TikTok 全部、Threads 影片）：FB 平均觀看時長（秒）、觀看總時數（小時）；IG 再加「前 3 秒滑走率（%）」；YouTube 為平均觀看時長、平均觀看百分比（%）、觀看總時數，三項都標「約晚 1～2 天」。FB 有留存曲線時另顯示 `.retention-chart`「觀眾留存」與「影片中段仍在看／看到結尾」。TikTok、Threads 只顯示一行說明官方 API 沒有這些數據。曲線卡片都用外框（`.metric-chart`）加分頁籤（`.tabs.chart-tabs`，role=tablist「曲線指標」，標籤多時換行、不橫向捲動）切換指標，不用下拉選單：「數據變化」放互動指標；影片貼文另有「觀看變化」卡片放觀看表現三項；FB 的「觀眾留存」也是同樣外框的卡片。2026-10-24 起移除「數據快照」表：它列的是同一批快照的其中三項，「數據變化」曲線已涵蓋全部指標（滑鼠移到點上看精確數字），只保留曲線；快照達 100 筆時在曲線下方顯示「顯示最近 100 筆快照。」。YouTube 上方成效數字格改為五項：觀看、按讚、留言、分享、新增訂閱。

