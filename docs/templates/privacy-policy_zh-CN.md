# 隐私政策模板 Privacy Policy template

> **语言 / Language / 語言 / 言語**：[繁體中文](privacy-policy.md) | 简体中文 | [English](privacy-policy_en.md) | [日本語](privacy-policy_ja.md)

使用方法：把 `{{…}}` 换成你的信息；删掉你没有连接的平台、没有用到的处理方（`[可选]` 段落）；保存天数要与你的 `.env` 一致。放到你自己的网站上，再把网址填进 Meta、Google、TikTok 后台。这是模板，不是法律意见。

| 占位符 | 填什么 |
|---|---|
| `{{TOOL_NAME}}` | 你的工作台名称（不能含 Facebook、Instagram、TikTok 等平台名称） |
| `{{OWNER}}` | 搭建者（你或你的品牌） |
| `{{BRAND}}` | 工作台管理的品牌／账号名称 |
| `{{CONTACT_EMAIL}}` | 隐私与删除请求的联系邮箱 |
| `{{UPDATED}}` | 最后更新日期 |
| `{{RETENTION_DAYS}}` | `COMMENT_RETENTION_DAYS`（默认 365） |
| `{{AI_PROVIDERS}}` | 你实际设置的 AI 服务（例如 OpenAI、Anthropic、付费方案的 Google Gemini） |
| `{{PRIVACY_URL}}` | 隐私政策网址（服务条款模板使用） |

---

## 中文

最后更新：{{UPDATED}}

“{{TOOL_NAME}}”是 {{OWNER}} 自行搭建、用于管理 {{BRAND}} 自己社交媒体账号的工具。本政策说明它通过各平台官方 API 获取哪些数据，以及如何使用与删除。工作台使用 YouTube API 服务；使用 YouTube 相关功能时，也适用 [Google 隐私权政策](https://policies.google.com/privacy)。

### 1. 获取的数据
- Facebook 公共主页、Instagram、Threads：自己账号的帖子、效果数据与粉丝数；帖子下的公开评论与回复，包括评论者的名称、账号标识符与评论内容。
- YouTube：自己频道的视频信息、缩略图、效果数据，以及视频下的公开评论。
- TikTok：账号的基本资料、粉丝数，以及公开视频与效果数据。不读取 TikTok 评论、私信或私密视频。
- 账号所有者主动上传、准备发布的文字、图片与视频。
- 工作台不读取私信，也不读取其他人账号的帖子。

### 2. 用途
仅用于：显示自己账号的效果与粉丝变化；整理公开评论，以了解观众的常见问题、策划内容选题；在账号所有者确认后发布内容。不用于广告、不出售，也不建立个人画像。

### 3. 存储与保护
数据存放在账号所有者自己电脑上的数据库中，不放在公开服务器上；工作台只能从本机或私有网络使用。平台访问令牌加密保存，不写入日志或导出文件。

### 4. 委托处理与共享
数据不出售，也不共享给广告商或数据经纪商。只有为了提供上述功能，才会把必要内容交给下列服务处理；发送前会先遮蔽电话、Email 等个人信息：
- [可选] TypeSafe（jev）：为评论分类，按其政策不使用输入内容训练模型。
- [可选] 账号所有者设置的 AI 服务（{{AI_PROVIDERS}}，例如 OpenAI、Anthropic，或已启用付费方案的 Google Gemini）：撰写选题与脚本。不使用会将内容用于训练模型的免费方案。
- [可选] 账号所有者自行连接的 AI Agent：通过工作台读取遮蔽后的帖子数据与评论。
- [可选] LINE：只把紧急评论的遮蔽摘要通知到账号所有者自己的 LINE 群组。

### 5. 保存期限
- 公开评论自工作台获取起保存 {{RETENTION_DAYS}} 天，到期自动删除。
- YouTube 评论 30 天内未再更新即删除；在 YouTube 上已删除的视频，相关数据在 30 天内删除。
- 自己账号的效果数据与粉丝数持续保存，用于比较历史变化；断开 YouTube 连接时立即删除 YouTube 的相关数据。
- 选题报告保留撰写出的选题，引用的评论原文会按上述期限移除。

### 6. 撤销授权与删除数据
- 在工作台断开平台连接：YouTube 会撤销授权，并立即删除工作台已保存的 YouTube 数据。这只删除工作台中的数据，不会删除 YouTube 上的视频。
- Google 账号可随时在 [Google 安全设置](https://security.google.com/settings/security/permissions) 中撤销工作台的访问权限；撤销后 7 天内删除相关数据。
- Facebook、Instagram、Threads、TikTok 可在各平台的应用权限设置中移除本工具。
- 曾在上述账号下发表评论的人，可发邮件要求删除工作台保存的评论与名称，收到后 7 天内处理。<a id="delete"></a>

### 7. 联系方式
隐私相关问题、删除请求或安全问题报告：{{CONTACT_EMAIL}}。

---

## English

Last updated: {{UPDATED}}

{{TOOL_NAME}} is a self-hosted tool that {{OWNER}} uses to manage {{BRAND}}'s own social media accounts. This policy explains what it obtains through each platform's official API and how that data is used and deleted. The tool uses YouTube API Services; when YouTube features are used, the [Google Privacy Policy](https://policies.google.com/privacy) also applies.

### 1. Data we obtain
- Facebook Pages, Instagram, Threads: the owner's posts, statistics and follower counts; public comments and replies on those posts, including the commenter's name, account ID and comment text.
- YouTube: the owner's channel videos, thumbnails, statistics, and public comments on those videos.
- TikTok: basic profile, follower count, and public videos with their statistics. TikTok comments, direct messages and private videos are not accessed.
- Text, images and videos the owner uploads to publish.
- The tool does not read direct messages or other accounts' posts.

### 2. How it is used
Only to show the owner's performance and follower changes, to summarize public comments to understand audience questions and plan content, and to publish content after the owner confirms. It is not used for advertising, sold, or used for profiling.

### 3. Storage and security
Data is stored in a database on the owner's own computer, not on a public server, and the tool is reachable only from that computer or a private network. Platform access tokens are stored encrypted and never written to logs or exports.

### 4. Processors and sharing
Data is never sold or shared with advertisers or data brokers. Only to provide the features above, the necessary content is processed by these services, with phone numbers, emails and similar personal data masked first:
- [optional] TypeSafe (jev): classifies comments; per its policy it does not train models on input.
- [optional] AI services the owner configures ({{AI_PROVIDERS}}): drafts topics and scripts. Free tiers that use content for training are not used.
- [optional] AI agents the owner connects: read masked post statistics and comments through the tool.
- [optional] LINE: sends masked summaries of urgent comments only to the owner's own LINE group.

### 5. Retention
- Public comments are kept for {{RETENTION_DAYS}} days from when the tool obtained them, then deleted automatically.
- YouTube comments not refreshed within 30 days are deleted; data about videos deleted on YouTube is deleted within 30 days.
- The owner's statistics and follower counts are kept to compare history; YouTube's are deleted immediately on disconnect.
- Topic reports keep the written topics; quoted comment text is removed on the schedule above.

### 6. Revoking access and deleting data
- Disconnect a platform in the tool. For YouTube this revokes access and immediately deletes the YouTube data the tool stored. It does not delete videos on YouTube.
- Google users can revoke the tool's access at any time on the [Google security settings page](https://security.google.com/settings/security/permissions); related data is deleted within 7 days.
- Facebook, Instagram, Threads and TikTok users can remove this tool in each platform's app permission settings.
- Anyone who commented on these accounts can email us to delete their stored comments and name; requests are handled within 7 days.

### 7. Contact
Privacy questions, deletion requests or security reports: {{CONTACT_EMAIL}}.
