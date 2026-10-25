# 给 AI Agent 的安装引导

> **语言 / Language / 語言 / 言語**：[繁體中文](agent安裝引導.md) | 简体中文 | [English](agent-install-guide.md) | [日本語](エージェント向けインストールガイド.md)
>
> **Agent：开始前先判断用户使用的语言**（看用户发给你的消息；还没开口就看系统语言）。不是简体中文时，改读上面对应语言的版本照做，全程用那种语言与用户沟通；四种都不符合时读 English 版，但仍用用户的语言回复。工作台界面也可以切换成同一种语言（登录页或“设置 → 我的账号”）。

这份文档是写给 **AI agent** 看的（例如 Claude Code、Codex 这类能在用户电脑上读文件、执行命令的 agent）。用户把这份文档交给你，请你**一步一步带用户把工作台搭起来**。用户不一定是工程师：你负责执行命令、检查结果、用大白话解释；需要本人操作的步骤，清楚告诉用户要点哪里、要把什么贴回来。

开始前先读 [`合规须知.md`](合规须知.md)（合规须知）。这份文档只写流程；平台规定与官方出处在 [`平台政策与API限制.md`](平台政策与API限制.md)（平台政策），进阶操作细节在 [`部署与运维.md`](部署与运维.md)。

下文的界面名称以简体中文界面为准。

## 给 agent 的规则（一定要遵守）

1. **机密只进本机 `.env`**：密钥、令牌、密码不要请用户贴在对话里，不要显示在屏幕上、不要写进日志、不要提交到 git。需要用户提供密钥时，请用户自己贴进 `.env`；或者你在本机写入文件，但不要回显数值。
2. **密码由本人输入**：管理员密码、各平台登录、授权同意页面，一律由用户本人操作，你不代填、不代点。
3. **不发送任何平台内容**：搭建过程中不发帖、不回复评论、不打开任何发送开关。发布只能由用户在工作台的确认窗口中点击。
4. **每一步先说、再做、再验证**：先用一两句话说明要做什么、为什么，执行后检查结果，成功才进入下一步。
5. **安装软件、注册账号、点击同意前，先问用户**：例如用 winget 安装 Node.js、注册 ngrok 账号，都要先取得同意。
6. **界面与文档不一致时不要猜**：平台后台会改版。先查官方文档，或请用户截图给你，再判断下一步。
7. **不要删除 `data/`**：里面是正式数据。不要执行 `git clean -x` 这类会删除被忽略文件的命令。
8. **用途不符就停下来**：用户想代运营客户账号、管理多家不同公司的品牌，或开放给他人注册时，先说明这不在支持范围内、可能违反平台规定（见合规须知），请用户决定是否继续。

## 阶段 0：确认用途与准备

先问用户这些问题，答案决定后面要做哪些步骤：

- 品牌名称是什么？创建管理员时会一并创建这个品牌（工作台只支持单一品牌），报表、通知与 AI 提示会用到它。
- 要管理哪些平台？Facebook 公共主页、Instagram、Threads、YouTube、TikTok，可以只选一部分。
- 这些账号是**用户自己的**（或用户自己的品牌）吗？
- 有没有自己的网站可以放隐私政策和服务条款？各平台都要求公开网址。没有的话，要先想办法搭一个简单的页面。
- 要不要用 AI 功能（选题策划、写脚本、评论分类）？用哪家的 API？
- 要不要 LINE 紧急评论通知？

## 阶段 1：安装环境

目前只支持 **Windows**（启动脚本是 PowerShell）。检查并安装以下软件，已经有的就跳过：

| 软件 | 用途 | 如何确认 |
|---|---|---|
| Git | 下载代码 | `git --version` |
| uv | 管理 Python 3.13 与后端依赖 | `uv --version` |
| Node.js（LTS） | 构建前端、运行连接网关 | `node --version`、`npm --version` |
| 7-Zip | 加密备份 | `C:\Program Files\7-Zip\7z.exe` 存在 |
| ngrok | 接收平台 Webhook 的公开入口（启动时必需） | `ngrok version` |
| Tailscale | 给工作台一个内部 HTTPS 地址，平台授权回调与其他设备连接都靠它 | `tailscale version` |

**需要用户本人做的**：注册 ngrok 账号并复制 authtoken；注册并登录 Tailscale。这两个账号都由本人创建，你只负责说明步骤。

Windows 默认可能禁止运行 `.ps1` 脚本（错误信息提到“执行策略”或 execution policy）。不要替用户修改系统的执行策略；改用单次绕过的方式运行，例如 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-all.ps1`，其他 `.ps1` 脚本同理。

## 阶段 2：获取代码与创建 `.env`

1. 下载代码：`git clone <repo 地址>`，进入文件夹。
2. 复制配置文件：把 `.env.example` 复制为 `.env`。
3. 路径类设置（`DATABASE_PATH`、`EXPORT_ROOT`、`LOG_PATH`、`PUBLISH_MEDIA_ROOT`）**可以先留空**，会自动使用项目内的 `data/`。
4. 请用户把 ngrok authtoken 贴到 `.env` 的 `NGROK_AUTHTOKEN=` 后面。
5. 生成加密主密钥（平台密钥会用它加密保存）：在 `backend` 文件夹执行
   ```bash
   uv run python ../scripts/initialize_ai_encryption.py
   ```
   它会自动写入 `ACCOUNT_ENCRYPTION_KEY`，不会显示数值。提醒用户：**`.env` 要另外备份到安全的地方**，主密钥丢失后，已加密的平台密钥就无法读回。
6. 备份设置（建议）：`BACKUP_LOCAL_ROOT`（本机文件夹）、`BACKUP_DRIVE_ROOT`（例如 Google Drive 电脑版的文件夹）、`BACKUP_PASSWORD`（请用户自己设一组长密码，自己贴进去）。
7. `.env` 里的 `*_INITIAL_PASSWORD` **不用填**，那是测试数据专用的。

## 阶段 3：首次启动与创建管理员

1. 安装依赖并创建数据库（在 `backend`）：
   ```bash
   uv sync
   uv run alembic upgrade head
   ```
2. 确认端口：用 `Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue` 查 8000 是否被占用。用户在自己的窗口运行 `start-all.ps1` 时，脚本在首次启动遇到占用会询问改用哪个端口；但你（agent）的 shell 没有交互输入，脚本不会询问，只会停下。所以被占用时先问用户要改用哪个端口（例如 8010），再把 `.env` 的 `BACKEND_INTERNAL_URL` 与 `APP_ORIGIN` 中的本机地址一起改成同一个端口。下面的 8000 都换成这个端口。
3. 启动（回到项目根目录）：
   ```bash
   ./scripts/start-all.ps1
   ```
   它会自动安装前端依赖、构建界面、启动后端与 Webhook 网关。看到带有 <http://127.0.0.1:8000> 的启动完成信息就成功了。
   **注意**：脚本会把后端与 Webhook 网关创建为独立进程（`Win32_Process`），所以即使你（agent）在自己的后台任务或临时 shell 里运行，任务结束时服务也不会跟着停止。如果输出出现“无法以独立进程启动”的警告，表示退回普通启动，服务仍可能绑在你的任务下，这时请用户在自己的 PowerShell 窗口重新运行。启动后轮询 `http://127.0.0.1:8000/api/health` 确认。失败时，错误信息会指出要看 `.runtime/` 里哪个日志，照着读。
4. 请用户在运行工作台的这台电脑上，用浏览器打开 `http://127.0.0.1:8000`。全新数据库会显示“创建管理员”，由用户本人填写管理员账号、密码（12–128 个字符，建议用较长的口令短语，不要与其他网站共用）与品牌名称，点击“创建并登录”。密码不要经过你。没有品牌的话，平台连接后账号不会登记，发布与数据页面都无法使用，所以品牌一定要填。这个页面只在本机地址开放；从其他设备或 Tailscale 地址打开只会看到“请在主机上完成首次设置”。
   无法使用浏览器时的备用做法：请用户在自己的交互式终端（`backend` 文件夹）执行 `uv run python ../scripts/set_password.py <账号名称> --create-admin --brand "<品牌名称>"`。
5. 验证：`./scripts/check_runtime.ps1` 全部通过。

## 阶段 4：设置 Tailscale 内部 HTTPS

1. 确认用户已登录 Tailscale。
2. 在项目根目录执行 `node scripts/tailscale.mjs configure`，它会把内部 HTTPS 地址写入 `.env`。
3. 重新启动：`./scripts/start-all.ps1 -Restart`。
4. 记下内部地址（`https://<设备>.<网络>.ts.net`），后面设置平台授权回调时要用。

## 阶段 5：隐私政策与服务条款

1. 根据 [`templates/`](templates/) 的模板，**按用户的实际设置**起草两页：连接了哪些平台、用了哪些 AI 服务、`COMMENT_RETENTION_DAYS` 是几天、联系邮箱。用不到的段落删掉，不要照抄别人的政策。
2. 用户确认内容后，放到自己的网站上，取得两个公开网址。
3. 应用名称不能包含平台名称（例如不能叫“我的 TikTok 工具”），建议用网站或品牌名称。

## 阶段 6：连接平台

先确认用户有正确的账号类型，没有的话先请用户准备：

| 平台 | 需要的账号 |
|---|---|
| Facebook | **公共主页**。Meta API 无法读写个人主页，工作台只连接公共主页 |
| Instagram | **专业账号**（创作者或商家，可在 IG App 设置中免费切换），并**关联到上面的 FB 公共主页**；工作台通过公共主页找到 IG 账号，普通个人 IG 无法连接 |
| Threads | 个人账号即可 |
| YouTube | 有频道的 Google 账号 |
| TikTok | 个人账号即可，要加入 Sandbox 的 Target Users |

每个平台都是：**用户在平台的开发者后台创建应用 → 把密钥填进工作台 → 在工作台点击“连接〇〇账号”并在平台同意授权**。你能操作浏览器时，开发者后台的设置可以由你代填，按照 [`agent平台对接引导.md`](agent平台对接引导.md)（agent 平台对接引导）进行，包括它的边界：登录、密钥、授权、提交审核都不代做。工作台“设置 → 平台连接”每张卡片都有“设置教程”按钮，会显示要填的回调地址，可以直接复制。详细步骤见 [`部署与运维.md`](部署与运维.md) 对应段落。

| 平台 | 用户在后台要做的事 | 重点 |
|---|---|---|
| Meta（FB／IG） | 在 Meta 开发者后台创建应用，加入 Facebook 登录，回调地址填 `<内部地址>/api/oauth/meta/callback`；基本信息填政策网址 | 自用只需标准访问权限，不必提交审核；连接的人要在应用上有角色 |
| Threads | 在同一个 Meta 应用加入 Threads API 用例，回调 `<内部地址>/api/oauth/threads/callback`；把自己的 Threads 账号加为测试人员并接受邀请 | 有独立的应用编号与密钥 |
| YouTube | 在 Google Cloud 创建项目、启用 YouTube Data API v3 与 YouTube Analytics API、创建 Web 应用客户端，回调 `<内部地址>/api/oauth/youtube/callback` | 同意屏幕的发布状态要改为**正式版**，否则每 7 天要重新连接；授权时出现“未经验证”警告时点“高级 → 继续” |
| TikTok | 在 TikTok for Developers 创建应用，Sandbox 加入 Login Kit 与 Content Posting API（关闭 Direct Post），Scopes 勾选 `user.info.basic`、`user.info.stats`、`video.list`、`video.upload`，回调 `<内部地址>/api/oauth/tiktok/callback`，Target Users 加入自己的账号 | 视频只能发送为收件箱草稿（24 小时内最多 5 个待处理），文案要在 App 内粘贴；在 App 发布时选“所有人”，发布后用未登录的浏览器确认已公开。Sandbox 的 App name 填网站或品牌名称，不能含 TikTok。不要提交 Production 审核：TikTok 不接受个人或自用工具 |

密钥请用户自己贴进工作台的卡片（会加密保存），不要贴在对话里。连接后，卡片会显示账号名称与“已连接”。

**Meta 评论 Webhook（可选）**：平台连接页的“Webhook”卡片会显示 ngrok 公开地址与 Meta 评论通知地址，“设置教程”里有完整步骤。没设置时工作台仍会每小时自己抓取，只是比较慢。

## 阶段 7：AI 与通知（可选）

- **AI 服务**：管理员在工作台“设置 → AI → 基本”选择供应商（Gemini、OpenAI、Anthropic）、填 API 密钥并验证（加密保存）。Gemini API 的免费层会用传入的内容训练模型，所以要先在 Google Cloud 项目绑定结算，再把 `.env` 的 `GEMINI_PAID_TIER` 设为 `true`，否则工作台不让 Gemini 处理平台数据。如果用户连接工作台的 agent 是用个人订阅登录（例如 Claude Pro／Max、ChatGPT Plus），提醒用户到该服务的隐私设置关闭“用对话训练模型”；agent 使用 API 密钥则不必。
- **jev 评论分类**：jev 是 TypeSafe 的判断模型，用来快速分类评论。在“设置 → 平台连接 → jev”卡片按“设置教程”贴入密钥、点击“测试连接”。
- **LINE 通知**：在“设置 → 平台连接 → LINE 通知”卡片按“设置教程”操作：创建 LINE 官方账号并启用 Messaging API、把 Channel secret 与 Channel access token 贴进卡片、Webhook URL 填卡片显示的地址（需要先有 ngrok 公开地址），把官方账号邀请进群组并发送一条消息，再到“设置 → 工作区 → 通知 → LINE 群组通知”选择群组并启用品牌通知，最后点击“测试连接”。Push 有月度额度。

## 阶段 8：日常运维设置

1. **每日备份**：`./scripts/install-backup-task.ps1` 安装每日计划任务，再手动运行一次 `./scripts/backup.ps1` 确认成功。
2. **数据保留**：先预览会删除多少条（只读）`uv run --project backend python scripts/data_retention.py`，与用户确认后再加 `--enable` 启用每日删除。
3. **开机自动启动**（可选）：管理员在“设置 → 工作区”打开“开机自动启动”。
4. **发布总开关**：发布页右上角的“开启发布”默认关闭。要不要开由用户自己决定、自己点击。
5. **品牌规则**：在“设置 → 工作区 → 品牌模板”设置主题、禁用词与品牌 prompt，AI 与 agent 撰写时会遵守禁用词。工作区名称（产品显示名称）也在工作区设置中。
6. **成员**（可选）：管理员在“设置 → 成员”添加成员、分配角色与品牌；也可以新增自定义角色，勾选每个角色能用的功能。临时密码只显示一次，由用户自己转交，你不要经手。其他成员要加入同一个 Tailscale 网络才能连接。
7. **界面语言**：登录页与“设置 → 我的账号”可以切换繁體中文、English、简体中文、日本語。

## 阶段 9：让 agent 连接工作台（可选）

工作台提供 MCP 接口，让 agent 帮忙写选题、脚本与发布草稿。请用户用**内部 https 地址**（阶段 4）打开工作台，到“设置 → 我的账号 → 安装 Agent”选择 Claude Code、Codex 或 Claude 桌面版，按界面安装；Claude Code 的 plugin marketplace 只接受 https 地址。首次使用时用自己的工作台账号登录批准。其他支持远程 MCP 的 agent 可以用连接令牌连接，见 [README](../README_zh-CN.md) 的“用 agent 操作工作台（MCP）”。细节见 [`部署与运维.md`](部署与运维.md) 的“Agent 连接”。发布一律分两步：agent 准备好明细给用户看，用户明确同意后才发出。

## 完成检查清单

- [ ] `./scripts/check_runtime.ps1` 全部通过，`http://127.0.0.1:8000` 能登录
- [ ] 已创建品牌（创建管理员时一并创建），禁用词与品牌模板已设置
- [ ] Tailscale 内部 HTTPS 地址能打开工作台
- [ ] 隐私政策与服务条款已公开，网址已填进各平台后台
- [ ] 需要的平台都显示“已连接”
- [ ] Google 同意屏幕是正式版
- [ ] 每日备份计划任务已安装，手动备份成功
- [ ] 数据保留已预览，并在用户同意后启用
- [ ] `.env` 已另外备份到安全的地方
- [ ] 管理员已在“设置 → 我的账号 → 密码恢复码”生成恢复码，并自己存到密码管理工具（agent 不要经手恢复码）
- [ ] 向用户说明：发布总开关、TikTok 只能发送草稿、不支持多品牌与代运营

## 卡住时

- 启动失败：错误信息会指出 `.runtime/` 的日志文件，读最后几行再判断；常见原因是端口被占用、ngrok authtoken 没填、依赖没装。`NGROK_AUTHTOKEN` 没填时脚本第一步就会停下。端口 8000 或 4040 被占用时，先用 `Get-NetTCPConnection -LocalPort 8000` 查是哪个进程；如果是另一份工作台，到那份文件夹执行 `./scripts/stop-all.ps1`，不要直接结束不认识的进程。
- 前端构建出现 `Type 'number' is not assignable to type 'Timeout'` 这类类型错误：通常是上层文件夹（例如用户主目录）有别的项目留下的 `node_modules/@types/node`。当前版本已避开这种情况；仍然遇到时把错误信息反馈给维护者，不要删除用户的文件。
- 平台连接失败：先看卡片上的错误说明，再对照 `部署与运维.md` 与 `平台政策与API限制.md`；权限名称或回调地址不符最常见。
- 忘记管理员密码：有恢复码就在登录页“忘记密码？”重置；没有就按 [`部署与运维.md`](部署与运维.md) 的“成员管理与账号恢复”在主机上执行命令。
