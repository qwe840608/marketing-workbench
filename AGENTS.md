# AGENTS.md — marketing-workbench

個人與團隊的通用行銷工作檯。

若有 `docs/專案現況.md`（維護者的私人現況紀錄，不隨公開版發佈），接手時先讀它，工作告一段落時更新它。開始修改前讀 `docs/architecture.md`；涉及介面時讀 `docs/UI規格.md`；部署、資料轉換及備份時讀 `docs/operations.md`；MCP 變更時讀 `docs/MCP規範.md`。涉及平台 API、資料保存、送審或條款時讀 `docs/平台政策.md`，查到新規定就補進去並更新查證日期。使用者請你協助安裝或初次設定工作檯時，照 `docs/agent安裝引導.md` 帶領，不必修改程式。要在各平台開發者後台建立應用程式（Meta／Threads／YouTube／TikTok）時，照 `docs/agent平台串接引導.md`，可以操作瀏覽器代填設定，但登入、密鑰與授權一律由使用者本人操作。維護者更新或推送開源公開版時讀 `docs/開源發佈.md`（私人文件，不隨公開版發佈），推送前一定跑 `scripts/release_scan.py` 並取得作者同意。使用者最新授權優先於歷史規則。

## 工作方式

- 聚焦單一任務，實作後跑適當驗收。提交須符合當次授權；禁止 force push 或改寫既有歷史。`.git` 唯讀時回報基準與未提交狀態，不產生提交腳本。
- session 禁止啟停服務時，僅修改程式及進行隔離驗收；建置至 `.runtime/`，避免覆蓋正在供應的前端。部署交由有權限操作人執行。
- 需要憑證或產品決策時列出具體需求；不可捏造資料或繞過驗證。既有使用者資料的破壞性處理須明確授權、預覽及備份。
- 顯示名稱、主題、禁語、prompt 及例會均由設定提供；新預設為中性或空白。隔離驗收資料不可送至真實平台。
- 驗收輸出置於忽略的 `.runtime/`。不將真實帳號、留言或私人路徑放入 fixture、文件、截圖或版控。

## 安全規則

- 金鑰、token、密碼不可進 git、日誌、匯出或快照。平台與加密主金鑰留在 `.env`；模型金鑰可由管理員驗證後加密入庫，只回遮罩。
- 所有 AI 執行均使用官方 API 金鑰。送雲端模型的文字先經 `redact.py`。
- AI 與 Agent 產出不得捏造價格、承諾或數據；品牌禁止承諾一律不能強制送出。
- 不得擅自修改實機 `send_enabled`、`publishing.enabled`，或送出任何平台內容。發佈到平台只能透過「發佈」功能，在總開關開啟並經確認視窗後由使用者操作送出；開發與驗收一律用 HTTP mock，不得呼叫平台 API。送出需後端權限與完整確認。
- Webhook 必須驗原始位元組簽章。公開入口只允許驗簽 Webhook 與限時媒體權杖路徑（`/media/<權杖>`）；UI/API 限本機及 Tailscale。
- 外部事件以平台 ID 冪等。LINE 只用於通知（品牌通知群組與收訊健康警示），Push 需確認額度。
- 未明確授權時不讀寫外部知識庫或第三方助理設定。MCP 寫入只能透過 `docs/MCP規範.md` 規範、`agent_tools` 註冊的工具，並由後端重驗權限；對外動作須兩段式確認（prepare／confirm），破壞性動作須先取得使用者同意；不將原始留言或個資寫入外部知識庫。
- `data/` 存放正式資料（資料庫、匯出、日誌），已被 git 忽略。**禁止執行會刪除被忽略檔案的指令**（例如 `git clean -x`、`git clean -X`、`git clean -fdx`），也不得刪除、搬移或覆寫 `data/` 內容；需要乾淨環境時改用 `.runtime/` 或另建副本。

## 技術與驗收

角色權限以 `backend/app/api/permissions.py` 的完整路由表與路由盤點測試為準；新增 API 必須明確列出權限。設定（AI、平台、訊息分類、工作區、成員）讀寫僅管理員；行銷可操作被指派品牌的內容，檢視者僅讀取，所有角色可改自己的密碼。非管理員僅顯示「我的帳號」設定頁與被指派品牌；須改密碼時禁止其他 API。成員寫入需 CSRF 與稽核，臨時密碼只回應一次，不進日誌／稽核／檔案。

Python 3.13、uv、FastAPI、SQLAlchemy 2、Alembic、SQLite WAL；路由只呼叫 services。資料表變更經 Alembic。時間存 UTC，顯示 Asia/Taipei。

前端 Vite／React／TypeScript；介面繁體中文並支援 390px。尺寸使用 UI 規格共用變數。程式識別字英文，註解說明原因。

常用命令見 README；資料轉換預設 dry-run，正式 apply 由部署操作人執行。

回報：完成項目、測試摘要、限制／部署待辦、基準與提交狀態。不得把隔離驗收說成已部署。

## Agent skills

### Issue tracker

議題記錄在本 repo 的 GitHub Issues，以 `gh` 指令操作。See `docs/agents/issue-tracker.md`.

### Triage labels

使用預設五個分類標籤（needs-triage、needs-info、ready-for-agent、ready-for-human、wontfix）。See `docs/agents/triage-labels.md`.

### Domain docs

單一情境。`CONTEXT.md` 與 `docs/adr/` 目前尚未建立，需要時才建立；不存在時直接略過。See `docs/agents/domain.md`.
