# TikTok 规划（第一版）

> **语言 / Language / 語言 / 言語**：[繁體中文](TikTok規劃.md) | 简体中文 | [English](tiktok-plan.md) | [日本語](TikTok計画.md)

2026-10-16 经规划问答定案。官方限制以 2026-10-16 核查的官方文档为准，尚未确认之处列在“实测待确认”。

## 前提

- 走 TikTok for Developers（developers.tiktok.com），**不送审**。送审涉及产品定位，并入开源规划再决定。
- 全站一组 TikTok 连接、一个账号；多账号留给多品牌规划。账号类型不影响可用的 API，不需要改成商业账号。
- 开源后每位用户自行创建 TikTok 应用，与 Meta、Threads、YouTube 相同。
- 只用官方 API；官方不开放的数据不用爬虫或非官方 API 获取。

## 官方限制（决策依据）

- 未审核的应用直接发布只能使用 `SELF_ONLY`，且发帖账号必须是私密账号；公开发布须通过审核。审核不受理私人或个人用途的应用。来源：<https://developers.tiktok.com/doc/content-sharing-guidelines>、<https://developers.tiktok.com/doc/app-review-guidelines>
- 图片帖子只能用 `PULL_FROM_URL`，网址必须属于已验证的域名；视频可用 `FILE_UPLOAD` 由后端直接上传。来源：<https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide>
- 发送到收件箱（`video.upload`）24 小时内最多 5 个待处理；时长上限因账号而异，以 creator_info 的 `max_video_post_duration_sec` 为准。来源：<https://developers.tiktok.com/doc/content-posting-api-reference-upload-video>、<https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info>
- 发布状态查询只在公开且应用已审核时返回公开帖子 ID。来源：<https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status>
- access token 有效期 24 小时、refresh token 365 天，续期返回的 refresh token 可能会更换。来源：<https://developers.tiktok.com/doc/oauth-user-access-token-management>
- Display API `video.list` 只返回公开视频。来源：<https://developers.tiktok.com/doc/tiktok-api-v2-video-list>
- 读取评论只有 TikTok API for Business 的 Accounts API 提供。开发者注册须使用公司域名 email 与公司网站（不受理个人网站与个人开发者），Accounts API 申请表须填写登记文件上的公司全称并做商业验证（登记文件或已验证的 Business Center）。来源：<https://business-api.tiktok.com/portal/docs/register-as-a-developer/v1.3>、<https://business-api.tiktok.com/portal/docs/accounts-api/v1.3>

## 连接账号与令牌

- 权限：`user.info.basic`、`user.info.stats`、`video.list`、`video.upload`。
- 回调网址先用工作台的 Tailscale https 网址；TikTok 不接受时改用桌面模式回调 `127.0.0.1`（PKCE，code challenge 为 SHA256 hex），此时连接必须在运行工作台的电脑上操作。
- access token 由后端在调用前自动续期，用户无需操作。refresh token 到期前 14 天或续期失败时，以 LINE 通知重新连接；卡片显示已连接／即将到期／已失效，以及台北时间的到期日。

## 数据

- 每小时同步公开视频与播放、点赞、评论数、分享数，以及粉丝数。
- 取得完整列表时，列表中没有的视频标为“已删除或改为私密”并从帖子数据中隐藏；列表不完整或为空时不做判定。
- 并入帖子数据与仪表盘；官方不开放的效果数据可用 TikTok Studio 导出的 CSV 导入。
- 选题策划不加 TikTok 标签页：选题策划以评论为依据，而 TikTok 没有评论来源。

## 发布

- 只发视频，方式为发送到 TikTok 收件箱（`MEDIA_UPLOAD`）；用户在 App 中编辑并发布。工作台按定时发布时间发送，不决定公开时间。
- 图文帖子勾选 TikTok 时拦下并提示“仅支持发布视频，图文需从 App 上传”。
- 并入共用文案流程，TikTok 分页可覆盖文案；若 API 无法带入文案，发布记录提供“复制文案”。
- 定时发布时与发送前用 creator_info 检查时长上限；收件箱已满时，以发送时的错误码写明原因并可重试。
- 以轮询追踪状态，不接 TikTok Webhook，公开入口不新增路径。最终状态为“已发送到 TikTok 收件箱”，能检测到时改为“已在 App 发布”；没有帖子 ID 时不附链接，也不自动比对之后出现的视频。

## 评论

- 第一版不实现，只放提示：“读取 TikTok 评论需要以公司身份申请 TikTok API for Business（个人开发者无法申请）”。位置：平台连接 TikTok 卡片的“评论（可选）”区块、设置教程“读取评论（需要公司身份）”一节、帖子数据中 TikTok 视频的评论区。
- 日后取得公司身份并通过申请时的方向：Business API 只负责评论，发布与数据仍走 TikTok for Developers；只读不回复；每小时抓取、不接 Webhook；连接后选题策划才出现 TikTok 标签页。

## 不做

直接公开发布（需审核）、图片帖子（需验证域名）、读取与回复评论（需公司身份）、非官方 API 与爬虫。

## 交付顺序

每一步验收通过后才进入下一步。

1. 改写 TikTok 设置教程（含评论提示），协助用户创建应用。（2026-10-16 完成，已按教程创建 Sandbox）
2. 连接账号、令牌自动续期、到期提醒；卡片加入“评论（可选）”提示。（2026-10-16 部署，实机连接成功，确认 Tailscale https 网址可作为回调网址）回调网址只能在工作台有了授权路由后才能实测，所以与原第 3 步对调：先完成连接功能，部署后再实测回调网址与读取权限。
3. 实测（见下节）；收件箱与文案两项留到第 5 步发布时实测。
4. 数据同步、帖子数据（含评论提示）、仪表盘。每小时一次 `video.list`（每页 20 个、最多 50 页），同时写入帖子与到期的效果快照，不逐个查询；每天一次 `user.info` 的 follower_count。只有完整且非空的列表才把消失的视频标为已删除或改为私密并隐藏；发布页的 TikTok 分页改为“发布尚未开放”。
5. 发布：只把视频发送到收件箱（`POST /v2/post/publish/inbox/video/init/` 的 FILE_UPLOAD，64 MB 以内一段，其余按 10 MB 一段依序 PUT）。先保存 publish_id，重试前先查状态，已进收件箱就不重发；发送后最多等 60 秒到 SEND_TO_USER_INBOX，之后每 10 分钟追踪一次、持续 7 天，看是否变成 PUBLISH_COMPLETE。收件箱 API 不接受文案（已查证），发布记录提供“复制文案”。时长上限按官方媒体传输指南固定为 10 分钟：按账号查询上限的 creator_info 需要 video.publish，第一版不申请。

## 实测待确认

- Tailscale https 网址能否作为 Web 回调网址。
- 未审核的应用能否把视频发送到收件箱（第 5 步部署后，用用户同意的测试视频实测）。
- 用户在 App 发布后，状态是否变为 `PUBLISH_COMPLETE`（官方状态文档写会变，待实测）。
- 发送到收件箱时能否带文案：官方 init 端点没有文案字段，确定不能带（2026-10-17 查证）。
