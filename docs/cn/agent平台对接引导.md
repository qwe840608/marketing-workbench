# 给 AI Agent 的平台对接引导（浏览器协助）

> **语言 / Language / 語言 / 言語**：[繁體中文](../zh-tw/agent平台串接引導.md) | 简体中文 | [English](../en/agent-platform-setup-guide.md) | [日本語](../jp/エージェント向けプラットフォーム連携ガイド.md)
>
> **Agent：开始前先判断用户使用的语言**（看用户发给你的消息；还没开口就看系统语言）。不是简体中文时，改读上面对应语言的版本照做，全程用那种语言与用户沟通；四种都不符合时读 English 版，但仍用用户的语言回复。

这份文档是写给 **AI agent** 看的。用户第一次搭好工作台后，要把 Facebook 公共主页、Instagram、Threads、YouTube、TikTok 连进来，得先在各平台的**开发者后台**创建自己的应用。步骤繁琐，你可以操作浏览器替用户填写设置，用户只做必须本人做的部分。

- 前提：已按 [`agent安装引导.md`](agent安装引导.md)（给 AI Agent 的安装引导）完成阶段 1–5（工作台能用内部 https 地址打开、隐私政策与服务条款已公开）。
- 你能操作浏览器时按这份文档做（例如 Claude in Chrome、Claude 内置浏览器、Codex 的浏览器工具）；不能时，就按同样的步骤用文字一步一步带用户自己点。
- 步骤与工作台“设置 → 平台连接 → 设置教程”相同（来源 `frontend/src/platformGuides.ts`，用的是后台实际页面的用语）；权限以 `backend/app/services/oauth.py` 为准；规定与出处见 [`平台政策与API限制.md`](平台政策与API限制.md)（平台政策）。三者不一致时以代码为准，并反馈给维护者。

下文的工作台界面名称以简体中文界面为准；平台后台的按钮名称以 Meta、Google Cloud 简体中文界面为准，与实际页面不同时以页面为准。

## 边界（一定要遵守）

可以做：在开发者后台导航、点击、填写**非机密**字段（应用名称、用例、回调网址、权限、scopes、启用 API、品牌名称与联系邮箱、类别、说明、隐私政策与服务条款网址），点击“保存”。

不可以做：

1. **登录、密码、2FA、安全确认**一律由用户本人输入。遇到登录页或“请输入密码”就停下来请用户操作，完成后再继续。
2. **不碰密钥**：不点击“显示”应用密钥／Client secret，不复制、不读出、不写进对话或文件、不截取含密钥的页面。应用编号与密钥由用户自己粘贴到工作台“设置 → 平台连接”对应的卡片（会加密保存），不要贴在对话里。
3. **不点击工作台的“连接〇〇账号”，不代为点击任何 OAuth 授权／同意页面**，也不代为同意开发者条款（例如 TikTok“Target Users”的登录与同意）。
4. **不提交审核、不改上线模式**：不提交 Meta App Review 或商家验证、Google 应用验证、TikTok Production 审核；不把 Meta 应用切换为 Live。TikTok 的 Direct Post 保持关闭。
5. **不发帖、不回复评论、不打开任何发送或发布开关**；不爬取网页、不使用非官方 API。浏览器只用于开发者后台的设置页面。
6. **会创建资源或同意条款的按钮先问**（创建应用、创建 Google Cloud 项目、Google“发布应用”），用户同意后才点。
7. **页面与这份文档不一致时不要猜**：后台经常改版。先截图给用户看并说明差异，必要时查官方文档，再决定下一步。
8. **用途不符就停**：要代运营客户账号、管理多家不同公司的品牌，或开放给他人注册时，先说明这不在支持范围内、可能违反平台规定（见 [`合规须知.md`](合规须知.md)（合规须知）），让用户决定。

## 开始前

1. 开新标签页工作，不动用户原本的标签页。
2. 询问要设置哪些平台，并确认账号类型：Facebook 要是**公共主页管理员**；Instagram 要是**专业账号并关联到该公共主页**；Threads 个人账号即可；YouTube 要用拥有频道的 Google 账号（品牌频道选择品牌账号）；TikTok 个人账号即可。
3. 获取**回调网址**：请用户打开工作台“设置 → 平台连接”，在该平台卡片的“设置教程”中点击复制按钮后贴给你（回调网址不是机密）；或者你自己用浏览器打开那个窗口读取。格式是 `<内部 https 地址>/api/oauth/<meta|threads|youtube|tiktok>/callback`。开头不是 `https://` 就先停下：工作台要用内部 https 地址打开才能连接。
4. 准备好**隐私政策与服务条款的公开网址**（TikTok Sandbox 也必填）。
5. **应用名称**用用户的网站或品牌名称（例如“〈品牌〉 Workbench”），不能包含 TikTok、Facebook、Instagram 等平台名称，也不要只描述功能。

每做完一步就截图确认，跟用户说一句做了什么；回调网址与权限要逐字核对。

## Meta（Facebook 公共主页＋Instagram）

后台：<https://developers.facebook.com/apps/>

1. （先问）“创建应用” <https://developers.facebook.com/apps/creation/>，名称用品牌名；用例选择与公共主页相关的项目，其余点击“下一步”。
2. “应用设置 → 基本”：填写隐私政策网址、服务条款网址、数据删除说明网址（可指向隐私政策的 `#delete`）、类别与联系邮箱，保存。应用编号与密钥请用户自己粘贴到工作台 Meta 卡片的“应用 ID”与“应用密钥”。
3. 在“Facebook 登录 → 设置”（通过用例流程创建的叫“Facebook 企业版登录 → 设置”）的“有效 OAuth 跳转 URI”中粘贴 meta 回调网址，点击“保存更改”。
4. 在“用例 → 自定义 → 权限和功能”中逐个找到并点击“添加”（不支持一次全部添加，可用页面搜索）：`pages_show_list`、`pages_read_engagement`、`pages_read_user_content`、`pages_manage_metadata`、`pages_manage_posts`、`read_insights`。可选：`pages_manage_engagement`（用于视频自定义封面；缺少时只停用封面功能）。
5. 有 Instagram 时：在同一页面再添加 `instagram_basic`、`instagram_manage_comments`、`instagram_manage_insights`、`instagram_content_publish`。同一页面找不到时，到“用例”添加“管理 Instagram 上的消息和内容”，选择“通过 Facebook 登录设置 API”后再添加。
6. 交给用户：在工作台点击“连接 Meta 账号”，在授权页面点击“编辑设置”（或“编辑访问权限”）勾选公共主页和 Instagram。

只供自己使用时，标准访问权限就够了，**不用提交审核**；进行连接的人要在应用上有角色。

### Meta Webhook（可选，要先完成 ngrok，WEBHOOK_PUBLIC_URL 有值）

1. 验证令牌由用户自己在工作台 Meta 卡片的“手动设置（高级）→ Webhook 验证令牌”中设置，并由用户自己在后台输入，你不经手。
2. 在后台左侧“Webhooks”中选择“Page”→“订阅此对象”，回调网址填写 `<WEBHOOK_PUBLIC_URL>/webhook/meta-inbound`；用户填好令牌后点击“验证并保存”。字段订阅“feed”。有 Instagram 时切换到“Instagram”对象，使用同样的网址与令牌，订阅“comments”。
3. 提醒：开发模式只收得到测试事件与有角色者自己发的评论；Instagram 评论 Webhook 需要 Live＋高级访问权限，不在这次范围内。没有 Webhook 时，工作台仍会每小时自己抓取。

## Threads（同一个 Meta 应用）

1. 打开应用 →“用例”中添加“访问 Threads API”→“自定义 → 设置”。
2. “Threads 应用编号”“Threads 应用密钥”（与 Facebook 的不是同一组）请用户自己粘贴到工作台 Threads 卡片。
3. 在同一页的“重定向回调网址”中粘贴 threads 回调网址并保存。如果取消授权／删除回调是必填项，先问用户要填什么（可以用隐私政策网址）。
4. 在“权限和功能”中逐个添加：`threads_content_publish`、`threads_manage_replies`、`threads_manage_insights`、`threads_read_replies`（`threads_basic` 已默认添加）。
5. 在“应用角色 → 角色 → 添加用户”中选择“Threads 测试人员”，输入用户提供的 Threads 账号名称。
6. 交给用户：在手机 Threads App 的“设置 → 账户 → 网站权限 → 邀请”中点击“接受”，再到工作台点击“连接 Threads 账号”。

## YouTube（Google Cloud）

1. （先问）创建项目 <https://console.cloud.google.com/projectcreate>，名称随意；确认顶部选中的是这个项目。
2. 启用两个 API（都点击“启用”）：[YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com)、[YouTube Analytics API](https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com)。
3. 在[品牌塑造](https://console.cloud.google.com/auth/branding)中点击“开始”：填写应用名称、用户支持邮箱；“目标对象”选择“外部”；填写联系邮箱；勾选同意前先问，再点击“创建”。可补充首页、隐私政策、服务条款网址。
4. （先问）在[目标对象](https://console.cloud.google.com/auth/audience)中点击“发布应用”改为“正式版”，否则授权每 7 天失效。这**不是**提交验证：100 人以下自用不需要验证，不要点击任何“提交验证”。
5. 在[数据访问](https://console.cloud.google.com/auth/scopes)中点击“添加或移除范围”→ 在“手动添加范围”中粘贴以下三行，点击“添加到表格”→“更新”→“保存”：
   - `https://www.googleapis.com/auth/youtube.readonly`
   - `https://www.googleapis.com/auth/yt-analytics.readonly`
   - `https://www.googleapis.com/auth/youtube.upload`

   不要添加 `youtube` 或 `youtube.force-ssl`。
6. 在[创建客户端](https://console.cloud.google.com/auth/clients/create)中选择“Web 应用”，在“已获授权的重定向 URI”中粘贴 youtube 回调网址，点击“创建”。
7. **立刻停手**：密钥只会显示这一次。请用户自己把“客户端 ID”“客户端密钥”粘贴到工作台 YouTube 卡片（可以先点击“下载 JSON”备份），关掉对话框后你再继续截图或操作。
8. 交给用户：在工作台点击“连接 YouTube 账号”；出现“Google 尚未验证此应用”时由用户点击“高级 → 前往（应用名称）”，权限全部勾选。

## TikTok（只用 Sandbox）

后台：<https://developers.tiktok.com/>（右上角“Developer Portal”）

1. （先问）创建应用，名称**不能包含“TikTok”**，用品牌名。
2. 在页面上方切换到“Sandbox”并创建一个。
3. 在“Add products”中添加 **Login Kit** 与 **Content Posting API**；**Direct Post 保持关闭**。
4. Login Kit 的“Redirect URI”选择 Web，粘贴 tiktok 回调网址。
5. 在“Scopes”中用“Add scopes”添加这四个：`user.info.basic`、`user.info.stats`、`video.list`、`video.upload`。不要添加 `video.publish`。
6. Basic information 的必填字段：App icon（请用户提供图片文件）、Category、Description（如实描述，例如“把自己的视频发送到 TikTok 收件箱、读取自己账号的公开视频数据”）、服务条款与隐私政策网址。点击“Apply changes”，没有红字才算完成。“Verify domains”不用点。
7. 交给用户：“Target Users”→“Add account”由用户登录 TikTok 并同意开发者条款（可能要等最多 1 小时才出现）。
8. 交给用户：Sandbox“Credentials”中的 Client key 与 Client secret 由用户自己粘贴到工作台 TikTok 卡片，再点击“连接 TikTok 账号”。

**绝对不要**：提交 Production 审核（TikTok 不接受私人或自用工具）、开启 Direct Post、申请 TikTok API for Business（只接受公司身份）。提醒用户：视频只会发送到收件箱草稿（24 小时内最多 5 个待处理），文案与封面在 App 内处理，发布时选择“所有人”，之后用未登录的浏览器确认已公开。

## 收尾

每个平台做完，向用户列出：已设置的回调网址、已添加的权限、还需要用户自己做的事（粘贴密钥、点击连接、接受邀请、Target Users）。工作台卡片显示账号名称与“已连接”就完成了；卡片显示缺少权限时，回到后台补上，再请用户重新连接。

常见错误：

- “网址不符”／`redirect_uri_mismatch`：回调网址要整串粘贴，不能多斜杠或改成 http。
- 授权时找不到公共主页：在授权页面点击“编辑设置”勾选，而且本人必须是公共主页管理员。
- Threads 提示不是测试人员：到 Threads App 接受邀请。
- “连接”按钮是灰色的：用内部 https 地址重新打开工作台。
- TikTok“Apply changes”出现红字：App icon、Category、Description、两个政策网址都要填写，名称不能包含 TikTok。
