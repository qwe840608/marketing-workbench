# Privacy Policy template

> **Language / 語言 / 语言 / 言語**: [繁體中文](../../zh-tw/templates/隱私權政策範本.md) | [简体中文](../../cn/templates/隐私政策模板.md) | English | [日本語](../../jp/templates/プライバシーポリシーのテンプレート.md)

How to use: replace each `{{…}}` with your own details; delete the platforms you have not connected and the processors you do not use (the `[optional]` items); make sure the retention days match your `.env`. Publish it on your own website, then enter its URL in the Meta, Google and TikTok consoles. This is a template, not legal advice.

| Placeholder | What to fill in |
|---|---|
| `{{TOOL_NAME}}` | Your workbench's name (must not contain platform names such as Facebook, Instagram or TikTok) |
| `{{OWNER}}` | Who runs it (you or your brand) |
| `{{BRAND}}` | Name of the brand/account the workbench manages |
| `{{CONTACT_EMAIL}}` | Contact email for privacy and deletion requests |
| `{{UPDATED}}` | Date of the last update |
| `{{RETENTION_DAYS}}` | `COMMENT_RETENTION_DAYS` (default 365) |
| `{{AI_PROVIDERS}}` | The AI services you actually configured (for example OpenAI, Anthropic, Google Gemini on a paid plan) |
| `{{PRIVACY_URL}}` | URL of the privacy policy (used by the terms of service template) |

---

## Policy

Last updated: {{UPDATED}}

{{TOOL_NAME}} is a self-hosted tool that {{OWNER}} uses to manage {{BRAND}}'s own social media accounts. This policy explains what data it obtains through each platform's official API, and how that data is used and deleted. The tool uses YouTube API Services; when YouTube features are used, the [Google Privacy Policy](https://policies.google.com/privacy) also applies.

### 1. Data we obtain
- Facebook Pages, Instagram, Threads: posts, performance figures and follower counts of the owner's own accounts; public comments and replies on those posts, including the commenter's name, account ID and comment text.
- YouTube: video data, thumbnails and performance figures of the owner's own channel, and public comments on those videos.
- TikTok: the account's basic profile, follower count, and public videos with their performance figures. TikTok comments, direct messages and private videos are not accessed.
- Text, images and videos that the account owner uploads to prepare for publishing.
- The tool does not read direct messages, nor posts from other people's accounts.

### 2. How it is used
Only to show the performance and follower changes of the owner's own accounts; to organize public comments in order to understand common audience questions and come up with content ideas; and to publish content after the account owner confirms. It is not used for advertising, is not sold, and is not used to build personal profiles.

### 3. Storage and security
Data is stored in a database on the account owner's own computer, not on a public server; the tool can be used only from that computer or a private network. Platform access tokens are stored encrypted and are never written to logs or export files.

### 4. Processors and sharing
Data is not sold, and is not shared with advertisers or data brokers. Only to provide the features above is the necessary content passed to the following services for processing; phone numbers, email addresses and other personal data are masked before it is sent:
- [optional] TypeSafe (jev): classifies comments; per its policy, it does not train models on input.
- [optional] AI services configured by the account owner ({{AI_PROVIDERS}}, for example OpenAI, Anthropic, or Google Gemini with a paid plan enabled): drafts topics and scripts. Free tiers that use content to train models are not used.
- [optional] AI agents the account owner connects: read masked post data and comments through the tool.
- [optional] LINE: sends masked summaries of urgent comments only to the account owner's own LINE group.

### 5. Retention
- Public comments are kept for {{RETENTION_DAYS}} days from when the tool obtained them, then deleted automatically.
- YouTube comments not refreshed within 30 days are deleted; data related to videos deleted on YouTube is deleted within 30 days.
- Performance figures and follower counts of the owner's own accounts are kept to compare changes over time; YouTube's are deleted immediately on disconnect.
- Topic reports keep the written topics; the original text of quoted comments is removed according to the periods above.

### 6. Revoking access and deleting data
- Disconnect a platform in the tool: for YouTube, this revokes access and immediately deletes the YouTube data the tool has stored. It only deletes the tool's data and does not delete videos on YouTube.
- Google account holders can revoke the tool's access at any time in [Google security settings](https://security.google.com/settings/security/permissions); related data is deleted within 7 days of revocation.
- For Facebook, Instagram, Threads and TikTok, this tool can be removed in each platform's app permission settings.
- Anyone who has commented on the accounts above can email us to request deletion of the comments and name the tool has stored; requests are handled within 7 days of receipt.<a id="delete"></a>

### 7. Contact
Privacy questions, deletion requests or security reports: {{CONTACT_EMAIL}}.
