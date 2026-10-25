# 部署与运维

> **语言 / Language / 語言 / 言語**：[繁體中文](operations.md) | 简体中文 | [English](operations_en.md) | [日本語](operations_ja.md)

数据库、导出、日志、备份及 MCP 审计路径通过配置提供；不依赖开发者的磁盘或主机名。`.env.example` 是配置字段参考，凭证只在本机填写。各功能的设计规则见 [architecture](architecture_zh-CN.md)；这里只记操作步骤。每次变更的验收细节记录在 git 历史中，不再写入本页。

## 部署顺序

开发 session 不停止／重启正在运行的服务，不修改实机发送开关，也不发送平台消息。由有权限的操作人在确认工作树与回退数据后执行：

1. **备份**：先执行 `./scripts/backup.ps1`，另外安全备份 `.env`、服务部署设置及旧版本；核对数据库、导出可读，记录账号发送开关与 `publishing.enabled`。备份包含历史内容及机密，仅限操作人访问，不放入开源归档。
2. **停止服务**：执行 `./scripts/stop-all.ps1`，确认 PID 属于本项目且服务端口已释放。权限不足就停止部署，不启动第二套收信服务。
3. **结构升级**：在 backend 目录执行 `uv run alembic upgrade head`。各个 migration 的前置检查与降级限制见下方“Migration 注意事项”。
4. **启动**：先 `npm --prefix frontend run build`，再 `./scripts/start-all.ps1 -SuppressSystemAlerts`。ngrok 使用新的控制请求头及 probe 路径 `/webhook/mwb-gateway-probe`。如果本次仍禁止推送，用进程环境变量停用 `SCHEDULER_NOTIFY_ENABLED`、`RECEIVE_HEALTH_ALERTS_ENABLED`，并让付费任务保持在当次授权范围内。
   - `start-all.ps1` 启动后端前会比对 `alembic current` 与 `alembic heads`：数据库结构不是最新就停止并指回第 1–3 步，不会自动升级（没有版本记录的全新数据库除外，会直接建立结构）。服务仍在运行时，这项检查在停止服务前就进行，不会先停掉旧服务。第 1–3 步完成后，也可以用 `-ApplyMigrations` 让脚本代为执行第 3 步的 upgrade。
   - 后端与 Webhook 网关通过 `Win32_Process` 创建为独立进程（父进程是 WMI，不在调用方的 job 内），关闭启动窗口、Agent 的后台 shell 或计划任务结束都不会连带停止服务；调用方当时的环境变量（包括上面的停用设置）会整份传给服务。WMI 不可用时退回 `Start-Process` 并显示警告。
5. **验证**：`node scripts/webhooks.mjs check` 的全部公开边界用例、`./scripts/check_runtime.ps1`、Tailscale 登录、名称各显示处、Word 页眉、模板预览／审计。核对账号 `send_enabled` 与 `publishing.enabled` 前后一致，检查新导出及外键。登记新账号前设置 REGISTRATION_BRAND_SLUG 或传入 --brand。

前后端与 `plugin/` 一律成套部署；隔离验收不代表已部署。

## Migration 注意事项

正式 migration 前，先以 SQLite `mode=ro` 打开正式库，用 backup API 复制到 `.runtime/`，在副本上执行 upgrade／downgrade／upgrade，核对各表行数、外键与账号发送开关。副本含真实内容，禁止提交、上传或截图原文，也不得部署演练副本；不要用 `immutable=1` 忽略仍在使用的 WAL。

| 版本 | 注意事项 |
|---|---|
| 0021 | 停用的供应商改为 JSON null；管理员须在 AI 设置中验证密钥并重新选择默认供应商。`downgrade 0020` 只恢复仍为未设置的字段。 |
| 0024 | 移除七张业务表的旧数据来源标记；任一表仍有 true 即中止整次升级并列出表名与行数，需另行确认处理方式。 |
| 0025 | 结束所有旧评论任务与回补探索，保留业务数据；downgrade 不恢复旧任务，退回旧程序时须另外停用旧的自动评论计划任务。 |
| 0026 | 降级到 0025 会删除粉丝快照表，请先备份。 |
| 0027 | `downgrade 0026` 移除三家备用模型设置，等待后续轮次的 AI 任务标为 skipped；回退前备份任务计划与品牌 AI 设置。 |
| 0030 | 删除已退役的 `auto_draft_jobs`；降级只重建空表。 |
| 0031 | 平台／jev 凭证可存入数据库；已存平台覆盖值时 `downgrade 0030` 会拒绝以免丢失设置，回退优先还原升级前的备份。 |
| 0032 | 成员管理；既有账号 `must_change_password=false`。 |
| 0033 | Meta／Threads OAuth。 |
| 0035–0043 | 发布（0035）、caption_job_json（0036，已不使用）、Agent 授权（0037）、Agent 草稿上传（0038）、删除检测（0039）、Facebook 未发布（0040）、平台选项与 Threads 串文（0041）、快拍（0042，有快拍时拒绝降级）、YouTube 发布与缩略图（0043，有 YouTube 发布或缩略图时拒绝降级）。0041 降级会移除选项／串文进度，已发送串文时不可在未备份的情况下降级。 |
| 0046 | 帖子缩略图缓存 `post_thumbnails`。降级直接删表（只是平台图片的缓存），升级后每小时的计划任务会重新抓取。 |
| 0048 | Instagram Reels 封面：`publish_media.role` 加入 `cover`，不改动既有数据行；已有封面时拒绝降级。 |
| 0049 | Facebook 视频／Reels 封面：`publish_media.role` 加入 `fb_cover`，不改动既有数据行；已有 FB 封面时拒绝降级。FB 封面需要 `pages_manage_engagement`：既有 Meta 连接要重新连接一次才会获得（不重新连接也能照常发布，只是封面不会应用）。 |

## 验收

**一条命令跑完全部验收**：在项目根目录执行 `python scripts/verify_all.py`。依次执行 ruff、tsc、构建到 `.runtime/verify-dist`，再并行执行 pytest、前端测试、`scripts/*.test.mjs`、全部隔离界面检查（自动收录 `scripts/check_*.py`，排除 `*_live.py`）与补充检查（清单在 `verify_all.SUPPLEMENTARY`），并行步骤全部结束后单独执行 `runtime-clean`（`scripts/test_runtime_clean.py`），最后扫描禁止字符串与写死的颜色（`git grep` 本身失败也算不通过）。每一步的输出在 `.runtime/verify/<步骤>.log`，最后一行是 `ALL PASS` 才算通过。开工前用 `python scripts/verify_all.py snapshot-data <文件>` 记录 `data/` 清单，收尾时加 `--data-baseline <文件>` 比对；开发中用 `--only pytest,check_xxx` 只跑指定步骤，用 `--jobs 1` 依次执行以排查互相干扰；步骤名称打错会直接报错并列出可用名称。`--only` 没有包含 `build` 时，界面检查用的是上次构建的 `.runtime/verify-dist`（会打印提醒），改过前端要一起选 `build`。新增检查只要放进 `scripts/check_*.py` 就会被收录，不需要在文档中记录数量。

界面检查用 Playwright 打开本机安装的 Google Chrome（`runtime_tmp.py` 指定 `channel="chrome"`），验收机器需先安装 Chrome。

隔离规则：

- 每个 check 的 DATABASE_PATH／EXPORT_ROOT／媒体与日志由 `browser_harness` 或 `runtime_tmp` 指向 `.runtime/tmp/<唯一名称>/`；纯 CSS 检查与 helper 不打开数据库。不读取正式配置或凭证、不调用真实 AI 或平台、不连外网（平台一律 HTTP mock）。
- 不覆盖正在提供服务的 `frontend/dist`：构建到 `.runtime/`，并以 `FRONTEND_DIST_DIR` 指向该处。

  ```powershell
  npm --prefix frontend run build -- --outDir ../.runtime/verification-dist
  $env:FRONTEND_DIST_DIR = (Resolve-Path .runtime/verification-dist).Path
  cd backend
  uv run python ../scripts/check_ui_scale.py
  ```

- `runtime_tmp.runtime_check` 用 `temporary_dir()` 管理临时文件；取得引擎、日志或子进程后立即登记 `cleanup()`，异常与 KeyboardInterrupt 同样会清理，删除失败只打印警告。Node 构建由 `runtime_tmp.mjs` 登记 after hook。清理行为由 `scripts/test_runtime_clean.py` 验证；它比对 `.runtime/tmp` 是否已清空，必须在其他检查都结束后单独执行，`verify_all.py` 的 `runtime-clean` 步骤已按这个顺序安排。
- 截图、Word 样本与 JSON 报告只保留最近一次，放在 `.runtime/check-output/<入口脚本名称>/`，每次开始时清空；跨次运行的 before／after 对照需另行保存。
- 验收脚本只停止自己创建的隔离进程。`*_live.py` 不在验收范围内，执行需另有明确授权。
- 对比度检查只读 CSS：文字 ≥4.5:1，图标／焦点／图表 ≥3:1。
- `eval_jev_questions.py` 默认只跑离线 transport 替身，通过只验证管线，不代表模型质量；`--live` 与 `evaluate_jev_hard.py` 会调用付费 API，需明确指定。

并行验收的稳定性：默认 `--jobs 4` 会让 pytest 与浏览器检查争抢 CPU，检查不得依赖“单独跑时足够快”。

1. `test_dashboard_trends_scale_read_only` 的查询次数与无写入是结构性断言；时间阈值只比较预热后连续运行五次的最佳值。
2. 上传端点的数据库步骤一律在 threadpool 中执行：在事件循环上等待 SQLite 写入锁会冻结服务器，形成约 15 秒的互锁后返回 503（`test_upload_waits_for_write_lock_off_event_loop` 可稳定复现）。发布页的媒体上传／移除与保存共用同一队列。
3. 打开草稿而内容未修改时，自动检查只调用 `/check` 不保存，避免无故递增 version 导致 Agent 的 `prepare_publish` 冲突。
4. 隔离检查服务器以 `ports.KEEP_ALIVE_SECONDS` 停用空闲连接关闭，避免 Playwright 复用连接时出现 `socket hang up`；新增启动 uvicorn 的检查须沿用此设置。

## 后端测试

在 `backend/` 中执行。并行模式用于日常验收，单线程用于调试与测量：

```powershell
uv run pytest -q -n auto --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
uv run pytest -q --basetemp ../.runtime/pytest -o tmp_path_retention_policy=none
```

- 每个测试会话（并行时为每个 worker）只执行一次 `alembic upgrade head` 生成模板数据库，各测试用 SQLite backup API 复制到自己的 `tmp_path`。模板绑定 migration 内容指纹，不跨运行缓存。实现在 `backend/tests/migration_database.py`。
- 验证 migration 本身的测试必须标记 `@pytest.mark.migration`，标记后改为逐个测试真实执行 migration。
- 测试期间对外连接与 DNS 查询会直接失败（只允许 loopback），新测试需用 mock 取代外部调用。
- 共用辅助函数在 `tests/conftest.py`：`login()`（获取 CSRF、登录并返回后续请求头）与 `seed_records()`（合成数据加历史价目行），新测试直接 `from conftest import ...`，不要再复制一份。
- 新测试不得依赖固定文件名、固定端口或模块级的共享状态。
- uv／pytest 缓存目录受限时，把 UV_CACHE_DIR、TEMP、TMP 与 `--basetemp` 指向允许写入的隔离目录，不更改正式数据配置。

## Agent 连接

工作台提供内部 `/mcp`（Streamable HTTP），与网页同一端口；只有本机与 Tailscale 可以访问，公开来源一律返回 404。接口规范见 [MCP規範](MCP規範_zh-CN.md)（MCP 规范）。成员先加入 Tailscale，用内部 HTTPS 地址打开“设置 → 我的账号 → 安装 Agent”；不需要私有 GitHub repo 权限。localhost 下载仅供参考与测试，Claude 托管 marketplace 的 archive 必须是 HTTPS。

**Claude Code**（至少 v2.1.224）：

```text
/plugin marketplace add <內部網址>/plugin/marketplace.json
/plugin install mwb@marketing-workbench
```

到 `/plugin → Marketplaces` 选择 marketing-workbench，打开 Enable auto-update（须成员自己操作）；首次使用 MCP 时用自己的工作台账号登录并批准。手动更新用 `/plugin marketplace update marketing-workbench`，更新后重新开始对话。用户本人也可以在 repo 根目录用 `claude --plugin-dir plugin/mwb` 加载开发文件，本机 URL 为 <http://127.0.0.1:8000/mcp>。

**Codex**（skills＋config）：在安装区切换到 Codex，下载并解压，把 skills 下的五个文件夹放到 `~/.agents/skills/`（已有同名内容先备份），把 ZIP 里的 config.toml 合并到 `~/.codex/config.toml`，再执行 `codex mcp login mwb` 用自己的账号批准。只读工具 approval_mode=approve，所有写入及 confirm_publish 为 prompt；客户端的批准设置不能取代后端权限与发布确认。更新时重新下载并合并。采用这种方式的原因：Codex plugin 的 installed server policy 需要用户在 config 中设置，且 `codex plugin marketplace add` 不接受托管的 JSON URL。

**Claude 桌面版**：切换到 Claude 桌面版下载 `.mcpb`，在桌面版“设置 → 扩展 → 安装扩展”中选择该文件。工作台地址从安装区复制（本机可填 <http://127.0.0.1:8000>），到“Agent 连接”创建连接令牌并粘贴到扩展设置中。更新需下载新版重新安装；移除扩展不等于在工作台撤销。官方格式的查证及手动 mcpb 验证命令见 `plugin/README.md`。

**Hermes**：见 [MCP規範](MCP規範_zh-CN.md)（MCP 规范）的“Hermes 连接”。

**发布新版 plugin**：修改 `plugin/mwb/` → 提高 `.claude-plugin/plugin.json` 的 version 并同步开发用 `.mcp.json` 的 header → 在 backend 执行 `uv run python ../scripts/update_plugin_hash.py` → 跑测试 → 由授权操作人部署前后端及 `plugin/`。version 的唯一来源是 plugin.json；更新工具会拒绝以同一版本覆盖不同的哈希。兼容性新增不改 MCP API 版本；plugin 最低兼容 0.3.0，更旧的版本只能读取 get_server_info／get_guide。部署者用 `claude plugin validate <解壓縮路徑>` 验证插件包，本人试用后再提供给成员。

**撤销与期限**：自己的 OAuth／连接令牌在“我的账号 → Agent 连接”中撤销；管理员可在成员页确认后全部撤销。停用、重置或更改密码会撤销连接。两种连接 30 天未使用即失效；OAuth 访问令牌 1 小时、refresh 30 天且每次轮换，重复使用旧 refresh 会撤销整个授权。计划任务每小时清除过期的授权数据。审计记录成员、连接名称与授权 id，不记录机密。

## 发布

- 发布总开关是 Setting `publishing.enabled`，默认 false，只有管理员可以在发布页确认后切换；部署不得改动其当前值。
- 定时发布与媒体清理需要 SCHEDULER_ENABLED、SCHEDULER_PUBLISH_ENABLED 都开启。PUBLISH_POLL_SECONDS 默认 5、PUBLISH_POLL_TIMEOUT 默认 300 秒；Threads 未完成的容器至少每 60 秒才再查询一次，都有超时且不会自动重新发布。
- 媒体存放在 PUBLISH_MEDIA_ROOT（默认 `data/publish-media`）。IG／Threads 需要 WEBHOOK_PUBLIC_URL 的 HTTPS origin，让平台下载 `/media/<權杖>`；公开边界与 ngrok 策略只额外允许精确的媒体令牌路径（含 IG 转码用的 `.jpg`）。
- 发布记录中的“检查平台帖子”（`POST /api/publish/presence-check`，管理员与营销人员）会重新抓取完整列表并消耗 Meta 调用配额；同一品牌 60 秒内只能手动检查一次。
- 结果无法确认（超时、中断）时，先到平台确认是否已发布，再点击“仅重试失败的平台”。
- 部署后的第一篇真实发布须在用户在场且当次同意的情况下进行：Facebook 先用未发布帖子、YouTube 先用“私享”视频、TikTok 先发送一支测试视频到收件箱（不在 App 内点发布就不会公开）。未经用户当次同意不得点击任何发布。

**快拍**：Facebook Login 路径的 IG 快拍需要商业账号及 instagram_content_publish、instagram_manage_insights。在 Meta 应用后台的 Instagram Webhooks 中勾选 `story_insights`，并确认该 IG 账号已订阅应用。接收端只写入本机已知快拍 ID 的 final 快照，不保存原始事件。

**Facebook 快拍数据只读核对**（尚未执行）：先取得用户对账号、既有未过期快拍及只读范围的同意；重新阅读官方 Page Stories／insights 文档，仅在文档明确支持时对已存在的快拍 ID 发 GET，不上传、不创建、不发布。记录版本、端点、HTTP／错误码与字段是否可用，不记录令牌、账号或原始响应。文档仍不明确就停止，维持“Facebook 不提供快拍数据”。

**部署前待核对的平台规格**：FB Reels 3–90 秒／9:16、Threads emoji 的字节计数、published_posts 是否包含 Reels、IG 快拍 3–60 秒与 JPEG 规格。这些值集中在 `publish_rules.RULES`，核对后只需改那里。

## Meta／Threads 首次连接

回调只允许内部已登录的管理员；公开入口的 `/api/oauth/*` 一律返回 404。ACCOUNT_ENCRYPTION_KEY 由部署者提供。

1. 在 Meta 开发者平台“Facebook 登录 → 设置”中，把“有效 OAuth 跳转 URI”加上 `<內部 https 網址>/api/oauth/meta/callback`（工作台的“设置教程”窗口会显示并可复制）。
2. 确认用例包含 `pages_manage_posts`、`instagram_content_publish`，以及读取所需的 `pages_show_list`、`pages_read_engagement`、`pages_read_user_content`、`pages_manage_metadata`、`read_insights`、`instagram_basic`、`instagram_manage_comments`、`instagram_manage_insights`；不再申请已退役的私信权限。
3. 在内部工作台“平台连接 → Meta → 手动设置（高级）”中设置应用编号与密钥，点击“连接 Meta 账号”。只有一个公共主页时自动采用；有多个公共主页时需要选择。没有 IG 时仍可连接 FB。

Threads：在“用例 → Threads API → 设置”中取得独立的应用编号与密钥，加入 `<內部 https 網址>/api/oauth/threads/callback`，确认 `threads_basic`、`threads_content_publish`、`threads_manage_replies`、`threads_manage_insights`、`threads_read_replies`，回到工作台填写这两个字段并点击“连接 Threads 账号”。既有连接缺少数据权限时，Threads 卡片会显示“需要重新连接以获取数据与回复权限”；重新连接前帖子列表与发布照常，数据与回复暂不抓取。

state 绑定管理员与登录 session，10 分钟内一次性有效。Facebook 用户令牌剩余不到七天时只能重新连接，公共主页令牌不另设到期。Threads 每天检查，剩余不到七天且距上次更新已满 24 小时才续期；失败与到期提醒发到既有的品牌 LINE 通知群组，没有设置群组则只记入审计。

Threads 部署后第一次实机运行请确认：六项 insights 能否一次请求（官方文档把 views、shares 标为开发中）、conversation 是否接受 limit 参数、回复中 username 缺失的比例。Threads 不经过 Meta 调用配额与 usage headers；每轮上限为列表 50 页、数据 300 篇。

## TikTok 连接

只使用 TikTok for Developers 的 Sandbox，不提交审核（见 `docs/TikTok規劃.md`）。按照平台连接中 TikTok 卡片的“设置教程”创建应用：Sandbox 加入 Login Kit 与 Content Posting API（Direct Post 关闭），Redirect URI 选 Web 并填写 `<BACKOFFICE_ORIGIN>/api/oauth/tiktok/callback`，Scopes 为 `user.info.basic`、`user.info.stats`、`video.list`、`video.upload`，Target Users 加入要连接的账号，必填字段包括公开的服务条款与隐私政策网址。Client key／Client secret 在卡片中加密入库（`.env` 的 `TIKTOK_*` 只作后备）。

连接采用与其他平台相同的两段式跳转。access token 有效期 24 小时，调用前剩余不足 5 分钟就用 refresh token 换发，并保存 TikTok 返回的新 refresh token；卡片显示 refresh token 的到期日。每天的 OAuth 维护会提前换发，换发失败（`invalid_grant`）时标记为需重新连接并通过 LINE 通知一次，refresh token 到期前 14 天同样会通知。“断开连接”会调用 TikTok revoke（令牌已失效时照常清除），删除 TikTok 令牌与已同步的数据，账号行保留并改名为“TikTok”。

连接后，每小时的数据计划任务用 `POST /v2/video/list/` 读取公开视频（含播放、点赞、评论、分享数），同一份列表写入帖子与到期的数据快照；粉丝数由每天的粉丝计划任务用 `GET /v2/user/info/` 的 follower_count 记录。只有从第一页走到最后一页且非空的列表，才会把消失的视频标为已删除（在 TikTok 上可能是删除或改为私密）并从帖子数据中隐藏，重新出现即恢复；列表中断或为空时不做判定。授权需要重新连接时，计划任务直接跳过 TikTok、不调用 API。TikTok 评论一律不读取。

发布：TikTok 只支持视频，发送到用户的 TikTok 收件箱（未审核的应用不能直接公开），收件箱 API 不接收文案，发布记录提供“复制文案”。需要 `video.upload`；先保存 publish_id，重试前先查询状态，已进入收件箱就不再发送。收件箱 24 小时内最多 5 支待处理，超过会返回 `inbox_full`。发送后由发布计划任务每 10 分钟查询一次状态（最多 7 天），用户在 App 中发布后显示“已在 App 发布”。migration 0047 放宽了 publish_targets 的平台限制；降级前如果已有 TikTok 发布目标会拒绝。

## YouTube 对接与发布

1. 在 Google Cloud Console 创建项目，在“API 和服务 → 库”中启用 **YouTube Data API v3** 与 **YouTube Analytics API**。
2. 在“Google Auth Platform → 品牌塑造”中创建同意屏幕；“目标对象”选 **外部**，发布状态改为 **正式版（In production）**（Testing 的 refresh token 通常七天到期）。
3. 在“数据访问”中加入 `https://www.googleapis.com/auth/youtube.readonly`、`https://www.googleapis.com/auth/yt-analytics.readonly`；要从发布页上传视频，另加 `https://www.googleapis.com/auth/youtube.upload`。
4. 在“客户端 → 创建客户端”中选 **Web 应用**，已获授权的重定向 URI 必须完全符合 `<內部 HTTPS 網址>/api/oauth/youtube/callback`。
5. 管理员在“设置 → 平台连接 → YouTube”填入客户端 ID／密钥并保存，点击“连接 YouTube 账号”（或点击“重新连接”并保留“上传视频”的勾选）。
6. 选择拥有目标频道的 Google 账号；看到未验证警告时，确认是自己的应用后点击“高级 → 转到（应用名称）（不安全）”，不绕过组织策略。频道属于品牌账号时选择该品牌频道。一次只登记一个频道；多品牌时须先登记频道归属的品牌。
7. 回到工作台确认频道名称与“已连接”，并在同一张卡片上设置“上传类别”（默认“人物和博客”）。invalid_grant 会标记为“需重新连接”；断开连接会向 Google 撤销授权并清除本地令牌，保留历史数据。

配额：读取用持久化的 `youtube.quota` 按美国西部日历日限制每天 8,000 单位（预留 2,000 给人工操作），每轮最多列表 50 页、数据 300 篇；`videos.insert` 每天 100 次，另计入 `youtube.uploads`；`thumbnails.set` 约 50 单位，计入 `youtube.quota`。未验证频道的视频超过 15 分钟会被拒收；缩略图失败最常见的原因是频道尚未通过电话验证，完成验证后点击“重新应用缩略图”即可（只更换缩略图，不重新上传视频；素材 30 天后清除就无法再应用）。缩略图上限暂采用保守的 2 MB（`RULES.youtube.thumbnail_bytes`）。如果 Google 对未经审核的项目限制公开状态，发布记录会标示“YouTube 实际为…”。

## 成员管理与账号恢复

- 管理员在“设置 → 成员 → 添加成员”输入账号、显示名称、角色及品牌。临时密码只显示一次，请直接安全地转交，不要贴进审计、日志或文档；新成员首次登录须先修改密码。
- “编辑 → 重置密码”会生成新的临时密码并撤销所有登录；停用也会立即撤销。最后一位启用中的管理员不可停用或降级，管理员不可停用自己。
- 所有角色都在“设置 → 我的账号”中修改密码（至少 12 个字符，新旧密码不可相同）；成功后保留当前登录，撤销其他登录。
- 同一账号连续失败五次会锁定 15 分钟；账号存在与否都返回“账号或密码不正确”。
- 其他成员须加入同一个 Tailscale 网络；登录后如果显示“尚未分配品牌，请联系管理员”，由管理员补上品牌。
- 登录页的“忘记密码？”说明成员应找管理员重置，并提供管理员恢复码表单与下方的主机命令。工作台没有邮件或短信渠道，所以前端不提供无需事先准备的自助重置。
- 管理员可以在“设置 → 我的账号 → 密码恢复码”输入当前密码生成一次性恢复码（只显示一次，数据库只存哈希），请保存在密码管理工具中，不要和密码放在一起。重新生成即作废旧码。
- 用恢复码重置成功后：设置新密码、作废恢复码、撤销该账号所有登录与 Agent 连接、清除登录锁定。只有启用中的管理员可以使用；错误一律返回“账号或恢复码不正确”，并与登录共用“五次失败锁定 15 分钟”的规则。

忘记最后一位管理员的密码又没有恢复码时，由有正式库操作权限的人在服务主机的交互式终端中执行：

1. 确认部署版本及正式 `.env` 指向正确的数据库，按照备份流程创建备份。
2. 在 `backend` 中执行 `uv run python ../scripts/set_password.py <管理員帳號>`，在隐藏输入提示中输入两次新密码（12–128 个字符）；不要把密码放在命令参数或管道中。恢复既有管理员时不加 `--create-admin`。
3. 工具会撤销该账号所有 session，清除“须修改密码”与登录锁定；重新登录后确认角色与品牌。工具不会启用已停用的账号，也不会改动角色。`--create-admin` 是首次初始化的备用做法（平时用网页的首次设置），数据库还没有品牌时会一并创建唯一的品牌（`--brand` 或交互式询问）。

## 数据转换工具

数据转换一律默认只读试运行（dry-run），确认结果后才加 `--apply`；正式 apply 由部署操作人在备份后执行。

### 私信数据清理（purge_direct_messages.py）

LINE inbound 验签后返回 200 并丢弃；LINE_CHANNEL_ACCESS_TOKEN／LINE_BOT_USER_ID、SCHEDULER_DM_ENABLED／META_DM_* 已退役，既有 env 可以保留但不会使用。LINE 通知及 NOTIFY_LINE_*、`/webhook/line-notify` 不变。

部署操作人须先备份 SQLite 与导出文件夹，安排停止写入的维护时段，再明确指定同一套数据库／导出目录，先试运行核对清单后才 apply：

```powershell
cd backend
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄>
uv run python ../scripts/purge_direct_messages.py --database <資料庫完整路徑> --export-root <匯出根目錄> --apply
```

脚本不加载 .env 或应用配置；database 为必填且必须已存在，未提供 export-root 就不删除文件。默认只读试运行，列出各表行数、文件与无法判定的 raw event ID。apply 使用单个 BEGIN IMMEDIATE，按外键顺序删除 DM 及相关数据、所有历史草稿、只出现在 DM 中的 contacts，保留混合联系人、评论、帖子、ideation 报告、audit_log 与设置。混合通知 delivery 含缓存私信时删除该缓存，公开评论的 notification 保留并解除 delivery 关联。纯 DM 的 raw payload 才删除；混合或来源未知的保留，留待另行决定。

导出只删除 DM 专属联系人目录内对应的 Markdown／Word，以及以 DM thread ID 命名的历史 Word；ideation 文件不删除。与保留联系人前缀冲突的文件不删除；遇到符号链接或 junction 时中止。文件操作失败会回滚数据库并写回本轮已删除的字节；文件系统和 SQLite 无法共同保证断电原子性，部署备份不可省略。删除前后的外键检查须为空，审计 `data.purge_dm` 只记录各表／文件的数量；重跑时删除数为零且不再写审计。删除前的备份是数据恢复的来源。

### 平台数据保留（data_retention.py）

按照平台条款删除不再允许保存的数据：所有平台中自工作台获取起超过 `COMMENT_RETENTION_DAYS`（默认 365）天的评论（按获取时间计算，不是评论发布时间）及其相关数据（分类、通知与投递缓存、无人引用的联系人）、同一期限的 webhook 原始事件内容（只清除原文，保留平台事件 ID，平台重发旧事件时视为已处理，不重建评论）；YouTube 30 天未再获取的评论，以及在 YouTube 上已删除超过 30 天的视频（含数据快照与缩略图）。选题策划报告只移除被删除的引用原文与帖子说明，选题保留；用户自己的发布记录保留。已导出的 Markdown／Word 不会被改动，需要时由操作人另行删除。

每日计划任务默认关闭。部署操作人先在 master 上部署并执行 `./scripts/backup.ps1`，再在**项目根目录**试运行查看数量（只读，不打印原文）。`--project backend` 让 uv 使用后端的环境；配置一律读取项目根目录的 `.env`，与当前所在文件夹无关：

```powershell
uv run --project backend python scripts/data_retention.py
uv run --project backend python scripts/data_retention.py --enable
```

帖子数据的评论区会根据同一份配置显示各平台的保存期限，以及每日删除是否已启用。确认 `would_delete` 后才加 `--enable` 启用；之后每天最多执行一次，每批最多 500 条、各自提交（第一次启用时数据量大也不会长时间锁住数据库），每批写入一条 `data.retention` 审计（只记录各表数量）。

评论者发邮件要求删除时（隐私政策承诺 7 天内处理），先备份，再按名称找出联系人、预览、确认后删除；只删除该人自己的评论与联系人，别人在其下的回复保留，报告移除其引用原文，审计 `data.delete_request` 只记录数量：

```powershell
uv run --project backend python scripts/data_retention.py --find-commenter <名稱>
uv run --project backend python scripts/data_retention.py --delete-contact <id>
uv run --project backend python scripts/data_retention.py --delete-contact <id> --apply
```

YouTube“断开连接”会撤销 Google 授权，并立即删除已同步的 YouTube 视频、快照、缩略图、评论与报告中的 YouTube 引用，频道账号行保留但名称改为“YouTube”（YouTube API 政策要求撤销后 7 天内删除）。

Gemini 免费方案的内容会被 Google 用于改进产品，并可能由真人审阅，因此工作台不让它处理任何数据：`GEMINI_PAID_TIER` 默认为 false 时，Gemini 在菜单中显示为不可用，后端执行时返回 `provider_unpaid_tier`，计划报告改用品牌的后台供应商或第一个可用的 API。只有在 Google Cloud 项目已绑定结算账号后才设为 true。

### 分类指纹重新标记（restamp_classifications.py）

部署者先备份，核对历史版本后执行 `uv run python ../scripts/restamp_classifications.py --database <資料庫路徑> --shared-revision <版本> --brand-revision <版本>`。两个版本都是必填，0 表示当时没有该 scope 的 prompt；正数从 prompt_versions 读取，缺少版本则整次失败。多品牌时各自按自己的 scope 查找相同版本号，只有完全符合旧指纹的行才会处理。确认 total／matched／updated／unmatched 后才加 `--apply`；单个 BEGIN IMMEDIATE 事务只修改相符行的 input_hash，每行写入 `classification.restamp` 审计，重跑不会再更新。此工具不读取 .env、不启动 worker、不调用平台或模型。

## 功能设置与操作备忘

**AI 供应商与 Agent 撰写**：文本模型只使用 Gemini、OpenAI、Anthropic 的官方 API 密钥；本地 CLI 已移除，读到旧的 CLI 设置一律视为未设置，管理员到“设置 → AI → 基本”选择 API 供应商并保存。选题策划可选“交给 Agent 撰写”，报告停在“等待 Agent 撰写选题”后，在 Claude Code 中用 `/mwb:ideas`、或在其他 Agent 中用 `get_guide("ideas")` 接手；报告页的“交给 Claude Code”“打开 Claude 对话”“打开 Codex”按钮通过官方 `claude://`、`codex://` 链接打开桌面 App，并预填含报告编号的指令（仍需自己发送），Antigravity 等其他 Agent 用“复制给其他 Agent”，24 小时内未存回就会失败。例会计划报告固定使用 Gemini API。旧的 `mode=subscription` 用量记录保留显示，不计入预算。

**AI 备用与配额**：每家的备用模型可以留空以停用；`AI_API_TIMEOUT_SECONDS` 控制主模型加备用的整次时间（规则见 architecture 的“AI 与消息分类”）。Gemini 免费方案额度用完时不重试也不切换备用，长期使用建议在 Google AI Studio 为项目设置付费结算；更换同一项目的密钥或备用模型都不能解除额度限制。

**评论按需读取**：只有用户在帖子上点击“抓取评论”才会创建一次性任务；`SCHEDULER_COMMENTS_ENABLED`／`COMMENTS_WAKE_ENABLED` 控制执行与唤醒，`META_API_CALLS_PER_HOUR` 控制共享的调用预算。`META_COMMENTS_AUTO_DAYS` 已被忽略。

**粉丝数**：metrics 计划任务每天对每个账号发一次 GET。没有第一条快照时，检查计划任务结果中的 `followers.errors`、账号登记、官方字段权限及预算／冷却；不要把 `fan_count` 当成粉丝数填入，也不要以零值替代。需要 `SCHEDULER_ENABLED`、`SCHEDULER_METRICS_ENABLED` 与界面上的 metrics 计划任务开关。

**Obsidian 评论导出**：路径存在 Setting 中，默认 `<專案根目錄>/社群留言`（已被忽略），管理员可以改为通过写入检查的独立文件夹；与一般导出共用 EXPORT_WORKER_ENABLED。`backup.py` 的加密备份包含 Obsidian 文档与哈希；还原的数据在新目的地的 `obsidian/` 中，由部署操作人核对后另行设置路径，不会自动覆盖既有笔记。备份目的地不得与评论文件夹重叠。

**平台凭证**：平台及 jev 凭证可以由管理员在设置中保存并即时生效；主密钥需要部署者先设置，未设置时会安全地拒绝保存。删除数据库中的值即回到 env。`platform_credentials.py`／`platform-credentials.mjs` 是本机配置桥接 helper，只在操作者另行运行平台工具时使用。

### 登录 Windows 后自动启动

工作区设置中的“开机自动启动”默认关闭，只有管理员可以查看与切换；状态直接查询 Windows 任务计划程序。打开后会创建根目录任务 `MWB-AutoStart`：当前 Windows 用户登录时（AtLogOn）延迟 45 秒，Interactive、Limited、不要求提升权限，允许使用电池运行，MultipleInstances 为 IgnoreNew，上限 30 分钟。操作为 `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`，参数 `-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "<專案>\scripts\start-all.ps1"`，起始目录为项目根目录。需要先登录 Windows，网络与 Google Drive 也必须就绪；不会补发离线期间的通知。刚登录时网络常常还没准备好：`tailscale.mjs check` 会每 10 秒重试、最多约 2 分钟，仍失败只显示警告，服务照常运行（本机地址可用）；Webhook 公开边界检查 `webhooks.mjs check` 同样会重试，仍失败就停止本次启动的服务。重启后残留的 `.runtime/*.pid` 如果指向比记录更晚创建的进程，会被视为过期记录并自动移除。

在“任务计划程序库”中找到 MWB-AutoStart 核对上述设置。关闭开关会移除此任务，不会停止已启动的服务。同名任务有任一设置不同时，打开与关闭都会返回 `autostart_conflict`，请先人工确认其归属。项目搬移后需要人工确认旧任务再重新创建。参考 [New-ScheduledTaskSettingsSet](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)、[New-ScheduledTaskPrincipal](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal)。

### 改用其他端口

后端默认 `127.0.0.1:8000`。第一次启动（还没有 `.runtime/start-fingerprint.txt`）且在交互式窗口中运行时，`start-all.ps1` 遇到端口被占用会询问要改用哪个端口，并把下面两个值一起写入 `.env`；之后的启动或非交互式运行只会报错并停止。同一台电脑要同时存在两份工作台（例如另装一份来测试首次安装）时，其中一份要在 `.env` 中同时修改 `BACKEND_INTERNAL_URL`（例如 `http://127.0.0.1:8010`）与 `APP_ORIGIN` 的本机地址，两者端口不同时 `start-all.ps1` 会拒绝启动。已设置 Tailscale 的要重新执行 `tailscale serve --bg --https=443 --yes <新網址>`（`tailscale.mjs configure` 不会覆盖指向旧端口的代理），ngrok 的 4040 管理端口仍是固定的，两份不能同时启动 Webhook 网关。

## 数据位置

正式数据集中在项目的 `data/`（git 忽略）：`data/db`（数据库）、`data/export`（导出）、`data/logs`（后端与 MCP 审计日志）、`data/manual-backups`（部署前的手动备份）、`data/legacy`（待清理的旧残留）。本机加密备份放在项目外的 `BACKUP_LOCAL_ROOT`，另一份在 `BACKUP_DRIVE_ROOT`。导出文件夹不可放在程序目录中，`.runtime/` 与 `data/` 的子文件夹除外（`data/` 本身不可以）。禁止执行 `git clean -x` 等会删除被忽略文件的命令。

## 备份与回退

`backup.ps1` 使用 SQLite backup API 和 7-Zip AES-256，目的地由 `BACKUP_LOCAL_ROOT`／`BACKUP_DRIVE_ROOT` 指定，各保留最近 14 份。`install-backup-task.ps1` 安装每日计划任务；如果已有旧名称的任务，核对并移除旧任务后再安装，避免重复执行。

备份格式为 `mwb-backup-v1`；旧格式请用备份当时的程序在隔离目录中还原，不要直接覆盖正在使用的数据库。`backup.ps1 -Action restore -Archive <ARCHIVE> -Destination <NEW_DIRECTORY>` 只接受尚不存在的目的地。

回退时先停止服务、备份转换后的增量，再用自动备份和相符的程序版本在独立目录中恢复。保留服务切换后的新数据，不可直接覆盖导致丢失。Git 历史不改写。

## 健康监测与排错

后端每五分钟检查计划任务调度器、公开签名 probe、验签失败量，保存 24 小时的历史；中断／恢复各告警一次。整台主机离线需要外部监控。

- 登录失败：检查 APP_ORIGIN、ALLOWED_HOSTS、Tailscale 域名及 Secure Cookie。
- 无法收信：检查固定公开网址、ngrok policy、控制请求头、签名与后端健康状态。不得暴露 UI/API 来绕过防护。
- 后台任务没有进度：检查 SCHEDULER_* 开关、租约、平台官方限速与权限，不要重置游标来冒充完成。
- 导出失败：检查独立的绝对路径、PROTECTED_PATHS、写入权限、加密主密钥与可用磁盘空间。

### AI 错误代码

| 原始代码 | 给用户的说明 |
|---|---|
| provider_http_503（Gemini） | Gemini 当前流量过高（Google 端问题）；等待中显示自动重试时间 |
| provider_http_429 | 当前请求过多或配额已达上限 |
| provider_quota_free_tier | Gemini 免费方案额度已用完，请到 Google AI Studio 开通付费方案，或稍后再试 |
| provider_rate_limited | 供应商请求过于频繁或配额已达上限；有建议秒数时显示约 N 秒后可再试 |
| provider_quota_exhausted | 供应商额度不足，请检查供应商的结算与用量上限 |
| provider_time_exhausted | 模型响应超时，请稍后再试 |
| provider_http_500／502／503／504 | 供应商服务暂时不可用 |
| provider_http_408／provider_timeout | 供应商响应超时 |
| provider_connection_error | 暂时无法连接到供应商 |
| provider_http_401／provider_invalid_key | API 密钥无效，请到 AI 设置更新 |
| provider_http_403 | API 权限不足，请检查密钥与模型访问权限 |
| provider_http_402 | API 额度不足，请检查供应商的结算 |
| configuration_missing／provider_unavailable | 尚未设置或供应商尚未开放，请到 AI 设置更新 |
| provider_unpaid_tier | Gemini 免费方案不能处理平台数据；改用其他供应商，或绑定结算账号后设置 `GEMINI_PAID_TIER=true` |
| monthly_budget_exceeded | 本月 AI 预算已达上限 |
| incomplete_output／empty_output | 模型未完成／内容被拒绝，或未返回文本 |
| input_too_large／output_too_large | 输入或响应过长 |
| provider_failed／generation_failed | AI 内容生成失败，请检查设置 |

错误字段可以附带 `;retry_after_seconds=N`，界面显示向上取整的约 N 秒；这是建议的重试时间，而非可用性保证。

### 数据库锁定的日志判读

`scheduler_tick_failed`、`receive_health_check_failed`、原生 worker、Webhook、导入与导出等异常都会记录 `error_type`；SQLite busy／locked 另有 `error_code="database_locked"` 及数字 `sqlite_errorcode`。只记录类别与代码，不记录异常消息、traceback、SQL、参数、第三方原文或生成内容。`DatabaseBusy` 是有限等待耗尽后的安全 503，原始 SQLite 类别／数字可以在同一次的 `database_lock_exhausted` 事件中查到。

- `sqlite_errorcode=517`：WAL 读取快照已过期，写入升级立即失败；不要只提高 busy timeout，应检查该路径是否先结束了读取事务、是否在查询前使用写入边界。
- 基础代码 5（BUSY）、6（LOCKED），或扩展代码的低八位为 5／6：锁竞争。检查是否有长事务、批量导入或同时工作的 worker。
- `database_lock_retry` 的 `attempt` 为 1–3；最终失败另记 `database_lock_exhausted`。这是 BEGIN 获取锁的三次上限，不会再次调用模型／平台。持续发生时由授权的部署者核对所有写入者的版本及事务范围，不要直接修改正式数据或发送开关。

503 的中文消息由前端错误区显示，可以等锁解除后重试。异步报告已返回 202 时，持续锁定可能连 failed 状态也无法存入数据库；同一进程会保留 processing、显示暂时的保存错误并允许重试（最多 128 条内存标记，重启后回到原有的租约到期判断）。未保存的结果需要人工重试。
