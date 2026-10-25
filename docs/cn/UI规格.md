# UI 规格

> **语言 / Language / 語言 / 言語**：[繁體中文](../zh-tw/UI規格.md) | 简体中文 | [English](../en/ui-spec.md) | [日本語](../jp/UI仕様.md)

## Agent 安装（agentpack）

- 在“我的账号”的密码表单与 Agent 连接之间加入 `.agent-install`，h3“安装 Agent”与 compact `SegmentedControl` 同行，用来切换 Claude Code／Codex／Claude 桌面版；所有角色可见，窄屏时控件换到下一行，宽度与卡片对齐。
- 每个 `.agent-install-command` 只有一行命令 code 和 `.secondary` 复制按钮，窄屏时命令可换行；复制成功后按钮变为“已复制”。Claude Code 的两条安装命令根据当前 location.origin 拼出，下方只保留一句自动更新说明。
- Codex 使用 `.secondary.agent-install-download` 下载 skills／config 包，列出解压命令、一句 skills 放置位置与 config 合并说明，以及 OAuth 登录命令；不在界面上列出所有工具设置。版本由现有的 workspace/identity API 提供。
- 通过 http://127.0.0.1 访问时显示 `.notice.agent-install-origin`，提示其他成员使用内部 HTTPS，链接由同一 API 的 backoffice_origin 提供，不写死主机。
- 命令使用 text-main／bg-subtle／ui-font-mono／help，说明使用 text-subtle／bg-surface；圆角使用 control Token，其余沿用 P1-1 与共用组件，零外部资源。1440／768／390px 不水平溢出，check_agent_auth 等数据、字体与布局稳定后才测量，check_ui_contrast 覆盖所有新增配对。
- Claude 桌面版只有 `.secondary`“下载桌面扩展”和三步清单：安装文件、填写工作台网址、粘贴连接令牌；网址与复制按钮同行，显示 location.origin，HTTPS 时可直接复制。127.0.0.1 的 HTTP 沿用来源提示，第二步同行建议成员使用内部 HTTPS、本机使用 <http://127.0.0.1:8000>；不增加小标题，沿用上述文字与底色 Token。

## Agent 选题与脚本（agentquery）

- 报告列表的 `.report-row-state` 与报告页的 `.report-heading-meta` 同行显示 `.agent-source-chip`“来自 <连接名称>”；脚本 `.script-heading` 在 h2 旁使用同样的胶囊，宽度与所在区块对齐并自然换行。
- awaiting_ideas 显示“等待 Agent 撰写选题”，报告页用一段 `.agent-awaiting` 说明证据已汇总、在对话中定稿后存回，以及 24 小时期限；此状态不显示导出或重新生成，可删除。轮询能接收 MCP 存回后的 ready 状态。
- 来源使用 text-subtle／bg-subtle、help 字号与 control 圆角；等待说明使用 text-subtle／bg-surface。只用 P1-1 Token，零外部资源；1440／768／390px 无水平溢出，配对纳入 check_ui_contrast。
- 选题／脚本页的提交用 primary；取消、重新标注、分镜增减、套用历史版本、脚本查看与下载、创建／打开发布草稿用 secondary；删除用 primary danger。本节覆盖下方历史按钮规则。

## 新版本提醒

- 已登录画面每 5 分钟及窗口重新获得焦点时，比对服务器 `index.html` 引用的主程序文件名；与当前加载的不同时，右下角显示 `.update-notice`：“工作台已更新”＋`.secondary`“刷新”。手机版放在底部导航上方。开发模式不检查。

## Agent 连接与批准（agentauth）

- 批准画面为 `.agent-approval-page > .section-card.agent-approval`，只有 h1 与 `.agent-approval-details`；应用自称名称、回调地址、当前成员／角色、可执行的操作各占一行。查看者只列查询；管理员与营销人员列查询、创建草稿，以及需另行确认的发布。批准用 primary、拒绝用 secondary，以同源表单带现有 CSRF 值提交；未登录与须改密码沿用原画面，网址保留授权请求。响应 DENY 防止被框架嵌入，批准页的 same-origin referrer policy 保留原生表单的 Origin 检查。
- 在“我的账号”的密码表单后加入 `.agent-connections`，标题与 secondary“创建连接令牌”同行，宽度与卡片对齐。创建沿用 `.member-dialog`，只有名称和 primary 创建；成功后 `.agent-token-row` 显示一次完整令牌，以及 secondary 复制／关闭。值只留在组件内存中，关闭或卸载即清除；不放入网址或浏览器存储。
- `.list-box.agent-connection-list` 每行 `.agent-connection-row` 同行显示名称、OAuth／连接令牌胶囊与 primary danger 撤销；创建、最后使用及到期时间合并为一行，以 Asia/Taipei 显示，30 天未使用即失效。撤销使用 ConfirmDialog，“取消”先获得焦点，支持 Escape／Tab 与焦点还原。
- 成员行新增 `.member-connections`，连接数与 secondary“全部撤销”同行；零条时停用，提交前使用 ConfirmDialog。900px 以下各行自然排成两栏，390px 时连接控件占满整行；回调、名称及令牌可换行。
- 只引用 P1-1 色彩／字体、control／card 圆角 Token，零外部资源；1440／768／390px 无水平溢出。文字与底色配对列入 check_ui_contrast；check_agent_auth 等数据与字体稳定后测量，截图中的一次性令牌以中性遮罩显示。

## 发布（publish）

- Agent 草稿、编辑与定时发布在现有格式行中同行显示 `.agent-source-chip.publish-agent-source`“来自 <连接名称>”；发布记录优先显示确认发布的连接名称，否则显示草稿来源。选题来源胶囊保留。编辑来源放在 `.publish-editor-heading`，不新增小标题或说明行。使用 text-subtle／bg-subtle、help 字号与 control 圆角；长名称自然换行，1440／768／390px 无溢出。

桌面侧栏与手机底部依次为仪表盘、帖子数据、选题策划、发布、设置，共五项。发布以 `view=publish` 保留刷新与返回状态；本节覆盖下方旧版四项导航规则。

- `.publish-page.settings-page` 保留唯一的 PageHeader“发布”，右侧 `.publish-switch` 为 ready／neutral 胶囊及管理员的 secondary 开关。关闭时顶部 `.notice.warning` 显示“发布功能尚未开启，帖子只能保存为草稿”。品牌与各账号同行，自然换行。
- `.publish-tabs` 为下划线 tablist，依次为新建帖子／快拍／草稿／定时中／发布记录，以 tab、tabpanel、aria-controls、roving tabindex 关联，支持左右方向键、Home／End。查看者只显示发布记录。
- composer2：新建帖子／草稿编辑上方的 `.publish-composer-tabs` 为通用、Facebook、Instagram、Threads、YouTube、TikTok 六个分页，支持 tab／tabpanel、方向键与 Home／End；平台标签合并了发布开关。已就绪平台为绿色，未连接／令牌失效及不支持的平台为灰色，开关停用但分页可进入，显示“尚未连接”及 secondary“设置 → 平台连接”，沿用 settings_tab=connections 导航；TikTok 分页与 YouTube 一样只支持视频：非视频格式时开关停用（title“仅支持发布视频，图文需从 App 上传”），分页只显示同一句话；视频时显示 TikTok 文案与 `.notice.tiktok-caption-notice`“收件箱不会带入文案…”，没有其他选项。确认弹窗中的 TikTok 项目为“视频 · 发送到 TikTok 收件箱（文案不会一并发送，需在 App 内粘贴后发布）”。发布记录中 TikTok 的成功行加 `.status-badge`“已发送到收件箱”（pending）／“已在 App 发布”（ready）／“TikTok 处理中”，以及 secondary“复制文案”（复制 TikTok 文案，未覆盖时用通用文案，按下后显示“已复制”）。平台未开启时仍可编辑，并标示“未开启”。
- composer3：快拍只有 Facebook／Instagram 两个平台分页与标签开关，连接颜色、停用及设置引导沿用 composer2。每份 1–10 条，每条一张图片或一个视频，支持拖曳、secondary 上移／下移及 primary danger 移除；没有文案、格式或帖子选项字段，沿用自动保存，只保留发布／定时发布提交按钮；规格原因合并在同一处红字中。9:16 预览以 secondary 上一条／下一条切换并显示条数；非 9:16 只提示会加边，IG 视频 3–60 秒、图片 ≤8MB（PNG 以警告提示“Instagram 会自动把 PNG 转为 JPEG，透明背景会变成白底”，其他非 JPEG 格式为错误）、FB 视频 ≤60 秒，错误以红字阻止发布。立即发布／定时发布的确认列出平台、账号、条数、素材及时间。记录标为“快拍”，展开后逐条显示 IG 效果／最终值，缺值显示“—”；FB 显示“Facebook 不提供快拍数据”，不增加仪表盘信息。部分成功后锁定素材，重试时显示已发布条数与失败位置。
- `.publish-composer-grid` 左侧编辑、右侧预览；通用分页放格式、通用素材及主文案，平台分页放默认跟随通用的文案，一经修改即为专属，secondary“恢复为通用文案”恢复跟随。FB 视频形式为视频帖子／Reels（新草稿默认 Reels，旧稿沿用 feed），不公开选项放在 FB 分页；IG 视频用“同时显示在动态”开关，默认开启；其下 `.publish-thumbnail.publish-cover` 同行放“Reels 封面”、54px 高的 9:16 封面预览、文件名与大小（尚无封面时为 text-subtle 小字“JPG／PNG · 8 MB 以内 · 建议 9:16 · 未上传则使用视频第一帧”）、secondary“上传封面”／“更换封面”与 primary danger“移除封面”（文件输入 aria-label“上传 Reels 封面”）；封面作为 IG 预览视频的 poster，非 9:16 或 PNG 只以 `.notice.warning` 提示。IG 已成功／发布中时封面按钮停用。确认弹窗的 IG 视频项目为“Reels · 同时显示在动态／不显示在动态 · 自定义封面／默认封面”。FB 视频在“保存为 FB 草稿”下方有 `.publish-thumbnail.publish-cover.publish-facebook-cover`“视频封面”行（54px 高、按原比例、最宽 96px；尚无封面时小字“JPG／PNG · 8 MB 以内 · 建议与视频同比例 · 未上传则由 Facebook 自动选择”；按钮同 IG，文件输入 aria-label“上传 Facebook 视频封面”），缺少 pages_manage_engagement 时在该行内加 `.notice.publish-cover-hint`（中性提示，不是警告）“自定义封面需要 pages_manage_engagement 权限，请重新连接 Meta”；封面作为 FB 预览视频的 poster，比例与视频不同时只提示。确认弹窗的 FB 视频项目为“视频帖子／Reels · 自定义封面／默认封面（· 草稿）”。发布记录中 FB 成功但封面失败时，同行显示 `.status-badge.pending`“封面未应用”、中文原因与 secondary“重新应用封面”（确认弹窗“重新应用封面到 Facebook？只会更换封面，不会重新上传视频。”；查看者看不到按钮）。已成功／发布中的平台及已部分发出的 Threads 选项会锁定。
- `.publish-preview` 使用品牌首字头像、账号名称、文字与本机素材，不加载外部资源。通用预览只列出已开启平台的 secondary 小按钮；平台分页固定显示本平台。文字按简化的字数／行数阈值折叠，以 secondary“更多／收起”切换；@／hashtag 使用 link-color，Threads 显示第一个话题标签及首段／回复串文，素材只在首段。IG 图片用 4:5，正方形用 1:1，Reels 用 9:16，FB 视频帖子／Threads 沿用原比例。视频一律完整显示（contain），框与视频比例不同时以 `--media-letterbox` 补边（例如竖版框里的横版视频上下补边），因为发出的是原文件、平台不会裁切；图片保持填满。≤767px 时预览放在编辑区顶部，1440／768／390px 无水平溢出。
- Threads 分段优先按空行、换行、句号，再硬切；Unicode 计数数据与测试向量放在 shared/publish_threads_vectors.json，由 pytest 与前端共同验证。自动模式实时跟随来源文案，手动修改／新增／删除后即停止重算，最少显示一段；每段一行，显示段数／字数／primary danger 删除段。secondary“按主文案重新分段”先用 ConfirmDialog 确认覆盖，发出的文案不加编号。
- 平台分页以红字显示字数、hashtag、@、素材长度／比例规则错误，分页标签加红点；后端提示以 notice warning 显示。任何已开启平台有阻挡错误时均停用发布。错误只显示在一处：`.publish-footer` 第一行的 `#publish-disabled-reason`（红字、独占一行，位于“立即发布／定时发布”与提交按钮上方），按“平台：原因”格式以“；”串接，列出已开启的平台，加上当前正在查看但未开启的平台分页；分页内不另列错误清单，只保留分页标签红点。Threads 字数超限只标在输入框下方，不在这里重复；只剩这类错误时显示“请先修正上方标出的错误”。发布功能未开启时只显示“发布功能尚未开启”；没有开启任何平台时以“请开启要发布的平台”开头，后面接当前分页的错误。按钮 title 保留完整原因。publish-actions 保留唯一的 primary 发布／定时发布及 secondary 保存为草稿；确认弹窗逐平台列出形式、IG 动态选项、FB 不公开、Threads 段数及账号／文案／素材／时间。记录中 Threads 的 detail 进度显示“已发 N／M 段”。
- 新建帖子初始只有空白表单。首次输入文案／平台后延迟自动保存，首次上传或保存为草稿时立即保存；切换分页／导航前完成未保存内容的保存。单独选择格式不会创建草稿。`publish_post_id` 在跨页网址中保留当前草稿；secondary“新帖子”先保存再清空，单纯刷新不会增加草稿。
- 发布页没有 AI 撰写文案的界面：主文案上方没有进度、未通过或完成提示，也没有“重新撰写”“套用 AI 文案”，草稿列表没有“AI 撰写中”。旧草稿即使数据库中带有文案任务数据，画面也不显示 AI 状态。从选题创建的草稿，主文案是由标题、开场与 hashtag 组成的初稿，可直接修改。
- 草稿使用 `.list-box.publish-records`，每行显示最后修改时间、格式／来自选题／AI 撰写中胶囊、单行省略的文案、媒体数量、平台与 secondary 编辑／primary danger 删除。删除需 ConfirmDialog。没有文案、媒体、平台的历史空白草稿只隐藏；发布记录只列出已发出、失败或错过的帖子。
- `.list-box.publish-records` 内的 `.list-row.publish-record` 同行显示时间、格式、文案开头、平台、状态；定时发布在前一分钟锁定。以“不公开到公共主页”发出的 Facebook，在平台名称后以“ · 不公开”标示（列表行与各平台结果都有）。记录可展开 `.publish-targets`，显示成功链接／安全的中文原因，Facebook 不公开且成功的结果胶囊为 `.status-badge.neutral`“Facebook · 成功 · 不公开”（与“已在平台删除”同色系，失败或进行中仍用原本的颜色并加同样后缀），失败时只重试失败的平台，已错过的可立即发布或重新定时。删除草稿为 primary danger 并需确认，其余操作为 secondary。
- 色彩、字体、圆角只引用 P1-1／共用 Token，零外部资源；文字与底色配对纳入 check_ui_contrast。1440／768／390px 无水平溢出，手机五栏导航保留安全区，check_publish 等数据、字体与布局稳定后测量。

## 平台 OAuth 连接（metaoauth）

- 平台连接依次显示 Meta、Threads、YouTube、TikTok、LINE 通知、jev。Meta／Threads 卡片顶部 `.oauth-account` 同行显示账号名称、IG 用户名、状态胶囊与台北时间的到期时间；ready 为已连接、pending 为即将到期、neutral 为未连接、failed 为缺少权限／失败。缺少的权限列在 `.notice.danger.oauth-permissions`，权限名称自然折行。
- 每张卡片保留次要按钮“测试连接”，强制重新检查；连接／重新连接为主要按钮（Threads 只缺数据权限时改为次要，见 threadsdata）。有多个公共主页时，`.oauth-page-choice` 用下拉框与主要按钮“使用此公共主页”取代连接按钮。非内部 HTTPS 来源时停用连接，并显示 `.notice.oauth-origin`，网址由 API 提供。
- 首次设置步骤与回调网址已移到“设置教程”弹窗（见 guides），卡片上不再重复显示；`.oauth-manual` 折叠“手动设置（高级）”，保留原有具名的凭据表单、遮罩、版本与密码输入。Threads 的应用编号与密钥直接显示，其余字段折叠。回调结果只使用固定中文的 `.notice.success`／`.notice.danger`，移除结果网址参数，不在浏览器中保存令牌。
- 采用 P1-1 色彩与系统字体 Token、现有 control／card 圆角，零外部资源。控件行自然换行，网址与权限 overflow-wrap；1440／768／390px 不水平溢出。新增配对纳入 check_ui_contrast，check_meta_oauth 验证连接、选择公共主页、缺少权限、Threads、非后台来源与教程。

## 平台设置教程弹窗（guides）

- Meta、Threads、YouTube、LINE 通知卡片与 TikTok 卡片的标题行右侧，在“测试连接”前各有一个次要按钮“设置教程”（jev 没有），按下后打开站内弹窗，不打开新的浏览器标签页；卡片与页面本身不得有 `target="_blank"` 链接（只有弹窗内的后台超链接例外，见下方）。回调网址与 Webhook 网址只在弹窗内显示与复制，卡片上不重复。
- `.ideation-modal-backdrop > .guide-dialog` 挂在 body 上：`role="dialog"`、`aria-modal`、`aria-labelledby` 指向标题；标题行固定，右上角为次要按钮“关闭”，内容 `.guide-body` 自行滚动。打开时焦点在“关闭”，Tab 在弹窗内循环，Esc、关闭、点击遮罩都能关闭，关闭后焦点回到“设置教程”按钮。390px 时满屏（无遮罩边距、高度 100dvh），内容可滚动且不水平溢出。
- 内容在 `frontend/src/platformGuides.ts`，写给第一次接触开发者后台的人（guides2 改写）：每份教程有预计时间 `minutes`、“开始前你需要” `needs`、可折叠的“名词小词典” `glossary`，以及分节步骤；每步只做一件事，按钮与菜单用「」标出实际界面用语，不确定时附“（英文界面为 …）”。步骤可带 `check`（“✅ 完成后会看到”，`.notice.success`）与 `trouble`（“⚠️ 遇到问题？看这里”，`.notice.warning`）。Meta 分为“Facebook 公共主页”“Instagram”“连接账号”三节。除 TikTok 外，最后一步都是“回到工作台…”：Meta、Threads、YouTube 说明“已连接”与每小时同步，LINE 说明“测试连接”“连接成功”。
- 弹窗开头 `.guide-intro`：“大约需要 N 分钟”、“开始前你需要”清单与默认折叠的 `details.guide-glossary`（“名词小词典”）。步骤 `.guide-steps` 用小方块编号（`::before` 计数，跨小节连续）；网址或权限以 `.guide-copy`（`<code>` 加次要按钮“复制”，成功后显示“已复制”）呈现，回调网址取自 `/api/oauth/status` 的 callbacks，LINE Webhook 网址取自设置中的 WEBHOOK_PUBLIC_URL，未设置时显示“尚未设置”并停用复制。步骤可带 `links`，在 `.guide-links` 列出直达平台后台的超链接（developers.facebook.com、console.cloud.google.com、manager.line.biz、developers.line.biz、developers.tiktok.com 等），`target="_blank"`、`rel="noopener noreferrer"`。内容不放真实账号、姓名或本机路径。
- TikTok 卡片与 YouTube 排版相同（`.connection-card`）：账号行与状态胶囊、“访问令牌自动续期”说明、refresh token 的台北时间到期时间；Client key／Client secret 两个凭据字段直接列在卡片上（没有“手动设置”折叠），未设置前“连接 TikTok 账号”停用；已连接时 secondary“断开连接”经 ConfirmDialog 说明会删除已同步的数据、不影响 TikTok 上的视频。卡片最后一行 `.notice.tiktok-comments`“评论（可选）”说明读取评论需要企业身份。教程带用户在 Sandbox 创建应用并连接，回调网址与四个权限各自可复制；范围见 `docs/cn/TikTok规划.md`。
- 配色只用现有 Token：正文与开头信息 text-main／bg-surface，词典说明 text-subtle／bg-surface，网址区块与“常见问题” text-subtle／bg-subtle，“完成后会看到” state-success／bg-subtle，步骤编号 bg-surface／brand-primary；圆角 control／card；零外部资源，已纳入 check_ui_contrast。检查见 `check_platform_guides.py`（五份教程的标题、开始前需要、确认点、词典展开、复制、Esc／遮罩／关闭、焦点还原、卡片无新标签页链接，以及弹窗内后台链接的域名及 `target`／`rel`；三种宽度下展开词典仍无水平溢出、滚动到底能看到最后一步且标题行固定；截图 `.runtime/guides2-screens/`）与前端 `platformGuides.test.mjs`。

## 帖子数据立即同步（metricsync）

- 管理员／营销人员的帖子数据页首以 secondary“立即同步”取代“刷新 ↻”，安排一轮帖子与效果数据同步；查看者仍只有“刷新 ↻”（只重新读取工作台数据）。执行中显示“同步中…”，已排入时显示“已加入同步队列…”，冷却中显示“立即同步（N 秒）”并停用，秒数以后端 `retry_after` 为准。完成后自动刷新并以 sync-notice 告知；每小时的定时任务跑完不会自动刷新。

## 帖子数据效果面板宽度（metricwidth）

- 2026-10-23 起由下方 postcenter 取代：效果改放在中间。原规则：桌面单篇详情右侧的效果面板（`.post-metrics`）固定 380px，左侧列表 320px，中间评论栏自动。数据快照表沿用每格 16px 文字内边距，抓取时间“2026/10/21 13:04”与指标栏名在 1440px 宽时都排在同一行；百万级数字时抓取时间可在日期与时间之间换行，但不可拆开日期或水平溢出。

## Threads 帖子数据（threadsdata）

- 帖子数据的 Threads 分页与 FB／IG 行为一致：帖子列表与发帖日期筛选、单篇“帖子效果”与只读的“评论与回复”（评论日期、显示更多同其他平台）；管理员／营销人员同样有“抓取评论”“完整重抓”“停止”，评论同步卡标题为“Threads 回复”。没有新增控件、小标题或说明行。
- 效果只显示 Threads 有的六项，依次为“浏览量、点赞、回复、转发、引用、分享”（回复即 comments 字段，转发与引用读取快照 extra_json）；覆盖人数与收藏不显示。数据变化曲线的指标下拉为同样六项，默认“浏览量”，快照表的栏位为“抓取时间、浏览量、点赞、回复”。“—”代表平台尚未提供，0 代表平台返回零；FB／IG 维持原来的六项与栏位。
- 设置页的 Threads 卡片：已连接且发布权限齐全，但缺少 `threads_manage_insights`、`threads_read_replies`（既有连接尚未取得）时，`.oauth-account` 下方显示 `.notice.warning.oauth-permissions`“需要重新连接以获取数据与回复权限”，状态胶囊维持“已连接”，连接按钮“重新连接”改为 `.secondary`；发布不受影响。取得权限后提示消失，按钮恢复为主要按钮。缺少发布权限时仍为 `.notice.danger` 与主要按钮。
- 选题策划的帖子菜单：期间内有 Threads 帖子时才多一个“Threads”标签页（FB／IG 标签页不变），帖子行的平台胶囊为“Threads”，第 3 步摘要在 IG 之后附“、Threads N 篇”；没有 Threads 帖子时画面与之前相同。
- 回复读取等待时显示 Threads 的文字（“Threads 暂时限制调用…”“Threads 响应超时或暂时出错…”），不显示 Meta 用量。
- 只用 P1-1 色彩与系统字体 Token、control／card 圆角，零外部资源；权限提示的 text-subtle／bg-subtle 已列入 check_ui_contrast。check_posts_batch2（Threads 分页列表、指标名称、回复，1440／768／390px）、check_meta_oauth（重新连接提示）、check_ideation_fixes（Threads 标签页）与 check_followers_frontend（Threads 分页会读取帖子列表）覆盖，没有新增检查入口。

## 成员与角色权限（members）

本节覆盖旧版设置标签页与非管理员只读设置的呈现规则。管理员的设置标签页依次为 AI、平台连接、消息分类、工作区、成员、我的账号；其他角色按功能权限显示（平台连接＝`connections.manage`、AI＝`ai.manage`、消息分类与工作区＝`settings.manage`，成员仅限管理员），营销人员与查看者只显示“我的账号”，书签链接到其他设置时也显示此标签页。侧栏品牌菜单只列出可访问的品牌；没有品牌的非管理员显示“尚未分配品牌，请联系管理员”。手机保留 `.mobile-logout`。

- 成员编辑中的角色改为 `fieldset.member-role-options` 单选列表：每行一个原生 radio，名称（字重 600，作为 radio 名称）下方用 text-subtle 小字列出可执行的操作（`aria-describedby`）；内置三种在前，自定义角色在后。成员列表下方的 `.member-roles` 为“角色”区：`.role-row` 排列名称（内置角色加 neutral“内置”徽章）、权限摘要、“N 位成员”，自定义角色另有 secondary 编辑／删除（仍有成员时删除停用，并以 title 说明）。新增／编辑角色沿用 `.member-dialog`：角色名称与“可使用的功能”勾选列表，勾选“提交、重试与取消发布”会一并勾选“编辑发布草稿”，取消后者也会取消前者。发布页在没有 `publish.submit` 时以 muted 文字取代“发布／定时发布”按钮，并隐藏取消定时、重试与重新应用按钮。
- 成员页使用 `.section-card.members-card`，标题行右侧一个“添加成员” primary；`.list-box.member-list` 内的 `.list-row.member-row` 排列名称／账号、角色、品牌、状态及 secondary 编辑。名称字重 600，账号 text-subtle；品牌以逗号列出，单行省略并提供完整 title。状态采用 ready／neutral／pending。390px 时名称与角色同行，编辑靠右，其余自然换行。
- 新增与编辑沿用现有 modal 外框，`.member-dialog` 具备 dialog／aria-modal、标题关联、Esc、Tab 焦点循环与关闭后焦点还原。角色使用 `.member-role-options` 单选列表；非管理员显示品牌 checkbox，只有一个品牌时默认勾选。管理员隐藏品牌 checkbox，显示“管理员可访问全部品牌”。
- 提交用 primary，取消／复制／重置密码／启用用 secondary，停用用 primary danger 并经 ConfirmDialog 二次确认。保护规则错误用 `.notice.danger`，不使用 window.confirm。每个提交区块只放一个主要提交按钮。
- “我的账号”的密码表单后，管理员多一段 `.recovery-code`：h3“密码恢复码”与状态胶囊（已设置 `.ready`／尚未设置 `.neutral`）同行，说明、“确认当前密码”字段与 secondary“生成恢复码／重新生成恢复码”。成功后沿用 `.member-dialog` 与 `.temporary-password` 显示一次恢复码，以及 secondary 复制与“我已保存”。
- 首次设置页：数据库中没有任何账号时，未登录画面改为显示首次设置，沿用登录页布局与字段样式。左侧 eyebrow“首次设置”＋“欢迎使用营销工作台。”；右侧 h2“创建管理员”、管理员账号、密码、再次输入密码、品牌名称与 primary“创建并登录”。两次密码不同时以 role=alert 显示“两次输入的密码不一致”，不提交。从非本机网址打开时只显示“请在主机上完成首次设置”与说明，没有表单。创建成功后直接进入工作台；之后只显示登录页。
- 登录页在“仅限已授权的团队成员使用”下方放折叠的 `.login-forgot`“忘记密码？”：成员说明、展开后才渲染的管理员恢复码表单（管理员账号、恢复码、两次设置新密码、primary“重置密码”；标签不与登录表单重名）、没有恢复码时的主机命令 `.login-command` 与锁定提醒。成功后以 `.notice.success` 取代表单，不自动登录。
- 临时密码对话框使用 `.temporary-password`、ui-font-mono，提供 secondary 复制，显示“仅显示这一次，请转交给对方；对方首次登录时需修改密码”。关闭时清除内存中的值，不保存在网址或浏览器存储中。
- “我的账号”在同一行显示账号、名称、角色、可访问的品牌，下方先是 `.language-picker.account-language`“界面语言”下拉框（选项以各语言自己的写法显示，选择后立即保存到账号并刷新），然后是三个密码字段与一个主要按钮“修改密码”。登录页在 `.login-panel` 右上角放同款下拉框 `.login-language`（手机上改为在表单上方靠右），登录前只记在 localStorage，登录后若账号没有语言偏好就把它保存到账号。须改密码时显示 `.password-required` 全页“请设置新密码”，只有表单与登出，没有侧栏／底部导航；成功后才进入工作台。
- 查看者的选题策划保留品牌选择、现有列表与卡片，隐藏策划表单、编辑、还原、查看脚本、创建／打开发布草稿及删除；脚本仍可从“脚本版本”列表查看。所有角色限制同时由 API 执行。

新增样式只引用 P1-1 色彩、系统字体与 ui-radius-control／ui-radius-card；不加载外部资源。1440／768／390px 无水平溢出，新增的文字底色配对纳入 check_ui_contrast。

## 全站统一第二轮（uniform2）

本节覆盖 uniform 第一轮的按钮与工作区折叠规则；只改呈现，API、文字语义及权限沿用。

- 工作区五个分组各是一张 `details.workspace-group.section-card`，整行 summary 可点击，section-title／600，右侧有展开图标。summary／内容使用 panel-padding；外层不重复内边距。展开内容用 `.workspace-subsection` 与 h3，标题下 12px、小节之间 24px，可用 border-subtle 分隔；卡片之间 24px，与开机自动启动一致。独立表单保留各自的提交，不以整个分组来限制主要按钮数量。
- 复选框行与下一个字段标签之间至少 16px，套用到设置区所有同类行，选题策划现有内容区的几何不变。
- 帖子列表使用 `.post-items.list-box` 外框；每个 `.post-card.list-row` 的 `.post-card-meta` 同行显示平台胶囊、账号与类型，正文最多两行，日期 text-subtle。行间 1px border-subtle，选中时为 bg-subtle／左侧 3px brand-primary 色条；行本身不另做成圆角卡片。分页在容器外下方，发帖与自定义日期筛选保留。
- 粉丝数年／月／周采用精简工具栏，1440px 时下拉框与数字同行，768／390px 时下拉框一行、数字一行。周次显示“第 N 周”，完整日期保留在选项 title 中；菜单所有选项须容纳文字、内边距及原生箭头，不只检查元素 scrollWidth。
- 390px 时全局 `.mobile-settings-controls` 位于主内容最上方、所有 h1 之上，保留 `.mobile-brand-picker` 与 `.mobile-logout` 行为／查看者登出。底部当前页使用 aria-current="page"、brand-primary 实心／bg-surface 白字／opacity 1；保留 enabled，重复点击不会重置当前页，hover 与选中时保持同样底色。
- 手机上的帖子详情、效果与评论卡片以容器 16px gap 排列，移除叠加的上下 margin；桌面卡片之间 24px。
- 平台凭据保留具名的 form，`.credential-heading` 第一行为 label（`.credential-name`＋`.credential-env`），第二行为 `.credential-status`（状态胶囊＋遮罩＋右侧更换／设置）。手机上名称不断字，环境变量可折行；展开输入与密码行为不变。
- 操作按钮采用实心 primary；取消、返回、分页、移除等次要操作采用 quiet。只用 P1-1 色彩／系统字体与 control／card 圆角 Token，不加载外部资源。新增配对纳入 check_ui_contrast。

选题策划内容样式不改；手机共用品牌行会改变整张画面，与“整张截图零差异”的要求冲突，实际像素与几何比较列在 uniform2 报告中。


## Obsidian 评论与选题操作（obsidian）

- 工作区 → 数据中加入 `.obsidian-settings`，单一字段“Obsidian 评论文件夹”与 `.obsidian-actions` 中的“保存 Obsidian 文件夹”“立即同步到 Obsidian”实心 primary 按钮；名称与导出文件夹的保存操作区分开。仅管理员可查看与操作，其他角色只看到“我的账号”；加载或操作中停用，结果沿用 status／alert，控件行自然换行。
- `.ideation-card` 左上角的 `.idea-card-heading` 放序号（`.idea-number`，text-subtle）及旧数据的“已重新生成”“延伸自 #序号”标记；不再有选择 checkbox，卡片区顶端也没有批量操作行。
- 底部 `.idea-card-actions` 只放 secondary：有脚本时先“查看脚本”，再“创建发布草稿”（已有未发布草稿时为“打开发布草稿”），最后“交给 Agent 写脚本”，间距 8px、靠左、flex-wrap。“交给 Agent 写脚本”只在报告 ready 时可点，切换卡片内的 `.agent-handoff`（与选题策划的四个接手按钮相同，卡片内固定两栏），命令带报告编号与题号（`/mwb:script …`；复制版带 `topic_index`），一次只展开一张卡片；网页本身不调用 AI 写脚本。可还原时显示独立的 secondary“还原上一版”，没有省略菜单。
- 重新生成与延伸选题已移除：卡片没有进度、骨架或失败提示；报告 JSON 中旧的 ideas_job 只保留在数据中，不影响画面，旧报告的“已重新生成”“延伸自 #序号”标记仍显示。报告处理中时停用卡片操作与删除。
- 帖子评论范围增加“全部”；没有范围参数时仍默认近 30 天，来源评论链接默认近 90 天，明确 comment_range=all 才选择全部，刷新后保留所选范围。只有全部范围显示次要按钮“完整重抓”，确认后发送 full_rescan=true。一般抓取与立即策划采用增量；首次抓取读到底。原有的 7／30／90 天与显示更多仍保留。
- 全部沿用 P1-1 的色彩／字体与 control／card 圆角 Token，390px 无溢出；新增文字底色配对纳入 check_ui_contrast。check_ideation_fixes、check_workspace、check_comment_sync_frontend 覆盖操作与手机，既有隔离检查入口数量不变。

## 从选题创建发布草稿（ideadraft）

- 选题卡片右上角的 `.idea-card-tools` 只有 secondary.small“编辑”，非 ready 或正在编辑时停用，查看者隐藏；底部 `.idea-card-actions` 见上文。已有未发布草稿时改为显示“打开发布草稿”，直接打开。两组都 flex-wrap，窄卡片自然换行。
- 点击编辑后 `.idea-editor` 就地替换选题内容，五个带标签的字段依次为标题、开场、切入角度、可拍画面、关键词，各最多 1000 字、不可为空；底部 primary 保存、secondary 取消。保存后标签行显示 `.ideation-chip.idea-edited`“已编辑”，原话保持可读；secondary 还原上一版沿用 history，Markdown／Word 重新导出使用编辑后的内容。
- “创建发布草稿”直接创建草稿并打开发布页，没有确认对话框与“参考脚本”勾选，也不调用 AI；草稿主文案是标题、开场与 hashtag 组成的初稿。
- 创建后切换到同品牌发布页的“新建帖子”，加载指定草稿；顶部 `.notice.success` 显示“已从选题创建草稿，请上传视频并确认平台”。草稿 ID 保存在网址 `publish_post_id` 中，刷新后仍会加载；加载期间停用编辑及自动保存。
- 发布记录／定时中的 `.publish-record-heading` 在格式胶囊旁同行放 `.publish-source`“来自选题”，不另增说明行。预览使用 text-main／bg-surface、body 字号；来源使用 text-subtle／bg-surface、help 字号；成功提示沿用 notice 的 state-success／bg-subtle。全部采用 P1-1 Token、现有 control／card 圆角与本机资源，1440／768／390px 无水平溢出。
- 发布记录列表上方一行 `.publish-presence`：左侧为 text-subtle／help 字号的“上次检查：<台北时间>”（取各平台结果中最近的 presence_checked_at，没有则显示“尚未检查”），右侧为实心 `.primary`“检查平台帖子”（用户指定为实心，是此分页唯一的主要按钮；查看者隐藏）。检查中按钮显示“检查中…”并停用；完成后以 `.notice.success`／`.notice.warning` 显示“已检查 N 篇，M 篇已在平台删除”，有无法判定的平台时用 warning 并附中文原因，429 以 `.notice.danger` 显示“刚检查过，请稍后再试”。各平台结果的 `deleted_at` 有值时，胶囊为 `.status-badge.neutral`“<平台> · 已在平台删除”，不显示“查看帖子”，改为显示“检测于 <台北时间>”；列表行整篇成功且成功的平台全部已删除时，状态胶囊改为 neutral“已在平台删除”，只有部分删除时维持原状态并加“· 部分已删除”。已删除的平台仍算成功，不会被重试或通过重新定时再次发送。只用现有 Token，1440／768／390px 无水平溢出。

- composer1（改版 1／3）只新增后端：现有发布页保持原版式，API 额外返回 platform_options、effective_platform_options、warnings 与串文进度；前端之后改版时再将平台视频选项、逐段预览及提示并入现有区块，不新增说明行。本轮没有新增文字／底色组合或按钮，不需要扩充对比断言；现有的 390px 与按钮三层规则维持不变。

## 色彩与字体 Token（P1-1）

色彩与字体集中在 `frontend/src/style.css :root`，CSS 与 inline／SVG 都使用 Token；不加载外部字体、CDN 或远程 `@font-face`。默认正文／标题使用 `--text-main`，品牌面才使用 `--brand-primary`。字号、尺寸、间距及圆角 Token 维持原值。

| Token | 定义 | 用途 |
|---|---|---|
| `--bg-app` | `#F8FAFC` | 全站画布 |
| `--bg-surface` | `#FFFFFF` | 卡片、控件、反白文字 |
| `--bg-subtle` | `#F1F5F9` | 浅底、hover、选中行 |
| `--border-subtle` | `#E2E8F0` | 边框与分隔线 |
| `--brand-primary` | `#0F3A2E` | 侧栏、主要按钮、深色选中行 |
| `--brand-accent` | `#10B981` | 仅用于交互高亮、选中、成功装饰 |
| `--text-main` | `#0F172A` | 正文与标题 |
| `--text-muted` | `#64748B` | 白底／画布上的辅助文字 |
| `--text-subtle` | `#475569` | 浅底上的文字与中性标签 |
| `--state-pending` | `#F59E0B` | 待处理、警告装饰 |
| `--state-pending-text` | `#B45309` | 待处理、警告文字／边线 |
| `--state-pending-bg` | `#FEF3C7` | 警告浅底 |
| `--state-danger` | `#B91C1C` | 错误、需修改、危险操作、红灯 |
| `--state-danger-bg` | `#FEE2E2` | 错误浅底 |
| `--state-success` | `#047857` | 成功、已回复文字、绿灯 |
| `--state-success-bg` | `#D1FAE5` | 成功浅底 |
| `--state-info` | `#1D4ED8` | 处理中标签 |
| `--state-info-bg` | `#EFF6FF` | 处理中浅底 |
| `--sidebar-text` | `#F8FAFC` | 深色品牌面文字 |
| `--sidebar-muted` | `#CBD5E1` | 深色品牌面辅助文字 |
| `--sidebar-border` | `#94A3B8` | 深色面控件边线 |
| `--sidebar-selected` | `color-mix(in srgb, var(--brand-primary) 85%, var(--bg-surface))` | 侧栏选中／控件底色 |
| `--brand-hover` | `color-mix(in srgb, var(--brand-primary) 88%, var(--bg-surface))` | 主要按钮 hover |
| `--focus-ring`、`--link-color` | `var(--state-success)` | 焦点与链接；亮绿对比不足时使用深绿 |
| `--list-red`、`--list-green`、`--list-black` | danger／success／text-main 的别名 | 名单圆点与框线 |
| `--media-letterbox` | text-main 的别名 | 发布预览中视频与框比例不同时的补边 |
| `--chart-line`、`--chart-point`、`--chart-intent` | success／info／pending-text 的别名 | 图表独立的线色、点色、意图柱条 |
| `--ui-font-family` | `system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif` | 全站系统无衬线字体，标题按字重区分 |
| `--ui-font-mono` | `ui-monospace, Consolas, "Cascadia Mono", Menlo, monospace` | 需要等宽时使用的系统字体 |

旧名称保留为别名：`--ink:var(--brand-primary)`、`--paper:var(--bg-surface)`、`--line:var(--border-subtle)`、`--muted:var(--text-muted)`。`--accent:var(--state-pending-text)` 仅为兼容别名，新样式不得引用；现有引用已全部按语义替换。

绿色只表示交互与成功；警告用琥珀色，错误、需修改与危险用红色。焦点外框使用达到 3:1 的深绿，链接与成功文字达到 4.5:1；亮绿不得用作白底上的小字。浅底中性标签使用 `--text-subtle`，避免辅助文字在浅底上对比不足 4.5:1。`transparent` 与 `currentColor` 保留 CSS 的透明／继承语义；其余衍生色由 `color-mix()` 引用 Token。

主要组合的 WCAG 2.1 对比（按上表数值计算，供调整 Token 时参考；以 `check_ui_contrast.py` 实际计算为准）：

| 文字 | 底色 | 对比 | 备注 |
|---|---|---|---|
| `--text-main` | `--bg-surface` | 17.85:1 | |
| `--text-muted` | `--bg-surface` | 4.76:1 | |
| `--text-muted` | `--bg-app` | 4.55:1 | 接近 4.5 下限，不可再调浅 |
| `--text-subtle` | `--bg-subtle` | 6.92:1 | 浅底文字改用此 Token 的原因 |
| `--bg-surface` | `--brand-primary` | 12.61:1 | 主要按钮、侧栏 |
| `--state-pending-text` | `--state-pending-bg` | 4.51:1 | 接近 4.5 下限 |
| `--state-success` | `--bg-surface` | 5.48:1 | 链接、焦点、成功文字 |
| `--state-danger` | `--state-danger-bg` | 5.30:1 | |

验收使用 `scripts/check_ui_contrast.py` 从 CSS 读取 Token 计算 WCAG，文字阈值 4.5:1、图标／焦点／图表阈值 3:1；`check_ui_scale.py` 另外检查实际计算出的字体、状态标签对比、红灯／警告／错误 Token 与零外部请求。

## 营销导航与 DOM（nav）

默认为仪表盘。桌面侧栏与手机底部都恰好四项，依次为仪表盘、帖子数据、选题策划、设置。设置以 `.settings-hub` 包含唯一的 PageHeader“设置”、`.settings-tabs` 与四个 tabpanel，依次为 AI、平台连接、消息分类、工作区；原页首移除，内容、品牌字段及角色权限沿用。手机的品牌选择与登出使用全局 `.mobile-settings-controls`，同行放在所有页面名称上方，不夹在设置分页下方，也不再提供“更多”菜单。没有收件箱计数、对话选择、回复区、未保存对话提示或成交进度跳转。选题策划现有报告的原话仍以文字呈现，公开评论可定位回帖子；来源选择遵循下方 ideaui 规格。


设置分页使用 tablist／tab／tabpanel，id、aria-controls、aria-labelledby 互相关联，aria-selected 与 roving tabindex 维持单一 Tab 焦点；左右方向键循环，Home／End 切换到首页／末页。选中为 primary，其他为 quiet；沿用色彩、字体与 control 圆角 Token。四个分页等宽并与内容对齐，390px 不溢出。非活动面板 hidden，内容沿用原页面切换时的卸载行为。

第一次从导航进入设置时默认 AI；`view=settings&settings_tab=ai|connections|policy|workspace` 保留最后的分页，刷新、切换到其他页面后返回及 popstate 均会恢复。旧的 `view=ai`、`view=policy`、没有 settings_tab 的 `view=settings` 分别导向 AI、消息分类、工作区；非法的 settings_tab 回到 AI。保留 brand_id、ai_tab、其他网址参数与 hash。工作区快捷方式改为切换设置分页。

`check_view_refresh` 验证四项导航、四个分页、键盘循环、网址／刷新／旧链接、单一标题、手机品牌与登出及 390px；`ui_navigation` 统一通过可见导航及分页操作。`check_ui_scale` 维持原有六种内容情境的尺寸、文字、内边距验证；手机品牌／登出改为验证设置页控件。新增配色组合纳入 `check_ui_contrast`。

仪表盘保留 KPI、客人正在问什么、趋势、排行与右上角导出；意图分布独占原双栏所在行，成交进度已移除。AI 设置保留营销内容指示的版本编辑，移除回复 prompt 组装／预览。工作区保留公开评论紧急通知、导出、品牌、例会与自动启动，移除私信补抓。

## 工作区开机自动启动（autostart）

- 开机自动启动（自 uiorder 起）放在“系统”分组内、消息接收健康监测之前：`.settings-section.workspace-subsection.autostart-settings`，不再是工作区最上方的独立卡片；包含 h3“开机自动启动”、`.autostart-row` 中的原生 checkbox／label“登录 Windows 后自动启动工作台”与同行状态，以及一行登录条件说明。卡片以 aria-labelledby 关联标题，操作中设 aria-busy；不增加保存按钮。
- 默认没有计划任务即为关闭；加载完成前停用，仅管理员可查看与切换。工作区 status 与 autostart GET／PUT 均仅限管理员，其他角色不挂载此卡片。处理中停用并显示“正在处理…”，成功后采用后端状态；错误使用繁体中文 alert，连接失败时另行读取实际状态，读取失败则停用并显示未知状态。非 Windows 显示“仅支持 Windows”并停用。
- 小节沿用分组卡的外框与圆角，使用系统字体；文字 text-main／bg-surface，说明与状态 text-muted／bg-surface，错误 danger／danger-bg，勾选 brand-primary。纳入 check_ui_contrast；390px 时同行信息可换行，不水平溢出。check_workspace 使用替身检查四种状态、只读、不支持与连接失败，1440×900／390×844 的最新截图在 `.runtime/check-output/check_workspace/`。

## 选题策划第二轮（ideapolish）

- 第一步 `.ideation-source-fields` 同行放品牌、开始时间、结束时间：桌面三等分，768px 两栏换行，390px 单栏。步骤标题使用 section-title／600，序号为 24px 品牌色底白字圆标，间距 8px；步骤之间 32px，标题下 12px。
- `.ideation-platform-tabs` 为下划线式 tablist，Facebook／Instagram 附篇数；默认选帖子较多的平台，零篇时停用，方向键与 Home／End 选择可用标签页。跨页保留勾选，三态全选只作用于当前平台；摘要同行列出全部 FB／IG 的已选篇数与评论范围。
- 帖子行 `.ideation-post-row` 包含可点击的 label 与独立的展开按钮；aria-expanded／aria-controls 关联评论预览。只读取已保存的评论，按当前范围最新在前，每批 20 条；作者遮蔽、正文 redact，显示台北时间与“加载更多”。切换范围时重新加载，卸载时取消过期请求，不抓取平台。
- 第三步摘要在 `.ideation-execution-row` 上方，左侧执行方式约 320px，右侧为立即策划 primary／重新标注 secondary quiet，控件 40px 并按底线对齐，覆盖 primary 的上边距；手机上自然换行。
- 提示框 `.ideation-notice` 使用 bg-subtle／text-subtle、左侧 3px border-subtle；警示与品牌复核用 state-pending 色条。control 圆角、12px 16px 内边距、help 字号、上下 12px。未生成的 Markdown／Word 为两个 chip。
- 类型分组上方 40px、标题下方 16px。卡片按钮一律共用 `.secondary`，`.secondary.brand` 已移除。
- 操作行与报告列表每秒显示阶段及“已运行 m:ss”，完成／失败时停止计时，报告标题行显示耗时。UTC 的 started_at／comments_synced_at／finished_at 来自报告 JSON，刷新后继续计算；旧报告没有这些字段时不补造时间。前端与新导出不呈现“全部选题与代表原话”，数据及卡片原话保留。
- 所有色彩／字体沿用 P1-1 Token；新增配对纳入 check_ui_contrast，check_ideation_fixes 验证分页、预览、计时、刷新、尺寸与无外链，check_ui_scale 同步验证新尺寸及提示内边距。

## 仪表盘与快照曲线（P1-2）

tmpclean 只调整验收文件的位置，DOM、呈现、Token 与现有断言不变。仪表盘截图改存到 `.runtime/check-output/ui_dashboard/`，其他页面按入口脚本命名；每次执行只保留最近一次。已退役的回复控件由 `check_polish_frontend` 验证，不依赖历史截图基准。

- 两张 KPI 依次为“本周新评论”“提问最多的类别”，合并了原来新消息／新评论的重复指标。期间沿用台北时间周一 00:00 至现在，只计算公开评论串中客人的入站消息；热门类别取本周评论中最新且指纹有效的分类，排除 spam，中文类别与条数同行，没有有效分类时显示“暂无数据”。`.dashboard-kpis` 直接包含两张 `section.kpi`，共用 `--bg-surface`、`--border-subtle`、`--ui-radius-card`；数字为 page-title／600，类别与空值为 section-title。桌面等宽两栏，390px 单栏；除下方一行增长比较外，不增加说明行。
- 页首 `PageHeader` 操作区并排“导出报表”与“刷新 ↻”，保留页首下方的期间说明。导出按钮只对 `canExport` 显示，不再占用内容区卡片。
- 导出以原生 `.inbox-dialog.report-export` 呈现，包含 `.sheet-heading` 与 `.sheet-content`；日期默认值、限制、提示、错误与下载请求／文件名沿用现有规则。下载中停用下载按钮；关闭、Esc 与点击背景均会关闭并恢复触发按钮的焦点，Tab 留在对话框内。
- 问题分布柱条使用 `--brand-primary` 与 `--bg-subtle` 轨道，沿用原有统计及点击行为；区块空数据沿用 `.empty-data`。
- KPI 下方的 `.dashboard-card.dashboard-trend` 显示“每日趋势”，标题右侧的 7／30 天选择默认 30，选中为实心 primary，次要为 quiet；`trend_days` 网址参数保留刷新与导航状态。品牌切换、刷新与每 15 秒轮询读取 `/api/dashboard/trends`，卡片错误不影响其他摘要。
- 趋势使用纯 SVG 的 620×220 viewBox，ResizeObserver 将轴文字补偿到 minimum Token；只保留新评论柱条与左侧评论轴。30 天每五天标一次 MM/DD，7 天逐日标示；单日时居中。全为零时显示“累积评论后会显示每日趋势”，不画轴。
- `.trend-day` 采用单一 Tab 焦点，左右方向键逐日移动、Home／End 到首日／末日，以深绿外框显示焦点；鼠标与焦点共用 `.trend-tooltip`，只含日期与新评论数。图下的单行图例为“柱条＝新评论 · 台北时间”，手机上自然换行，390px 不水平溢出。
- 柱条用 `--brand-primary`，白底图形对比 ≥3:1。轴与图例用 text-muted／bg-surface，提示用 text-subtle／bg-subtle，错误用 state-danger／state-danger-bg，圆角与字体沿用共用 Token；配对纳入 `check_ui_contrast.py`。`ui_dashboard.py` 验证有数据、空数据、切换、网址、焦点、提示、错误隔离与手机尺寸。
- 增长比较（2026-10-16）：“本周新评论”数字下方一行 `.kpi-compare`（text-muted、help 字号）“比上周同期增加／减少 N%（小于 10% 保留一位小数）· 上周同期 M 条”，相同时为“与上周同期持平”，上周同期为 0 时显示“上周同期没有，无法比较”或“上周同期也没有”，不用红绿色暗示好坏。每日趋势图例下方的 `.trend-compare` 按同样规则显示“近 N 天共 X 条 · 比前 N 天…（前 N 天 Y 条）”。
- 转化漏斗：趋势卡下方的 `.dashboard-card.dashboard-funnel`（region“转化漏斗”），标题右侧的 7／30 天选择与趋势同款，`funnel_days` 网址参数保留状态，轮询、品牌切换、刷新与错误隔离同趋势。说明行为“近 N 天发布且有覆盖人数数据的 K 篇帖子”；`ol.funnel-stages` 四行依次为覆盖人数、互动次数、评论、消费咨询，每行标签与千分位数字同行，下方为 12px 的 `.funnel-track`（bg-subtle 轨道、brand-primary 柱条，宽度以第一阶段为 100%，非零时最少 2%），从第二阶段起显示 `.funnel-rate`“上一阶段的 N%”，上一阶段为 0 时显示“上一阶段为 0，无法计算转化率”。卡片底部的 `.funnel-note`（text-subtle）说明互动是次数，以及消费咨询的分类。没有帖子时只显示“近 N 天没有带覆盖人数数据的帖子”。`ui_dashboard.py` 的 `check_growth_funnel` 验证文字、柱条比例、7／30 切换、网址、错误、空状态、1440／390 无水平溢出。
- 受众分析（2026-10-19）：漏斗卡下方的 `.dashboard-card.dashboard-audience`（region“受众分析”），标题下方为六格平台分段控件（Instagram、Facebook、Threads、YouTube、TikTok、LINE；桌面一行六格、最宽 640px，600px 以下三格两行、占满宽度），网址 `audience_platform` 记住选择。各项以 `.audience-grid`（最小 260px 自动栏）排列：分布用 `--brand-primary`／`--bg-subtle` 的 8px 轨道柱条，右侧占比后加 text-muted 的人数；在线时段为 24 根竖条，人数最多的三个时段用 `--brand-primary`，其他用 `--text-subtle`，下方列出台北时间的高峰。缺少数据的项目、TikTok 与 LINE 以 `.audience-hint`（bg-subtle、help 字号）说明原因；平台共通说明用 `.audience-note`。
- 帖子缩略图：帖子列表中有缩略图的 `.post-card` 加 `.has-thumb`，左侧 56px 方形 `.post-thumb`（object-fit cover、control 圆角）跨三行，平台胶囊、正文、日期在右栏；没有缩略图的卡片维持原样。单篇介绍在类型行下方显示 `.post-detail-thumb`（最宽 320px、最高 240px、contain、card 圆角）。仪表盘排行在名次后显示 48px 的 `.rank-thumb`。图片加载失败即隐藏，不显示破图。
- `MetricChart` 保留纯 SVG，空数组或全为 null 时不画坐标轴，以一行文字引导累积快照；单笔数据或时间相同时将数据点居中，不产生 NaN 坐标。指标缺值时不跨段连线，轴标签仍维持最低字号补偿。

## AI 设置分页（creds）

- 本机 CLI 已移除（nocli）：基本页的默认 AI 只列三个 API 提供商，没有“尚未检测”状态。

- 用量沿用 `.usage-table > table > tbody > tr > td[data-label]`，桌面为表格、390px 为卡片。本机 CLI 已移除，但历史记录保留：提供商名称标为“（已停用）”，有数字（含 0）时沿用“输入 / 输出”，两者都缺时显示“未上报”，单边缺值时只在该边显示“未上报”，美元估算一律为“订阅”；API 格式不变。表格下方的 `.muted` 费用说明不再提 CLI。文字沿用 text-main、说明 text-muted，搭配桌面 bg-app／手机 bg-surface，纳入 check_ui_contrast，不新增样式或控件。

- 三个子分页“基本”“品牌说明”“AI 密钥”保留 tablist／tab／tabpanel、aria 关联、单一 Tab 焦点、方向键、Home／End。非活动面板 hidden；切换分页时保留未保存的输入。桌面等宽，390px 不水平溢出；与主设置分页同一行。
- 基本放默认 AI、每月预算、用量。品牌说明沿用版本、差异与还原。AI 密钥只含 Gemini、OpenAI、Anthropic，备用模型放在对应提供商卡片下方；管理员保留验证后保存、更换及删除密钥。非管理员不读取密钥 API，备用模型仍沿用原品牌权限。
- `ai_tab=basic|brand|keys` 可通过刷新及 popstate 还原；旧的 usage→basic、prompt→brand、advanced→keys，keys 回到自己的位置；已移除的 cli 与非法值回到 basic，保留其余 query 与 hash。
- 密钥 password 为 uncontrolled，不存入 React state 或浏览器存储。主操作 primary，次要 quiet。

## 平台连接（creds）

`.platform-connections` 放三张 `.settings-section.connection-card`：Meta（FB／IG）、LINE 通知、jev；标题行右侧为实心“测试连接”。每个 `.credential-field` 是具名的 form，`.credential-heading` 同行显示环境变量名、DB／env／未设置来源与遮罩，`.credential-controls` 放 password 与保存／取消，已设置时改为显示更换；只有 DB 值可移除。移除后回到 env；版本冲突时清空机密输入并显示中文错误，刷新以取得新版本。测试连接只测试已保存的设置，发送空对象。

平台 API 与设置页全部仅限管理员；其他角色不显示平台分页、不发出凭据请求，只看到“我的账号”。最后一张 `.connection-endpoints` 只读显示 WEBHOOK_PUBLIC_URL 及 meta-inbound、line-notify 两个网址（line-inbound 已退役，不再显示）；其下只有一段文字列出 .env 专属名称与原因，没有实际值。所有 password 都不读回明文、不进入浏览器存储；Webhook 网址是特别允许公开复制的只读设置。

名称／字段用 text-main／bg-surface，遮罩 text-subtle／bg-surface，来源 success／success-bg，说明 muted／bg-surface，错误 danger／danger-bg；提供商浅底遮罩改为 text-subtle／bg-subtle。圆角用 control／card Token，不加载外部资源；390px 时名称与变量名为第一行，状态／遮罩／操作为第二行，名称不断字，变量名可折行，无水平溢出。配对纳入 check_ui_contrast。

## 工作区内容（creds）

`.general-settings` 上方保留当前品牌 label／select。下方五个原生 `details.workspace-group.section-card`，依次为“品牌模板”“选题策划”“数据”“通知”“系统”（uiorder 调整了顺序），summary 是卡片标题行，内容在同一张卡片的 `.workspace-group-content` 中，不得嵌套 section-card。data-group 为 ideation／data／notifications／system／brand，默认全部折叠，展开互不排斥，刷新后回到折叠。

选题策划包含例会与选题；数据包含 CSV、私信补抓、导出；通知包含通知政策；系统包含开机自动启动与接收健康；品牌模板包含工作区名称、模板预览／套用与禁用词。展开／折叠保留输入，品牌及角色权限不变，没有旧的单一高级设置与上班时间字段。摘要使用 text-main／bg-surface、card 圆角与共用内边距，卡片宽度对齐。

check_all_features 操作全部 16 个字段的保存、遮罩、刷新、409、移除及四组连接成功／失败替身；viewer 验证平台只读。check_ai_resilience_frontend 验证三个子分页（没有本机 CLI）、未保存数据、旧网址与键盘、旧 CLI 用量行及默认 AI；check_view_refresh 验证四个主分页；check_workspace 验证五个分组默认折叠及独立展开；check_ui_scale 保留各控件原有的尺寸／文字／滚动验证。

## 手动 AI 与默认 AI（ai-unify-2；本机 CLI 已在 nocli 中移除）




- 默认 AI 在基本页（“默认 AI（选题策划）”），只列三个 API 提供商；未设置时显示“请选择 API 提供商”，旧的 CLI 值视为未设置，菜单宽度与所在区块对齐。三家 API 的备用模型在 AI 密钥，预算与用量在基本。
- 选题策划 `.policy-grid` 的执行方式使用原生 select，不分 optgroup：已设置的 API 提供商（不可用项停用并标“（未配置）”），最后是“交给 Agent 撰写”。默认顺序为可用的 `ideation-choice:<brandId>` 浏览器记忆、品牌默认 AI、第一个可用的 API、交给 Agent 撰写；CLI 记忆与默认值一律跳过。选择“交给 Agent 撰写”时，报告停在“等待 Agent 撰写选题”，`.agent-awaiting` 说明请在 Claude Code 中使用 /mwb:ideas，或在其他 Agent 中使用 get_guide("ideas") 接手。数据加载前停用菜单，避免切换品牌时沿用旧值；不新增说明行。

## 消息分类（noinbox）

设置页的“消息分类”分页内有品牌选择与一张 `.settings-section.intent-notes`；只有“类别说明”及九行 label／input。每个字段最多 200 字，保存为 primary；只读时停用输入并隐藏按钮。409 时保留输入，切换品牌时重新加载。分类阈值、转人工、主管与路由设置已移除。

沿用 text-main／bg-surface、placeholder text-muted／bg-surface、danger／danger-bg、primary 及 control／card 圆角 Token；390px 字段不溢出。补充说明只影响后续分类，不会自动重新计算历史。

## 选题策划的选帖、列表与卡片（ideadesign／ideaui）

- 同一张 `.ideation-form` 保留标题与原说明，内含三个 `.ideation-step`：“1 选择帖子”“2 评论范围”“3 生成”，小节间距 32px。品牌与开始／结束时间按 ideapolish 的三／二／一栏排列；第 3 步保留执行方式、选帖摘要及操作。字段标签为 help／muted／500，与控件间距 8px。
- 共用的 `SegmentedControl` 使用 radiogroup／radio／aria-checked、单一 Tab 焦点；左右／上下方向键循环并选中，Home／End 到首项／末项。外框 surface／border-subtle、control 圆角、3px 内边距，五段等宽、高度同输入框；整组 520px 且不超过父容器，390px 时内部横向滚动。未选中为 main／透明底，hover 为 subtle；选中为 surface／brand-primary／600。自定义日期时，下方 8px 处出现两个约 200px 的日期字段与“～”。
- `.ideation-posts` 为带边框、card 圆角、最高 360px 的滚动容器；44px 的 sticky 标题行同行放三态 checkbox、“已选 X / Y 篇”与范围内的评论合计。整行原生 label 切换选中，行间有分隔线、hover 为 subtle；平台 FB／IG 浅底标签、单行省略的正文、右侧日期与范围内评论数。正数为 brand-primary／600，零为 subtle；390px 时右侧信息改放在正文下方一行。无数据时居中保留原空状态。
- 摘要实时显示全部 FB／IG 的已选篇数与评论范围；操作间距 12px。“立即策划”为 primary；“重新标注所选评论”使用 `.secondary.quiet`。共用的 `.secondary` 在 style.css 中定义为 surface 底、border-subtle 1px 边框、main 文字、hover subtle、button 高度与 control 圆角。
- `.report-row` 最低 48px，手机上计时可换行撑高；白底边框、control 圆角、行间 8px。选中时为 subtle 底、左侧 3px brand-primary 色条及文字 600。状态胶囊：完成为 success、失败为 danger、进行中为 pending-text，搭配各状态的浅底。删除沿用 primary danger，改为 small button 32px／help 字号。
- 三个 `.ideation-goal[data-goal]` 标题左侧的 4px 色条依次为 success／info／pending，题数同行。类型胶囊使用 success／info／pending-text 与对应浅底。卡片顺序为标签、两行标题、`dl.ideation-fields` 的开场／切入角度／可拍画面、关键词、折叠的原话、靠左的次要操作；字段 dt 为 caption／muted、dd 为 body，间距 12px。“延伸选题”胶囊的 title 为“证据不足，按主题延伸”。卡片 padding 20px、grid gap 16px／stretch／等高，flex column 中的操作 margin-top:auto；1440／768／390 分别为三／二／一栏，不水平溢出。

- cwindow：开始／结束时间只筛选帖子的发布期间，可选择任意历史帖子。第 2 步 `.ideation-comment-window.post-date-filter` 保留“评论范围”group；内部的共用分段控件依次为近 90／60／30／7 天、自定义日期，默认近 30 天。只有自定义时才显示 `.post-date-inputs` 的评论起始日／评论截止日；title 说明台北时间与包含起止日，不另加说明行。
- 评论范围行使用透明底色并沿用外层表单的内边距，不建立第二层卡片内边距；其标签、日期字段与上方 `.policy-grid` 左右对齐。尺寸检查同时验证零额外内边距，以及文字到外层底色边界的距离。
- `comment_range`、`comment_from`、`comment_to` 保存在网址中，刷新及 popstate 时恢复。自定义日期必填，且起始日 ≤ 截止日 ≤ 今天；尚未有效时停用策划／重新标注。评论范围改变时保留所选帖子，重新加载期间内的计数；品牌／帖子期间变更时才全选。每篇显示“范围内 N 条评论”，title 保留已保存的总数。
- 报告期间段落以 br 分成“帖子期间”“评论范围”两行，显示台北时间且不含结束时间；旧报告缺少 comment_range 时，评论范围沿用帖子期间。Markdown／Word 同样保留两行，不回填历史数据。重新标注采用当前的评论范围与所选帖子。
- 帖子数据目前提供评论 7／30／90 天；手动抓取时传入当前选项，原说明改为“点击‘抓取评论’仅读取当前评论日期范围内的评论与回复，完成后结束”。没有新增操作或说明行。评论范围的文字、日期、计数、实心选中底色沿用 P1-1 Token、control 圆角，纳入 check_ui_contrast。

- no90：开始时间不限历史长度，结束时间须晚于开始时间且不得晚于现在（后端保留五秒容差）。第 3 步的 `.ideation-actions` 同行放 primary“立即策划”、secondary quiet“重新标注所选评论”与操作完成时的 status；重新标注只发送当前期间与勾选的帖子，不依赖内容生成模型，未加载／未选帖时停用。工作区不再提供全品牌重新标注。沿用 Token，390px 自然折行、无水平溢出。
- 报告及导出中的前期提示为“前期有部分时间早于所选帖子发布，变化仅供参考”。前期为评论范围往前推相同长度，旧报告内容与既有的比较标记仍可显示，不回填历史数据。

- 顶部的“从评论中策划选题”只使用所选帖子的客人评论。品牌与执行方式按三个步骤分开；时间字段沿用 `.policy-grid`，日期 label 的 title 说明台北时区及不含结束时间。`.ideation-posts` 内为三态全选 checkbox 与 `.ideation-post-list` 原生 checkbox 列表，平台、正文、日期与评论数按上述版式排列。品牌或期间改变后重新加载并全选；加载中、没有帖子或未勾选时停用立即策划，空数据显示“此期间没有帖子”。
- “选题列表”的 `.report-history > .report-row` 包含左侧的 `.report-select` 及右侧的小型 `primary danger` 删除按钮；禁止嵌套 button。选中行保留 `aria-current="true"`，列表约六行高度后在内部滚动。pending／processing／syncing_comments 时删除停用并附 title；viewer 不显示删除。抓取期间状态显示“正在抓取评论”。
- `.ideation-modal-backdrop > .ideation-delete-dialog` 是居中的自制 modal，具备 `role="dialog"`、`aria-modal` 与文字标题关联，打开时聚焦“取消”、Tab 循环，Esc／取消／点击背景关闭并还原原按钮的焦点。确认文字为“删除选题列表 #id？由此生成的脚本也会一并隐藏，已导出的文件不受影响。”删除为危险色实心、取消为主要色实心；不使用 window.confirm。内容区不再有删除或两段式确认行。
- 删除成功后移除该行；若删除的是选中的报告，则选中下一份（末项改为前一份）、清空脚本并同步网址；删除最后一份时回到空状态。删除其他行不影响当前阅读。错误维持 alert，轮询不得让已删除的项目复活。
- `.ideation-goal` 按变现型／流量型／引流型排列，h2 显示实际题数，`.ideation-grid` 内每题一张 `article.settings-section.ideation-card`。桌面三栏，1100px 以下两栏，600px 以下一栏。旧报告按实际题数呈现，不强制补足。
- 卡片顺序按 ideadesign 规则；题目 title 可读到完整文字，开场／切入角度／可拍画面完整折行；原索引保留与脚本的对应。没有 quote_ids 时标示“延伸选题”。`.ideation-evidence` 放在所有卡片之后且默认折叠，保留主题统计、备用标示与代表原话；不呈现已退役的预约字段。
- 公开评论原话以链接定位到帖子，并保留返回报告／脚本的参数；旧报告缺少可用的公开来源时，显示原话文字与“来源已无法访问”，不再显示已退役的来源类型文字。
- 报告与脚本共用 `.ideation-exports > .export-card`，保留 Markdown／Word 下载及不可用／错误状态；不显示磁盘路径。报告导出按三类分组，每题的字段顺序与卡片一致，附佐证原话；不再附全部主题统计。
- 色彩与字体只引用 P1-1 Token；一般 chip 使用 text-subtle／bg-subtle，类型与状态使用对应 state 浅底，日期 text-subtle／bg-surface、分类 text-muted／bg-surface，卡片与 modal text-main／bg-surface，删除 bg-surface／state-danger，其余实心操作 bg-surface／brand-primary。圆角为 control／card Token，不加载外部资源，390px 不水平溢出。配对由 check_ui_contrast 验证。
- check_ideation_fixes 与 check_all_features 使用合成数据与替身，保留下载、来源定位、权限、表单保存、409／422、失败与旧报告验证，测量前等待数据与 DOM 挂载。chip／平台胶囊左右内边距 8px、卡片 20px，ui_padding 按各容器用途测量；check_ui_scale 同时验证 8px 正确内边距会通过、零内边距会失败，不排除测量。

尺寸定义集中在 `frontend/src/style.css` 的 `:root`。新增或修改画面时，使用下表的共用变量；不在页面、inline style 或 SVG 中写死字号及表单／按钮高度。页面框架样式集中在 `frontend/src/ui-shell.css`，各页面保留自己的内容配置、滚动与操作功能。

| 变量 | 桌面值 | 用途 |
|---|---:|---|
| `--ui-font-page-title` | 26px | 页面 h1、登录标题、大型统计数值 |
| `--ui-font-section-title` | 18px | h2／h3 区块与对话框标题 |
| `--ui-font-body` | 14px | 正文、字段标签、表格内容 |
| `--ui-font-help` | 13px | 说明、时间、提示与来源信息 |
| `--ui-font-minimum` | 12px | 全站最小字号、紧凑徽章、图表轴标签 |
| `--ui-font-caption` | 引用 minimum | 紧凑的元信息 |
| `--ui-font-button` | 引用 body | 按钮文字 |
| `--ui-font-conversation` | 16px | 消息气泡、回复框、帖子评论正文 |
| `--ui-font-input` | 引用 body | input／select／textarea 文字 |
| `--ui-choice-size` | 16px | checkbox／radio 宽高 |
| `--ui-choice-line` | 1.5 | 选项标签行高，换行后仍与第一行对齐 |
| `--ui-height-button` | 36px | 一般操作按钮 |
| `--ui-height-button-small` | 32px | 筛选、数据来源切换、平台、阶段及标签按钮 |
| `--ui-height-input` | 40px | 单行输入框、下拉菜单 |
| `--ui-height-reply-min` | 56px | 回复框缩小时的下限 |
| `--ui-height-prompt-min` | 150px | 多行 system prompt 编辑框的最低高度 |

> 已移除的历史规格：
> 手机 `<600px` 时，`:root` 将 `--ui-font-input` 改为 `--ui-font-conversation`（16px）。回复框在所有尺寸下均为 16px。单行控件仍高 40px；多行文本框按内容／rows 决定高度，保留现有的拖曳功能，以及回复区不超过对话栏 35% 的上限。

## 全站页面框架

四个主页面使用 PageHeader，设置的三个分页共用一个页首：桌面标题在左、页面操作在右；手机上可换行。桌面侧栏 220px，内容起点 252px；外框、左右 padding 及页首由 ui-shell.css 共用。选题策划使用相同框架，不另定外框尺寸。

手机顶部 56px、页首 152px，底部预留 --ui-mobile-nav-space（64px 加安全区）。内容可滚动到固定导航上方，出现接收健康警示时也一样。手机设置页保留品牌选择与登出，切回桌面后改用侧栏控件，所选品牌不变。

页面操作用 primary、次要操作用 quiet，表单及状态沿用系统字体与色彩 Token。表格数字靠右、使用等宽数字；空数据与未知值不捏造为零。控件使用共用的高度、字号及圆角；390px 不得水平溢出，不以裁切来隐藏实际文字。

## 消息接收健康横幅与文字完整性

`--ui-health-banner-height`（72px）定义全站红色的消息接收警示，位于页面框架上方；工作区可用高度扣除此值，手机对话中也保持横幅可见。字号沿用 body，内边距沿用 content-padding／shell-gap。回复状态不得 flex 收缩到文字行高以下；名称与摘要可换行。

`check_ui_scale.py` 现在输出到 `.runtime/dm-only/`：除了现有的尺寸断言，也检查文字自身的 scrollWidth 与 overflow:hidden／clip 祖先元素造成的裁切，包括省略号。刻意以 clip 隐藏的无障碍表头不属于可见文字，垂直滚动容器允许滚动阅读。检测器另以水平省略号、垂直 hidden 两个反向案例验证会失败。三种尺寸逐一截图营销六个页面、脚本、导出、帖子评论与全站异常横幅。


## 复选框与单选框

带 checkbox／radio 的 label 使用共用的横向排列、左对齐。控件宽高引用 `--ui-choice-size`，标签字号引用 body、行高引用 `--ui-choice-line`；与文字的间距引用 brand-gap。长标签在手机上可换行，控件与第一行文字对齐。

`check_ui_scale.py` 逐一测量所有已呈现（包括可滚动区域）的 checkbox／radio，以 `input.labels` 找到标签，用 DOM Range 测量第一行可见文字，要求垂直中心差 ≤6px，控件右边缘不超过文字左边缘。不存在可见的文字标签也视为失败。另外验证 checkbox／radio 各自的纵向错位、左右颠倒与正确横排，共 6 个检测器案例。收尾截图与报告见 `.runtime/polish/`。

## 全站区块内边距（2026-09-27）

水平内边距集中在 `style.css :root`，手机覆盖集中在 `ui-shell.css :root`，实际套用由 `ui-padding.css` 统一管理。六个页面共用下列规则，不按页面另定数值。

| 变量 | 桌面 ≥600px | 手机 <600px | 用途 |
|---|---:|---:|---|
| `--ui-panel-padding` | 24px | 16px | 卡片、面板、横条、信息栏、消息气泡、评论、提示、图表、筛选工具栏 |
| `--ui-list-padding` | 20px | 16px | 帖子列表行 |
| `--ui-small-padding` | 12px | 12px | 帖子效果等小型数据格 |
| `--ui-metric-min-width` | `9ch + 2 × small-padding` | 同桌面 | 按数值字号容纳百万级数字；小格宽度不足时整格换行 |

`check_ui_scale.py` 加载 `scripts/ui_padding.js`，在 1440×900、1609×914、390×844 下对七个页面及打开的对话框、信息栏、帖子、评论、工具栏与下方内容进行测量。DOM Range 检查可见文字的每一行，从文字本身向上找最近具有非透明底色、背景图或可见边框的容器；桌面至少 20px、手机至少 14px；新分类的小型数据格至少 12px。原有面板／列表阈值不变。排除操作按钮、chips／徽章、表单控件（含搜索图标）的内部；内容型按钮不排除。等待字体、React 画面与有限动画完成后才测量与截图。

> 已移除的历史规格：
> 另外逐一检查面板／列表左右 padding 等于共用值（±1px），七个页面中同类容器的差距 ≤2px。现有的字号、高度、水平溢出、文字裁切、复选框、页首、侧栏、三栏与回复区比例断言维持原预期值；新增的 SVG 文字不得被图表 viewport 裁切，以及 18 个内边距检测器的正反案例。

最新输出默认为 `.runtime/padding/after/`，可用 `UI_SCALE_ARTIFACT_DIR` 指定目录。`report.json` 中的 `measurements[].padding.rows` 为文字距离，`containers` 为逐区块的左右内边距，`padding_violations` 为违规清单；测量输出只保存在本机被忽略的目录中。

数字完整性由 `scripts/ui_numbers.js` 以 DOM Range 计算文字行数：只含数字、逗号、小数点、百分号与货币符号的可呈现文字，一律不得多行，包括可滚动区域的内容。三种尺寸与七个页面全部检查；另以 IG 最新浏览量 `1,234,567` 的隔离数据走真实数据格与快照表，并以 8 个正反例验证检测器。回归验收通过 `UI_SCALE_ARTIFACT_DIR=.runtime/padding-fix` 存放。

## 共用组件（uniform）

以选题策划现有的设计为基准，样式集中在 `frontend/src/ui-components.css`，由 `main.tsx` 导入；只引用 P1-1 色彩与字体 Token，不加载外部资源。选题策划保留原 class 别名及尺寸，侧栏不变。

1. `.section-card`：surface 底、subtle 边框 1px、card 圆角、panel 内边距；卡片之间及标题区到内容均为 24px。h2 为 section-title、600；现有说明使用 help／subtle，与标题间距 4–8px。区块操作放在右上角，不补充不必要的说明。
2. 小节 h3：section-title、600、下边距 12px。序号圆点只用于选题策划的顺序流程。
3. 第一层 `.tabs`：subtle 下划线 1px，间距 16px，按文字宽度排列；未选中为 subtle，选中为 primary 文字、600 与 3px 下划线，底色透明。保留 tablist／tab／aria-selected、方向键及 Home／End；手机上在行内滚动。
4. 第二层及日期范围使用 `SegmentedControl`；外框内边距 3px、选中为实心。其他页面使用 compact，按内容宽度；AI 第二层保留 tab 语义，其余为 radio。选题策划原宽度不变。
5. 字段标签放在上方，help／muted、500、下边距 8px；输入框与菜单高度为 height-input。桌面两／三栏 grid、栏距 16px，390px 一栏；品牌工具栏不超过 360px。
6. 提交操作 `.primary` 为实心 primary，每张卡片最多一个；非提交（更换、测试、更新、取消、刷新、导出）使用白底框线的 `.secondary`；删除使用 `.primary.danger`。共用样式消除了同行 primary 的旧 margin-top。底部 action-row 靠右，主要按钮在次要按钮右侧、间距 12px，手机上可换行。
7. `.list-box`：subtle 1px 边框、card 圆角、overflow hidden；标题行 subtle 底、44px 高、左右 16px、help／subtle。内容行内边距 12px 16px、1px 分隔；可选行 hover 为 subtle，选中为 subtle 底、左侧 primary 3px 色条及 600。空状态居中、muted、上下 32px。表格同样规则，手机上现有的用量表转为纵向排列。
8. `.status-badge` 沿用 `.report-status`，ready 为成功、failed 为失败、pending 为处理中；neutral 为 subtle 底与 subtle 文字，表示未设置、env 或未安装。
9. `.notice`：subtle 底、左侧 3px 色条、help 字号；warning 用 pending，danger 用 danger 色条与文字，success 用 success。全局 `.error` 使用 danger 提示外观，保留 class／role。
10. `.stat-tile` 使用卡片外框、20px 内边距、help／muted 标签；数值 28px、600、tabular-nums，无数据时“—”用 subtle。数字卡间距 16px、手机上一栏；文字类分类 KPI 沿用 section-title，避免长文字被截断。
11. `details` 的 summary 使用 body、600、pointer 与可见的原生展开标记；折叠标题不单独画成空卡片。
12. 确认对话框共用选题策划的 backdrop／delete-dialog 外观；不得使用 window.confirm，保留 Escape、焦点限制与关闭后焦点恢复。

仪表盘：日期说明在共用 PageHeader 下方，两张数字卡同行；趋势与提问列表各一张卡片，范围切换位于标题右侧，列表使用 list-box，图表颜色不变。

帖子数据：平台下划线分页；粉丝工具栏左侧为年份／月份／周次三个精简下拉框，高度与一般控件相同；右侧以“粉丝数 1,234”“本周 +5”“本月 +12”行内呈现，历史的周／月显示“该周／该月”。不使用数字卡、额外标题或说明行。1440px 时为一行（控件高度加上下各 12px 内边距），768／390px 时最多两行且不水平溢出。正增长为 state-success、负增长为 state-danger、无数据为 text-subtle“—”，一般数字为 text-main，均搭配 bg-surface；圆角沿用 card Token。FB／IG／Threads 共用工具栏，YouTube／TikTok 以同宽的精简区块显示“尚未连接，连接后开始记录粉丝数”。释放出的高度供下方三栏使用，栏宽不变。左栏的范围分段控件与自定义日期与列表内容对齐，帖子列表有分隔、平台胶囊、两行正文与日期。右侧的介绍、评论与数据各自为卡片，手机上保持数据在评论之前，以及返回与分页行为。

- 工具栏内嵌筛选（例外）：发帖日期筛选并入粉丝工具栏（期间、发帖日期、统计同行），分段控件整组外框与下拉框同为 40px，扣掉 3px 内边距与框线后按钮为 32px，不套用分段按钮 40px 的规则；这段筛选不另加面板内边距，沿用外层工具栏。起始日／截止日字样只给屏幕阅读器（视觉隐藏，不用 font-size:0）。窄于 1100px 时发帖日期自成一行，不计入“最多两行”。`check_ui_scale` 与 `ui_padding.js` 将此列为例外。

设置：第一层为下划线分页，AI 第二层为分段外观，品牌菜单在独立工具栏中。基本设置与本月用量分卡；品牌说明、密钥、分类、平台、工作区沿用共用卡片。平台凭据行点击更换才展开输入，单一平台同时只展开一行，以保留单一的保存按钮；取消不变更数据。工作区原有的五组折叠保留语义，移除 summary 自身的外框，实际设置仍放在组内卡片中。Obsidian 保存为主要按钮、立即同步为次要按钮。

PageHeader 标题与操作垂直居中，工作区小字在操作左侧；1440×900、768×1024、390×844 下页面均不得水平溢出。选题策划抽取前后以相同的隔离数据截图并比对关键尺寸。

## 已移除的回复界面

收件箱、回复草稿／检查／发送、价目表、转人工条件、主管与路由分派、待回复／期限提醒及成交进度已移除。回复请使用 LINE／Facebook 原生 App。Webhook、消息保存、分类队列、私信补抓、紧急通知、选题策划、脚本及导出保留；没有删除数据或新增 migration。

### 私信退场（nodm）

工作区分页移除 DmBackfill 组件及全部操作／状态 DOM；导出、品牌、例会、通知分组维持对齐。平台连接不显示 LINE 官方账号或其三个凭据字段，保留独立的 LINE 通知卡片；Meta 没有仅供 Messenger 使用的字段，共用的连接字段保留。CSV 只接受 Facebook／Instagram 的公开评论。除选题策划现有内容外，前端不再使用“私信”字样。

新评论 KPI 与趋势沿用现有的色彩／字体 Token，没有新色彩；文字配对列入 check_ui_contrast。check_dm_backfill_frontend 保留入口名称，改为验证已退役组件不存在、零补抓 API、平台三张卡片与 390px 无溢出；不新增隔离界面检查入口。

## 移除本机 CLI 与网页 AI 撰写（nocli）

- 设置 → AI 只有“基本”“品牌说明”“AI 密钥”；没有本机 CLI 分页、启用／更新／检测／模型按钮，默认 AI 与执行方式只列 API 提供商。
- 选题策划创建区的“执行方式”为 API 提供商加上“交给 Agent 撰写”，两者都使用现有的 `.policy-grid` 与原生 select；选择后者时不调用 AI，报告停在“等待 Agent 撰写选题”并显示接手说明。可编辑者另外会看到 `.agent-handoff`：三个 secondary 链接“交给 Claude Code”（`claude://code/new?q=/mwb:ideas …`）、“打开 Claude 对话”（`claude://claude.ai/new?q=`）、“打开 Codex”（`codex://new?prompt=…&mode=codex`），加上 secondary“复制给其他 Agent”；四个按钮等宽等高，手机版两栏；命令带报告编号，链接只预填、不发送。Codex 与 ChatGPT 是同一个 App，`mode` 参数（chat／work／codex）文档中未列出，2026-10-21 实测 `mode=codex` 才会打开到 Codex 模式；Antigravity 桌面版没有官方的带命令链接，只能复制。
- 选题卡片右上角只剩“编辑”，底部只有 secondary 的“查看脚本”（有脚本时才显示）、“创建发布草稿”／“打开发布草稿”与“交给 Agent 写脚本”（2026-10-25 补回脚本入口）；旧报告的“已重新生成”“延伸自 #序号”标记保留显示。
- 创建发布草稿不再有对话框，发布页没有 AI 文案状态、“重新撰写”或“套用 AI 文案”。
- 新增或保留的文字与底色配对（卡片序号 text-subtle／bg-surface、卡片 secondary 按钮 text-main／bg-surface、Agent 接手说明 text-subtle／bg-surface、旧 CLI 报告错误说明 danger／bg-subtle、旧 CLI 用量行 text-main）已纳入 check_ui_contrast；390px 不水平溢出，不加载外部资源。

## YouTube 读取接入（ytdata）

- 平台连接在 Threads 之后新增 YouTube；同行显示频道、连接状态、令牌自动续期／失效提示及到期时间。客户端 ID／密钥沿用凭据具名表单、遮罩与保存；只有一个连接／重新连接 primary，断开与测试为 secondary；未设置／非内部 HTTPS 时停用连接。教程改为由卡片上的次要按钮“设置教程”打开站内弹窗（见 guides），不再在外部打开标签页，卡片不显示回调网址。
- 帖子数据中的 YouTube 与 FB／IG 使用相同的列表及日期筛选；Shorts 用现有的类型文字标签，其余为视频。效果七项依次为浏览量、点赞、评论、分享、平均观看时长（秒）、总观看时长（小时）、新增订阅；后四项旁标注“约延迟 1～2 天”。快照表为抓取时间／浏览量／点赞／评论，曲线默认浏览量；未知为—，已知为零时为 0。
- 订阅工具栏沿用年／月／周与本周／本月增减，名称改为订阅数；频道隐藏订阅数时显示—，说明按钮提示原因。未连接时提示连接后开始记录订阅数。评论沿用抓取／完整重抓／停止与日期窗口，显示代号与遮蔽后的正文；选题策划在有 YouTube 帖子时才显示其标签页并加入摘要。
- 色彩／字体／圆角全部沿用 P1-1 与共用 Token；延迟说明 text-subtle／bg-surface，教程弹窗见 guides，Shorts 胶囊 text-subtle／bg-subtle，已纳入 check_ui_contrast。check_youtube_data 验证四种连接状态、列表、效果、评论、订阅与 1440／768／390 无溢出；只拍修改后的 1440×900 与 390×844。

## YouTube 发布（ytpublish）

- 发布页的 YouTube 分页（`#composer-panel-youtube`）在已连接、具有上传权限且通用格式为视频时启用。顶行为频道名称与“未开启”胶囊，依次为标题字段（`aria-label=YouTube 标题`，旁注 N／100 字；为空时以灰色 placeholder 显示默认标题＝说明的第一行）、说明字段（`aria-label=YouTube 说明`，旁注 N／5,000 字节，沿用“恢复为通用文案”与 Markdown 提示）、`公开状态` 分段控件（公开／不公开列出／私享，默认公开）、儿童内容复选框“这是为儿童制作的内容”（默认不勾选）与 `.publish-thumbnail` 缩略图行。类别只在设置页中，发布页不出现。
- `.publish-thumbnail` 同行放“自定义缩略图”、96px 宽的 16:9 缩略图预览、文件名与大小（尚无缩略图时为 text-subtle 小字“JPG／PNG · 2 MB 以内 · 未上传则使用自动缩略图”）、secondary“上传缩略图／更换缩略图”与 primary danger“移除缩略图”，手机上自动换行、不水平溢出。缩略图不进入通用素材列表。
- 通用格式为图片／轮播／纯文字时，YouTube 开关停用（title“YouTube 仅支持视频”）并从已选平台中移除，分页只显示 `.notice.warning`“YouTube 仅支持视频”，分页标签不加红点。竖版或正方形且 ≤3 分钟时显示 `.notice.warning`“将被归为 Shorts…”；缩略图行改为“Shorts 不支持自定义缩略图”并停用上传，已有缩略图时以红字要求移除并阻止发布，预览改为 9:16 且不套用缩略图。标题超过 100 字、说明超过 5,000 字节时以红字阻止发布，分页标签加红点。
- 既有连接缺少上传权限：YouTube 开关为灰色，分页显示“需要重新连接以获取上传权限”与 secondary“设置 → 平台连接”（未连接时仍是“尚未连接”）。设置页的 YouTube 卡片以 `.notice.warning.oauth-permissions`“需要重新连接以获取上传权限”提示，状态胶囊维持“已连接”，“重新连接”改为 secondary，其余读取功能不受影响；已连接时另有“上传类别”下拉框（默认“人物与博客”，选择后即保存并提示“已保存上传类别”）。
- YouTube 预览 `.publish-preview-post` 依次为视频（一般 16:9，Shorts 9:16，缩略图作为封面 poster）、粗体 `.publish-preview-title` 标题、`.publish-preview-identity` 频道名称、`.publish-preview-actions.is-youtube` 互动行（赞／分享／保存，只画外观）、`.publish-preview-caption` 说明（bg-subtle 圆角框，仍可折叠，并以 link-color 标示 hashtag）。
- 确认弹窗的 YouTube 项目为“视频 · 公开状态 · 儿童内容／非儿童内容 · 自定义缩略图／自动缩略图（· Shorts）”与“标题：…”。
- 发布记录：YouTube 结果链接为“查看视频”。缩略图失败时同行显示 `.status-badge.pending`“缩略图未应用”、安全的中文原因与 secondary“重新应用缩略图”（查看者不显示，需开启发布总开关，先经 ConfirmDialog“只会更换缩略图，不会重新上传视频”）；视频仍算成功。YouTube 返回的实际公开状态与所选不同（例如被限制为私享）时，加 `.status-badge.pending`“YouTube 实际为私享”。
- 色彩、字体、圆角全部沿用 P1-1 Token，没有新增写死的颜色；新的文字／底色组合已纳入 check_ui_contrast。check_publish 验证 YouTube 分页的字段与上限、缩略图、Shorts、非视频停用、预览顺序／粗体／比例／封面、缺权限引导、确认弹窗与记录中的缩略图失败／重新应用，check_youtube_data 验证连接卡片的上传权限提示与类别保存，都包含 1440／768／390 无水平溢出。只拍修改后的 1440×900 与 390×844。

## 界面排列调整（uiorder）

只改排列，不改功能与文字；覆盖前文的相关描述。

- 发布（新建帖子、快拍同样规则）：`.publish-footer` 把“立即发布／定时发布”切换（定时发布时含日期时间字段 `.publish-schedule`）与右侧的 `.publish-submit`（`.publish-actions` 按钮行加上其下方的 `#publish-disabled-reason`）放在同一个底部操作行中。桌面上同行，时间设置靠左、按钮靠右，停用原因在按钮下方右对齐；390px 时分为两行，但仍在同一个操作行内，原因左对齐。“新帖子／新快拍”按钮在 `.publish-editor-heading` 右侧，位于平台分页之上。
- 选题策划：评论范围的顺序为近 7、30、60、90 天、自定义日期（默认仍为 30 天）；390px 时分段按钮换行，不横向溢出、不裁切。第 3 步的按钮顺序为 secondary“重新标注所选评论”在左、primary“立即策划”在最右。页首不再显示没有标签的数字，“选题列表”标题显示为“选题列表（N）”。
- 帖子数据：评论同步区 `.comment-sync`（状态、“抓取评论”“完整重抓”“停止”）位于“评论与回复”卡片内，在评论日期筛选与范围总数之后；右侧的“帖子效果”只保留效果数字、图表与快照。FB／IG／Threads／YouTube 一致。“评论与回复”标题下方一行 `.comment-retention.muted` 按 `/api/posts/platforms` 的设置说明观众评论的保存期限（FB／IG／Threads 自获取起 N 天；YouTube 30 天内未重新抓取即删除；TikTok 不读取评论），未启用每日删除时在同一句中说明；这是平台条款要求的披露，是此卡片唯一的说明行，读不到设置时就不显示。

### 品牌菜单整合与文字（uiorder 第二轮）

- 品牌只在侧栏（手机上为 `.mobile-brand-picker`）中选择；AI 的“套用品牌”、消息分类的“套用品牌”、选题策划第 1 步的“品牌”、发布的“品牌”、工作区的“当前品牌”全部移除，各页面使用 App 传入的 brand。发送给后端的 brand_id 参数不变。
- 用户只能看到一个品牌时，侧栏与手机都不显示品牌菜单，App 的有效品牌直接使用该品牌（网址仍带 brand_id）；多于一个品牌时照旧包含“全部可见品牌”。仪表盘、帖子数据可使用“全部”；选题策划、发布、设置中的 AI、消息分类改为显示 `.need-brand`“请先在左侧选择品牌”（手机上为“请先在上方选择品牌”，以 CSS 按 600px 切换），不显示编辑内容；工作区在“全部”时只保留与品牌无关的数据、系统分组。网址中的 brand_id 照旧有效。
- 文字：全站统一为“工作台”；侧栏移除“品牌工作区”标签与底部标语，只保留“品牌运营工作台”；页首右上角不再重复工作区名称；标题为“仪表盘”“帖子数据”；发布标题行移除“已开启／未开启”胶囊（保留顶部提醒、开关按钮与按钮下方的原因）；成员行为“Agent 连接 N 个”“撤销全部 Agent 连接”；Webhook 字段标签为“公开网址”“Meta 评论通知网址”“LINE 通知网址”；凭据字段的 .env 名称改为小号 text-subtle 等宽字。
- 设置分页顺序为平台连接、AI、消息分类、工作区、成员、我的账号；默认分页为平台连接（网址指定 settings_tab 时照旧）。帖子数据的粉丝数行加小标题“粉丝数统计周期”（YouTube 为“订阅数统计周期”）。选题策划报告状态为已完成，但导出文件不存在或未全部生成时，标题显示“已完成 · 导出未完成”。
- check_brand_scope 验证单一品牌时没有菜单、多品牌时“全部”的提示与选择后的内容、新的文字、分页顺序与默认分页；多品牌时以浏览器端替身 /api/brands 加入第二个品牌，不写入数据库。

## 帖子数据效果居中与完整帖子（postcenter）

覆盖前文 metricwidth、YouTube“效果七项”与正文“展开全文／收起”的描述。

- 桌面（≥1280px）三栏：左侧帖子列表 280px，中间 `.post-metrics`“帖子效果”自动宽度（最宽），右侧 360px 的 `.post-conversation`（帖子摘要卡＋评论与回复）。效果数字格按宽度自动排列（每格至少 120px）。
- 600～1279px 与手机一样为单栏：帖子摘要、帖子效果、评论与回复依次排列。
- 帖子摘要卡：72px 缩略图（裁切填满）在左，右侧为账号・类型、两行正文（`p.post-caption.collapsed`，正文不是标题，不用 h2）、时间；下方一行 secondary“完整帖子”与“打开原帖 ↗”。不再有“展开全文／收起”。
- “完整帖子”打开 `.guide-dialog.post-full-dialog` 弹窗（沿用设置教程弹窗的外框、焦点进出、Tab 循环、Esc 与“关闭”）：账号・类型、原比例图片、完整正文（保留换行）、发帖时间、原帖链接。手机上全屏。
- “观看表现”区（`.watch-metrics`，h4）接在效果数字格之后，只在视频帖子中出现（FB／IG 视频与 Reels、YouTube 全部、TikTok 全部、Threads 视频）：FB 为平均观看时长（秒）、总观看时长（小时）；IG 再加“前 3 秒划走率（%）”；YouTube 为平均观看时长、平均观看百分比（%）、总观看时长，三项都标注“约延迟 1～2 天”。FB 有留存曲线时另外显示 `.retention-chart`“观众留存”与“视频中段仍在看／看到结尾”。TikTok、Threads 只显示一行说明，官方 API 没有这些数据。曲线卡片都用外框（`.metric-chart`）加标签页（`.tabs.chart-tabs`，role=tablist“曲线指标”，标签多时换行、不横向滚动）切换指标，不用下拉菜单：“数据变化”放互动指标；视频帖子另有“观看变化”卡片，放观看表现的三项；FB 的“观众留存”也是同样外框的卡片。2026-10-24 起移除“数据快照”表：它列出的是同一批快照中的其中三项，“数据变化”曲线已涵盖全部指标（鼠标移到点上可看精确数字），只保留曲线；快照达 100 条时在曲线下方显示“显示最近 100 条快照。”。YouTube 上方的效果数字格改为五项：浏览量、点赞、评论、分享、新增订阅。
