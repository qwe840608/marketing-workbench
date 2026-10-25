# 平台政策与 API 限制

> **语言 / Language / 語言 / 言語**：[繁體中文](平台政策.md) | 简体中文 | [English](platform-policies.md) | [日本語](プラットフォームポリシー.md)

整理工作台会涉及的平台条款与 API 规格，免得每次重新查。每条都注明出处与核实日期；**“推论”**是我们根据条文做出的判断，**“未核实”**是还没在官方文档中找到依据的说法。条款会更新，发现与官方不符时以官方为准，并更新这份文档与核实日期。

核实日期：2026-10-15～2026-10-17（应用模式、Google OAuth、TikTok Sandbox 于 2026-10-17 补查；FB 公共主页 Webhook 与各平台受众数据于 2026-10-19 补查）。

> 这份文档只记录规定与工作台的对应做法，不是法律意见。开源后每位自托管者都是自己应用的开发者，义务在他们身上（README 待补，见开源规划）。

## 通用原则

- 只用官方 API 与官方密钥；不爬取网页、不模拟登录。
- 对外文字（App 名称、说明、官网）如实描述用途与功能，不把用途包装成不符合事实的样子去提交审核。
- 隐私政策与服务条款：放在自托管者自己的网站上（模板见 `docs/templates/`，须知见 `docs/合规须知.md`），各平台后台填写这组网址，数据删除说明可指向隐私政策的 `#delete` 段落。
- 观众评论保存期限：自工作台**获取**起 365 天（`COMMENT_RETENTION_DAYS`），不是自评论发布时起算。这是工作台自定的规则（Meta 没有规定天数），隐私政策写同样的期限。实现见 `docs/部署与运维.md` 的数据保留段落。

## Meta（Facebook／Instagram／Threads）

出处：[Meta 开放平台使用条款](https://developers.facebook.com/terms/)（2026-02-03 版）、[开发者政策](https://developers.facebook.com/devpolicy/)。

| 规定 | 内容 | 工作台的做法 |
|---|---|---|
| 隐私政策（条款 4） | 要有公开的隐私政策，写明处理哪些数据、目的、如何请求删除。 | 自托管者自己的隐私政策页，含 `#delete`（模板 `docs/templates/隐私政策模板.md`）。 |
| 数据删除（条款 3.d） | 没有正当用途时删除，并提供删除渠道；没有规定天数。 | 评论 365 天（自获取起）；`scripts/data_retention.py --find-commenter／--delete-contact` 处理个别删除请求。 |
| 服务提供商（条款 5.a） | 提供商只能按你的指示处理数据，不得用于自己的目的，且要**书面**同意。 | Gemini 免费方案会用内容改进产品 → 默认停用，`GEMINI_PAID_TIER=true` 才开放。TypeSafe 隐私政策写明不用输入数据训练，但严格来说还缺 DPA（由用户决定是否发邮件索取）。 |
| IG 用户内容 | 未经同意不得导入或备份 Instagram 用户内容。 | 只缓存自己账号帖子的缩略图。**推论**可以，没有明确依据。 |
| 权限闲置 | 权限或 API 超过 28 天未使用，Meta 可能停用。 | 每小时同步会持续使用读取权限；发布权限需要定期有发帖。 |

### Meta 应用模式与访问级别（2026-10-17 核实）

出处：[应用模式](https://developers.facebook.com/docs/development/build-and-test/app-modes)、[访问级别](https://developers.facebook.com/docs/graph-api/overview/access-levels)、[Instagram Webhooks](https://developers.facebook.com/docs/instagram-platform/webhooks)、[Threads 入门](https://developers.facebook.com/docs/threads/get-started)。

- **标准访问权限（Standard Access）**：所有商家应用自动获得，不需要 App Review；只能向“在应用上有角色”的用户（管理员、开发者、测试人员）请求。只供自己使用的工具，这样就足够了。
- **高级访问权限（Advanced Access）**：要服务没有角色的用户时才需要，必须逐项通过 App Review，并完成商家验证。
- **开发模式**：只能向有角色的用户请求权限；文档没写期限，但也没明说可以长期这样使用。
- **Instagram 评论 Webhook**：应用必须处于 **Live** 模式，`comments` 需要 **Advanced Access**，账号必须公开。只用标准访问权限时收不到 IG 评论 Webhook，要靠定期 API 读取。FB 公共主页评论 Webhook：开发模式只发送后台测试事件与有应用角色者自己触发的事件，其他人的评论要应用上线后才会发送；另外公共主页必须用公共主页访问令牌调用 `POST /{page-id}/subscribed_apps?subscribed_fields=feed` 安装应用（需要 `pages_manage_metadata`），只在后台订阅字段是不够的。工作台目前没有做这个调用（2026-10-19 核实：[Webhooks](https://developers.facebook.com/docs/graph-api/webhooks)、[Webhooks for Pages](https://developers.facebook.com/documentation/pages-api/webhooks-for-pages)）。
- **Threads**：有角色的测试人员可随时授权，不需要 App Review；要服务没有角色的用户时，每个权限都要审核并发布应用。

### Meta API 规格（发布相关）

- **IG Reels 封面**（[IG User Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media)）：`cover_url` 仅限 Reels，须为公开网址、JPEG、8 MB 以内、sRGB；建议 9:16，否则裁切中间部分，分享到动态时裁成 1:1。同时提供 `cover_url` 与 `thumb_offset` 时使用 `cover_url`。快拍与轮播子项目不支持 `cover_url`。工作台 0048 已实现（PNG 转 JPEG 后发送）。
- **FB 普通视频封面**（[Page Videos](https://developers.facebook.com/docs/graph-api/reference/page/videos/)）：上传时的 `thumb` 参数（图片原始数据）；文档没写格式与大小限制。
- **FB Reels 封面**（[Reels Publishing](https://developers.facebook.com/docs/video-api/guides/reels-publishing)）：Reels 发布三个步骤（start／upload／finish）都没有封面参数；文档最后指向 [Video Thumbnails](https://developers.facebook.com/docs/graph-api/reference/video/thumbnails) 来“为 Reels 添加自定义封面”。
- **Video Thumbnails**：`POST /{video-id}/thumbnails`，`source`（图片文件）＋ `is_preferred=true`；最大 10 MB，建议与视频同比例；只能用于已关联公共主页的视频。需要 Page 令牌与 `pages_read_user_content`、`pages_manage_engagement`、`pages_show_list`。文档没有明说适用于 Reels，只是 Reels 文档指向它 → 实测确认。工作台 0049 对普通视频与 Reels 都用这个接口（不用 `thumb` 参数），在帖子发布成功后才应用；`pages_manage_engagement` 是可选权限，在 Meta 后台开启后还要重新连接才会出现在令牌中（2026-10-17 确认正式令牌缺少该权限）。
- Graph API 版本：`v26.0`（`oauth.FB`）。

## YouTube／Google

出处：[YouTube API 服务开发者政策](https://developers.google.com/youtube/terms/developer-policies)、[Google API 服务用户数据政策](https://developers.google.com/terms/api-services-user-data-policy)、[YouTube 服务条款](https://www.youtube.com/t/terms)。

| 规定 | 内容 | 工作台的做法 |
|---|---|---|
| 30 天规则（III.E.4） | 统计数字（观看、点赞）可长期保存，但每 30 天要确认授权与视频仍然有效；其他数据（标题、缩略图、评论）最多保存 30 天，到期删除或重新获取。 | 每小时同步更新视频；YouTube 评论 30 天未重新获取就删除；YouTube 上已删除的视频数据 30 天后删除。 |
| 撤销授权 | 撤销后 7 天内删除通过该授权获取的数据；要提供删除已存数据的方式，7 天内完成。 | “断开连接”撤销授权并立即删除 YouTube 视频、快照、缩略图、评论与报告引用（不会删除 YouTube 上的视频）。 |
| 隐私政策 | 说明使用了 YouTube API 服务，附 [Google 隐私政策](https://policies.google.com/privacy) 与撤销授权页 `https://security.google.com/settings/security/permissions`。 | 隐私政策模板已包含。 |
| 服务条款 | 附 YouTube 服务条款链接，并写明用户同意受其约束。 | 服务条款模板已包含。 |
| 范围最小化 | 只申请需要的范围。 | `youtube.readonly`、`yt-analytics.readonly`、`youtube.upload`；不请求 `youtube`／`force-ssl`。 |

OAuth 发布状态（2026-10-17 核实，[OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)、[何时不需要验证](https://support.google.com/cloud/answer/13464323)）：
- 同意屏幕为“外部”且发布状态为 **Testing（测试）** 时，refresh token **7 天后失效**（只请求名称、邮箱、个人资料的情况除外），相当于每周要重新连接一次。
- **个人使用（100 人以下）不需要验证**：发布状态改为“正式版（In production）”后，用户登录时可以跳过“未经验证的应用”警告页面；超过 100 人才必须验证。未经验证时仍须遵守 API 用户数据政策。
- 未经验证的 API 项目上传的视频**不会**被限制为私享（`videos.insert` 文档原文，2026-10-17）；工作台实际上传过一个“不公开列出”的视频，实际状态也是不公开列出。

API 规格：`videos.insert` 使用 resumable upload；缩略图 `thumbnails.set` 接受 JPEG／PNG、2 MB 以内；Shorts 自定义缩略图 API 未列出支持（工作台已停用）。配额：`videos.insert` 另有每日上传额度，其余读取共用 `youtube.quota`（见 `docs/部署与运维.md`）。

## TikTok

出处：[开发者服务条款](https://www.tiktok.com/legal/page/global/tik-tok-developer-terms-of-service/en)（2025-12-26 版）、[App 审核准则](https://developers.tiktok.com/doc/app-review-guidelines)、[内容分享规范](https://developers.tiktok.com/doc/content-sharing-guidelines)、[Content Posting API 入门](https://developers.tiktok.com/doc/content-posting-api-get-started)、[媒体传输指南](https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide)、[上传视频（收件箱）](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video)、[查询发布状态](https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status)、[令牌管理](https://developers.tiktok.com/doc/oauth-user-access-token-management)、[视频列表](https://developers.tiktok.com/doc/tiktok-api-v2-video-list)。工作台的完整规划见 `docs/TikTok规划.md`。

### 开发者条款

| 规定 | 内容 | 工作台的做法 |
|---|---|---|
| 调用量（III.3.g） | 不得过量或滥用；发帖相关 API 每分钟最多 6 次。 | 每小时同步；只在定时发布的时间发送。 |
| 水印（III.3.t） | 不得在用户视频上叠加品牌、logo、水印。 | 不修改视频文件。 |
| 同意 | 用户明确同意前不得上传任何内容。 | 只有用户确认发布或定时发布后才发送。 |
| 隐私披露（III.2.c） | 完整、准确地披露隐私做法。 | 自托管者的隐私政策页。 |
| 个人档案（III.3.h） | 不得收集他人数据、建立个人档案或数据库。 | 只读取自己的账号，不读取评论。 |
| 背书（III.3.o） | 不得让人误以为与 TikTok 合作或获得其背书。 | App 名称不含 TikTok（作者自用的是“ruidefilm Workbench”）。 |
| 公开声明（X） | 未经书面同意，不得就你与 TikTok 的关系或获得开发者服务一事发表公开声明。 | **推论**：介绍时说“用官方 API 发送到收件箱”这类功能描述，不说“与 TikTok 合作／官方认可”。 |
| 商业用途（III.3.c） | 未经书面同意不得用于商业广告、招揽、滥发。 | 发布自己的作品属于 Content Posting API 本来的用途；商业合作内容要按 TikTok 规定披露。界线模糊，**未确认**。 |
| 身份真实（III.3.q） | 不得使用虚假身份。 | 不以公司名义申请 Business API。 |
| 开源（III.3.e） | 不得让 TikTok 开发者服务受开源许可义务约束。 | 只调用 API，不包含 TikTok SDK 或示例代码；开源时再检查。 |
| 安全事件（III.2.f） | 被入侵时立即断开连接并报告 TikTok。 | 运维人员的责任。 |
| 终止（VI） | 开发者服务终止时删除所有通过 API 获取的数据。 | “断开连接”会撤销授权并删除 TikTok 数据。 |
| App 名称（审核准则） | 不能提及社交媒体公司，要与 App／网站名称一致，不能只描述功能。 | 用自己的网站或品牌名称，例如“〈品牌〉 Workbench”。 |

### 审核与发布限制

- **Sandbox**（[文档](https://developers.tiktok.com/doc/add-a-sandbox)）：“无需审核即可试用集成的受限环境”，最多 5 个、每个最多 10 个目标账号，文档没写到期日；**没有说能否长期作为正式用途**，定位是测试。Sandbox 不开放公开视频的 Content Posting API。工作台目前依靠 Sandbox 运行，属于灰色地带（推论：最坏情况是应用被限制，而不是 TikTok 账号被封，因为视频是你自己在 App 内发布的）。
- **未审核（Sandbox）**：Direct Post 只能 `SELF_ONLY`，发帖账号必须是私密账号，24 小时内最多 5 个用户发帖。收件箱上传（`video.upload`）可用，由用户在 App 内完成发布。
- **App 审核准则的通则**（2026-10-17 查）：“Apps must not be for private or personal use”、“Apps that are still in development or testing will not be approved”，只申请需要的权限，且每个产品与权限都要在演示视频中呈现；演示视频要用 Sandbox 录制完整流程，域名要与填写的网站一致。准则本身没有 Content Posting API 的用途清单（清单在内容分享规范中）。**推论**：只供自己或自家客户账号使用的工作台属于“私人用途”，提交审核（无论是否申请 Direct Post）很可能被拒。
- **Direct Post 审核**：用途要是“协助真实创作者发布原创内容”并面向广泛用户。明确列出**不接受**：“帮你或团队管理的账号上传内容的工具”、仅供测试、搬运其他平台的内容。审核表单要填写使用量估计，用于决定每 24 小时的创作者上限。**推论**：工作台目前的定位（管理自己的账号）无法通过，只有变成真正供多位创作者使用的产品才能如实提交审核。
- **Direct Post 界面要求**（仅审核时需要）：每次读取 creator_info 并显示昵称、按 `max_video_post_duration_sec` 检查时长、隐私下拉菜单无默认值、评论／合拍／拼接默认不勾选、音乐使用声明、商业内容披露、预览、提示处理需要几分钟并追踪状态。演示视频与 2–6 周审核期只见于第三方文章，**未核实**。
- **收件箱上传**：init 接口没有文案字段（文案只能在 App 内粘贴），也没有封面字段（封面在 App 内选择；`video_cover_timestamp_ms` 只属于 Direct Post）。24 小时内最多 5 个待处理（`spam_risk_too_many_pending_share`），每个账号每天约 15 篇。
- **收件箱能否带文案**（2026-10-17 再查）：视频收件箱 init 的 body 只有 `source_info`（`source`、`video_size`、`chunk_size`、`total_chunk_count` 或 `video_url`），没有 `post_info`／`title`／`description`；`video.upload` 范围的说明也是“以草稿形式发送到创作者账号，再到 TikTok 编辑发布”。能带文字的只有：Direct Post（`post_info.title`，需要 `video.publish`＋审核）、图片帖子（`/v2/post/publish/content/init/` 的 `post_info.title`／`description`，但图片要从已验证域名拉取）、Share Kit（原生 iOS／Android SDK，文档只提到 partner hashtag，没有文案字段，网页工具用不到）。实测：2026-10-17 未经审核的 Sandbox 应用已成功把视频发送到收件箱。
- **视频规格**：API 上传最长 10 分钟；64 MB 以内可一次发送，否则分段（工作台用 10 MB）。按账号查询上限的 `creator_info` 需要 `video.publish`，工作台没有申请。
- **图片帖子**：只能从已验证域名的公开网址下载 → 工作台不支持，提示“仅支持发布视频，图文需从 App 上传”。
- **令牌**：access token 24 小时；refresh token 365 天，每次刷新都会轮换。
- **数据**：Display API 视频列表只返回公开视频（含播放等计数）；粉丝数来自 user/info。私密视频不在列表中，所以“已删除或改为私密”一并处理。
- **封面**（[Query Videos](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query)，2026-10-19 查）：`POST /v2/video/query/` 需要 `video.list`，一次最多 20 个视频 ID，只返回授权账号自己的视频，文档说可用来“刷新封面网址的有效期”（没写多久）。工作台的缩略图缓存用它获取 `cover_image_url` 后立即缩小成 JPEG 存档。CDN 域名文档没写，工作台暂时允许 `tiktokcdn.com`／`tiktokcdn-us.com`／`tiktokcdn-eu.com`，**未实测**。
- **评论**：只有 TikTok API for Business 能读取，申请者须为公司并使用公司域名邮箱，不接受个人开发者 → 工作台不读取 TikTok 评论。

## 受众数据（各平台，2026-10-19 核实）

| 平台 | 官方提供 | 条件 | 工作台的做法 |
|---|---|---|---|
| Instagram | `follower_demographics`（年龄、性别、国家、城市，`timeframe` 必填）；`online_followers`（每小时在线人数，只保留 30 天） | `instagram_manage_insights`；粉丝 ≥100 人。`online_followers` 只出现在官方页面的限制段落、不在指标表中，**未核实**是否会停用 | 每天获取一次，见 `docs/架构.md` 受众分析 |
| Facebook 公共主页 | 只剩地区：`page_follows_country`／`page_follows_city` | `read_insights`。年龄与性别（`page_fans_gender_age`、`page_follows_gender_age`）2024-03-14 停用、无替代；`page_fans_city／country` 2025-11-15 停用 | 只显示地区，并说明年龄与性别已停用 |
| Threads | `follower_demographics`（国家、城市、年龄、性别，一次一种） | `threads_manage_insights`；粉丝 ≥100 人；不支持 since／until。没有在线时段指标 | 每天获取一次 |
| YouTube | YouTube Analytics：按 `ageGroup`、`gender` 的 `viewerPercentage`；按 `country` 的 `views` | `yt-analytics.readonly`。年龄与性别只包含已登录的观众。Studio 的“观众在线时间”API 没有提供（**推论**：官方维度清单中没有对应项目） | 近 28 天 |
| TikTok | Display API 没有受众数据；Business API（企业账号）有年龄、性别、地区、活跃时段 | Business API 要另外申请、审核，且仅限企业账号 | 不做，界面中说明原因 |
| LINE | Messaging API 提供官方账号好友的人口统计（`/v2/bot/insight/demographic`） | 需要连接品牌官方账号；工作台的 LINE 只用于通知（`AGENTS.md`） | 不做，界面中说明原因 |

出处：[IG 账号 Insights](https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights)、[已停用的公共主页 Insights 指标](https://developers.facebook.com/documentation/pages-api/platforminsights/page/deprecated-metrics)、[Threads Insights](https://developers.facebook.com/docs/threads/insights/)。

## 视频观看指标（各平台，2026-10-23 核实）

| 平台 | 官方提供 | 工作台的做法 |
|---|---|---|
| Instagram Reels | 媒体 insights：`ig_reels_avg_watch_time`、`ig_reels_video_view_total_time`（毫秒，官方标注为开发中）、`reels_skip_rate`（前 3 秒划走的比例，估计值、开发中）。没有留存曲线 | 三项合并为一次调用（原本就要调用平均观看时长，不额外消耗 Meta 配额）；整批被拒时退回只读取平均观看时长，多一次调用 |
| Facebook 视频／Reels | 帖子 insights：`post_video_avg_time_watched`、`post_video_view_time`（毫秒）、`post_video_retention_graph`（40 等分的留存比例）。2026-06-15 停用的是 `post_video_views_unique` 等去重人数指标，这三项不在停用清单中 | 同上，三项一次调用；留存曲线显示在“观看表现”中 |
| YouTube | Analytics：`averageViewDuration`、`estimatedMinutesWatched`、`averageViewPercentage`；留存曲线 `audienceWatchRatio` 要为每个视频另外调用一次报表 | 平均观看百分比与原有报表在同一次调用中获取；留存曲线暂不获取（每个视频多一次调用，会占用每轮 420 次的上限） |
| Threads | 帖子 insights 只有 views、likes、replies、reposts、quotes、shares | 没有观看时长或留存，界面中说明 |
| TikTok | Display API `video/list` 只有 view／like／comment／share 次数与视频时长；观看时长、完播率需要 Business API（企业账号、另行审核） | 不做，界面中说明 |

出处：[IG Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights)、[Page／Post Insights](https://developers.facebook.com/docs/graph-api/reference/insights)、[YouTube Analytics 指标](https://developers.google.com/youtube/analytics/metrics)。

## AI 与其他服务提供商

| 服务 | 规定 | 工作台的做法 |
|---|---|---|
| Gemini API（[附加条款](https://ai.google.dev/gemini-api/terms)） | 免费方案会用传入的内容改进 Google 产品，可能由真人审阅，不要发送个人信息；付费方案不会。 | 默认停用，`GEMINI_PAID_TIER=true` 才能处理平台数据。2026-10-01～02 曾用免费方案处理过屏蔽后的 IG 评论，无法撤回。 |
| Anthropic 个人方案（[消费者条款更新](https://www.anthropic.com/news/updates-to-our-consumer-terms)） | Free／Pro／Max（含 Claude Code）在用户允许时会用对话训练，数据保留 5 年。 | Agent 通过 MCP 读到的评论会进入对话 → 用户需关闭“Help improve Claude”。 |
| ChatGPT／Codex | 应该有类似的数据控制设置。 | **未核实**菜单位置与条款。 |
| TypeSafe（[隐私政策](https://typesafe.ai/legal/privacy-policy)，2025-11-19 版） | 不用输入内容训练或微调；只提供给服务提供商。 | 符合 Meta 的精神，但缺少书面 DPA。 |
| LINE（[开发者协议](https://terms2.line.me/LINE_Developers_Agreement?lang=en)） | 只在必要范围内处理数据。 | 只把屏蔽后的评论前 180 个字发送到自己的通知群组；Push 先确认额度。 |
| 所有云端模型 | — | 发送前一律经过 `redact.py` 屏蔽个人信息。 |
