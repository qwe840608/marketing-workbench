# 营销管理工作台（marketing-workbench）

给个人创作者或自有品牌自行部署的营销工作台：把 Facebook、Instagram、Threads、YouTube、TikTok 的帖子数据与观众评论集中管理，从评论中整理内容选题，并在两步确认后发布到多个平台。

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)
![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)
![TypeScript](https://img.shields.io/badge/TypeScript-7-3178C6.svg)

[繁體中文](README_zh-TW.md) | [English](README.md) | **简体中文** | [日本語](README_ja.md)

> 界面支持繁体中文、简体中文、English、日本語（截图为繁体中文界面）。`docs/` 下的文档同样提供四种语言版本。

![仪表盘](docs/images/dashboard.png)

| 帖子数据 | 选题策划 |
|---|---|
| ![帖子数据](docs/images/posts.png) | ![选题策划](docs/images/ideation.png) |

<sub>截图均来自作者自己的账号 ruidefilm 的实际画面。</sub>

## 功能特点

- 同步 Facebook、Instagram、Threads、YouTube、TikTok 的帖子效果；仪表盘显示趋势、增长对比、转化漏斗与受众分析。
- 每小时抓取自家帖子的评论；发送给云端模型前先对个人信息脱敏。
- 从选定帖子的评论中整理证据，生成 15 个内容选题，并附上观众原话。
- 根据选题撰写脚本，检查品牌禁用词，可导出。
- 定时或立即发布到 FB／IG／Threads／YouTube，发送前两步确认；TikTok 只能发送到 App 收件箱草稿。
- 内置 MCP 端点（Streamable HTTP），可连接 Claude Code plugin、Claude 桌面版扩展与 Codex。
- 成员与角色权限（管理员／营销人员／查看者）、审计日志、管理员一次性恢复码。
- 界面支持繁中、简中、English、日本語，适配 390px 手机宽度。
- 7-Zip 加密备份、LINE 通知（品牌通知群组与消息接收健康告警）。

技术栈：Python 3.13、uv、FastAPI、SQLAlchemy 2、Alembic、SQLite（WAL）；前端 React 19、TypeScript、Vite。

## 自行部署前必读

自行部署这个工作台，你就是自己那套 Meta、Google、TikTok 应用的开发者，平台条款的义务由你承担。

- **只供自己或自有品牌使用**（单一品牌）。不要用来代运营客户账号或开放给他人注册，这需要各平台审核，TikTok 明确不接受。
- **账号类型**：Facebook 需要公共主页；Instagram 需要专业账号并关联该主页；Threads、YouTube、TikTok 使用个人账号即可。
- **隐私政策与服务条款要自己写**，放在自己的网站上，再填到各平台开发者后台，模板在 [`docs/templates/`](docs/templates/)。
- **TikTok 只能发送为收件箱草稿**，文案需要在 TikTok App 内粘贴。
- **Google 同意屏幕要设为正式版**，否则 YouTube 授权每 7 天失效。

详情见 [`docs/合规须知.md`](docs/合规须知.md)（合规须知），每条规定的官方出处见 [`docs/平台政策与API限制.md`](docs/平台政策与API限制.md)（平台政策）。

## 安装步骤

要求：Windows（启动与备份脚本是 PowerShell，暂不支持 macOS／Linux）、Python 3.13、[uv](https://docs.astral.sh/uv/)、Node.js、7-Zip、ngrok；建议另装 Tailscale。

不熟悉命令行的话，可以把 [`docs/agent安装引导.md`](docs/agent安装引导.md)（agent 安装引导）交给自己的 AI agent，由它一步步带你安装。引导有简体中文、繁體中文、English、日本語四个版本，agent 会按你使用的语言自动选用。

```powershell
# 1. 创建配置文件并填入 NGROK_AUTHTOKEN；数据路径可留空（见下方“环境变量”）
copy .env.example .env

# 2. 后端：安装依赖、生成加密主密钥、创建数据库
cd backend
uv sync
uv run python ../scripts/initialize_ai_encryption.py
uv run alembic upgrade head

# 3. 前端：构建
cd ../frontend
npm ci
npm run build

# 4. 启动
cd ..
./scripts/start-all.ps1
```

`start-all.ps1` 只会为全新数据库创建结构，不会升级已有数据库；升级步骤见 [`docs/部署与运维.md`](docs/部署与运维.md)。

## 使用示例

首次启动时若 8000 已被其他程序占用，`start-all.ps1` 会询问改用哪个端口并写入 `.env`。

启动后在运行工作台的电脑上打开 <http://127.0.0.1:8000>（或你改用的端口），首次会看到“首次设置”页面，填入管理员账号、密码与品牌名称后自动登录。之后在“设置”的平台连接卡片中填入各平台应用的密钥并点击“连接〇〇账号”。每张卡片的设置教程会列出需要填到平台后台的回调地址。

让 Claude Code 连接工作台（地址从“设置 → 我的账号 → 安装 Agent”复制）：

```text
/plugin marketplace add <内部地址>/plugin/marketplace.json
/plugin install mwb@marketing-workbench
```

Codex 与 Claude 桌面版的安装方式见 [`docs/部署与运维.md`](docs/部署与运维.md#agent-连接)。

### 用 agent 操作工作台（MCP）

工作台在 `<内部地址>/mcp` 提供 MCP 端点（Streamable HTTP），只接受本机与 Tailscale 连接。除了上面的 plugin，其他支持远程 MCP 的 agent 也能直接连接：在“设置 → 我的账号 → Agent 连接”创建连接令牌，放进环境变量 `MWB_TOKEN`，再把下面这段加入 agent 的 MCP 配置（这是 Claude Code `.mcp.json` 的写法，其他 agent 填同样的地址与请求头）：

```json
{
  "mcpServers": {
    "mwb": {
      "type": "http",
      "url": "<内部地址>/mcp",
      "headers": { "Authorization": "Bearer ${MWB_TOKEN}" }
    }
  }
}
```

令牌只显示一次，不要粘贴到对话里或提交到 git。连接后 agent 会先读取服务器信息与品牌说明（含禁用词），再用 `get_guide` 获取完整流程，所以直接用大白话交代即可：

| 你可以这样说 | agent 会用到的工具 |
|---|---|
| “`/mwb:report` 整理近 30 天各平台的效果，哪篇表现最好？” | `get_dashboard`、`list_posts`、`get_post` |
| “最近的评论里，观众最常问什么？” | `get_popular_questions`、`list_comments` |
| “`/mwb:ideas` 根据最近三个视频的评论策划选题” | `start_ideation`、`get_ideation_report`、`save_ideation_ideas` |
| “`/mwb:script` 把第 3 个选题写成 60 秒短视频脚本，定稿后保存” | `get_script`、`save_script` |
| “`/mwb:post` 根据这份脚本写 IG 和 Threads 文案，附上这个视频” | `create_draft_from_idea`、`save_publish_draft`、`create_upload_link` |
| “`/mwb:publish` 定时在明天晚上 8 点发布” | `prepare_publish`，你确认后才 `confirm_publish` |

发布一律分两步：agent 先把平台、账号、完整文案、素材与发布时间列给你看，你明确同意后才会发出。选题与脚本也要你定稿并说“保存”才会保存。斜杠命令是 Claude Code plugin 的快捷方式，其他 agent 直接用大白话说即可；实际可用的工具以 agent 读到的工具列表为准。

部署、更新、备份与排错见 [`docs/部署与运维.md`](docs/部署与运维.md)；架构见 [`docs/架构.md`](docs/架构.md)。

开发时可以分开启动：

```powershell
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ../frontend
npm run dev
```

## 环境变量

复制 `.env.example` 为 `.env`。后端每个设置都有默认值，未填写的路径会放在 repo 下的 `data/`；完整列表与说明见 `.env.example` 的注释。

**启动前必须处理：**

| 变量 | 说明 |
|---|---|
| `NGROK_AUTHTOKEN` | `start-all.ps1` 启动 Webhook 网关时必填，缺少会直接停止。ngrok 可执行文件需在 PATH 中，或用 `NGROK_PATH` 指定完整路径 |
| `ACCOUNT_ENCRYPTION_KEY` | 在界面保存平台密钥或 AI 密钥前必须有。在 `backend/` 执行 `uv run python ../scripts/initialize_ai_encryption.py` 自动写入，并另外备份 `.env`；丢失后已加密的密钥无法读回 |

**首次启动会自动生成，无需手填：** `INGEST_API_KEY`、`WEBHOOK_PROBE_SECRET`、`WEBHOOK_PUBLIC_URL`（ngrok 分配的固定地址）。

**建议设置：**

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_PATH` | `data/db/mwb.db` | 数据库位置，建议使用绝对路径 |
| `EXPORT_ROOT` | `data/export` | 导出文件目录 |
| `LOG_PATH` | `data/logs/backend.jsonl` | 日志文件 |
| `APP_ORIGIN` | `http://127.0.0.1:8000` | 允许的来源，可用逗号分隔多个。加入 HTTPS 地址（例如 Tailscale）时，`SESSION_COOKIE_SECURE` 必须设为 `true`，否则无法启动 |
| `BACKEND_INTERNAL_URL` | `http://127.0.0.1:8000` | 后端监听地址。改端口时 `APP_ORIGIN` 的本机地址要一起改，两者端口不同时 `start-all.ps1` 会拒绝启动；它询问端口时会两个一起写入 |
| `ALLOWED_HOSTS` | `["127.0.0.1","localhost"]` | 允许的主机名，必须逐一列出，不能使用通配符 |
| `TAILSCALE_ENABLED` | `false` | 使用 Tailscale 时设为 `true`，再执行 `node scripts/tailscale.mjs configure` 自动填好来源与主机 |
| `COMMENT_RETENTION_DAYS` | `365` | 他人评论保留天数（30–3650），每日定时删除到期评论 |

**可选：**

| 变量 | 说明 |
|---|---|
| `GEMINI_API_KEY`／`OPENAI_API_KEY`／`ANTHROPIC_API_KEY` 与对应的 `*_MODEL` | 内置 AI 供应商；也可由管理员在界面验证后加密保存 |
| `GEMINI_PAID_TIER` | 默认 `false`；只有 Google Cloud 项目已绑定结算时才设为 `true`，否则 Gemini 不会处理平台数据 |
| `AI_MONTHLY_BUDGET_USD` | AI API 每月预算上限 |
| `NOTIFY_LINE_*` | LINE 通知用的 Messaging API 凭证与群组 |
| `BACKUP_LOCAL_ROOT`／`BACKUP_DRIVE_ROOT`／`BACKUP_PASSWORD`／`SEVEN_ZIP_PATH` | 加密备份位置、密码与 7-Zip 路径 |

各平台（Meta、Threads、YouTube、TikTok）的应用密钥建议在界面的平台连接卡片中填写，会加密保存到数据库；令牌由连接流程写入，无需手动填写。不要把密钥、令牌、密码提交到 git。

## 贡献指南

- 提交 PR 前请在 `backend/` 运行 `uv run pytest`，并在根目录运行 `npm --prefix frontend test`、`npm --prefix frontend run build`、`node --test scripts/*.test.mjs`。完整验收是 `python scripts/verify_all.py`（需要 Chromium）。
- 测试一律使用隔离数据与 HTTP 替身，不可调用真实平台 API。
- 数据表变更一律通过 Alembic migration。
- 新增界面文字用 `t('繁中原文')` 包起来，并补充 `frontend/src/locales/` 的英文、简中、日文翻译，用词依照 [`docs/i18n术语表.md`](docs/i18n术语表.md)。
- 平台对接只使用官方 API，不接受爬虫、非官方 API 或浏览器自动化。
- 架构与规则见 [`docs/架构.md`](docs/架构.md)、[`docs/MCP规范.md`](docs/MCP规范.md)、[`docs/UI规格.md`](docs/UI规格.md)。

欢迎提交 PR。较大的改动（新平台、数据表变更、权限规则）请先开 issue 讨论方向。回复时间不固定，敬请谅解。

问题或合作请发邮件到 support@ruidefilm.com。安全问题请直接发邮件，不要提交公开 issue。

## 许可

MIT License，见 [`LICENSE`](LICENSE)。使用本项目仍须遵守各平台条款，见 [`docs/合规须知.md`](docs/合规须知.md)。

## 致谢

本项目建立在许多开源项目之上，特别感谢 [FastAPI](https://fastapi.tiangolo.com/)、[SQLAlchemy](https://www.sqlalchemy.org/)、[Alembic](https://alembic.sqlalchemy.org/)、[React](https://react.dev/)、[Vite](https://vite.dev/)、[uv](https://docs.astral.sh/uv/)、[Playwright](https://playwright.dev/) 与 [Model Context Protocol](https://modelcontextprotocol.io/)。
