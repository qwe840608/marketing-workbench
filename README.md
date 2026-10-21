# 行銷管理工作檯（marketing-workbench）

給個人創作者或自有品牌**自己架設**的行銷工作檯。它把各平台的貼文數據和觀眾留言收在同一個地方，從留言整理出下一支內容的主題，寫好腳本後一次發佈到多個平台；寫作的部分可以交給你自己的 AI agent。

English summary: [see below](#english).

## 能做什麼

- **數據**：同步 Facebook、Instagram、Threads、YouTube、TikTok 的貼文成效，儀表板顯示趨勢、成長比較與轉換漏斗。
- **留言**：每小時抓取自家貼文的留言，個資先遮蔽才交給 AI。
- **主題發想**：從選定貼文的留言整理證據，產生 15 個內容主題，每個主題附上觀眾原話。
- **腳本與草稿**：依主題撰寫腳本，套用品牌禁語檢查，可匯出。
- **發佈**：排程或立即發佈到 FB／IG／Threads／YouTube，送出前有兩段式確認；TikTok 只能送到 App 收件匣草稿。
- **AI agent**：內建 MCP 端點，可接 Claude Code、Claude 桌面版、Codex 等，讓 agent 讀數據、寫主題和腳本、準備發佈草稿。
- **其他**：成員與角色權限、繁體中文／简体中文／English／日本語介面、手機版、加密備份、LINE 通知。

## 自架前必讀

自架這個工作檯，你就是自己那組 Meta、Google、TikTok 應用程式的開發者，**平台條款的義務在你身上**。

- **只給自己或自有品牌使用。** 目前只支援單一品牌。不要拿來代操客戶帳號或開放他人註冊，這需要各平台審核，TikTok 明確不接受。
- **帳號類型**：Facebook 要有粉絲專頁；Instagram 要是專業帳號並連結到該粉專；Threads、YouTube、TikTok 用個人帳號即可。
- **隱私權政策和服務條款要自己寫**，放在自己的網站再填進各平台後台。可以從 [`docs/templates/`](docs/templates/) 的範本改。
- **TikTok 只能送到草稿**：未審核的應用程式不能直接公開發佈，文案要在 TikTok App 內貼上。
- **Google 同意畫面要設成正式版**，否則 YouTube 授權每 7 天失效。
- **Gemini 只能用付費方案**；用個人方案的 AI 當 agent 時，記得關閉「用對話訓練模型」。

細節請讀 [`docs/合規須知.md`](docs/合規須知.md)，每條規定的官方出處見 [`docs/平台政策.md`](docs/平台政策.md)。

## 系統需求

- **Windows**：啟動、停止、開機自動啟動與備份腳本都是 PowerShell。Python／Node 程式本身跨平台，但還沒有提供 macOS／Linux 的啟動方式，也沒有實測。
- Python 3.13 與 [uv](https://docs.astral.sh/uv/)
- Node.js
- 7-Zip（加密備份用）
- ngrok：只公開 Webhook 與限時媒體網址（平台通知與 IG／Threads 素材需要）
- Tailscale（建議）：從手機或其他電腦用 HTTPS 開啟工作檯，平台 OAuth 回呼也走這個網址

## 安裝

**不熟指令的話**，把 [`docs/agent安裝引導.md`](docs/agent安裝引導.md) 交給你自己的 AI agent（例如 Claude Code、Codex），它會一步一步帶你完成安裝、平台連結與日常設定。

自己動手的話：

1. 複製 `.env.example` 為 `.env`，填入資料路徑（資料庫、匯出、日誌請用絕對路徑）。平台憑證之後可以在網頁「設定 → 平台連線」填寫。
2. 安裝後端並建立資料庫與第一個管理員：

   ```powershell
   cd backend
   uv sync
   uv run alembic upgrade head
   uv run python ../scripts/set_password.py <管理員帳號> --create-admin
   ```

   帳號名稱自己決定，密碼在終端機隱藏輸入，不會寫進 `.env`。

3. 建置前端並啟動：

   ```powershell
   cd ../frontend
   npm ci
   npm run build
   cd ..
   ./scripts/start-all.ps1
   ```

4. 開啟 http://127.0.0.1:8000 登入，到「設定」連結各平台。每張平台卡片都有「設定教學」，會列出要填的回呼網址。

忘記密碼時：管理員可以事先在「我的帳號 → 密碼復原碼」產生一次性復原碼，在登入頁使用。其他密碼管理指令見 `uv run python ../scripts/set_password.py --help`（在 `backend/` 內執行）。

## 更新與維運

- `start-all.ps1` 只會替全新的資料庫建立結構，**不會自動升級既有資料庫**。資料庫結構落後時它會停下來，請照 [`docs/operations.md`](docs/operations.md) 的「部署順序」先備份、停止服務，再執行 `uv run alembic upgrade head`（或加 `-ApplyMigrations` 重新啟動）。
- 備份、還原、健康監測與排錯也都在 [`docs/operations.md`](docs/operations.md)。
- 公開到網路上的只有驗簽過的 Webhook 和限時媒體網址；網頁與 API 只限本機和 Tailscale。

## 連接你的 AI agent

工作檯在同一個埠提供 `/mcp`（Streamable HTTP）。登入後到「設定 → 我的帳號 → 安裝 Agent」，依你用的工具安裝：

- **Claude Code**：加入工作檯提供的 plugin marketplace，安裝 `mwb` plugin。
- **Claude 桌面版**：下載 `.mcpb` 擴充並貼上連線權杖。
- **Codex**：下載 skills 與設定檔，合併後執行 `codex mcp login mwb`。

agent 只能透過後端註冊的工具操作，權限由後端重新檢查，發佈一定要經過兩段式確認。細節見 [`docs/operations.md`](docs/operations.md#agent-連線) 與 [`docs/MCP規範.md`](docs/MCP規範.md)。

## 開發與測試

```powershell
# 後端與前端分開啟動
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ../frontend
npm run dev
```

```powershell
# 測試
cd backend
uv run pytest
cd ..
npm --prefix frontend test
npm --prefix frontend run build
node --test scripts/*.test.mjs
```

完整驗收是 `python scripts/verify_all.py`（需要 Chromium）。驗收一律使用隔離資料與平台替身，不會呼叫真實平台；輸出放在被 git 忽略的 `.runtime/`。

新增介面文字時用 `t('繁中原文')` 包起來，並補上 `frontend/src/locales/` 的三個翻譯表，`npm test` 會檢查。資料表變更一律走 Alembic。

## 文件

| 文件 | 內容 |
|---|---|
| [`docs/agent安裝引導.md`](docs/agent安裝引導.md) | 給 AI agent 的逐步安裝引導 |
| [`docs/合規須知.md`](docs/合規須知.md) | 自架者要遵守的平台規定與後台設定 |
| [`docs/平台政策.md`](docs/平台政策.md) | 各平台條款與 API 限制的出處和查證日期 |
| [`docs/operations.md`](docs/operations.md) | 部署、更新、備份、排錯 |
| [`docs/architecture.md`](docs/architecture.md) | 架構與設計決定 |
| [`docs/MCP規範.md`](docs/MCP規範.md) | MCP 工具規範 |
| [`docs/UI規格.md`](docs/UI規格.md) | 介面尺寸與元件規格 |
| [`docs/i18n術語表.md`](docs/i18n術語表.md) | 多語言用詞 |

## 聯絡

問題、安全性回報或合作：support@ruidefilm.com。安全性問題請直接寄信，不要開公開 issue。

## 授權

MIT License，見 [`LICENSE`](LICENSE)。使用本專案仍須遵守各平台條款，見 [`docs/合規須知.md`](docs/合規須知.md)。

---

## English

A self-hosted marketing workspace for independent creators and their own brand. It syncs post analytics and audience comments from Facebook, Instagram, Threads, YouTube and TikTok, turns comments into evidence-backed content ideas, helps write scripts, and publishes to several platforms with a two-step confirmation. An MCP endpoint lets your own AI agent (Claude Code, Claude Desktop, Codex) do the writing. The UI is available in Traditional Chinese, Simplified Chinese, English and Japanese; most documentation is in Traditional Chinese.

**Before you self-host:** you become the developer of your own Meta, Google and TikTok apps, so their terms apply to you. Use it only for your own brand (single brand, no client accounts). Facebook needs a Page and Instagram a professional account linked to it. Write and publish your own privacy policy and terms (templates in `docs/templates/`). TikTok uploads arrive as drafts only. Set the Google consent screen to production. Use Gemini only on a paid plan.

**Requirements:** Windows (startup and backup scripts are PowerShell; macOS/Linux startup is not provided yet), Python 3.13 with uv, Node.js, 7-Zip, Tailscale and ngrok.

**Install:** copy `.env.example` to `.env`, then run the commands in [Install](#安裝) above: `uv sync`, `alembic upgrade head`, `set_password.py <username> --create-admin`, `npm ci && npm run build`, and `./scripts/start-all.ps1`. Open http://127.0.0.1:8000 and connect platforms under Settings.

**Contact:** support@ruidefilm.com (please report security issues by e-mail, not in public issues).

**License:** MIT, see `LICENSE`.
